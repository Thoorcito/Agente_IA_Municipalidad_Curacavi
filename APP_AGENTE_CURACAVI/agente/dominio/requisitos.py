"""Requisitos de cada trámite (dominio).

Compara lo que el vecino dice tener con la lista de requisitos del trámite y separa el requisito
legal del antecedente que pide la municipalidad (cada requisito trae su fundamento tipificado).
Son funciones puras: reciben el catálogo de trámites (data/requisitos.json) como parámetro.
"""
import json
import re
from functools import lru_cache

from agente.dominio import citas
from agente.dominio.texto import normalizar

@lru_cache(maxsize=1)
def cargar_catalogo() -> dict:
    """Trámites con sus requisitos y fundamentos (data/requisitos.json, dato de referencia)."""
    from agente.configuracion import settings

    return json.loads(settings.REQUISITOS.read_text(encoding="utf-8"))["tramites"]


NEGACION = r"\b(?:no tengo|me faltan?|sin|todavia no tengo|aun no tengo|no traigo)\b"


def _menciona(texto_normalizado: str, sinonimo: str) -> bool:
    """Coincidencia por palabra completa (evita que "seguro" calce dentro de "asegurado")."""
    return re.search(rf"(?<![a-z0-9]){re.escape(normalizar(sinonimo))}(?![a-z0-9])", texto_normalizado) is not None


def detectar_documentos(tramite: dict | None, texto: str) -> list[str]:
    """Ids de requisitos que el texto menciona. Ignora los mencionados como faltantes
    ("no tengo el SOAP", "me falta la revisión técnica")."""
    if not tramite:
        return []
    texto_n = normalizar(texto)
    # Se recortan las partes negadas: "no tengo X", "me falta X", "sin X" hasta la siguiente coma o punto.
    negadas = " ".join(re.findall(NEGACION + r"([^,.;]*)", texto_n))
    afirmado = re.sub(NEGACION + r"[^,.;]*", " ", texto_n)
    return [req["id"] for req in tramite["requisitos"]
            if any(_menciona(afirmado, s) for s in req["sinonimos"])
            and not any(_menciona(negadas, s) for s in req["sinonimos"])]


def _fundamentos_citados(fundamentos: list[dict]) -> list[dict]:
    return [{"tipo": f["tipo"], "cita": citas.formatear_cita(f["fuente"], f.get("articulo")), "detalle": f["detalle"],
             "fuente_id": f["fuente"], "articulo": f.get("articulo")} for f in fundamentos]


def verificar(tramites: dict, tramite_id: str, documentos_declarados: list[str]) -> dict:
    """Devuelve presentados, faltantes (con su fundamento legal, municipal u orientativo) y etapas."""
    tramite = tramites.get(tramite_id)
    if not tramite:
        return {"error": f"Trámite desconocido: {tramite_id}"}
    ids_validos = {r["id"] for r in tramite["requisitos"]}
    presentados = set()
    for d in documentos_declarados:
        presentados.update([d] if d in ids_validos else detectar_documentos(tramite, d))
    faltantes, opcionales, etapas = [], [], []
    for req in tramite["requisitos"]:
        ficha = {"id": req["id"], "nombre": req["nombre"], "fundamentos": _fundamentos_citados(req["fundamentos"])}
        if req["tipo"] == "etapa":
            etapas.append(ficha)
        elif req["id"] in presentados:
            continue
        elif req["obligatorio"]:
            faltantes.append(ficha)
        else:
            opcionales.append(ficha)
    return {"tramite": tramite["nombre"], "tramite_id": tramite_id, "unidad": tramite["unidad"],
            "completos": not faltantes, "presentados": sorted(presentados),
            "presentados_nombres": [r["nombre"] for r in tramite["requisitos"] if r["id"] in presentados],
            "faltantes": faltantes, "opcionales_no_presentados": opcionales, "etapas": etapas,
            "valor": tramite["valor"], "requiere_hora": tramite["requiere_hora"]}
