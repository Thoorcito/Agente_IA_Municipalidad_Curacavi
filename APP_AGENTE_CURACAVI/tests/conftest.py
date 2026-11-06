"""Fixtures y dobles de prueba (mocks) compartidos por todos los tests.

Ningún test usa internet ni claves:
- Embeddings: HashingEmbeddings (determinista, sin descargas) en lugar de MiniLM.
- LLM del agente y juez: LLMSimulado, que devuelve respuestas preparadas por cada test.
- Fecha: fija en 2026-11-04, para que los plazos calculados no cambien con el día en que se corren.
- Persistencia: adaptador local (SQLite + Chroma) en una carpeta temporal. Las pruebas contra
  PostgreSQL + pgvector están en tests/integracion/ y se activan con DATABASE_URL_TEST.
"""
from datetime import date

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda
from pydantic import Field

from agente.configuracion.contenedor import crear_agente, crear_contenedor
from agente.adaptadores.salida.memoria.ingesta import HashingEmbeddings
from agente.adaptadores.entrada.herramientas import todas
from agente.configuracion import settings

FECHA_PRUEBAS = date(2026, 11, 4)


class LLMSimulado(BaseChatModel):
    """Mock de un modelo de chat.

    respuestas: lista de textos o AIMessage que se entregan en orden (la última se repite).
    estructurada: diccionario que devuelve with_structured_output (para el NLU).
    falla: si es True, toda llamada lanza un error (simula un modelo caído o sin cuota).
    """
    respuestas: list = Field(default_factory=list)
    estructurada: dict | None = None
    falla: bool = False
    llamadas: int = 0

    @property
    def _llm_type(self) -> str:
        return "simulado"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.llamadas += 1
        if self.falla:
            raise RuntimeError("modelo no disponible")
        r = self.respuestas.pop(0) if len(self.respuestas) > 1 else self.respuestas[0]
        mensaje = r if isinstance(r, AIMessage) else AIMessage(content=r)
        return ChatResult(generations=[ChatGeneration(message=mensaje)])

    def bind_tools(self, tools, **kwargs):
        return self

    def with_structured_output(self, schema, **kwargs):
        def responder(_):
            if self.falla:
                raise RuntimeError("modelo no disponible")
            return schema(**self.estructurada)
        return RunnableLambda(responder)


@pytest.fixture(scope="session", autouse=True)
def persistencia_local():
    """Las pruebas unitarias siempre usan el adaptador local, aunque el .env diga PERSISTENCIA=postgres."""
    anterior, settings.PERSISTENCIA = settings.PERSISTENCIA, "local"
    yield
    settings.PERSISTENCIA = anterior


@pytest.fixture(scope="session")
def contenedor_base(tmp_path_factory):
    """Contenedor local (SQLite + índices Chroma) construido UNA vez por sesión, con embeddings simulados."""
    directorio = tmp_path_factory.mktemp("runtime")
    return crear_contenedor("local", directorio, "offline", reiniciar=True, fecha=lambda: FECHA_PRUEBAS,
                            embeddings=HashingEmbeddings())


@pytest.fixture
def contenedor(contenedor_base):
    """Antes de cada test: base de datos en su estado inicial y sin condiciones de simulación."""
    contenedor_base.registro.inicializar(FECHA_PRUEBAS)
    contenedor_base.condiciones.clear()
    yield contenedor_base
    contenedor_base.condiciones.clear()


@pytest.fixture
def h(contenedor):
    """Las 17 herramientas conectadas al contenedor de pruebas, por nombre: h["agendar_hora"]."""
    return {t.name: t for t in todas(contenedor.herramientas())}


@pytest.fixture
def agente(contenedor):
    """Agente híbrido en modo offline (sin LLM) con memoria en RAM."""
    return crear_agente(contenedor)


@pytest.fixture
def llm_simulado():
    return LLMSimulado(respuestas=["respuesta simulada"])
