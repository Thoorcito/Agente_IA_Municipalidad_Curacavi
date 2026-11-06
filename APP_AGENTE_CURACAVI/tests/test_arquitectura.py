"""Reglas de la arquitectura hexagonal, verificadas con pruebas.

1. Regla de dependencia: el dominio no importa frameworks ni bases de datos.
2. Los adaptadores cumplen los puertos.
3. Un adaptador se puede reemplazar por otro (aquí, un doble de prueba) sin tocar las herramientas.
4. El controlador es la única entrada de la interfaz.
"""
import ast
from pathlib import Path

import pytest

from agente.configuracion.contenedor import Contenedor, crear_agente, crear_contenedor
from agente.adaptadores.entrada.controlador import ControladorAtencion
from agente.dominio.requisitos import cargar_catalogo
from agente.adaptadores.salida.local.registro_sqlite import RegistroSQLite
from agente.adaptadores.salida.local.indice_chroma import IndiceChroma
from agente.aplicacion.puertos import BuscadorFuentes, RegistroMunicipal
from agente.adaptadores.entrada.herramientas import todas
from agente.configuracion import settings
from tests.conftest import FECHA_PRUEBAS

TECNOLOGIA = {"sqlite3", "psycopg", "psycopg_pool", "chromadb", "langchain_chroma", "rank_bm25", "streamlit",
              "openai", "langchain_openai", "langchain_huggingface"}
FRAMEWORKS_DE_AGENTES = {"langchain", "langchain_core", "langgraph"}
AGENTE = settings.BASE_DIR / "agente"


def _modulos_importados(ruta: Path) -> set[str]:
    """Módulos importados por un archivo: externos por su nombre raíz; internos con su ruta completa."""
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    nombres = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            nombres.update(a.name if a.name.startswith("agente") else a.name.split(".")[0] for a in nodo.names)
        elif isinstance(nodo, ast.ImportFrom) and nodo.module:
            nombres.add(nodo.module if nodo.module.startswith("agente") else nodo.module.split(".")[0])
    return nombres


@pytest.mark.parametrize("ruta", sorted((AGENTE / "dominio").glob("*.py")), ids=lambda p: p.name)
def test_el_dominio_no_depende_de_frameworks_ni_de_otras_capas(ruta):
    # Act
    importados = _modulos_importados(ruta)
    internos = {m for m in importados if m.startswith("agente")}

    # Assert: ni LangChain ni bases de datos; de agente solo el dominio y los parámetros de configuración
    assert not importados & (TECNOLOGIA | FRAMEWORKS_DE_AGENTES)
    assert internos <= {m for m in internos if m.startswith("agente.dominio")} | {"agente.configuracion"}


@pytest.mark.parametrize("ruta", sorted((AGENTE / "aplicacion").glob("*.py")), ids=lambda p: p.name)
def test_la_aplicacion_no_depende_de_adaptadores_ni_de_bases_de_datos(ruta):
    # Act
    importados = _modulos_importados(ruta)

    # Assert: usa LangGraph (su framework) pero ningún adaptador ni tecnología de persistencia
    assert not importados & TECNOLOGIA
    assert not [m for m in importados if m.startswith(("agente.adaptadores", "agente.configuracion.contenedor"))]


def test_los_adaptadores_locales_cumplen_los_puertos(contenedor):
    # Act / Assert
    assert isinstance(contenedor.registro, RegistroSQLite) and isinstance(contenedor.registro, RegistroMunicipal)
    assert isinstance(contenedor.indice, IndiceChroma) and isinstance(contenedor.indice, BuscadorFuentes)


class BuscadorFalso:
    """Doble de prueba del puerto BuscadorFuentes: siempre devuelve el mismo artículo de ley."""

    def construir(self, colecciones): return {}
    def agregar(self, coleccion, texto, metadata): return "x"
    def corpus(self, coleccion): return []
    def conteo(self): return {}

    def buscar(self, coleccion, consulta, k=4, tramite=None, hibrida=True, umbral=None, boost=True):
        return [{"chunk_id": "f1", "texto": "Los plazos de días son hábiles.", "fuente_id": "ley_19880",
                 "articulo": "25", "pagina": None, "similitud": 0.9}]


def test_un_adaptador_se_reemplaza_sin_tocar_las_herramientas(contenedor):
    # Arrange: mismo registro, otro buscador
    otro = Contenedor(registro=contenedor.registro, indice=BuscadorFalso(), requisitos=cargar_catalogo(),
                      fecha=lambda: FECHA_PRUEBAS)
    herramientas = {t.name: t for t in todas(otro.herramientas())}

    # Act
    r = herramientas["buscar_normativa_nacional"].invoke({"consulta": "plazos"})

    # Assert: la herramienta formatea la cita con el dominio, venga de donde venga el fragmento
    assert isinstance(otro.indice, BuscadorFuentes)
    assert r["resultados"][0]["cita"] == "Ley N° 19.880, art. 25"


def test_postgres_sin_url_avisa_que_falta_la_configuracion(monkeypatch):
    # Arrange
    monkeypatch.setattr(settings, "DATABASE_URL", "")

    # Act / Assert
    with pytest.raises(ValueError, match="DATABASE_URL"):
        crear_contenedor("postgres", proveedor_embeddings="offline")


def test_el_controlador_atiende_y_consulta_sin_conocer_la_base(contenedor):
    # Arrange
    ctl = ControladorAtencion(contenedor, crear_agente(contenedor))

    # Act
    r = ctl.enviar_mensaje("¿En qué estado está mi reclamo SOL-2026-0006?", "hilo-ctl", "V-003")
    ctl.fijar_condiciones(agenda_sin_cupos=True, cupo_tomado_por_otro=True)
    condiciones = dict(contenedor.condiciones)
    ctl.fijar_condiciones(agenda_sin_cupos=False, cupo_tomado_por_otro=False)

    # Assert
    assert r["decision"]["regla_id"] == "R3" and r["pendiente_aprobacion"]
    assert ctl.resolver_aprobacion("hilo-ctl", False)["decision"]["accion"] == "informar_estado"
    assert len(ctl.conversacion("hilo-ctl")["messages"]) == 2
    assert condiciones == {"agenda_sin_cupos": True, "cupo_tomado_por_otro": True}
    assert "cupo_tomado_por_otro" not in contenedor.condiciones
    assert ctl.solicitudes_del_vecino("V-003")[0]["folio"] == "SOL-2026-0006"
    assert ctl.info_sistema() == {"modelo": "sin LLM (respuestas con plantillas)", "persistencia": "SQLite + Chroma (local)",
                                  "fecha": "2026-11-04"}
    assert len(ctl.reglas()) == 10


def test_el_controlador_reinicia_la_demo_y_muestra_notificaciones(contenedor):
    # Arrange
    ctl = ControladorAtencion(contenedor, crear_agente(contenedor))
    ctl.enviar_mensaje("Quiero renovar el permiso de circulación de mi auto. Tengo el permiso del año anterior, "
                       "la revisión técnica, el certificado de gases y el SOAP.", "hilo-n", "V-002")

    # Act
    antes = ctl.notificaciones("V-002")
    ctl.reiniciar_demo()

    # Assert
    assert len(antes) == 1 and ctl.notificaciones("V-002") == []
