"""Fixtures de las pruebas de CONTRATO: la misma prueba corre contra cada adaptador.

- "sqlite": adaptador local (siempre se ejecuta).
- "postgres": PostgreSQL + pgvector real. Se ejecuta si DATABASE_URL_TEST apunta a una base disponible;
  si no, se omite (skip). Con Docker:  docker compose run --rm tests
"""
import os

import pytest

from agente.adaptadores.salida.memoria.ingesta import HashingEmbeddings
from agente.adaptadores.salida.local.registro_sqlite import RegistroSQLite
from agente.adaptadores.salida.local.indice_chroma import IndiceChroma
from tests.conftest import FECHA_PRUEBAS

URL_PRUEBAS = os.getenv("DATABASE_URL_TEST", "")


def postgres_disponible() -> bool:
    if not URL_PRUEBAS:
        return False
    try:
        import psycopg

        with psycopg.connect(URL_PRUEBAS, connect_timeout=3):
            return True
    except Exception:
        return False


POSTGRES = postgres_disponible()
solo_postgres = pytest.mark.skipif(not POSTGRES, reason="Sin PostgreSQL de prueba (defina DATABASE_URL_TEST)")
ADAPTADORES = ["sqlite", pytest.param("postgres", marks=[pytest.mark.integracion, solo_postgres])]


@pytest.fixture(params=ADAPTADORES)
def registro(request, tmp_path):
    """Registro municipal recién inicializado, con el adaptador del parámetro."""
    if request.param == "postgres":
        from agente.adaptadores.salida.postgres.registro import RegistroPostgres

        r = RegistroPostgres(URL_PRUEBAS)
    else:
        r = RegistroSQLite(tmp_path / "registro.sqlite")
    r.inicializar(FECHA_PRUEBAS)
    return r


@pytest.fixture(params=ADAPTADORES)
def crear_indice(request, tmp_path):
    """Fábrica de índices semánticos con embeddings simulados, con el adaptador del parámetro."""
    def fabrica(umbrales=None):
        if request.param == "postgres":
            from agente.adaptadores.salida.postgres.indice import IndicePgvector

            return IndicePgvector(URL_PRUEBAS, HashingEmbeddings(), umbrales=umbrales, tabla="fragmentos_prueba")
        return IndiceChroma(tmp_path / "indice", HashingEmbeddings(), umbrales=umbrales)

    if request.param == "postgres":   # tabla limpia en cada prueba
        import psycopg

        with psycopg.connect(URL_PRUEBAS) as conn:
            conn.execute("DROP TABLE IF EXISTS fragmentos_prueba")
    return fabrica
