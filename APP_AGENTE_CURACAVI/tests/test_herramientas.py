"""Herramientas de consulta, escritura y razonamiento (cada una con su función específica)."""
import pytest

from agente.dominio.modelo import normalizar_folio
from agente.dominio.plazos import dias_habiles_entre, parsear_fecha
from agente.adaptadores.entrada.herramientas import NOMBRES_POR_TIPO, todas


def test_catalogo_de_herramientas_cubre_los_tres_tipos(contenedor):
    # Act: el contenedor crea las herramientas ya conectadas a sus puertos
    por_tipo = contenedor.herramientas()
    tipos = {t: len(lista) for t, lista in por_tipo.items()}

    # Assert
    assert tipos == {"consulta": 7, "escritura": 6, "razonamiento": 4}
    assert {t: [x.name for x in lista] for t, lista in por_tipo.items()} == NOMBRES_POR_TIPO
    assert all(x.description for x in todas(por_tipo))   # el LLM necesita la descripción


# --- Razonamiento ---------------------------------------------------------------------------------

def test_plazo_habil_omite_fines_de_semana_y_feriados(contenedor, h):
    # Arrange: 10 días hábiles desde el 15-09-2026 (incluye el 18 de septiembre)
    args = {"fecha_inicio": "2026-09-15", "dias_habiles": 10}

    # Act
    r = h["calcular_plazo_habil"].invoke(args)

    # Assert
    assert r["vencimiento"] == "2026-09-30"
    assert any("2026-09-18" in f for f in r["feriados_omitidos"])
    assert r["fundamento"] == "Ley N° 19.880, art. 25"


def test_plazo_habil_acepta_formato_chileno_y_rechaza_fechas_invalidas(contenedor, h):
    # Act
    valido = h["calcular_plazo_habil"].invoke({"fecha_inicio": "15/09/2026", "dias_habiles": 10})
    invalido = h["calcular_plazo_habil"].invoke({"fecha_inicio": "ayer", "dias_habiles": 3})

    # Assert
    assert valido["vencimiento"] == "2026-09-30"
    assert "error" in invalido


def test_dias_habiles_entre_fechas():
    # Arrange
    viernes, lunes = parsear_fecha("2026-10-30"), parsear_fecha("2026-11-02")

    # Act / Assert: sábado y domingo no cuentan; el 31-10 es feriado
    assert dias_habiles_entre(viernes, lunes) == 1
    assert dias_habiles_entre(lunes, viernes) == 0


def test_fecha_actual_usa_la_fecha_de_referencia(contenedor, h):
    # Act
    r = h["fecha_actual"].invoke({})

    # Assert
    assert r == {"fecha": "2026-11-04", "dia_semana": "miércoles"}


def test_verificar_requisitos_detecta_faltantes_con_su_fundamento(contenedor, h):
    # Arrange
    declarados = ["Tengo la cédula, las fotos y el certificado de antecedentes, pero no tengo el certificado de estudios"]

    # Act
    r = h["verificar_requisitos"].invoke({"tramite_id": "primera_licencia_b", "documentos_declarados": declarados})

    # Assert
    faltantes = {f["id"] for f in r["faltantes"]}
    assert faltantes == {"estudios", "residencia"}
    assert r["completos"] is False and r["requiere_hora"] is True
    assert all(f["fundamentos"][0]["tipo"] == "municipal" for f in r["faltantes"])
    assert {e["id"] for e in r["etapas"]} == {"examenes", "vehiculo"}


def test_verificar_requisitos_separa_requisito_legal_y_recomendado(contenedor, h):
    # Arrange
    ids = ["permiso_anterior", "revision_tecnica", "certificado_gases", "soap"]

    # Act
    r = h["verificar_requisitos"].invoke({"tramite_id": "permiso_circulacion", "documentos_declarados": ids})

    # Assert: completo; el padrón solo lo recomienda ChileAtiende (orientativo, no obligatorio)
    assert r["completos"] is True
    assert r["opcionales_no_presentados"][0]["fundamentos"][0]["tipo"] == "orientativo"


def test_verificar_requisitos_tramite_desconocido(contenedor, h):
    # Act
    r = h["verificar_requisitos"].invoke({"tramite_id": "pasaporte", "documentos_declarados": []})

    # Assert
    assert "error" in r


def test_contrastar_fuentes_detecta_diferencias_entre_ley_y_municipio(contenedor, h):
    # Arrange
    tema = "¿Cuál es el plazo para renovar el permiso de circulación según la ley y según la municipalidad?"

    # Act
    r = h["contrastar_fuentes"].invoke({"tema": tema, "tramite_id": "permiso_circulacion"})

    # Assert
    niveles = [x["nivel"] for x in r["por_nivel"]]
    assert niveles[0] == "Normativa nacional" and "Información municipal" in niveles
    assert r["discrepancia"] is True and "prevalece" in r["explicacion"]


def test_contrastar_fuentes_sin_resultados(contenedor, h):
    # Act
    r = h["contrastar_fuentes"].invoke({"tema": "receta de empanadas de pino"})

    # Assert
    assert r["por_nivel"] == [] and r["explicacion"].startswith("SIN_RESULTADOS")


# --- Consulta ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("texto,esperado", [
    ("SOL-2026-0012", "SOL-2026-0012"), ("folio sol 2026 12", "SOL-2026-0012"),
    ("SOL_2026_0003", "SOL-2026-0003"), ("sin folio", None)])
def test_normalizar_folio(texto, esperado):
    assert normalizar_folio(texto) == esperado


def test_consultar_estado_no_expone_datos_personales(contenedor, h):
    # Act
    r = h["consultar_estado_solicitud"].invoke({"folio": "sol 2026 0012"})

    # Assert
    assert r["encontrado"] and r["estado"] == "Rechazada"
    assert not {"rut", "telefono", "domicilio", "vecino_id"} & set(r)
    assert r["dias_habiles_desde_ingreso"] > 50


@pytest.mark.parametrize("folio", ["SOL-2026-9999", "12345"])
def test_consultar_estado_folio_inexistente_o_invalido(contenedor, folio, h):
    # Act
    r = h["consultar_estado_solicitud"].invoke({"folio": folio})

    # Assert
    assert r["encontrado"] is False


def test_historial_del_vecino_incluye_rechazo_previo(contenedor, h):
    # Act
    r = h["consultar_historial_vecino"].invoke({"vecino_id": "V-001"})

    # Assert
    assert [s["estado"] for s in r["solicitudes"]] == ["Rechazada"]
    assert r["n_decisiones_previas"] == 0


def test_agenda_entrega_cupos_solo_para_tramites_con_hora(contenedor, h):
    # Act
    licencia = h["consultar_agenda"].invoke({"tramite_id": "primera_licencia_b"})
    permiso = h["consultar_agenda"].invoke({"tramite_id": "permiso_circulacion"})

    # Assert
    assert licencia["requiere_hora"] and len(licencia["cupos"]) == 3
    assert permiso == {"requiere_hora": False, "cupos": []}


def test_agenda_sin_cupos_cuando_cambia_la_condicion(contenedor, h):
    # Arrange
    contenedor.condiciones["agenda_sin_cupos"] = True

    # Act
    r = h["consultar_agenda"].invoke({"tramite_id": "renovacion_licencia"})

    # Assert
    assert r["cupos"] == []


def test_busquedas_separadas_por_tipo_de_fuente(contenedor, h):
    # Act
    leyes = h["buscar_normativa_nacional"].invoke({"consulta": "cómputo de los plazos de días hábiles"})
    municipal = h["buscar_informacion_municipal"].invoke({"consulta": "documentos para renovar el permiso de circulación",
                                                     "tramite": "permiso_circulacion"})
    chileatiende = h["buscar_orientacion_chileatiende"].invoke({"consulta": "renovar licencia de conducir"})

    # Assert
    assert leyes["resultados"][0]["nivel_normativo"] == "Normativa nacional"
    assert leyes["resultados"][0]["cita"] == "Ley N° 19.880, art. 25"
    assert municipal["resultados"][0]["fuente_id"] == "guia_permiso_circulacion"
    assert chileatiende["resultados"][0]["nivel_normativo"] == "Orientación general (ChileAtiende)"


def test_busqueda_fuera_de_tema_devuelve_sin_resultados(contenedor, h):
    # Act
    r = h["buscar_informacion_municipal"].invoke({"consulta": "¿Cuál es la capital de Francia?"})

    # Assert
    assert r["sin_resultados"] is True


def test_casos_similares_recupera_historial_resuelto(contenedor, h):
    # Act
    r = h["buscar_casos_similares"].invoke({"descripcion": "Renovación permiso de circulación rechazada"})

    # Assert
    assert r["casos"] and "Caso SOL-2026" in r["casos"][0]["texto"]


# --- Escritura ---------------------------------------------------------------------------------------

def test_registrar_solicitud_crea_folio_y_bitacora(contenedor, h):
    # Act
    r = h["registrar_solicitud"].invoke({"vecino_id": "V-002", "tramite_id": "reclamo"})

    # Assert
    assert r == {"ok": True, "folio": "SOL-2026-0031", "estado": "Ingresada",
                 "unidad": "Oficina de Informaciones, Reclamos y Sugerencias (OIRS)"}
    assert contenedor.registro.bitacora("SOL-2026-0031")[0]["evento"] == "registro"


def test_registrar_solicitud_de_tramite_desconocido(contenedor, h):
    # Act / Assert
    assert h["registrar_solicitud"].invoke({"vecino_id": "V-002", "tramite_id": "otro"})["ok"] is False


def test_actualizar_solicitud_registra_fundamento(contenedor, h):
    # Act
    ok = h["actualizar_solicitud"].invoke({"folio": "SOL-2026-0003", "estado": "En revisión", "observacion": "Completa",
                                      "fundamento": "Ley N° 19.880, art. 31"})
    no_existe = h["actualizar_solicitud"].invoke({"folio": "SOL-2026-9999", "estado": "x", "observacion": "y"})

    # Assert
    assert ok["ok"] and not no_existe["ok"]
    assert contenedor.registro.bitacora("SOL-2026-0003")[-1]["fundamento"] == "Ley N° 19.880, art. 31"


def test_agendar_hora_y_cupo_tomado_por_otra_persona(contenedor, h):
    # Arrange
    cupos = contenedor.registro.cupos_disponibles(limite=2)
    contenedor.condiciones["cupo_tomado_por_otro"] = True

    # Act
    fallido = h["agendar_hora"].invoke({"folio": "SOL-2026-0003", "cupo_id": cupos[0]["id"]})
    exitoso = h["agendar_hora"].invoke({"folio": "SOL-2026-0003", "cupo_id": cupos[1]["id"]})

    # Assert: la condición se consume una sola vez
    assert fallido == {"ok": False, "motivo": "cupo_tomado", "cupo_id": cupos[0]["id"]}
    assert exitoso["ok"] and exitoso["fecha"] == cupos[1]["fecha"]


def test_escalar_lista_de_espera_y_notificar(contenedor, h):
    # Act
    escalado = h["derivar_o_escalar"].invoke({"folio": "SOL-2026-0006", "destino": "Jefatura OIRS", "motivo": "plazo",
                                         "fundamento": "Ley N° 19.880, art. 25"})
    espera = h["inscribir_lista_espera"].invoke({"vecino_id": "V-008", "tramite_id": "renovacion_licencia", "folio": "SOL-2026-0003"})
    aviso = h["notificar_vecino"].invoke({"vecino_id": "V-001", "folio": "SOL-2026-0004", "mensaje": "Hola"})

    # Assert
    assert escalado["ok"] and contenedor.registro.escalamientos("SOL-2026-0006")[0]["destino"] == "Jefatura OIRS"
    assert espera["ok"] and len(contenedor.registro.lista_espera()) == 1
    assert aviso["ok"] and contenedor.registro.notificaciones("V-001")[0]["canal"] == "correo"


def test_actualizar_solicitud_resuelta_respeta_la_regla_de_dominio(h, contenedor):
    # Act: SOL-2026-0004 ya está «Rechazada»
    r = h["actualizar_solicitud"].invoke({"folio": "SOL-2026-0004", "estado": "Ingresada", "observacion": "reabrir"})
    inexistente = h["actualizar_solicitud"].invoke({"folio": "SOL-2026-9999", "estado": "Ingresada", "observacion": "x"})

    # Assert: no se modifica la base ni la bitácora
    assert not r["ok"] and "Rechazada" in r["error"]
    assert contenedor.registro.obtener_solicitud("SOL-2026-0004")["estado"] == "Rechazada"
    assert contenedor.registro.bitacora("SOL-2026-0004") == [] and not inexistente["ok"]
