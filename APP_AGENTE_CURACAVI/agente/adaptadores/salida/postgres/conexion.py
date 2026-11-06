"""Pool de conexiones a PostgreSQL (psycopg 3), compartido por los adaptadores.

Un pool reutiliza conexiones abiertas: es más rápido que conectar en cada operación y es seguro con
los hilos de Streamlit. Al salir del bloque `with pool.connection()` se confirma la transacción
(commit) o se revierte si hubo un error.
"""
import atexit

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

_POOLS: dict[tuple[str, bool], ConnectionPool] = {}


def pool(url: str, autocommit: bool = False) -> ConnectionPool:
    """Un pool por URL (se crea una vez por proceso).

    autocommit=True es el modo que exige el checkpointer de LangGraph (PostgresSaver); los
    adaptadores del registro y del índice usan transacciones normales.
    """
    clave = (url, autocommit)
    if clave not in _POOLS:
        kwargs = {"row_factory": dict_row}
        if autocommit:
            kwargs.update(autocommit=True, prepare_threshold=0)
        _POOLS[clave] = ConnectionPool(url, min_size=1, max_size=8, kwargs=kwargs, open=True)
    return _POOLS[clave]


@atexit.register
def cerrar_pools() -> None:
    """Cierra las conexiones al terminar el proceso (evita hilos colgados al salir)."""
    while _POOLS:
        _POOLS.popitem()[1].close()


def esperar_base(url: str, intentos: int = 30) -> None:
    """Espera a que PostgreSQL acepte conexiones (útil al arrancar con Docker Compose)."""
    import time

    import psycopg

    for i in range(intentos):
        try:
            with psycopg.connect(url, connect_timeout=3):
                return
        except psycopg.OperationalError:
            if i == intentos - 1:
                raise
            time.sleep(2)
