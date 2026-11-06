"""Memoria de corto plazo: el estado de cada conversación (hilo) guardado por LangGraph.

- El checkpointer guarda el estado completo del grafo después de cada paso, por thread_id. Si se
  cierra la app y el vecino vuelve con el mismo número de atención (thread_id), el agente retoma
  el trámite donde quedó: qué trámite era, qué documentos ya declaró y qué folio se creó.
- El resumen de conversaciones largas está en agente/aplicacion/resumen.py.

Adaptadores del checkpointer (todos son de LangGraph y cumplen la misma interfaz):
  InMemorySaver (pruebas) · SqliteSaver (modo local y Colab) · PostgresSaver (Docker).
"""
import sqlite3
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver



def crear_checkpointer(destino: str | Path | None = None):
    """Elige el adaptador según el destino:
    None -> InMemorySaver · "postgresql://..." -> PostgresSaver · ruta de archivo -> SqliteSaver."""
    if destino is None:
        return InMemorySaver()
    if str(destino).startswith(("postgresql://", "postgres://")):
        from langgraph.checkpoint.postgres import PostgresSaver

        from agente.adaptadores.salida.postgres.conexion import pool

        guardador = PostgresSaver(pool(str(destino), autocommit=True))
        guardador.setup()   # crea las tablas de checkpoints si no existen
        return guardador
    from langgraph.checkpoint.sqlite import SqliteSaver

    Path(destino).parent.mkdir(parents=True, exist_ok=True)
    return SqliteSaver(sqlite3.connect(str(destino), check_same_thread=False))
