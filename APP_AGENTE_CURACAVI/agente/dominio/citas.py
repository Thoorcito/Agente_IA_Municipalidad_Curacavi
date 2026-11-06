"""Catálogo de fuentes, citas canónicas, validación de citas y contraste entre fuentes (dominio).

Idea central: una ley nacional, una norma municipal, una guía municipal y una ficha de ChileAtiende
NO valen lo mismo ni se citan igual. El catálogo (data/catalogo_fuentes.json) define para cada documento
su nivel, su título oficial y su cita corta. El LLM solo usa etiquetas ([L1], [M2], [O1]...) y el
código las convierte en la cita exacta. Así el modelo no puede inventar el título de una ley.

El catálogo es un dato de referencia de solo lectura (como una tabla de parámetros): por eso se
carga aquí y no a través de un puerto.
"""
import json
import re
from functools import lru_cache

from agente.dominio.texto import normalizar
from agente.configuracion import settings

# Orden de presentación de los niveles en una respuesta.
ORDEN_NIVELES = [1, 2, 3, 5, 4]
TITULOS_SECCION = {
    1: "Normativa nacional",
    2: "Normativa municipal",
    3: "Información municipal",
    4: "Orientación general (ChileAtiende)",
    5: "Procedimiento interno (documento simulado)",
}


@lru_cache(maxsize=1)
def catalogo() -> dict:
    """Carga el catálogo una sola vez y lo indexa por id de fuente."""
    datos = json.loads(settings.CATALOGO_FUENTES.read_text(encoding="utf-8"))
    return {
        "niveles": {int(k): v for k, v in datos["niveles"].items()},
        "fuentes": {f["id"]: f for f in datos["fuentes"]},
    }


def fuente(fuente_id: str) -> dict:
    """Devuelve la ficha de una fuente; lanza KeyError si no existe (error de programación)."""
    return catalogo()["fuentes"][fuente_id]


def fuente_por_archivo(archivo: str) -> dict | None:
    """Busca una fuente por su nombre de archivo (con o sin carpeta)."""
    nombre = archivo.split("/")[-1]
    for f in catalogo()["fuentes"].values():
        if f["archivo"].split("/")[-1] == nombre:
            return f
    return None


def nivel_info(nivel: int) -> dict:
    return catalogo()["niveles"][int(nivel)]


def formatear_cita(fuente_id: str, articulo: str | None = None, pagina: int | None = None) -> str:
    """Construye la cita canónica según el tipo de fuente.

    - Leyes: "Ley N° 19.880, art. 25" (se cita por artículo, no por página).
    - Guías, fichas y documentos simulados: título + página si existe.
    """
    f = fuente(fuente_id)
    if f["nivel"] == 1:
        cita = f["cita_corta"] + (f", art. {articulo}" if articulo else "")
    else:
        cita = f["cita_corta"] + (f", pág. {pagina}" if pagina else "")
    return cita


def nota_version(fuente_id: str) -> str:
    """Advierte cuando el texto consultado no es la versión vigente (transparencia normativa)."""
    f = fuente(fuente_id)
    if f.get("vigente_al_descargar", True):
        return ""
    return f"Texto consultado: {f['version'].lower()}; verificar la versión vigente en {f['url']}."


def etiquetar(fragmentos: list[dict]) -> list[dict]:
    """Asigna etiquetas por nivel ([L1], [M1], [O1], [S1]) a una lista de fragmentos.

    Fragmentos repetidos (misma fuente y artículo/página) reciben la misma etiqueta.
    """
    contadores: dict[str, int] = {}
    vistas: dict[tuple, str] = {}
    salida = []
    for frag in fragmentos:
        f = fuente(frag["fuente_id"])
        letra = nivel_info(f["nivel"])["etiqueta"]
        clave = (frag["fuente_id"], frag.get("articulo"), frag.get("pagina"))
        if clave not in vistas:
            contadores[letra] = contadores.get(letra, 0) + 1
            vistas[clave] = f"{letra}{contadores[letra]}"
        salida.append({**frag, "etiqueta": vistas[clave], "nivel": f["nivel"],
                       "cita": formatear_cita(frag["fuente_id"], frag.get("articulo"), frag.get("pagina"))})
    return salida


PATRON_ETIQUETA = re.compile(r"\[([LNMOS]\d+)\]")
# Menciones de normas en texto libre: "Ley N° 19.880", "Ley 18.695", "D.L. 3.063", "DFL N° 1".
PATRON_NORMA = re.compile(r"\b(?:Ley|D\.?\s?L\.?|Decreto Ley)\s*(?:N[°º]?\.?\s*)?(\d{1,2}\.?\d{3})", re.IGNORECASE)


def _numeros_respaldados(fragmentos: list[dict]) -> set[str]:
    """Números de norma que aparecen en las fuentes realmente recuperadas (sin puntos)."""
    numeros = set()
    for frag in fragmentos:
        f = fuente(frag["fuente_id"])
        texto = f"{f.get('cita_corta', '')} {f.get('titulo_oficial', '')} {frag.get('texto', '')}"
        numeros.update(n.replace(".", "") for n in PATRON_NORMA.findall(texto))
    return numeros


def validar_citas(texto: str, fragmentos_etiquetados: list[dict]) -> dict:
    """Revisa que cada etiqueta usada exista y que no se nombren leyes que no se recuperaron.

    Devuelve el texto sin etiquetas inválidas y un reporte usado por la evaluación
    (métrica "cita_valida").
    """
    validas = {f["etiqueta"] for f in fragmentos_etiquetados}
    usadas = PATRON_ETIQUETA.findall(texto)
    invalidas = sorted({e for e in usadas if e not in validas})
    limpio = PATRON_ETIQUETA.sub(lambda m: m.group(0) if m.group(1) in validas else "", texto)

    respaldadas = _numeros_respaldados(fragmentos_etiquetados)
    mencionadas = {n.replace(".", "") for n in PATRON_NORMA.findall(texto)}
    no_respaldadas = sorted(mencionadas - respaldadas)

    return {
        "texto": limpio,
        "etiquetas_usadas": sorted(set(usadas) & validas),
        "etiquetas_invalidas": invalidas,
        "normas_no_respaldadas": no_respaldadas,
        "cita_valida": not invalidas and not no_respaldadas,
    }


def bloque_fuentes(fragmentos_etiquetados: list[dict], usadas: list[str] | None = None) -> str:
    """Lista final "Fuentes", agrupada por nivel normativo y con advertencias de versión."""
    usadas_set = set(usadas) if usadas is not None else None
    por_nivel: dict[int, dict[str, dict]] = {}
    for frag in fragmentos_etiquetados:
        if usadas_set is not None and frag["etiqueta"] not in usadas_set:
            continue
        por_nivel.setdefault(frag["nivel"], {})[frag["etiqueta"]] = frag
    if not por_nivel:
        return ""
    lineas = ["**Fuentes**"]
    for nivel in ORDEN_NIVELES:
        if nivel not in por_nivel:
            continue
        lineas.append(f"\n*{TITULOS_SECCION[nivel]}* — {nivel_info(nivel)['naturaleza']}\n")
        for etiqueta, frag in sorted(por_nivel[nivel].items()):
            nota = nota_version(frag["fuente_id"])
            lineas.append(f"- [{etiqueta}] {frag['cita']}" + (f" ({nota})" if nota else ""))
    return "\n".join(lineas)


# ---------------------------------------------------------------------------------------------
# Contraste entre niveles normativos (ley, municipalidad, ChileAtiende)
# ---------------------------------------------------------------------------------------------

MESES = "enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre"
PATRON_PERIODO = re.compile(rf"(\d{{1,2}} de (?:{MESES})|mes de (?:{MESES})|\d+ d[ií]as(?: h[áa]biles)?)", re.IGNORECASE)


def menciones_periodo(texto: str) -> list[str]:
    """Fechas y plazos mencionados en un texto ("31 de marzo", "mes de marzo", "5 días hábiles")."""
    return sorted({normalizar(m) for m in PATRON_PERIODO.findall(re.sub(r"\s+", " ", texto))})


def contrastar(resultados_por_coleccion: dict[str, list[dict]], tema: str, unidad: str) -> dict:
    """Compara lo que dice cada nivel sobre un tema y explica cuál prevalece.

    resultados_por_coleccion: fragmentos recuperados de "leyes", "municipal" y "chileatiende".
    La ley tiene rango superior; la guía municipal y ChileAtiende son informativas.
    """
    por_nivel = {}
    for resultados in resultados_por_coleccion.values():
        resultados = [r for r in resultados if r["fuente_id"] != "procedimiento_simulado"] or resultados
        if not resultados:
            continue
        # Se prefiere el fragmento más relevante que efectivamente mencione fechas o plazos.
        mejor = next((r for r in resultados if menciones_periodo(r["texto"])), resultados[0])
        nivel = fuente(mejor["fuente_id"])["nivel"]
        por_nivel[nivel] = {
            "nivel": TITULOS_SECCION[nivel], "cita": formatear_cita(mejor["fuente_id"], mejor.get("articulo"), mejor.get("pagina")),
            "verbo": nivel_info(nivel)["verbo"], "extracto": re.sub(r"\s+", " ", mejor["texto"])[:400],
            "menciones": menciones_periodo(mejor["texto"]), "fuente_id": mejor["fuente_id"],
        }
    conjuntos = [tuple(v["menciones"]) for v in por_nivel.values() if v["menciones"]]
    discrepancia = len(set(conjuntos)) > 1
    if not por_nivel:
        explicacion = "SIN_RESULTADOS: no se encontraron fuentes sobre este tema."
    elif discrepancia:
        explicacion = ("Las fuentes no expresan el plazo o la fecha de la misma forma. La ley tiene rango superior y "
                       "prevalece; la guía municipal y ChileAtiende son informativas y pueden simplificar o detallar. "
                       f"Ante la diferencia, conviene confirmar en {unidad}.")
    else:
        explicacion = "Las fuentes encontradas no muestran diferencias en fechas o plazos."
    return {"tema": tema, "por_nivel": [por_nivel[n] for n in sorted(por_nivel)], "discrepancia": discrepancia,
            "explicacion": explicacion}
