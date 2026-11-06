"""Percepción: entiende el mensaje del vecino (intención, trámite, folio, documentos y riesgos).

Primero se aplican reglas deterministas (expresiones regulares): son rápidas, gratuitas y
predecibles. Solo si no se logra identificar la intención y hay un LLM disponible, se le pide al
modelo que clasifique el mensaje con salida estructurada. Si el LLM falla, se mantiene lo
determinista (el agente nunca queda bloqueado por el modelo).
"""
import re
from typing import Literal, Optional

from pydantic import BaseModel, Field

from agente.dominio.modelo import normalizar_folio
from agente.dominio.requisitos import cargar_catalogo, detectar_documentos
from agente.dominio.texto import normalizar

INTENCIONES = ["riesgo", "fuera_alcance", "consultar_estado", "consultar_informacion",
               "iniciar_tramite", "aportar_antecedentes", "desconocida"]

PATRONES_TRAMITE = [
    ("reclamo", r"\b(reclamo|reclamar|queja)\b"),
    ("permiso_circulacion", r"permiso de circulacion|permiso del (auto|vehiculo|carro)|renovar (el )?permiso"),
    ("renovacion_licencia", r"licencia.*\b(renov\w*|control)\b|\b(renov\w*|control)\b.*licencia"),
    ("primera_licencia_b", r"licencia"),
    ("patente_comercial", r"patente|almacen|negocio|local comercial|emprendimiento"),
]

# Trámites que no realiza la municipalidad (procedimiento interno, documento simulado).
FUERA_DE_ALCANCE = [
    (r"pasaporte|certificado de (nacimiento|matrimonio|defuncion)|(sacar|renovar|obtener) (la |mi )?(cedula|carnet)",
     "Servicio de Registro Civil e Identificación"),
    (r"(hacer|sacar|tramitar) (el |mi )?inicio de actividades|declaracion de renta|impuesto a la renta",
     "Servicio de Impuestos Internos (SII)"),
    (r"(hacer|sacar|pasar) (la |mi )?revision tecnica|planta de revision", "una planta de revisión técnica autorizada"),
]

PATRON_INYECCION = r"olvida (tus|las|todas) (reglas|instrucciones)|ignora (tus|las|todas)|system prompt|actua como|desactiva (tus|las)"
PATRON_DATOS = r"\b(rut|telefono|domicilio|direccion|correo|celular)\b"
PATRON_TERCERO = r"(de la persona|del vecino|de quien|que ingreso|del solicitante|de otra persona|de mi vecin|de un tercero)"
PATRON_INICIAR = (r"\b(quiero|necesito|vengo a|deseo|me gustaria|quisiera|voy a)\b.*\b(renovar|sacar|obtener|solicitar|"
                  r"tramitar|pagar|abrir|ingresar|hacer|poner|presentar|reclamar)\b|\bponer un reclamo\b")
PATRON_PREGUNTA = r"\?|\b(que|cuanto|cuando|donde|como|cual|cuales|requisitos|hasta cuando|que necesito|se puede)\b"
PATRON_APORTA = r"\b(ya tengo|ya consegui|traigo|aqui tengo|consegui|ahora tengo|adjunto)\b"
PATRON_SALUDO = r"(hola|buenas|buenos dias|buenas tardes|buenas noches|saludos|que tal)([\s,.!¡?¿]+(hola|buenas|buenos dias|buenas tardes|buenas noches|que tal|como esta|como estas))*[\s,.!?]*"
PATRON_FECHA = re.compile(r"(\d{1,2}) de (enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|"
                          r"noviembre|diciembre)(?: de (\d{4}))?|(\d{1,2})/(\d{1,2})/(\d{4})")
MESES = {m: i for i, m in enumerate(["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                                     "septiembre", "octubre", "noviembre", "diciembre"], start=1)}


def detectar_tramite(texto_n: str) -> Optional[str]:
    for tramite_id, patron in PATRONES_TRAMITE:
        if re.search(patron, texto_n):
            return tramite_id
    return None


def detectar_calculo_plazo(texto_n: str, anio_por_defecto: int) -> Optional[dict]:
    """Detecta preguntas del tipo "ingresé el 15 de septiembre ... 10 días hábiles"."""
    dias = re.search(r"(\d+)\s*dias habiles", texto_n)
    fecha = PATRON_FECHA.search(texto_n)
    if not (dias and fecha):
        return None
    if fecha.group(1):
        anio = int(fecha.group(3) or anio_por_defecto)
        iso = f"{anio:04d}-{MESES[fecha.group(2)]:02d}-{int(fecha.group(1)):02d}"
    else:
        iso = f"{int(fecha.group(6)):04d}-{int(fecha.group(5)):02d}-{int(fecha.group(4)):02d}"
    return {"fecha_inicio": iso, "dias_habiles": int(dias.group(1))}


class PercepcionLLM(BaseModel):
    """Esquema que se le pide al LLM cuando las reglas no bastan."""
    intencion: Literal["consultar_estado", "consultar_informacion", "iniciar_tramite", "fuera_alcance", "desconocida"]
    tramite_id: Optional[Literal["permiso_circulacion", "primera_licencia_b", "renovacion_licencia",
                                 "patente_comercial", "reclamo"]] = Field(default=None)


def percibir(texto: str, previo: dict | None = None, anio: int = 2026, llm=None, requisitos: dict | None = None) -> dict:
    """Devuelve la percepción del mensaje, combinada con el contexto previo de la conversación.

    previo: tramite_activo, esperando ("antecedentes" si el agente pidió documentos) y documentos ya
    declarados en turnos anteriores (memoria de corto plazo).
    requisitos: catálogo de trámites (lo inyecta el contenedor; por defecto, data/requisitos.json).
    """
    previo = previo or {}
    requisitos = requisitos if requisitos is not None else cargar_catalogo()
    t = normalizar(texto)
    p = {"texto": texto, "intencion": "desconocida", "tramite_id": None, "folio": normalizar_folio(texto),
         "documentos": [], "riesgo": None, "fuera_alcance": None, "calculo_plazo": None, "fuente_nlu": "reglas"}

    if re.search(PATRON_INYECCION, t):
        p["riesgo"] = "inyeccion_de_instrucciones"
    elif re.search(PATRON_DATOS, t) and (re.search(PATRON_TERCERO, t) or re.search(r"\b\d{1,2}\.?\d{3}\.?\d{3}-[\dk]\b", t)):
        p["riesgo"] = "datos_personales_de_terceros"

    p["tramite_id"] = detectar_tramite(t)
    # Un trámite de otro organismo gana, salvo que el vecino nombre explícitamente un trámite municipal
    # ("quiero sacar la patente; ya hice el inicio de actividades").
    explicito = re.search(r"patente|licencia|permiso de circulacion|reclamo", t)
    for patron, institucion in FUERA_DE_ALCANCE:
        if re.search(patron, t) and not (p["tramite_id"] and explicito):
            p["fuera_alcance"] = {"institucion": institucion}
            p["tramite_id"] = None
            break

    continua = previo.get("esperando") == "antecedentes" and previo.get("tramite_activo")
    if continua and (not p["tramite_id"] or p["tramite_id"] == previo["tramite_activo"]):
        p["tramite_id"] = previo["tramite_activo"]
    if p["tramite_id"]:
        p["documentos"] = detectar_documentos(requisitos.get(p["tramite_id"]), texto)
    p["calculo_plazo"] = detectar_calculo_plazo(t, anio)

    # Prioridad de intenciones: riesgo > fuera de alcance > estado por folio > aportar > iniciar > consultar
    if p["riesgo"]:
        p["intencion"] = "riesgo"
    elif p["fuera_alcance"]:
        p["intencion"] = "fuera_alcance"
    elif p["folio"]:
        p["intencion"] = "consultar_estado"
    elif continua and (p["documentos"] or re.search(PATRON_APORTA, t)):
        p["intencion"] = "aportar_antecedentes"
    elif p["tramite_id"] and (p["documentos"] or (re.search(PATRON_INICIAR, t) and not re.search(PATRON_PREGUNTA, t))):
        p["intencion"] = "iniciar_tramite"
    elif p["tramite_id"] == "reclamo" and re.search(PATRON_INICIAR, t):
        p["intencion"] = "iniciar_tramite"
    elif p["tramite_id"] or p["calculo_plazo"] or re.search(PATRON_PREGUNTA, t):
        p["intencion"] = "consultar_informacion"

    # Un saludo solo ("hola, buenas tardes") se responde pidiendo aclaración (R10) sin gastar una llamada al LLM.
    if p["intencion"] == "desconocida" and re.fullmatch(PATRON_SALUDO, t.strip()):
        p["fuente_nlu"] = "reglas (saludo)"
    elif p["intencion"] == "desconocida" and llm is not None:
        try:
            r = llm.with_structured_output(PercepcionLLM).invoke(
                "Clasifica el mensaje de un vecino a la Municipalidad de Curacaví. "
                f"Mensaje: {texto!r}")
            intencion = r.intencion
            # Guarda: el LLM no puede inventar una consulta de estado sin folio (p. ej. clasificar un saludo
            # como "consultar_estado"); sin folio que consultar, se pide aclaración (R10).
            if intencion == "consultar_estado" and not p["folio"]:
                intencion = "desconocida"
            p.update({"intencion": intencion, "tramite_id": r.tramite_id or p["tramite_id"], "fuente_nlu": "llm"})
        except Exception:  # el modelo gratuito puede fallar: se mantiene la percepción por reglas
            p["fuente_nlu"] = "reglas (LLM no disponible)"
    return p
