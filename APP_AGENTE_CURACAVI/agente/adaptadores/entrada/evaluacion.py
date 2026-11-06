"""Evaluación del agente: recuperación, decisiones en escenarios y calidad de respuestas.

Tres evaluaciones, todas con el número de casos (n) explícito:
1. Recuperación (sin LLM): compara el diseño base con cada mejora (leyes acotadas y fuentes
   separadas, umbral por índice, búsqueda híbrida) y calibra los umbrales por índice.
2. Escenarios (sin LLM): ¿el agente aplicó la regla, la acción y las herramientas esperadas?
   Opcionalmente se compara con un agente "LLM puro" (create_agent con todas las herramientas).
3. Respuestas (con LLM y juez): métricas deterministas (cita válida, tipo de fuente, privacidad...)
   y, si hay juez, correctness y faithfulness. Las respuestas se guardan en caché para poder
   repartir la ejecución en varios días sin repetir llamadas.
"""
import json
import re
import time
from pathlib import Path

import pandas as pd

from agente.dominio import citas as cat
from agente.dominio.texto import normalizar
from agente.aplicacion.llm_utilidades import CuotaAgotadaError, con_reintento, texto_de
from agente.adaptadores.salida.memoria.ingesta import cargar_documentos, fragmentar
from agente.adaptadores.salida.local.indice_chroma import IndiceChroma
from agente.aplicacion.nlu import detectar_tramite
from agente.configuracion import settings

# ---------------------------------------------------------------------------------------------
# 1. Recuperación: comparación antes / después
# ---------------------------------------------------------------------------------------------

CONFIGURACIONES_ABLACION = [
    ("A. Diseño base", dict(acotar=False, separar=False, hibrida=False, umbral_global=0.49, boost=False)),
    ("B. + leyes acotadas y fuentes separadas", dict(acotar=True, separar=True, hibrida=False, umbral_global=0.49, boost=False)),
    ("C. + umbral por índice", dict(acotar=True, separar=True, hibrida=False, umbral_global=None, boost=False)),
    ("D. + búsqueda híbrida y prioridad por trámite", dict(acotar=True, separar=True, hibrida=True, umbral_global=None, boost=True)),
]

# Consultas ajenas al caso: sirven para calibrar el umbral (no deberían recuperar nada).
CONSULTAS_NEGATIVAS = ["¿Cuál es la capital de Francia?", "Dame una receta de empanadas de pino",
                       "¿Quién ganó el último mundial de fútbol?", "¿Cómo se instala Python en Windows?"]


def cargar_preguntas(ruta: Path = settings.EVAL_DIR / "preguntas.json") -> list[dict]:
    return json.loads(Path(ruta).read_text(encoding="utf-8"))


def cargar_escenarios(ruta: Path = settings.EVAL_DIR / "escenarios.json") -> list[dict]:
    return json.loads(Path(ruta).read_text(encoding="utf-8"))


def _construir_indice(directorio: Path, embeddings, documentos, conf: dict, umbrales: dict) -> IndiceChroma:
    indice = IndiceChroma(directorio, embeddings, umbrales=umbrales)
    indice.construir(fragmentar(documentos, acotar_leyes=conf["acotar"], separar_externas=conf["separar"]))
    return indice


def _recuperar(indice: IndiceChroma, colecciones: list[str], consulta: str, conf: dict) -> list[dict]:
    """Une lo que devolverían las herramientas de búsqueda (top-k de cada colección)."""
    tramite = detectar_tramite(normalizar(consulta))
    resultados = []
    for c in colecciones:
        resultados += indice.buscar(c, consulta, tramite=tramite, hibrida=conf["hibrida"],
                                    umbral=conf["umbral_global"], boost=conf["boost"])
    return sorted(resultados, key=lambda r: r["similitud"] if r["similitud"] is not None else 0, reverse=True)


def evaluar_recuperacion(embeddings, directorio: Path, preguntas: list[dict] | None = None,
                         umbrales: dict | None = None, configuraciones=CONFIGURACIONES_ABLACION) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Devuelve (detalle por pregunta y configuración, resumen por configuración)."""
    preguntas = preguntas or cargar_preguntas()
    umbrales = umbrales or settings.umbrales()
    documentos = cargar_documentos()
    filas = []
    for nombre, conf in configuraciones:
        indice = _construir_indice(Path(directorio) / re.sub(r"\W+", "_", nombre), embeddings, documentos, conf, umbrales)
        colecciones = ["municipal", "leyes", "chileatiende"] if conf["separar"] else ["municipal", "externa"]
        for p in preguntas:
            if p["tipo"] == "rechazo" and not p["fuentes_esperadas"]:
                continue   # preguntas que no requieren búsqueda (pasaporte, datos personales)
            r = _recuperar(indice, colecciones, p["pregunta"], conf)
            fuentes_rec = [x["archivo"] for x in r]
            esperadas = set(p["fuentes_esperadas"])
            if esperadas:
                encontradas = esperadas & set(fuentes_rec)
                primero = next((i + 1 for i, f in enumerate(fuentes_rec) if f in esperadas), None)
                filas.append({"configuracion": nombre, "id": p["id"], "recall": len(encontradas) / len(esperadas),
                              "hit": float(bool(encontradas)), "mrr": 1 / primero if primero else 0.0,
                              "n_fragmentos": len(r), "fuentes": ", ".join(dict.fromkeys(fuentes_rec))})
        for q in CONSULTAS_NEGATIVAS:
            r = _recuperar(indice, colecciones, q, conf)
            filas.append({"configuracion": nombre, "id": "NEG", "rechazo_correcto": float(not r), "n_fragmentos": len(r)})
    detalle = pd.DataFrame(filas)
    positivas = detalle[detalle["id"] != "NEG"]
    resumen = positivas.groupby("configuracion", sort=False)[["recall", "hit", "mrr"]].mean().round(3)
    resumen["rechazo_fuera_de_tema"] = detalle[detalle["id"] == "NEG"].groupby("configuracion", sort=False)["rechazo_correcto"].mean().round(3)
    resumen["n_preguntas"] = positivas.groupby("configuracion", sort=False).size()
    return detalle, resumen.reset_index()


def calibrar_umbrales(indice: IndiceChroma, preguntas: list[dict] | None = None) -> dict:
    """Busca, para cada índice, el umbral que mejor separa preguntas del caso de preguntas ajenas.

    Positivo: la similitud del mejor fragmento de una fuente esperada en ese índice.
    Negativo: la similitud del mejor fragmento para una consulta ajena.
    Se elige el umbral que maximiza (positivos retenidos − negativos retenidos).
    """
    preguntas = preguntas or cargar_preguntas()
    resultado = {}
    for coleccion in ("municipal", "leyes", "chileatiende"):
        archivos = {r["metadata"]["archivo"] for r in indice.corpus(coleccion)}
        positivos = []
        for p in preguntas:
            esperadas = set(p["fuentes_esperadas"]) & archivos
            if not esperadas:
                continue
            r = indice.buscar(coleccion, p["pregunta"], k=8, hibrida=False, umbral=-1, boost=False)
            sims = [x["similitud"] for x in r if x["archivo"] in esperadas and x["similitud"] is not None]
            if sims:
                positivos.append(max(sims))
        negativos = [max([x["similitud"] for x in indice.buscar(coleccion, q, k=1, hibrida=False, umbral=-1)] or [0])
                     for q in CONSULTAS_NEGATIVAS]
        if not positivos:
            continue
        mejor, mejor_puntaje = None, -9
        for i in range(10, 80):
            u = i / 100
            puntaje = sum(s >= u for s in positivos) / len(positivos) - sum(s >= u for s in negativos) / len(negativos)
            if puntaje > mejor_puntaje:
                mejor, mejor_puntaje = u, puntaje
        resultado[coleccion] = {"umbral": mejor, "positivos": len(positivos), "separacion": round(mejor_puntaje, 3)}
    return resultado


# ---------------------------------------------------------------------------------------------
# 2. Escenarios: decisiones del agente
# ---------------------------------------------------------------------------------------------

def ejecutar_escenario(escenario: dict, contenedor, crear_agente) -> dict:
    """Ejecuta los turnos de un escenario sobre una base reiniciada y compara con lo esperado."""
    contenedor.registro.inicializar(contenedor.fecha())
    agente = crear_agente()
    thread = f"eval-{escenario['id']}-{time.time_ns()}"
    salida = None
    for turno in escenario["turnos"]:
        if turno.get("reiniciar_agente"):
            agente = crear_agente(agente.checkpointer)   # simula cerrar y volver a abrir la app
        contenedor.condiciones.clear()
        contenedor.condiciones.update(turno.get("condiciones", {}))
        salida = agente.conversar(turno["texto"], thread, turno["vecino_id"])
        if salida.get("pendiente_aprobacion") is not None:
            salida = agente.resolver_aprobacion(thread, turno.get("aprobar", True))
    contenedor.condiciones.clear()
    esp = escenario["esperado"]
    llamadas = [o["herramienta"] for o in salida.get("observaciones", [])]
    escrituras = [o["herramienta"] for o in salida.get("observaciones", []) if o.get("tipo") == "escritura"]
    return {
        "id": escenario["id"], "descripcion": escenario["descripcion"],
        "regla": salida["decision"]["regla_id"], "accion": salida["decision"]["accion"],
        "regla_ok": salida["decision"]["regla_id"] == esp["regla"], "accion_ok": salida["decision"]["accion"] == esp["accion"],
        "herramientas_ok": set(esp["herramientas"]) <= set(llamadas),
        "escrituras_ok": set(escrituras) == set(esp["escrituras"]),
        "replanificaciones": salida.get("replanificaciones", 0),
        "replanificacion_ok": salida.get("replanificaciones", 0) == esp.get("replanificaciones", 0),
        "cita_valida": (salida.get("validacion") or {}).get("cita_valida"),
        "latencia_s": salida.get("latencia_s"), "respuesta": salida.get("respuesta", ""),
    }


def evaluar_escenarios(contenedor, crear_agente, escenarios: list[dict] | None = None) -> pd.DataFrame:
    return pd.DataFrame([ejecutar_escenario(e, contenedor, crear_agente) for e in (escenarios or cargar_escenarios())])


PROMPT_LLM_PURO = ("Eres el asistente de trámites de la Municipalidad de Curacaví. Atiende al vecino {vecino}. "
                   "Usa las herramientas disponibles para consultar, registrar solicitudes, agendar, escalar y notificar "
                   "cuando corresponda. Responde en español.")


def evaluar_llm_puro(llm, contenedor, escenarios: list[dict] | None = None, max_herramientas: int = 8) -> pd.DataFrame:
    """Línea de comparación: un agente que decide TODO con el LLM (sin planner de reglas).

    Solo se usa el primer turno de cada escenario. Mide si llamó a las herramientas esperadas y si
    hizo escrituras correctas o indebidas.
    """
    from langchain.agents import create_agent
    from langchain.agents.middleware import ToolCallLimitMiddleware
    from langchain_core.messages import AIMessage
    from agente.adaptadores.entrada.herramientas import NOMBRES_POR_TIPO, todas

    herramientas = todas(contenedor.herramientas())
    nombres_escritura = set(NOMBRES_POR_TIPO["escritura"])
    filas = []
    for e in escenarios or cargar_escenarios():
        contenedor.registro.inicializar(contenedor.fecha())
        turno = e["turnos"][0]
        contenedor.condiciones.clear()
        contenedor.condiciones.update(turno.get("condiciones", {}))
        agente = create_agent(llm, tools=herramientas, system_prompt=PROMPT_LLM_PURO.format(vecino=turno["vecino_id"]),
                              middleware=[ToolCallLimitMiddleware(run_limit=max_herramientas, exit_behavior="continue")])
        inicio = time.time()
        try:
            r = con_reintento(lambda: agente.invoke({"messages": [("user", turno["texto"])]}, {"recursion_limit": 30}))
        except CuotaAgotadaError:
            break
        llamadas = [tc["name"] for m in r["messages"] if isinstance(m, AIMessage) for tc in m.tool_calls]
        escrituras = [n for n in llamadas if n in nombres_escritura]
        esp = e["esperado"]
        filas.append({"id": e["id"], "herramientas_ok": set(esp["herramientas"]) <= set(llamadas),
                      "escrituras_ok": set(escrituras) == set(esp["escrituras"]),
                      "escrituras_indebidas": len(set(escrituras) - set(esp["escrituras"])),
                      "n_llamadas": len(llamadas), "latencia_s": round(time.time() - inicio, 2)})
    contenedor.condiciones.clear()
    return pd.DataFrame(filas)


# ---------------------------------------------------------------------------------------------
# 3. Respuestas: métricas deterministas + juez
# ---------------------------------------------------------------------------------------------

PATRON_RUT = re.compile(r"\b\d{1,2}\.?\d{3}\.?\d{3}-[\dkK]\b")
PATRON_TELEFONO = re.compile(r"(\+?56\s?)?9\s?\d{4}\s?\d{4}")

PROMPT_JUEZ = """Eres un evaluador estricto de un asistente de trámites municipales.

Pregunta: {pregunta}
Respuesta de referencia: {referencia}
Contexto recuperado por las herramientas:
{contexto}

Respuesta generada:
{respuesta}

Evalúa con un número entre 0 y 1:
- correctness: ¿la respuesta generada contiene la información clave de la referencia sin contradecirla?
  Si la pregunta debía rechazarse o no había información, puntúa 1 si la respuesta lo reconoce.
- faithfulness: ¿todo lo afirmado está respaldado por el contexto recuperado (no inventa)?
Responde SOLO con JSON: {{"correctness": x, "faithfulness": y, "comentario": "..."}}"""


def juzgar(juez, pregunta: str, referencia: str, contexto: str, respuesta: str) -> dict:
    r = con_reintento(lambda: juez.invoke(PROMPT_JUEZ.format(pregunta=pregunta, referencia=referencia,
                                                             contexto=contexto[:6000], respuesta=respuesta)))
    texto = texto_de(r)
    m = re.search(r"\{.*\}", texto, re.DOTALL)
    try:
        datos = json.loads(m.group(0)) if m else {}
        return {"correctness": float(datos.get("correctness")), "faithfulness": float(datos.get("faithfulness")),
                "comentario_juez": str(datos.get("comentario", ""))[:300]}
    except (TypeError, ValueError):
        pass
    # Respaldo: JSON cortado o con texto alrededor; se leen los dos puntajes si aparecen.
    puntajes = {k: re.search(rf'"?{k}"?\s*:\s*([01](?:\.\d+)?)', texto) for k in ("correctness", "faithfulness")}
    if all(puntajes.values()):
        return {**{k: float(v.group(1)) for k, v in puntajes.items()}, "comentario_juez": texto[:300]}
    return {"correctness": None, "faithfulness": None, "comentario_juez": f"Respuesta no interpretable: {texto[:200]}"}


def metricas_deterministas(pregunta: dict, salida: dict) -> dict:
    llamadas = {o["herramienta"] for o in salida.get("observaciones", [])}
    respuesta = salida.get("respuesta", "")
    validacion = salida.get("validacion") or {}
    usadas = validacion.get("etiquetas_usadas", [])
    nivel = pregunta.get("nivel_esperado")
    letra = cat.nivel_info(nivel)["etiqueta"] if nivel else None
    fila = {
        "herramienta_correcta": float(set(pregunta["herramientas_requeridas"]) <= llamadas) if pregunta["herramientas_requeridas"] else float(salida["decision"]["regla_id"] in ("R1", "R2", "R4")),
        "cita_fuentes": float("**Fuentes**" in respuesta or "No encontré" in respuesta),
        "cita_valida": float(bool(validacion.get("cita_valida"))),
        "tipo_fuente_correcto": float(any(u.startswith(letra) for u in usadas)) if letra else None,
        "privacidad": float(not PATRON_RUT.search(respuesta) and not PATRON_TELEFONO.search(respuesta)) if pregunta["tipo"] == "rechazo" else None,
    }
    return fila


def evaluar_respuestas(crear_agente, contenedor, preguntas: list[dict] | None = None, juez=None,
                       cache: Path | None = None, etiqueta: str = "hibrido") -> pd.DataFrame:
    """Responde cada pregunta con el agente y la evalúa. La caché evita repetir llamadas al LLM y al juez."""
    preguntas = preguntas or cargar_preguntas()
    cache = Path(cache or settings.EVIDENCE_DIR / f"cache_respuestas_{etiqueta}.json")
    guardado = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else {}
    # Solo se reutilizan respuestas válidas: las guardadas con su modo de redacción y sin fallo del LLM.
    # (Una respuesta extractiva por cuota agotada no debe quedar en caché como si fuera del LLM.)
    guardado = {k: v for k, v in guardado.items() if "modo_redaccion" in v and not v.get("aviso_llm")}
    filas = []
    for p in preguntas:
        if p["id"] not in guardado:
            contenedor.registro.inicializar(contenedor.fecha())
            try:
                salida = crear_agente().conversar(p["pregunta"], f"preg-{p['id']}-{time.time_ns()}", "V-009")
            except CuotaAgotadaError:
                break
            if (salida.get("aviso_llm") or "").startswith("CuotaAgotadaError"):
                break   # cuota diaria agotada: se detiene sin guardar una respuesta que no es del LLM
            contexto = "\n".join(f"[{o['herramienta']}] {json.dumps(o['resultado'], ensure_ascii=False, default=str)[:1500]}"
                                 for o in salida.get("observaciones", []))
            guardado[p["id"]] = {"respuesta": salida["respuesta"], "contexto": contexto, "latencia_s": salida["latencia_s"],
                                 **metricas_deterministas(p, salida), "regla": salida["decision"]["regla_id"],
                                 "modo_redaccion": salida.get("modo_redaccion"), "aviso_llm": salida.get("aviso_llm")}
        if juez is not None and guardado[p["id"]].get("correctness") is None:   # incluye juicios no interpretables
            try:
                guardado[p["id"]].update(juzgar(juez, p["pregunta"], p["respuesta_referencia"],
                                                guardado[p["id"]]["contexto"], guardado[p["id"]]["respuesta"]))
            except CuotaAgotadaError:
                juez = None   # se detiene el juez; lo avanzado queda en caché
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(guardado, ensure_ascii=False, indent=1), encoding="utf-8")
        filas.append({"id": p["id"], "categoria": p["categoria"], **{k: v for k, v in guardado[p["id"]].items()
                                                                       if k not in ("contexto",)}})
    return pd.DataFrame(filas)
