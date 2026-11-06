"""Pruebas de extremo a extremo del agente (grafo completo) en los escenarios de evaluación."""
import pytest
from langchain_core.messages import AIMessage

from agente.adaptadores.entrada.evaluacion import cargar_escenarios, ejecutar_escenario
from agente.aplicacion.orquestador import AgenteTramites
from tests.conftest import LLMSimulado

ESCENARIOS = cargar_escenarios()


@pytest.mark.parametrize("escenario", ESCENARIOS, ids=[e["id"] for e in ESCENARIOS])
def test_escenario(contenedor, escenario):
    # Arrange
    def crear_agente(checkpointer=None):
        return AgenteTramites(contenedor, checkpointer=checkpointer)

    # Act
    r = ejecutar_escenario(escenario, contenedor, crear_agente)

    # Assert
    assert r["regla_ok"], r["regla"]
    assert r["accion_ok"], r["accion"]
    assert r["herramientas_ok"] and r["escrituras_ok"] and r["replanificacion_ok"]
    assert r["cita_valida"] is True


def test_aprobacion_humana_pausa_el_grafo(agente, contenedor):
    # Act: el agente decide escalar y queda esperando al funcionario
    r = agente.conversar("¿En qué estado está mi reclamo SOL-2026-0006?", "hilo-hitl", "V-003")

    # Assert: nada se escribió todavía
    assert r["pendiente_aprobacion"]["accion"] == "escalar_por_plazo"
    assert contenedor.registro.escalamientos("SOL-2026-0006") == []

    # Act: el funcionario aprueba
    final = agente.resolver_aprobacion("hilo-hitl", True)

    # Assert
    assert final["pendiente_aprobacion"] is None
    assert contenedor.registro.escalamientos("SOL-2026-0006")[0]["destino"] == "Jefatura OIRS"
    assert "ticket N° 1" in final["respuesta"]


def test_replanificacion_queda_en_la_traza(agente, contenedor):
    # Arrange
    contenedor.condiciones["cupo_tomado_por_otro"] = True

    # Act
    r = agente.conversar("Quiero renovar mi licencia de conducir. Tengo mi licencia anterior, la cédula, comprobante "
                         "de domicilio y el certificado de antecedentes.", "hilo-replan", "V-007")

    # Assert
    nodos = [e["nodo"] for e in r["traza"]]
    assert nodos.count("planificar") == 2 and nodos.count("ejecutar") == 2
    assert any("REPLANIFICACIÓN 1" in e["detalle"] for e in r["traza"])
    assert "Hora reservada" in r["respuesta"]


def test_caso_resuelto_se_guarda_en_memoria_episodica(agente, contenedor):
    # Arrange
    antes = contenedor.indice.conteo()["casos_resueltos"]

    # Act
    agente.conversar("Quiero poner un reclamo porque me atendieron mal.", "hilo-caso", "V-012")

    # Assert
    assert contenedor.indice.conteo()["casos_resueltos"] == antes + 1


def test_respuesta_con_llm_cita_con_etiquetas_validas(contenedor):
    # Arrange: el LLM simulado responde citando una etiqueta que sí existe
    llm = LLMSimulado(respuestas=["La ley establece que los plazos son de días hábiles [L1]."])
    agente = AgenteTramites(contenedor, llm=llm)

    # Act
    r = agente.conversar("¿Cómo se cuentan los plazos de días hábiles?", "hilo-llm", "V-009")

    # Assert
    assert r["respuesta"].startswith("La ley establece") and "[L1] Ley N° 19.880" in r["respuesta"]
    assert r["validacion"]["cita_valida"] is True
    assert any("Respuesta por llm" in e["detalle"] for e in r["traza"])
    assert r["modo_redaccion"] == "llm" and r["aviso_llm"] is None


def test_si_el_llm_inventa_citas_se_usa_la_respuesta_extractiva(contenedor):
    # Arrange: el LLM inventa una ley y una etiqueta (dos veces)
    llm = LLMSimulado(respuestas=["Según la Ley N° 20.500 los plazos son de 3 días [L9]."])
    agente = AgenteTramites(contenedor, llm=llm)

    # Act
    r = agente.conversar("¿Cómo se cuentan los plazos de días hábiles?", "hilo-llm-malo", "V-009")

    # Assert: se reintenta una vez y luego se descarta el texto del LLM
    assert llm.llamadas == 2
    assert "20.500" not in r["respuesta"] and "**Normativa nacional**" in r["respuesta"]
    assert r["validacion"]["cita_valida"] is True
    assert r["modo_redaccion"] == "plantilla" and "validación" in r["aviso_llm"]


def test_si_el_llm_falla_el_agente_igual_responde(contenedor):
    # Arrange
    agente = AgenteTramites(contenedor, llm=LLMSimulado(respuestas=["x"], falla=True))

    # Act
    r = agente.conversar("¿Qué días atiende la Dirección de Tránsito para licencias de conducir?", "hilo-caido", "V-009")

    # Assert
    assert r["decision"]["regla_id"] == "R5" and "**Fuentes**" in r["respuesta"]
    # El fallo no queda oculto: el motivo llega al panel y a la traza
    assert r["modo_redaccion"] == "plantilla" and "modelo no disponible" in r["aviso_llm"]
    assert any("LLM no usado" in e["detalle"] for e in r["traza"])


def test_si_el_llm_agota_tokens_razonando_se_informa_el_motivo(contenedor):
    # Arrange: un modelo "de razonamiento" que gasta todo el límite pensando y no escribe nada
    vacio = AIMessage(content="", response_metadata={"finish_reason": "length"})
    agente = AgenteTramites(contenedor, llm=LLMSimulado(respuestas=[vacio]))

    # Act
    r = agente.conversar("¿Cómo se cuentan los plazos de días hábiles?", "hilo-vacio", "V-009")

    # Assert: responde con la versión extractiva y el panel muestra por qué
    assert "**Normativa nacional**" in r["respuesta"] and r["modo_redaccion"] == "plantilla"
    assert "límite de tokens" in r["aviso_llm"]


def test_respuesta_de_tramite_no_usa_llm(contenedor):
    # Arrange: aunque haya LLM, los trámites se responden con plantillas (datos exactos)
    llm = LLMSimulado(respuestas=[AIMessage(content="no debería usarse")])
    agente = AgenteTramites(contenedor, llm=llm)

    # Act
    r = agente.conversar("Quiero poner un reclamo porque me atendieron mal.", "hilo-plantilla", "V-012")

    # Assert
    assert llm.llamadas == 0 and "folio **SOL-2026-0031**" in r["respuesta"]
    assert r["modo_redaccion"] == "plantilla" and r["aviso_llm"] is None
