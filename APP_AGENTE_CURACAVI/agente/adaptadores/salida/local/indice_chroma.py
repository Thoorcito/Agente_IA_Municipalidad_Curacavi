"""Memoria semántica · ADAPTADOR LOCAL: Chroma (vectores) + BM25 (palabras exactas).

Implementa el puerto BuscadorFuentes (agente/aplicacion/puertos.py). Se usa en Google Colab, en las pruebas y
en el modo local sin Docker. En Docker se usa IndicePgvector (agente/adaptadores/salida/postgres/indice.py),
que cumple el mismo contrato.

Decisiones de diseño:
- Una colección por tipo de fuente: "leyes", "municipal", "chileatiende". Así las leyes, que son muy
  largas, no tapan a las guías ni a las fichas prácticas.
- Búsqueda híbrida: la vectorial encuentra por significado; BM25 por palabras exactas (números de
  artículo, "SOAP", "UTM"). Se combinan con RRF en adaptadores/salida/memoria/busqueda_hibrida.py.
- Colección "casos_resueltos": memoria episódica. Cada caso cerrado se agrega aquí y se recupera
  cuando llega un caso parecido.
"""
import json
from pathlib import Path

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from rank_bm25 import BM25Okapi

from agente.dominio.texto import tokenizar
from agente.adaptadores.salida.memoria.busqueda_hibrida import fusionar
from agente.configuracion import settings


class IndiceChroma:
    """Colecciones Chroma persistentes y su espejo BM25 (corpus en archivos .jsonl).

    directorio: carpeta donde Chroma guarda los vectores y donde se guarda el corpus para BM25.
    """

    def __init__(self, directorio: Path, embeddings: Embeddings, umbrales: dict | None = None):
        import chromadb
        from chromadb.config import Settings as ChromaSettings

        self.directorio = Path(directorio)
        self.directorio.mkdir(parents=True, exist_ok=True)
        self.embeddings = embeddings
        self.umbrales = umbrales or settings.umbrales()
        self.cliente = chromadb.PersistentClient(path=str(self.directorio / "chroma"),
                                                 settings=ChromaSettings(anonymized_telemetry=False))
        self._stores: dict = {}
        self._corpus: dict[str, list[dict]] = {}
        self._bm25: dict[str, BM25Okapi | None] = {}

    # --- persistencia ---------------------------------------------------------------------
    def _store(self, coleccion: str):
        from langchain_chroma import Chroma

        if coleccion not in self._stores:
            self._stores[coleccion] = Chroma(client=self.cliente, collection_name=coleccion,
                                             embedding_function=self.embeddings,
                                             collection_metadata={"hnsw:space": "cosine"})
        return self._stores[coleccion]

    def _ruta_corpus(self, coleccion: str) -> Path:
        return self.directorio / f"corpus_{coleccion}.jsonl"

    def corpus(self, coleccion: str) -> list[dict]:
        if coleccion not in self._corpus:
            ruta = self._ruta_corpus(coleccion)
            filas = [json.loads(l) for l in ruta.read_text(encoding="utf-8").splitlines()] if ruta.exists() else []
            self._corpus[coleccion] = filas
            self._bm25.pop(coleccion, None)
        return self._corpus[coleccion]

    def _indice_bm25(self, coleccion: str):
        if coleccion not in self._bm25:
            filas = self.corpus(coleccion)
            self._bm25[coleccion] = BM25Okapi([tokenizar(f["texto"]) for f in filas]) if filas else None
        return self._bm25[coleccion]

    def construir(self, colecciones: dict[str, list[Document]], lote: int = 64) -> dict[str, int]:
        """(Re)crea las colecciones indicadas. Devuelve cuántos fragmentos quedó en cada una."""
        resumen = {}
        for coleccion, docs in colecciones.items():
            try:
                self.cliente.delete_collection(coleccion)
            except Exception:  # la colección no existía
                pass
            self._stores.pop(coleccion, None)
            filas = [{"id": d.metadata["chunk_id"], "texto": d.page_content,
                      "metadata": {k: v for k, v in d.metadata.items() if v is not None}} for d in docs]
            self._ruta_corpus(coleccion).write_text(
                "\n".join(json.dumps(f, ensure_ascii=False) for f in filas), encoding="utf-8")
            self._corpus[coleccion] = filas
            self._bm25.pop(coleccion, None)
            store = self._store(coleccion)
            for i in range(0, len(filas), lote):
                parte = filas[i:i + lote]
                store.add_texts([f["texto"] for f in parte], metadatas=[f["metadata"] for f in parte],
                                ids=[f["id"] for f in parte])
            resumen[coleccion] = len(filas)
        return resumen

    def agregar(self, coleccion: str, texto: str, metadata: dict) -> str:
        """Agrega un fragmento (se usa para guardar casos resueltos: memoria episódica)."""
        filas = self.corpus(coleccion)
        chunk_id = metadata.get("chunk_id") or f"{coleccion}:{len(filas)}"
        metadata = {**metadata, "chunk_id": chunk_id, "coleccion": coleccion}
        self._store(coleccion).add_texts([texto], metadatas=[metadata], ids=[chunk_id])
        filas.append({"id": chunk_id, "texto": texto, "metadata": metadata})
        with self._ruta_corpus(coleccion).open("a", encoding="utf-8") as fh:
            fh.write(("\n" if self._ruta_corpus(coleccion).stat().st_size else "")
                     + json.dumps(filas[-1], ensure_ascii=False))
        self._bm25.pop(coleccion, None)
        return chunk_id

    def conteo(self) -> dict[str, int]:
        return {c: len(self.corpus(c)) for c in settings.COLECCIONES + ["externa"] if self.corpus(c)}

    # --- búsqueda ---------------------------------------------------------------------------
    def buscar(self, coleccion: str, consulta: str, k: int = settings.TOP_K, tramite: str | None = None,
               hibrida: bool = True, umbral: float | None = None, boost: bool = True) -> list[dict]:
        """Búsqueda híbrida con umbral. Devuelve hasta k fragmentos ordenados por relevancia."""
        filas = self.corpus(coleccion)
        if not filas or not consulta.strip():
            return []
        umbral = self.umbrales.get(coleccion, 0.4) if umbral is None else umbral
        candidatos = min(len(filas), k * 3)

        # 1) Vectorial (similitud coseno = 1 - distancia)
        vectorial = [(doc.metadata["chunk_id"], 1 - float(distancia)) for doc, distancia
                     in self._store(coleccion).similarity_search_with_score(consulta, k=candidatos)]

        # 2) BM25 (palabras exactas)
        por_palabras = []
        tokens = list(set(tokenizar(consulta)))
        if hibrida and tokens:
            puntajes = self._indice_bm25(coleccion).get_scores(tokens)
            orden = sorted(range(len(puntajes)), key=lambda i: puntajes[i], reverse=True)[:candidatos]
            por_palabras = [filas[i]["id"] for i in orden if puntajes[i] > 0]

        return fusionar(coleccion, consulta, {f["id"]: f for f in filas}, vectorial, por_palabras,
                        k, umbral, tramite, boost)
