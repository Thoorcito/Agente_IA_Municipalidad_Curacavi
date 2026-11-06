"""Planificador (servicio de dominio): decide QUÉ hacer y en qué ORDEN, a partir de los hechos reunidos.

decidir(hechos) es una función pura (sin LLM, sin base de datos): con los mismos hechos siempre
entrega la misma decisión. Por eso es fácil de probar y de explicar.

Las reglas se evalúan de arriba hacia abajo y gana la PRIMERA que se cumple. El orden refleja
prioridades: primero la seguridad y lo que no corresponde a la municipalidad, después los casos
que requieren intervención humana (plazos vencidos), y al final el flujo normal.

Cada decisión trae:
- pasos: el plan ordenado de herramientas a ejecutar (con sus argumentos),
- fundamentos: en qué se basa, indicando el TIPO de fuente (legal, municipal, orientativo, simulado),
- requiere_aprobacion: si un funcionario debe confirmar antes de ejecutar (humano en el ciclo).

El planner no ejecuta nada: devuelve el plan. Quien lo ejecuta es el orquestador (agente/aplicacion/orquestador.py)
a través de las herramientas. Los parámetros de negocio (plazos, aprobación humana) se leen de
agente/configuracion/settings.py, la fuente única de configuración.
"""
from dataclasses import asdict, dataclass, field
from datetime import date

from agente.dominio import citas as cat
from agente.dominio.modelo import EstadoSolicitud
from agente.dominio.plazos import parsear_fecha, sumar_dias_habiles, sumar_meses
from agente.configuracion import settings

FOLIO_PENDIENTE = "{folio}"   # el ejecutor lo reemplaza por el folio creado en un paso anterior


@dataclass
class Decision:
    regla_id: str
    regla: str
    accion: str
    motivo: str
    fundamentos: list = field(default_factory=list)
    pasos: list = field(default_factory=list)
    requiere_aprobacion: bool = False
    notas: list = field(default_factory=list)

    def a_dict(self) -> dict:
        return asdict(self)


TIPO_POR_NIVEL = {1: "legal", 2: "normativa municipal", 3: "municipal", 4: "orientativo", 5: "simulado"}


def fundamento(tipo: str, fuente_id: str, detalle: str, articulo: str | None = None) -> dict:
    return {"tipo": tipo, "cita": cat.formatear_cita(fuente_id, articulo), "detalle": detalle,
            "fuente_id": fuente_id, "articulo": articulo}


def fundamento_guia(fuente_id: str) -> dict:
    """Fundamento con el tipo deducido del nivel de la fuente (evita etiquetar mal un documento simulado)."""
    return fundamento(TIPO_POR_NIVEL[cat.fuente(fuente_id)["nivel"]], fuente_id, "Requisitos y forma de atención del trámite")


FUND_SIMULADO_DATOS = ("simulado", "procedimiento_simulado", "El personal y los canales digitales no entregan datos personales de terceros")
FUND_SIMULADO_ALCANCE = ("simulado", "procedimiento_simulado", "Trámites que no realiza la municipalidad")


# ---------------------------------------------------------------------------------------------
# Cálculo del plazo aplicable a una solicitud abierta (se usa al reunir los hechos)
# ---------------------------------------------------------------------------------------------

def evaluar_plazo(solicitud: dict, hoy: date) -> dict | None:
    """Determina qué plazo aplica a una solicitud abierta y si está vencido.

    Distingue el TIPO de plazo, porque no es lo mismo un plazo interno (política de atención,
    aquí simulada) que uno informado por una guía municipal o uno fijado por ley.
    """
    if not solicitud or solicitud.get("estado") not in [e.value for e in EstadoSolicitud if e.abierto]:
        return None
    computo = fundamento("legal", "ley_19880", "Los plazos de días son hábiles (sin sábados, domingos ni festivos)", "25")
    tramite = solicitud.get("tramite_id")
    if solicitud["estado"] == "Observada":
        base = parsear_fecha(solicitud["ultima_actualizacion"])
        dias, tipo = settings.PLAZO_SUBSANAR_DIAS, "legal para completar antecedentes (corre para el vecino)"
        fund = [fundamento("legal", "ley_19880", "Plazo de cinco días para subsanar la solicitud incompleta", "31"),
                fundamento("simulado", "procedimiento_simulado", "Observada: el vecino tiene 5 días hábiles para completar"), computo]
        responsable = "vecino"
    elif tramite == "reclamo":
        base = parsear_fecha(solicitud["fecha_ingreso"])
        dias, tipo, responsable = settings.PLAZO_OIRS_DIAS_HABILES, "interno (procedimiento simulado)", "municipalidad"
        fund = [fundamento("simulado", "procedimiento_simulado", "Los reclamos OIRS se responden en un máximo de 10 días hábiles"), computo]
    elif tramite == "patente_comercial":
        base = parsear_fecha(solicitud["fecha_ingreso"])
        dias, tipo, responsable = settings.PLAZO_PATENTE_DIAS, "informado por la guía municipal", "municipalidad"
        fund = [fundamento("municipal", "guia_patentes", "Revisión en un plazo de 10 días para otorgamiento (la guía no precisa si son hábiles; se computan como hábiles)"), computo]
    else:
        base = parsear_fecha(solicitud["fecha_ingreso"])
        dias, tipo, responsable = None, "legal máximo", "municipalidad"
        fund = [fundamento("legal", "ley_19880", "El procedimiento no puede exceder de 6 meses", "27")]
        limite = sumar_meses(base, settings.PLAZO_MAXIMO_PROCEDIMIENTO_MESES)
        return {"tipo": tipo, "dias_habiles": None, "vencimiento": limite.isoformat(), "vencido": hoy > limite,
                "responsable": responsable, "fundamentos": fund}
    vencimiento, _ = sumar_dias_habiles(base, dias)
    return {"tipo": tipo, "dias_habiles": dias, "vencimiento": vencimiento.isoformat(), "vencido": hoy > vencimiento,
            "responsable": responsable, "fundamentos": fund}


# ---------------------------------------------------------------------------------------------
# Reglas (en orden de prioridad)
# ---------------------------------------------------------------------------------------------

def _paso(herramienta: str, **args) -> dict:
    return {"herramienta": herramienta, "args": args}


def _registro_o_actualizacion(h: dict, estado: str, observacion: str, fundamento_txt: str) -> dict:
    """Si el trámite ya tiene folio en esta conversación se actualiza; si no, se registra."""
    if h.get("folio_en_curso"):
        return _paso("actualizar_solicitud", folio=h["folio_en_curso"], estado=estado, observacion=observacion,
                     fundamento=fundamento_txt)
    return _paso("registrar_solicitud", vecino_id=h["vecino_id"], tramite_id=h["tramite_id"], estado=estado,
                 observacion=observacion)


def _folio(h: dict) -> str:
    return h.get("folio_en_curso") or FOLIO_PENDIENTE


def _notas_historial(h: dict) -> list:
    return [f"Antecedente: la solicitud {s['folio']} ({s['fecha_ingreso']}) de este mismo trámite quedó "
            f"«{s['estado']}»: {s['observacion']}" for s in h.get("previos_mismo_tramite", [])]


def r1_seguridad(h):
    if not h.get("riesgo"):
        return None
    return Decision("R1", "Seguridad y privacidad", "rechazar_solicitud_riesgosa",
                    f"La solicitud implica {h['riesgo'].replace('_', ' ')}; no se entregan datos personales de terceros "
                    "ni se modifican las instrucciones del asistente.",
                    [fundamento(*FUND_SIMULADO_DATOS)])


def r2_fuera_de_alcance(h):
    if not h.get("fuera_alcance"):
        return None
    inst = h["fuera_alcance"]["institucion"]
    return Decision("R2", "Fuera del alcance municipal", "derivar_institucion_externa",
                    f"El trámite no lo realiza la municipalidad; corresponde a {inst}.", [fundamento(*FUND_SIMULADO_ALCANCE)])


def r3_plazo_vencido(h):
    sol, plazo = h.get("solicitud"), h.get("plazo")
    if h.get("intencion") != "consultar_estado" or not (sol and plazo and plazo["vencido"]):
        return None
    if plazo["responsable"] == "vecino":
        return None   # vencido el plazo del vecino no se escala: se informa (lo resuelve R4)
    motivo = (f"La solicitud {sol['folio']} ({sol['tramite']}) sigue «{sol['estado']}» y venció el plazo "
              f"{plazo['tipo']} el {plazo['vencimiento']}.")
    destino = "Jefatura OIRS" if sol.get("tramite_id") == "reclamo" else f"Jefatura de {sol['unidad']}"
    texto_fund = "; ".join(f"{f['cita']} ({f['tipo']})" for f in plazo["fundamentos"])
    return Decision("R3", "Plazo vencido", "escalar_por_plazo", motivo, plazo["fundamentos"], [
        _paso("derivar_o_escalar", folio=sol["folio"], destino=destino, motivo=motivo, fundamento=texto_fund),
        _paso("notificar_vecino", vecino_id=h["vecino_id"], folio=sol["folio"],
              mensaje=f"Su solicitud {sol['folio']} fue escalada a {destino} por plazo vencido."),
    ], requiere_aprobacion=settings.APROBACION_HUMANA)


def r4_informar_estado(h):
    if h.get("intencion") != "consultar_estado":
        return None
    sol, plazo = h.get("solicitud"), h.get("plazo")
    if not sol or not sol.get("encontrado"):
        return Decision("R4", "Consulta de estado", "informar_estado", "El folio indicado no existe en el registro.")
    motivo = f"Solicitud {sol['folio']}: «{sol['estado']}» en {sol['unidad']}."
    fund = [fundamento("simulado", "procedimiento_simulado", "Significado de los estados de una solicitud")]
    if plazo:
        motivo += f" Plazo {plazo['tipo']}: vence el {plazo['vencimiento']}" + (" (vencido)." if plazo["vencido"] else ".")
        fund += plazo["fundamentos"]
    return Decision("R4", "Consulta de estado", "informar_estado", motivo, fund)


def r5_consulta_informacion(h):
    if h.get("intencion") != "consultar_informacion":
        return None
    texto, tramite = h["texto"], h.get("tramite_id") or ""
    pasos = [_paso("buscar_informacion_municipal", consulta=texto, tramite=tramite),
             _paso("buscar_normativa_nacional", consulta=texto, tramite=tramite),
             _paso("buscar_orientacion_chileatiende", consulta=texto, tramite=tramite)]
    if h.get("tema_de_plazos"):
        pasos.append(_paso("contrastar_fuentes", tema=texto, tramite_id=tramite))
    if h.get("calculo_plazo"):
        pasos.append(_paso("calcular_plazo_habil", **h["calculo_plazo"]))
    return Decision("R5", "Consulta de información", "responder_consulta",
                    "Pregunta informativa: se consultan las tres fuentes por separado (ley, municipalidad y ChileAtiende).",
                    pasos=pasos)


def _es_tramite(h):
    return h.get("intencion") in ("iniciar_tramite", "aportar_antecedentes") and h.get("verificacion")


def r6_faltan_antecedentes(h):
    if not _es_tramite(h) or h["verificacion"]["completos"]:
        return None
    faltan = h["verificacion"]["faltantes"]
    nombres = "; ".join(f["nombre"] for f in faltan)
    fund = [f for req in faltan for f in req["fundamentos"]]
    fund.append(fundamento("legal", "ley_19880", "Se requiere al interesado subsanar la falta en un plazo de cinco días", "31"))
    plazo_txt = f"Tiene {settings.PLAZO_SUBSANAR_DIAS} días hábiles para completarlos."
    return Decision("R6", "Faltan antecedentes", "solicitar_antecedentes", f"Faltan: {nombres}.", fund, [
        _registro_o_actualizacion(h, "Observada", f"Faltan antecedentes: {nombres}", "Ley N° 19.880, art. 31"),
        _paso("notificar_vecino", vecino_id=h["vecino_id"], folio=_folio(h),
              mensaje=f"Para continuar su trámite faltan: {nombres}. {plazo_txt}"),
    ], notas=_notas_historial(h))


def r7_sin_cupos(h):
    if not _es_tramite(h) or not h["verificacion"]["requiere_hora"] or (h.get("agenda") or {}).get("cupos"):
        return None
    return Decision("R7", "Sin horas disponibles", "inscribir_lista_espera",
                    "Los antecedentes están completos, pero no hay horas disponibles en la agenda.",
                    [fundamento("municipal", "guia_licencias", "Atención martes a viernes y segundo sábado; reservar con 20 días de anticipación")], [
        _registro_o_actualizacion(h, "Ingresada", "Antecedentes completos; en lista de espera de hora", ""),
        _paso("inscribir_lista_espera", vecino_id=h["vecino_id"], tramite_id=h["tramite_id"], folio=_folio(h)),
        _paso("notificar_vecino", vecino_id=h["vecino_id"], folio=_folio(h),
              mensaje="Sus antecedentes están completos. No hay horas disponibles: quedó en lista de espera y le avisaremos."),
    ], notas=_notas_historial(h) + (["Replanificado: la hora elegida fue tomada por otra persona."] if h.get("cupo_fallido") else []))


def _pasos_tramite_completo(h, observacion: str) -> list:
    pasos = [_registro_o_actualizacion(h, "Ingresada", observacion, "")]
    mensaje = f"Su solicitud de {h['verificacion']['tramite'].lower()} fue ingresada en {h['verificacion']['unidad']}."
    cupos = (h.get("agenda") or {}).get("cupos") or []
    if h["verificacion"]["requiere_hora"] and cupos:
        c = cupos[0]
        pasos.append(_paso("agendar_hora", folio=_folio(h), cupo_id=c["cupo_id"]))
        mensaje += f" Hora reservada: {c['fecha']} a las {c['hora']}."
    if h.get("tramite_id") == "reclamo":
        venc, _ = sumar_dias_habiles(parsear_fecha(h["hoy"]), settings.PLAZO_OIRS_DIAS_HABILES)
        mensaje += f" Plazo interno de respuesta (procedimiento simulado): {venc.isoformat()}."
    pasos.append(_paso("notificar_vecino", vecino_id=h["vecino_id"], folio=_folio(h), mensaje=mensaje))
    return pasos


def r8_reingreso_con_historial(h):
    if not _es_tramite(h) or not h.get("previos_mismo_tramite"):
        return None
    return Decision("R8", "Reingreso con historial", "reingreso_guiado",
                    "Antecedentes completos; el vecino tiene una solicitud anterior rechazada u observada del mismo trámite.",
                    [fundamento_guia(h["tramite_principal_fuente"])],
                    _pasos_tramite_completo(h, "Reingreso: antecedentes completos; revisar motivo del rechazo anterior"),
                    notas=_notas_historial(h) + (["Replanificado: la hora elegida fue tomada por otra persona."] if h.get("cupo_fallido") else []))


def r9_tramite_estandar(h):
    if not _es_tramite(h):
        return None
    return Decision("R9", "Trámite estándar", "registrar_tramite", "Antecedentes completos: se ingresa la solicitud.",
                    [fundamento_guia(h["tramite_principal_fuente"])],
                    _pasos_tramite_completo(h, "Antecedentes completos"),
                    notas=["Replanificado: la hora elegida fue tomada por otra persona."] if h.get("cupo_fallido") else [])


def r10_aclarar(h):
    return Decision("R10", "Aclarar solicitud", "pedir_aclaracion",
                    "No se identificó el trámite o la consulta; se pide al vecino que precise.")


REGLAS = [r1_seguridad, r2_fuera_de_alcance, r3_plazo_vencido, r4_informar_estado, r5_consulta_informacion,
          r6_faltan_antecedentes, r7_sin_cupos, r8_reingreso_con_historial, r9_tramite_estandar, r10_aclarar]

# Tabla legible de las reglas (se usa en DOCUMENTACION/reglas.md, en el notebook y en las pruebas)
TABLA_REGLAS = [
    ("R1", "Seguridad y privacidad", "Intento de manipular instrucciones o pedido de datos de terceros", "rechazar_solicitud_riesgosa"),
    ("R2", "Fuera del alcance municipal", "Trámite de otro organismo (Registro Civil, SII, revisión técnica)", "derivar_institucion_externa"),
    ("R3", "Plazo vencido", "Consulta por folio abierto cuyo plazo (interno, municipal o legal) venció", "escalar_por_plazo (con aprobación humana)"),
    ("R4", "Consulta de estado", "Consulta por folio (sin plazo vencido de la municipalidad)", "informar_estado"),
    ("R5", "Consulta de información", "Pregunta sobre requisitos, costos, plazos o normas", "responder_consulta"),
    ("R6", "Faltan antecedentes", "Trámite iniciado con documentos obligatorios faltantes", "solicitar_antecedentes"),
    ("R7", "Sin horas disponibles", "Trámite completo que requiere hora y la agenda no tiene cupos", "inscribir_lista_espera"),
    ("R8", "Reingreso con historial", "Trámite completo de un vecino con rechazo u observación previa del mismo trámite", "reingreso_guiado"),
    ("R9", "Trámite estándar", "Trámite completo", "registrar_tramite"),
    ("R10", "Aclarar solicitud", "No se reconoce trámite ni consulta", "pedir_aclaracion"),
]


def decidir(hechos: dict) -> Decision:
    """Aplica las reglas en orden de prioridad y devuelve la primera decisión que corresponde."""
    for regla in REGLAS:
        decision = regla(hechos)
        if decision is not None:
            return decision
    raise AssertionError("r10_aclarar siempre decide")  # pragma: no cover
