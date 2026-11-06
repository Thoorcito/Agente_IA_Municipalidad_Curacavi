"""Pruebas de contrato: SQLite/Chroma y PostgreSQL/pgvector deben comportarse igual.

Si una prueba pasa con un adaptador y falla con el otro, el adaptador no cumple el puerto.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest
from langchain_core.documents import Document

from agente.dominio.modelo import dia_de_atencion_licencias
from agente.aplicacion.puertos import BuscadorFuentes, RegistroMunicipal
from tests.conftest import FECHA_PRUEBAS
from tests.integracion.conftest import URL_PRUEBAS, solo_postgres

# --- Registro municipal (memoria de largo plazo) ----------------------------------------------------------


def test_registro_inicial_cumple_el_puerto(registro):
    # Act
    cupos = registro.cupos_disponibles(limite=500)

    # Assert
    assert isinstance(registro, RegistroMunicipal)
    assert len(registro.todas_las_solicitudes()) == 30 and registro.existe()
    assert cupos and all(dia_de_atencion_licencias(date.fromisoformat(c["fecha"])) for c in cupos)


def test_folio_correlativo_estado_y_bitacora(registro):
    # Act
    folio = registro.registrar_solicitud("V-002", "reclamo", "Reclamo por atención", "OIRS", "Ingresada", "x", FECHA_PRUEBAS)
    actualizado = registro.actualizar_estado(folio, "Observada", "Falta detalle", "Ley N° 19.880, art. 31", FECHA_PRUEBAS)
    inexistente = registro.actualizar_estado("SOL-2026-9999", "Observada", "", "", FECHA_PRUEBAS)

    # Assert
    assert folio == "SOL-2026-0031" and actualizado and not inexistente
    assert registro.obtener_solicitud(folio)["estado"] == "Observada"
    assert [b["evento"] for b in registro.bitacora(folio)] == ["registro", "cambio_estado"]
    assert registro.solicitudes_de_vecino("V-002")[0]["folio"] == folio


def test_reserva_de_hora_es_atomica(registro):
    # Arrange
    cupo = registro.cupos_disponibles(limite=1)[0]["id"]

    # Act
    primera = registro.reservar_cupo(cupo, "SOL-2026-0031")
    segunda = registro.reservar_cupo(cupo, "SOL-2026-0032")

    # Assert
    assert primera and not segunda
    assert registro.reserva_de_folio("SOL-2026-0031")["id"] == cupo and registro.reserva_de_folio("SOL-2026-0032") is None


def test_comunicaciones_lista_de_espera_y_decisiones(registro):
    # Act
    ticket = registro.registrar_escalamiento("SOL-2026-0006", "Jefatura OIRS", "plazo vencido", "procedimiento", FECHA_PRUEBAS)
    aviso = registro.registrar_notificacion("V-001", "SOL-2026-0004", "mensaje", FECHA_PRUEBAS)
    espera = registro.agregar_lista_espera("V-002", "primera_licencia_b", "SOL-2026-0031", FECHA_PRUEBAS)
    decision = registro.registrar_decision("hilo", "V-001", "R9", "registrar_tramite", "ok", "reclamo", None)

    # Assert
    assert ticket == 1 and aviso == 1 and espera == 1 and decision == 1
    assert registro.escalamientos("SOL-2026-0006")[0]["destino"] == "Jefatura OIRS" and len(registro.escalamientos()) == 1
    assert registro.notificaciones("V-001")[0]["canal"] == "correo"
    assert registro.lista_espera()[0]["folio"] == "SOL-2026-0031"
    assert registro.decisiones("V-001")[0]["regla"] == "R9" and len(registro.decisiones()) == 1


@solo_postgres
@pytest.mark.integracion
def test_dos_atenciones_simultaneas_no_reservan_la_misma_hora():
    # Arrange: 8 hilos intentan reservar el mismo cupo al mismo tiempo
    from agente.adaptadores.salida.postgres.registro import RegistroPostgres

    registro = RegistroPostgres(URL_PRUEBAS)
    registro.inicializar(FECHA_PRUEBAS)
    cupo = registro.cupos_disponibles(limite=1)[0]["id"]

    # Act
    with ThreadPoolExecutor(max_workers=8) as hilos:
        resultados = list(hilos.map(lambda i: registro.reservar_cupo(cupo, f"SOL-2026-{100 + i:04d}"), range(8)))

    # Assert: solo una atención obtiene la hora
    assert resultados.count(True) == 1


# --- Índice semántico (memoria semántica y episódica) -----------------------------------------------------

DOCS = [Document(page_content="Requisitos para la licencia de conducir clase B en la comuna",
                 metadata={"chunk_id": "a", "fuente_id": "guia_licencias", "tramites": "primera_licencia_b", "nivel": 3}),
        Document(page_content="Requisitos para la licencia de conducir profesional y permisos",
                 metadata={"chunk_id": "b", "fuente_id": "guia_licencias", "tramites": "patente_comercial", "nivel": 3})]
DOCS += [Document(page_content=t, metadata={"chunk_id": f"r{i}", "tramites": "otro"}) for i, t in enumerate(
    ["Horario de atención de la tesorería municipal", "Pago del impuesto territorial y contribuciones",
     "Reclamos y sugerencias en la oficina OIRS", "Certificados de la dirección de obras"])]


def test_busqueda_hibrida_umbral_y_prioridad_por_tramite(crear_indice):
    # Arrange
    indice = crear_indice({"pruebas": 0.99})
    indice.construir({"pruebas": DOCS})

    # Act
    solo_vectorial = indice.buscar("pruebas", "requisitos licencia de conducir", hibrida=False)
    hibrida = indice.buscar("pruebas", "requisitos licencia de conducir", tramite="patente_comercial")

    # Assert: con umbral 0.99 la vectorial no deja pasar nada; la búsqueda por palabras sí, y prioriza el trámite
    assert isinstance(indice, BuscadorFuentes)
    assert solo_vectorial == []
    assert hibrida[0]["chunk_id"] == "b" and hibrida[0]["cobertura_bm25"] >= 0.34


def test_busqueda_vectorial_y_consulta_ajena(crear_indice):
    # Arrange
    indice = crear_indice({"pruebas": 0.2})
    indice.construir({"pruebas": DOCS})

    # Act
    cercano = indice.buscar("pruebas", "licencia de conducir clase B", k=2)
    ajeno = indice.buscar("pruebas", "receta de empanadas de pino")

    # Assert
    assert cercano[0]["chunk_id"] == "a" and cercano[0]["similitud"] > 0.2 and len(cercano) <= 2
    assert ajeno == [] and indice.buscar("pruebas", "   ") == []


def test_memoria_episodica_persiste_y_se_recupera(crear_indice):
    # Arrange
    indice = crear_indice({"casos_resueltos": 0.2})
    indice.construir({"casos_resueltos": [Document(page_content="Caso inicial de patente comercial",
                                                   metadata={"chunk_id": "c0", "tramites": "*"})]})

    # Act
    indice.agregar("casos_resueltos", "Caso SOL-2026-0040: licencia en lista de espera por falta de horas", {"tramites": "*"})
    recargado = crear_indice({"casos_resueltos": 0.2})   # "se reinicia la app"
    r = recargado.buscar("casos_resueltos", "lista de espera licencia falta de horas")

    # Assert
    assert r[0]["texto"].startswith("Caso SOL-2026-0040")
    assert recargado.conteo()["casos_resueltos"] == 2
    assert [f["id"] for f in recargado.corpus("casos_resueltos")] == ["c0", "casos_resueltos:1"]


def test_coleccion_inexistente_devuelve_lista_vacia(crear_indice):
    # Act / Assert
    indice = crear_indice()
    assert indice.buscar("no_existe", "algo") == [] and indice.corpus("no_existe") == []
