"""Fusión de la búsqueda híbrida, común a los adaptadores Chroma y pgvector.

Cada adaptador entrega dos listas ordenadas:
- vectorial: [(chunk_id, similitud coseno)] desde Chroma o desde pgvector;
- por palabras: [chunk_id] desde BM25 (Chroma) o desde la búsqueda de texto completo de PostgreSQL.

Esta función aplica las mismas reglas a ambas, para que cambiar de adaptador no cambie el criterio:
1. Reciprocal Rank Fusion (RRF): puntaje = Σ 1 / (RRF_K + posición) en cada lista.
2. Umbral por índice: un fragmento entra si su similitud supera el umbral de la colección, o si la
   búsqueda por palabras lo ubica entre los primeros k y contiene al menos un tercio de las palabras
   de la consulta (mínimo 2). Si nada entra, la herramienta responde SIN_RESULTADOS.
3. Prioridad por trámite: los fragmentos asociados al trámite consultado multiplican su puntaje.
"""
from agente.dominio.texto import tokenizar
from agente.configuracion import settings


def fusionar(coleccion: str, consulta: str, filas_por_id: dict[str, dict], vectorial: list[tuple[str, float]],
             por_palabras: list[str], k: int, umbral: float, tramite: str | None, boost: bool) -> list[dict]:
    """Combina ambas listas y devuelve hasta k fragmentos con su similitud, cobertura y puntaje."""
    similitud: dict[str, float] = {}
    rrf: dict[str, float] = {}
    for rango, (cid, sim) in enumerate(vectorial):
        similitud[cid] = round(sim, 4)
        rrf[cid] = rrf.get(cid, 0) + 1 / (settings.RRF_K + rango)

    tokens = set(tokenizar(consulta))
    aceptados_palabras: dict[str, float] = {}
    for rango, cid in enumerate(por_palabras):
        rrf[cid] = rrf.get(cid, 0) + 1 / (settings.RRF_K + rango)
        comunes = tokens & set(tokenizar(filas_por_id[cid]["texto"]))
        cobertura = len(comunes) / len(tokens) if tokens else 0
        if rango < k and cobertura >= 0.34 and len(comunes) >= min(2, len(tokens)):
            aceptados_palabras[cid] = round(cobertura, 3)

    resultados = []
    for cid, puntaje in rrf.items():
        if not (similitud.get(cid, -1) >= umbral or cid in aceptados_palabras):
            continue
        meta = filas_por_id[cid]["metadata"]
        tramites = str(meta.get("tramites", ""))
        if boost and tramite and (tramite in tramites.split("|") or tramites in ("*", "general")):
            puntaje *= settings.BOOST_TRAMITE
        resultados.append({
            "chunk_id": cid, "texto": filas_por_id[cid]["texto"], "fuente_id": meta.get("fuente_id", ""),
            "archivo": meta.get("archivo", ""), "coleccion": coleccion, "nivel": meta.get("nivel"),
            "pagina": meta.get("pagina") or None, "articulo": meta.get("articulo") or None,
            "similitud": similitud.get(cid), "cobertura_bm25": aceptados_palabras.get(cid),
            "score": round(puntaje, 5), "tramites": tramites,
        })
    resultados.sort(key=lambda r: r["score"], reverse=True)
    return resultados[:k]
