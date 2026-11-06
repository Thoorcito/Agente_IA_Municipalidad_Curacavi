"""Dominio puro: entidades, objetos de valor, plazos, requisitos y contraste de fuentes.

Estas pruebas no usan base de datos, índices, red ni LLM: el dominio no depende de nada de eso.
"""
from datetime import date

import pytest

from agente.dominio import citas
from agente.dominio import requisitos as req
from agente.dominio.modelo import (Cupo, EstadoSolicitud, Solicitud, TransicionInvalida, siguiente_folio)
from agente.dominio.plazos import sumar_meses

FILA = {"folio": "SOL-2026-0099", "vecino_id": "V-001", "tramite": "Reclamo por atención", "tramite_id": "reclamo",
        "fecha_ingreso": "2026-10-01", "estado": "Ingresada", "unidad_responsable": "OIRS", "observacion": "",
        "fecha_actualizacion": "2026-10-01"}


@pytest.mark.parametrize("estado, abierto", [("Ingresada", True), ("En revisión", True), ("Observada", True),
                                             ("Aprobada", False), ("Rechazada", False), ("Cerrada", False)])
def test_estados_abiertos_y_resueltos(estado, abierto):
    # Act / Assert
    assert EstadoSolicitud(estado).abierto is abierto


def test_solicitud_abierta_cambia_de_estado():
    # Arrange
    solicitud = Solicitud.desde_registro(FILA)

    # Act
    solicitud.cambiar_estado("Observada", "Falta el SOAP", date(2026, 11, 4))

    # Assert
    assert solicitud.estado is EstadoSolicitud.OBSERVADA and solicitud.abierta
    assert solicitud.a_dict()["estado"] == "Observada" and solicitud.fecha_actualizacion == "2026-11-04"


def test_solicitud_resuelta_no_cambia_de_estado():
    # Arrange
    solicitud = Solicitud.desde_registro({**FILA, "estado": "Rechazada"})

    # Act / Assert
    with pytest.raises(TransicionInvalida):
        solicitud.cambiar_estado("Ingresada", "reabrir", date(2026, 11, 4))
    with pytest.raises(ValueError):
        Solicitud.desde_registro(FILA).cambiar_estado("Inventado", "", date(2026, 11, 4))


def test_siguiente_folio_es_correlativo_por_anio():
    # Act / Assert
    assert siguiente_folio(2026, ["SOL-2026-0007", "SOL-2026-0030", "SOL-2025-0099"]) == "SOL-2026-0031"
    assert siguiente_folio(2027, ["SOL-2026-0030"]) == "SOL-2027-0001"


def test_cupo_y_suma_de_meses():
    # Act
    cupo = Cupo.desde_registro({"id": 7, "fecha": "2026-11-24", "hora": "09:00", "estado": "disponible"})

    # Assert
    assert cupo == Cupo(7, "2026-11-24", "09:00")
    assert sumar_meses(date(2026, 8, 31), 6) == date(2027, 2, 28)


def test_requisitos_se_verifican_con_el_catalogo_inyectado():
    # Arrange: un catálogo mínimo, sin leer archivos
    tramites = {"demo": {"nombre": "Trámite demo", "unidad": "Unidad", "valor": "0", "requiere_hora": False,
                         "requisitos": [{"id": "cedula", "nombre": "Cédula", "tipo": "documento", "obligatorio": True,
                                         "sinonimos": ["cedula", "carnet"], "fundamentos": []},
                                        {"id": "foto", "nombre": "Foto", "tipo": "documento", "obligatorio": True,
                                         "sinonimos": ["foto"], "fundamentos": []}]}}

    # Act
    r = req.verificar(tramites, "demo", ["traigo mi carnet pero no tengo la foto"])

    # Assert
    assert r["presentados"] == ["cedula"] and [f["id"] for f in r["faltantes"]] == ["foto"]
    assert req.verificar(tramites, "otro", [])["error"].startswith("Trámite desconocido")


def test_contraste_explica_que_la_ley_prevalece():
    # Arrange: fragmentos ya recuperados (sin índice)
    resultados = {
        "leyes": [{"fuente_id": "dl_3063", "articulo": "15", "texto": "El pago se hará hasta el 31 de marzo de cada año."}],
        "municipal": [{"fuente_id": "guia_permiso_circulacion", "pagina": 1, "texto": "Se renueva durante el mes de marzo."}],
        "chileatiende": [],
    }

    # Act
    r = citas.contrastar(resultados, "plazo del permiso", "la Dirección de Tránsito")

    # Assert
    assert r["discrepancia"] and "prevalece" in r["explicacion"]
    assert [n["nivel"] for n in r["por_nivel"]] == ["Normativa nacional", "Información municipal"]
    assert citas.contrastar({}, "x", "y")["explicacion"].startswith("SIN_RESULTADOS")
