"""Registro municipal · ADAPTADOR LOCAL: un archivo SQLite (Colab, pruebas y modo sin Docker).

Implementa el puerto RegistroMunicipal heredando la lógica SQL común de RegistroSQL.
"""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from agente.adaptadores.salida.memoria.registro_sql import TABLAS, RegistroSQL, esquema


class RegistroSQLite(RegistroSQL):
    """ADAPTADOR LOCAL del registro municipal: un archivo SQLite.

    Cada operación abre y cierra su conexión (seguro con los hilos de Streamlit y sin archivos
    bloqueados en Windows).
    """

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _conectar(self):
        """Abre la conexión, confirma los cambios y la cierra siempre (aunque haya error)."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _recrear_esquema(self, conn) -> None:
        for tabla in TABLAS:
            conn.execute(f"DROP TABLE IF EXISTS {tabla}")
        conn.executescript(esquema("INTEGER PRIMARY KEY AUTOINCREMENT"))

    def existe(self) -> bool:
        return self.db_path.exists() and bool(self._filas("SELECT name FROM sqlite_master WHERE name = 'solicitudes'"))
