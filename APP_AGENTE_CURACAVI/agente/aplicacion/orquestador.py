"""Orquestación del agente con LangGraph (capa de APLICACIÓN de la arquitectura hexagonal).

Flujo de cada mensaje del vecino (ver DOCUMENTACION/arquitectura.md):

    percibir -> diagnosticar -> planificar -> [aprobacion] -> ejecutar -> (¿replanificar?) -> responder -> memorizar

- percibir: entiende el mensaje (nlu.py) y lo combina con la memoria de corto plazo del hilo.
- diagnosticar: reúne hechos con herramientas de CONSULTA y RAZONAMIENTO (estado del folio,
  historial del vecino, requisitos, agenda, plazos, casos parecidos).
- planificar: el planner (reglas priorizadas) decide la acción y arma el plan de pasos.
- aprobacion: si la decisión lo exige (escalamientos), el grafo se PAUSA (interrupt) hasta que un
  funcionario apruebe o rechace. El estado queda guardado en el checkpointer mientras espera.
- ejecutar: corre los pasos (herramientas de ESCRITURA). Si una condición cambió (por ejemplo, otra
  persona tomó la hora), detiene el plan y vuelve a diagnosticar: REPLANIFICACIÓN (máximo 2 veces).
- responder: redacta la respuesta con citas por tipo de fuente (redaccion.py).
- memorizar: guarda la decisión en la memoria de largo plazo, indexa el caso resuelto (memoria
  episódica), actualiza la memoria de trabajo del hilo y resume la conversación si es larga.

El grafo recibe el contenedor (puertos ya conectados a sus adaptadores) y las herramientas creadas
para ese contenedor. No sabe si la base es SQLite o PostgreSQL.
"""
import re
import time
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, RemoveMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import Command, interrupt

from agente.aplicacion.nlu import percibir as percibir_mensaje
from agente.aplicacion.redaccion import redactar
from agente.aplicacion.resumen import resumir
from agente.configuracion import settings
from agente.dominio.planner import FOLIO_PENDIENTE, decidir, evaluar_plazo
from agente.dominio.texto import normalizar

ACCIONES_QUE_CIERRAN = {"registrar_tramite", "reingreso_guiado", "inscribir_lista_espera", "escalar_por_plazo",
                        "derivar_institucion_externa"}
PATRON_TEMA_PLAZOS = r"plazo|hasta cuando|cuando|fecha|vence|dias|periodo|mes de"


def acumular(actual: list | None, nuevo: list) -> list:
    """Reductor de listas del turno: agrega elementos, pero si el primero es {"reset": True} reinicia la lista.

    Así la traza y las observaciones muestran solo el turno actual, aunque el estado completo del
    hilo quede guardado en el checkpointer.
    """
    if nuevo and isinstance(nuevo[0], dict) and nuevo[0].get("reset"):
        return list(nuevo[1:])
    return (actual or []) + nuevo


class EstadoAgente(TypedDict, total=False):
    # Conversación (se resume cuando crece)
    messages: Annotated[list[AnyMessage], add_messages]
    vecino_id: str
    # Memoria de trabajo del hilo (persiste entre turnos gracias al checkpointer)
    tramite_activo: str | None
    esperando: str | None
    documentos: list
    folio_en_curso: str | None
    resumen: str
    turnos: int
    # Datos del turno actual
    percepcion: dict
    hechos: dict
    decision: dict
    plan: list
    observaciones: Annotated[list, acumular]
    traza: Annotated[list, acumular]
    replanificaciones: int
    replanificar: bool
    respuesta: str
    validacion: dict
    modo_redaccion: str          # "llm" o "plantilla" (las acciones de trámite siempre usan plantilla)
    aviso_llm: str | None        # por qué no se pudo usar el LLM (se muestra en el panel; nunca se oculta)


def _evento(nodo: str, detalle: str, **extra) -> dict:
    return {"nodo": nodo, "detalle": detalle, **extra}


def construir_grafo(ctx, herramientas: dict[str, list], llm=None):
    """Arma el StateGraph. ctx: contenedor de dependencias; llm puede ser None (modo offline)."""
    # Las herramientas llegan ya creadas y agrupadas por tipo (consulta, escritura, razonamiento).
    por_nombre = {h.name: h for lista in herramientas.values() for h in lista}
    tipo_de = {h.name: tipo for tipo, lista in herramientas.items() for h in lista}

    def _invocar(nombre: str, args: dict) -> dict:
        """Ejecuta una herramienta y devuelve la observación (con su tipo y tiempo)."""
        inicio = time.time()
        resultado = por_nombre[nombre].invoke(args)
        return {"herramienta": nombre, "tipo": tipo_de[nombre], "args": args, "resultado": resultado,
                "ms": round((time.time() - inicio) * 1000)}

    def percibir(estado: EstadoAgente) -> dict:
        texto = estado["messages"][-1].content
        previo = {"tramite_activo": estado.get("tramite_activo"), "esperando": estado.get("esperando")}
        p = percibir_mensaje(texto, previo, anio=ctx.fecha().year, llm=llm, requisitos=ctx.requisitos)
        documentos = p["documentos"]
        if p["tramite_id"] and p["tramite_id"] == estado.get("tramite_activo"):
            documentos = sorted(set(estado.get("documentos") or []) | set(p["documentos"]))
        # Si el vecino cambia de trámite, se olvida el folio del trámite anterior.
        cambio = p["tramite_id"] and estado.get("tramite_activo") and p["tramite_id"] != estado.get("tramite_activo")
        return {"percepcion": p, "documentos": documentos, "hechos": {}, "decision": {}, "plan": [],
                "replanificaciones": 0, "replanificar": False, "respuesta": "",
                "folio_en_curso": None if cambio else estado.get("folio_en_curso"),
                "observaciones": [{"reset": True}], "traza": [{"reset": True},
                _evento("percibir", f"Intención: {p['intencion']} · trámite: {p['tramite_id'] or '—'} · folio: {p['folio'] or '—'}"
                        f" · documentos: {', '.join(documentos) or '—'} · fuente: {p['fuente_nlu']}")]}

    def diagnosticar(estado: EstadoAgente) -> dict:
        p, vecino = estado["percepcion"], estado.get("vecino_id", "V-000")
        obs = []
        hechos = {**p, "vecino_id": vecino, "hoy": ctx.fecha().isoformat(), "documentos": estado.get("documentos", []),
                  "folio_en_curso": estado.get("folio_en_curso"), "cupo_fallido": estado.get("replanificar", False),
                  "tema_de_plazos": bool(re.search(PATRON_TEMA_PLAZOS, normalizar(p["texto"])))}
        tramite = p.get("tramite_id")
        if tramite in ctx.requisitos:
            hechos["tramite_principal_fuente"] = ctx.requisitos[tramite]["fuente_principal"]

        obs.append(_invocar("consultar_historial_vecino", {"vecino_id": vecino}))
        historial = obs[-1]["resultado"]
        if p.get("folio"):
            obs.append(_invocar("consultar_estado_solicitud", {"folio": p["folio"]}))
            hechos["solicitud"] = obs[-1]["resultado"]
            if hechos["solicitud"].get("encontrado"):
                hechos["plazo"] = evaluar_plazo(hechos["solicitud"], ctx.fecha())
        if p["intencion"] in ("iniciar_tramite", "aportar_antecedentes") and tramite in ctx.requisitos:
            obs.append(_invocar("verificar_requisitos", {"tramite_id": tramite, "documentos_declarados": hechos["documentos"]}))
            hechos["verificacion"] = obs[-1]["resultado"]
            if hechos["verificacion"]["requiere_hora"]:
                obs.append(_invocar("consultar_agenda", {"tramite_id": tramite}))
                hechos["agenda"] = obs[-1]["resultado"]
            hechos["previos_mismo_tramite"] = [x for x in historial["solicitudes"] if x["tramite_id"] == tramite
                                               and x["estado"] in ("Rechazada", "Observada")
                                               and x["folio"] != estado.get("folio_en_curso")]
            obs.append(_invocar("buscar_casos_similares", {"descripcion": p["texto"]}))
        resumen = " · ".join(f"{o['herramienta']}" for o in obs)
        return {"hechos": hechos, "observaciones": obs, "traza": [_evento("diagnosticar", f"Consultas: {resumen}")]}

    def planificar(estado: EstadoAgente) -> dict:
        decision = decidir(estado["hechos"]).a_dict()
        plan = [{**paso, "estado": "pendiente"} for paso in decision["pasos"]]
        detalle = f"{decision['regla_id']} {decision['regla']} → {decision['accion']}"
        if estado.get("replanificaciones"):
            detalle = f"REPLANIFICACIÓN {estado['replanificaciones']}: " + detalle
        return {"decision": decision, "plan": plan,
                "traza": [_evento("planificar", detalle, pasos=[x["herramienta"] for x in plan],
                                  requiere_aprobacion=decision["requiere_aprobacion"])]}

    def aprobacion(estado: EstadoAgente) -> dict:
        """Humano en el ciclo: el grafo se detiene aquí hasta recibir la respuesta del funcionario."""
        d = estado["decision"]
        respuesta = interrupt({"tipo": "aprobacion", "accion": d["accion"], "motivo": d["motivo"],
                               "fundamentos": [f["cita"] for f in d["fundamentos"]],
                               "pasos": [p["herramienta"] for p in estado["plan"]]})
        aprobado = bool(respuesta.get("aprobado")) if isinstance(respuesta, dict) else bool(respuesta)
        if aprobado:
            return {"traza": [_evento("aprobacion", "Funcionario aprobó la acción")]}
        decision = {**d, "accion": "informar_estado", "aprobacion_rechazada": True, "pasos": []}
        return {"decision": decision, "plan": [], "traza": [_evento("aprobacion", "Funcionario rechazó: solo se informa")]}

    def ejecutar(estado: EstadoAgente) -> dict:
        folio = estado.get("folio_en_curso")
        obs, plan, replanificar = [], [], False
        for paso in estado.get("plan", []):
            args = {k: (folio if v == FOLIO_PENDIENTE else v) for k, v in paso["args"].items()}
            o = _invocar(paso["herramienta"], args)
            obs.append(o)
            r = o["resultado"]
            if paso["herramienta"] == "registrar_solicitud" and r.get("ok"):
                folio = r["folio"]
            if paso["herramienta"] == "agendar_hora" and not r.get("ok"):
                plan.append({**paso, "args": args, "estado": "fallido"})
                replanificar = True
                break
            plan.append({**paso, "args": args, "estado": "hecho"})
        n = estado.get("replanificaciones", 0) + (1 if replanificar else 0)
        detalle = " · ".join(f"{x['herramienta']} ({x['estado']})" for x in plan) or "sin acciones de escritura"
        if replanificar:
            detalle += " → condición cambiante: la hora ya no estaba disponible"
        return {"observaciones": obs, "plan": plan, "folio_en_curso": folio, "replanificar": replanificar,
                "replanificaciones": n, "traza": [_evento("ejecutar", detalle)]}

    def responder(estado: EstadoAgente) -> dict:
        hechos = {**estado["hechos"], "folio_en_curso": estado.get("folio_en_curso")}
        observaciones = estado.get("observaciones", [])
        r = redactar(estado["decision"], hechos, observaciones, llm=llm)
        detalle = f"Respuesta por {r['modo']} · cita válida: {r['validacion']['cita_valida']}"
        if r.get("aviso_llm"):
            detalle += f" · LLM no usado: {r['aviso_llm']}"
        return {"respuesta": r["texto"], "validacion": r["validacion"], "messages": [AIMessage(content=r["texto"])],
                "modo_redaccion": r["modo"], "aviso_llm": r.get("aviso_llm"), "traza": [_evento("responder", detalle)]}

    def memorizar(estado: EstadoAgente, config: RunnableConfig) -> dict:
        d, p = estado["decision"], estado["percepcion"]
        folio = estado.get("folio_en_curso") or p.get("folio")
        ctx.registro.registrar_decision(config["configurable"]["thread_id"], estado.get("vecino_id", ""), d["regla_id"],
                                      d["accion"], d["motivo"], p.get("tramite_id"), folio)
        cambios: dict[str, Any] = {"turnos": estado.get("turnos", 0) + 1}
        if d["accion"] == "solicitar_antecedentes":
            cambios.update(tramite_activo=p["tramite_id"], esperando="antecedentes")
        elif d["accion"] in ACCIONES_QUE_CIERRAN:
            cambios.update(tramite_activo=None, esperando=None, documentos=[])
            # Memoria episódica: el caso resuelto queda disponible para casos futuros parecidos.
            ctx.indice.agregar("casos_resueltos",
                             f"Caso {folio or 'sin folio'}: {p['texto'][:200]} → {d['accion']}: {d['motivo']}",
                             {"fuente_id": "registro_solicitudes", "folio": folio or "", "tramites": "*", "nivel": 0})
        mensajes = estado["messages"]
        eventos = [_evento("memorizar", f"Decisión guardada en memoria de largo plazo ({d['regla_id']})")]
        if len(mensajes) > settings.MENSAJES_ANTES_DE_RESUMIR:
            antiguos = mensajes[:-4]
            memoria = {"tramite_activo": cambios.get("tramite_activo", estado.get("tramite_activo")),
                       "folio_en_curso": folio, "documentos": estado.get("documentos"), "ultima_accion": d["accion"]}
            cambios["resumen"] = resumir(antiguos, estado.get("resumen", ""), memoria, llm)
            cambios["messages"] = [RemoveMessage(id=m.id) for m in antiguos]
            eventos.append(_evento("memorizar", f"Conversación resumida: {len(antiguos)} mensajes condensados"))
        cambios["traza"] = eventos
        return cambios

    def ruta_tras_planificar(estado: EstadoAgente) -> str:
        return "aprobacion" if estado["decision"].get("requiere_aprobacion") else "ejecutar"

    def ruta_tras_ejecutar(estado: EstadoAgente) -> str:
        if estado.get("replanificar") and estado.get("replanificaciones", 0) <= settings.MAX_REPLANIFICACIONES:
            return "diagnosticar"
        return "responder"

    g = StateGraph(EstadoAgente)
    for nombre, nodo in [("percibir", percibir), ("diagnosticar", diagnosticar), ("planificar", planificar),
                         ("aprobacion", aprobacion), ("ejecutar", ejecutar), ("responder", responder),
                         ("memorizar", memorizar)]:
        g.add_node(nombre, nodo)
    g.add_edge(START, "percibir")
    g.add_edge("percibir", "diagnosticar")
    g.add_edge("diagnosticar", "planificar")
    g.add_conditional_edges("planificar", ruta_tras_planificar, ["aprobacion", "ejecutar"])
    g.add_edge("aprobacion", "ejecutar")
    g.add_conditional_edges("ejecutar", ruta_tras_ejecutar, ["diagnosticar", "responder"])
    g.add_edge("responder", "memorizar")
    g.add_edge("memorizar", END)
    return g


class AgenteTramites:
    """Fachada del agente para el controlador, el notebook y las pruebas.

    Recibe por constructor el contenedor (puertos conectados), el LLM (o None) y el checkpointer.
    Normalmente se crea con agente.configuracion.contenedor.crear_agente().
    """

    def __init__(self, contenedor, llm=None, checkpointer=None):
        self.contenedor = contenedor
        self.llm = llm
        self.herramientas = contenedor.herramientas()
        self.checkpointer = checkpointer or InMemorySaver()   # sin persistencia: solo para pruebas
        self.grafo = construir_grafo(contenedor, self.herramientas, llm).compile(checkpointer=self.checkpointer)

    def _config(self, thread_id: str) -> dict:
        return {"configurable": {"thread_id": thread_id}, "recursion_limit": 40}

    def _salida(self, thread_id: str, inicio: float) -> dict:
        snapshot = self.grafo.get_state(self._config(thread_id))
        estado = dict(snapshot.values)
        pendiente = None
        for tarea in snapshot.tasks:
            for intr in getattr(tarea, "interrupts", ()):
                pendiente = intr.value
        estado["pendiente_aprobacion"] = pendiente
        estado["latencia_s"] = round(time.time() - inicio, 2)
        return estado

    def conversar(self, texto: str, thread_id: str, vecino_id: str) -> dict:
        """Procesa un mensaje del vecino y devuelve el estado final del turno."""
        inicio = time.time()
        self.grafo.invoke({"messages": [HumanMessage(content=texto)], "vecino_id": vecino_id}, self._config(thread_id))
        return self._salida(thread_id, inicio)

    def resolver_aprobacion(self, thread_id: str, aprobado: bool) -> dict:
        """Reanuda un hilo pausado con la decisión del funcionario."""
        inicio = time.time()
        self.grafo.invoke(Command(resume={"aprobado": aprobado}), self._config(thread_id))
        return self._salida(thread_id, inicio)

    def estado(self, thread_id: str) -> dict:
        return dict(self.grafo.get_state(self._config(thread_id)).values)
