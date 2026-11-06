"""Ingesta RAG compartida por los dos adaptadores de memoria semántica (Chroma y pgvector).

Flujo de indexación (scripts/preparar_datos.py):
    cargar_documentos() -> fragmentar() -> indice.construir()

- Embeddings: MiniLM multilingüe local (384 dimensiones) o HashingEmbeddings (pruebas / sin red).
- Limpieza: se quitan encabezados y anotaciones de la Biblioteca del Congreso en las leyes.
- Fragmentación: 800 caracteres con solape de 120; las leyes se cortan primero por ARTÍCULO y se
  conservan solo los artículos pertinentes al caso (lista en el catálogo de fuentes).
- Metadatos por fragmento: fuente, archivo, colección, nivel normativo, página, artículo y trámites.
"""
import hashlib
import math
import re
from pathlib import Path

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

from agente.dominio import citas as cat
from agente.dominio.texto import tokenizar
from agente.configuracion import settings

# ---------------------------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------------------------


class HashingEmbeddings(Embeddings):
    """Embeddings sin descargas: cada palabra (y par de palabras) se proyecta a una dimensión por hash.

    No entiende sinónimos (no es semántico de verdad), pero es determinista y gratuito. Se usa en los
    tests (mock de embeddings) y en el modo offline. En la ejecución real se usa MiniLM.
    """

    def __init__(self, dim: int = settings.EMBEDDING_DIM):
        self.dim = dim

    def _vector(self, texto: str) -> list[float]:
        tokens = tokenizar(texto)
        rasgos = tokens + [f"{a}_{b}" for a, b in zip(tokens, tokens[1:])]
        vec = [0.0] * self.dim
        for rasgo in rasgos:
            h = int(hashlib.md5(rasgo.encode()).hexdigest(), 16)
            vec[h % self.dim] += 1.0 if (h >> 8) % 2 else -1.0
        norma = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norma for v in vec]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


def crear_embeddings(proveedor: str | None = None) -> Embeddings:
    """Fábrica de embeddings según la configuración ("local" = MiniLM, "offline" = hashing)."""
    proveedor = proveedor or settings.EMBEDDINGS_PROVIDER
    if proveedor == "offline":
        return HashingEmbeddings()
    from langchain_huggingface import HuggingFaceEmbeddings  # import tardío: es pesado

    return HuggingFaceEmbeddings(model_name=settings.EMBEDDING_MODEL_LOCAL,
                                 encode_kwargs={"normalize_embeddings": True})


# ---------------------------------------------------------------------------------------------
# Carga y limpieza de documentos
# ---------------------------------------------------------------------------------------------

# Encabezados/pies de la Biblioteca del Congreso y anotaciones al margen (fechas del Diario Oficial,
# referencias a leyes modificatorias). Ensucian el texto del artículo y bajan la calidad de búsqueda.
PATRONES_RUIDO_LEY = [
    r"^.*Biblioteca del Congreso Nacional.*$",
    r"^\s*página \d+ de \d+\s*$",
    r"^(Ley \d+|DFL 1, [A-ZÁÉÍÓÚ]+ \(\d{4}\)|Decreto \d+, [A-ZÁÉÍÓÚ]+ \(\d{4}\))\s*$",
    r"D\.O\.\s*\d{2}\.\d{2}\.\d{4}",
    r"D\.F\.L\.?\s*1-19\.704",
    r"\bART\.\s*\d+[º°]?",
    r"\bLEY\s*N[º°]\s*\d+\.?\d*",
    r"\bLey\s+\d{5}\b",
    r"\bArt\.\s*\d+[º°]?,?\s*N[°º]\s*\d+(?:,?\s*[a-z]\))?",
    r"\bArt\.\s*(?:ÚNICO|único|PRIMERO|SEGUNDO|TERCERO|CUARTO)\s*(?:N[°º]\s*\d+)?",
]


def limpiar_texto_ley(texto: str) -> str:
    for patron in PATRONES_RUIDO_LEY:
        texto = re.sub(patron, " ", texto, flags=re.MULTILINE)
    texto = re.sub(r"[ \t]+", " ", texto)
    return re.sub(r"\n\s*\n+", "\n", texto).strip()


def cargar_documentos(fuentes_dir: Path | None = None) -> list[Document]:
    """Lee todas las fuentes del catálogo. Un Document por página (PDF) o por archivo (MD)."""
    fuentes_dir = fuentes_dir or settings.FUENTES_DIR
    documentos = []
    for f in cat.catalogo()["fuentes"].values():
        ruta = fuentes_dir / f["archivo"]
        base = {"fuente_id": f["id"], "archivo": ruta.name, "coleccion": f["coleccion"], "nivel": f["nivel"]}
        if ruta.suffix.lower() == ".pdf":
            for n, pagina in enumerate(PdfReader(str(ruta)).pages, start=1):
                texto = pagina.extract_text() or ""
                if f["nivel"] == 1:
                    texto = limpiar_texto_ley(texto)
                if texto.strip():
                    documentos.append(Document(page_content=texto, metadata={**base, "pagina": n}))
        else:
            documentos.append(Document(page_content=ruta.read_text(encoding="utf-8"), metadata={**base, "pagina": 0}))
    return documentos


# ---------------------------------------------------------------------------------------------
# Fragmentación
# ---------------------------------------------------------------------------------------------

PATRON_ARTICULO = re.compile(r"(?:^|\n)\s*Art[íi]culo\s+(\d+)\s*(?:bis|ter|quáter)?\s*[\.º°]*\s*-?", re.IGNORECASE)


def _tramites_de_articulo(fuente: dict, articulo: int | None) -> str:
    """Asocia un artículo de ley a los trámites que regula (para priorizarlo en la búsqueda)."""
    mapa = fuente.get("tramites_por_articulo", {})
    for clave, tramites in mapa.items():
        if clave == "general" or articulo is None:
            continue
        if "-" in clave:
            ini, fin = (int(x) for x in clave.split("-"))
            if ini <= articulo <= fin:
                return tramites
        elif int(clave) == articulo:
            return tramites
    return mapa.get("general", "*")


def _dividir_ley_por_articulo(paginas: list[Document]) -> list[tuple[int | None, int, str]]:
    """Une las páginas de una ley y la corta en artículos: (n° de artículo, página inicial, texto)."""
    texto, marcas = "", []
    for p in paginas:
        marcas.append((len(texto), p.metadata["pagina"]))
        texto += p.page_content + "\n"

    def pagina_de(pos: int) -> int:
        actual = marcas[0][1]
        for inicio, pag in marcas:
            if inicio <= pos:
                actual = pag
        return actual

    coincidencias = list(PATRON_ARTICULO.finditer(texto))
    articulos = []
    vistos = set()
    for i, m in enumerate(coincidencias):
        numero = int(m.group(1))
        fin = coincidencias[i + 1].start() if i + 1 < len(coincidencias) else len(texto)
        # Los textos refundidos repiten números en disposiciones transitorias: se toma la primera aparición.
        if numero in vistos:
            continue
        vistos.add(numero)
        articulos.append((numero, pagina_de(m.start()), texto[m.start():fin].strip()))
    return articulos


def fragmentar(documentos: list[Document], acotar_leyes: bool = True,
               separar_externas: bool = True) -> dict[str, list[Document]]:
    """Divide los documentos en fragmentos y los agrupa por colección.

    acotar_leyes=False y separar_externas=False reproducen el diseño base (todas las leyes completas
    y ChileAtiende en un mismo índice "externa"); se usan solo para la comparación antes/después.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.CHUNK_SIZE, chunk_overlap=settings.CHUNK_OVERLAP,
        separators=["\n## ", "\n### ", "\n\n", "\n", ". ", " "],
    )
    por_fuente: dict[str, list[Document]] = {}
    for d in documentos:
        por_fuente.setdefault(d.metadata["fuente_id"], []).append(d)

    colecciones: dict[str, list[Document]] = {}
    for fuente_id, paginas in por_fuente.items():
        f = cat.fuente(fuente_id)
        coleccion = f["coleccion"] if separar_externas or f["coleccion"] == "municipal" else "externa"
        fragmentos: list[Document] = []
        if f["nivel"] == 1:
            pertinentes = set(f.get("articulos_pertinentes", []))
            for numero, pagina, texto in _dividir_ley_por_articulo(paginas):
                if acotar_leyes and numero not in pertinentes:
                    continue
                meta = {**paginas[0].metadata, "pagina": pagina, "articulo": str(numero),
                        "tramites": _tramites_de_articulo(f, numero)}
                fragmentos += splitter.split_documents([Document(page_content=texto, metadata=meta)])
        else:
            for p in paginas:
                meta = {**p.metadata, "articulo": "", "tramites": f.get("tramites", "general")}
                fragmentos += splitter.split_documents([Document(page_content=p.page_content, metadata=meta)])
        fragmentos = [x for x in fragmentos if len(x.page_content.strip()) >= settings.MIN_CARACTERES_CHUNK]
        for i, x in enumerate(fragmentos):
            x.metadata["coleccion"] = coleccion
            x.metadata["chunk_id"] = f"{fuente_id}:{i}"
        colecciones.setdefault(coleccion, []).extend(fragmentos)
    return colecciones



# ---------------------------------------------------------------------------------------------
# Memoria episódica: casos históricos
# ---------------------------------------------------------------------------------------------

def textos_casos_historicos(solicitudes: list[dict]) -> list[tuple[str, dict]]:
    """Convierte solicitudes ya resueltas del registro en "casos" para la memoria episódica."""
    casos = []
    for s in solicitudes:
        if s["estado"] in ("Aprobada", "Rechazada", "Cerrada"):
            texto = (f"Caso {s['folio']} ({s['fecha_ingreso']}): {s['tramite']} en {s['unidad_responsable']}. "
                     f"Resultado: {s['estado']}. {s['observacion']}")
            casos.append((texto, {"fuente_id": "registro_solicitudes", "folio": s["folio"],
                                  "tramites": "*", "nivel": 0, "chunk_id": f"caso:{s['folio']}"}))
    return casos

