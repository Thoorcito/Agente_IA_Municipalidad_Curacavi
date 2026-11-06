"""El agente completo sobre PostgreSQL + pgvector: los 22 escenarios y la memoria entre sesiones.

Es la evidencia de que cambiar de adaptador (SQLite/Chroma -> PostgreSQL/pgvector) no cambia
ninguna decisión del agente.
"""
import uuid

import pytest

from agente.adaptadores.entrada import evaluacion as ev
from agente.configuracion.contenedor import crear_agente, crear_contenedor
from agente.adaptadores.salida.memoria.ingesta import HashingEmbeddings
from agente.adaptadores.salida.memoria.conversaciones import crear_checkpointer
from tests.conftest import FECHA_PRUEBAS
from tests.integracion.conftest import URL_PRUEBAS, solo_postgres

pytestmark = [pytest.mark.integracion, solo_postgres]


@pytest.fixture(scope="module")
def contenedor_pg():
    return crear_contenedor("postgres", proveedor_embeddings="offline", reiniciar=True, fecha=lambda: FECHA_PRUEBAS,
                            embeddings=HashingEmbeddings(), database_url=URL_PRUEBAS)


def test_los_22_escenarios_dan_lo_mismo_con_postgres(contenedor_pg):
    # Act
    df = ev.evaluar_escenarios(contenedor_pg, lambda checkpointer=None: crear_agente(contenedor_pg, checkpointer=checkpointer))

    # Assert
    columnas = ["regla_ok", "accion_ok", "herramientas_ok", "escrituras_ok", "replanificacion_ok"]
    assert len(df) == 22 and df[columnas].all().all()
    assert contenedor_pg.descripcion() == "PostgreSQL + pgvector (Docker)"


def test_la_conversacion_se_retoma_desde_postgres(contenedor_pg):
    # Arrange: dos agentes distintos (como cerrar y abrir la app) con el checkpointer en PostgreSQL
    contenedor_pg.registro.inicializar(FECHA_PRUEBAS)
    texto = ("Quiero sacar mi primera licencia de conducir clase B. Tengo mi cédula, dos fotos, el certificado "
             "de antecedentes y el certificado de residencia de la junta de vecinos.")
    hilo = f"hilo-pg-{uuid.uuid4().hex[:8]}"
    primero = crear_agente(contenedor_pg, checkpointer=crear_checkpointer(URL_PRUEBAS))
    r1 = primero.conversar(texto, hilo, "V-002")

    # Act
    segundo = crear_agente(contenedor_pg, memoria_persistente=True)
    r2 = segundo.conversar("Ya tengo el certificado de estudios de 8° básico.", hilo, "V-002")

    # Assert
    assert r1["decision"]["accion"] == "solicitar_antecedentes"
    assert r2["folio_en_curso"] == r1["folio_en_curso"] and r2["decision"]["accion"] == "registrar_tramite"
