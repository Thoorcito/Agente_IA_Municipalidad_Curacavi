"""Evaluación (métricas, juez, caché, comparación de recuperación) y conexión a los modelos (mocks)."""
import json

import pytest
from langchain_core.messages import AIMessage

from agente.adaptadores.entrada import evaluacion as ev
from agente.adaptadores.salida.llm import cliente as modulo_llm
from agente.aplicacion import llm_utilidades
from agente.aplicacion.orquestador import AgenteTramites
from agente.adaptadores.salida.memoria.ingesta import HashingEmbeddings
from agente.configuracion import settings
from tests.conftest import LLMSimulado

# --- LLM -------------------------------------------------------------------------------------------------


def test_crear_llm_sin_clave_avisa(monkeypatch):
    # Arrange
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    # Act / Assert
    with pytest.raises(ValueError, match="Falta la clave"):
        modulo_llm.crear_llm()


def test_crear_llm_apunta_al_proveedor_correcto(monkeypatch):
    # Arrange
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-prueba")
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-prueba")

    # Act
    agente, juez = modulo_llm.crear_llm(), modulo_llm.crear_llm(proveedor="google")

    # Assert
    assert agente.model_name == settings.LLM_MODEL and "openrouter" in str(agente.openai_api_base)
    assert juez.model_name == settings.GEMINI_MODEL and "googleapis" in str(juez.openai_api_base)
    # Margen para modelos que razonan: el razonamiento cuenta dentro de max_tokens
    assert agente.max_tokens == settings.LLM_MAX_TOKENS >= 2000
    assert agente.extra_body == {"reasoning": {"effort": settings.LLM_REASONING_EFFORT}} and juez.extra_body is None


def test_juez_puede_ser_otro_modelo_de_openrouter(monkeypatch):
    # Arrange: la clave de Gemini no tiene nivel gratuito, así que el juez se configura en OpenRouter
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-prueba")
    monkeypatch.setattr(settings, "JUEZ_PROVIDER", "openrouter")
    monkeypatch.setattr(settings, "JUEZ_MODEL", "recursive/flint-v1.0:free")

    # Act
    juez = modulo_llm.crear_juez()

    # Assert: otro modelo que el del agente, temperatura 0 y margen de tokens
    assert juez.model_name == "recursive/flint-v1.0:free" != settings.LLM_MODEL
    assert "openrouter" in str(juez.openai_api_base) and juez.temperature == 0.0 and juez.max_tokens == settings.LLM_MAX_TOKENS
    assert "OpenRouter" in settings.ficha_tecnica()["Evaluador (juez)"]


def test_modo_offline_no_crea_llm(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "offline")
    assert modulo_llm.llm_del_agente() is None


def test_texto_de_mensajes_con_bloques():
    assert llm_utilidades.texto_de(AIMessage(content=[{"type": "text", "text": "Hola"}, " mundo"])) == "Hola mundo"


def test_reintento_ante_limite_por_minuto_y_error_por_cuota_diaria(monkeypatch):
    # Arrange
    monkeypatch.setattr(llm_utilidades.time, "sleep", lambda s: None)
    intentos = {"n": 0}

    def falla_una_vez():
        intentos["n"] += 1
        if intentos["n"] == 1:
            raise RuntimeError("Error 429: rate limit")
        return "ok"

    def cuota_diaria():
        raise RuntimeError("429 free-models-per-day")

    def otro_error():
        raise KeyError("x")

    # Act / Assert
    assert llm_utilidades.con_reintento(falla_una_vez) == "ok" and intentos["n"] == 2
    with pytest.raises(llm_utilidades.CuotaAgotadaError):
        llm_utilidades.con_reintento(cuota_diaria)
    with pytest.raises(KeyError):
        llm_utilidades.con_reintento(otro_error)


# --- Juez y métricas ---------------------------------------------------------------------------------------

def test_juez_devuelve_puntajes_o_avisa_si_no_entiende():
    # Arrange
    bueno = LLMSimulado(respuestas=['Resultado: {"correctness": 1, "faithfulness": 0.5, "comentario": "ok"}'])
    malo = LLMSimulado(respuestas=["no sé"])

    # Act
    r1 = ev.juzgar(bueno, "p", "ref", "ctx", "resp")
    r2 = ev.juzgar(malo, "p", "ref", "ctx", "resp")

    # Assert
    assert r1 == {"correctness": 1.0, "faithfulness": 0.5, "comentario_juez": "ok"}
    assert r2["correctness"] is None and "no interpretable" in r2["comentario_juez"]


def test_metricas_deterministas_de_privacidad_y_tipo_de_fuente():
    # Arrange
    pregunta = {"herramientas_requeridas": [], "tipo": "rechazo", "nivel_esperado": 1}
    salida = {"observaciones": [], "respuesta": "Su RUT es 12.345.678-9", "decision": {"regla_id": "R1"},
              "validacion": {"cita_valida": True, "etiquetas_usadas": ["M1"]}}

    # Act
    m = ev.metricas_deterministas(pregunta, salida)

    # Assert
    assert m["privacidad"] == 0.0 and m["tipo_fuente_correcto"] == 0.0 and m["herramienta_correcta"] == 1.0


def test_juez_con_json_cortado_igual_se_interpreta():
    # Arrange: caso real del Colab: el juez gratuito cortó el JSON en medio del comentario
    juez = LLMSimulado(respuestas=['{"correctness": 0.85, "faithfulness": 0.6, "comentario": "La respuesta cubre'])

    # Act
    r = ev.juzgar(juez, "pregunta", "referencia", "contexto", "respuesta")

    # Assert
    assert (r["correctness"], r["faithfulness"]) == (0.85, 0.6)


def test_un_juicio_no_interpretable_se_reintenta_en_la_siguiente_ejecucion(contenedor, tmp_path):
    # Arrange: primera ejecución con un juez que responde vacío
    preguntas = [p for p in ev.cargar_preguntas() if p["id"] == "P08"]
    cache = tmp_path / "cache.json"
    ev.evaluar_respuestas(lambda: AgenteTramites(contenedor), contenedor, preguntas, juez=LLMSimulado(respuestas=[""]), cache=cache)

    # Act: segunda ejecución con un juez que sí responde
    df = ev.evaluar_respuestas(lambda: AgenteTramites(contenedor), contenedor, preguntas,
                               juez=LLMSimulado(respuestas=['{"correctness": 1, "faithfulness": 1}']), cache=cache)

    # Assert
    assert df["correctness"].tolist() == [1.0]


def test_evaluar_respuestas_usa_cache_y_juez(contenedor, tmp_path):
    # Arrange
    preguntas = [p for p in ev.cargar_preguntas() if p["id"] in ("P08", "P12")]
    juez = LLMSimulado(respuestas=['{"correctness": 1, "faithfulness": 1}'])
    cache = tmp_path / "cache.json"

    # Act: dos ejecuciones; la segunda no debe volver a llamar al juez
    df = ev.evaluar_respuestas(lambda: AgenteTramites(contenedor), contenedor, preguntas, juez=juez, cache=cache)
    llamadas_juez = juez.llamadas
    ev.evaluar_respuestas(lambda: AgenteTramites(contenedor), contenedor, preguntas, juez=juez, cache=cache)

    # Assert
    assert list(df["id"]) == ["P08", "P12"] and df["correctness"].tolist() == [1.0, 1.0]
    assert juez.llamadas == llamadas_juez == 2
    assert set(json.loads(cache.read_text(encoding="utf-8"))) == {"P08", "P12"}


def test_cache_descarta_respuestas_sin_llm_por_fallo(contenedor, tmp_path):
    # Arrange: una caché antigua (sin modo de redacción) y otra con el LLM caído por cuota
    preguntas = [p for p in ev.cargar_preguntas() if p["id"] in ("P08", "P12")]
    cache = tmp_path / "cache.json"
    cache.write_text(json.dumps({
        "P08": {"respuesta": "vieja", "contexto": "", "latencia_s": 1, "regla": "R2"},
        "P12": {"respuesta": "extractiva", "contexto": "", "latencia_s": 1, "regla": "R5",
                "modo_redaccion": "plantilla", "aviso_llm": "CuotaAgotadaError: per-day"}}), encoding="utf-8")

    # Act
    df = ev.evaluar_respuestas(lambda: AgenteTramites(contenedor), contenedor, preguntas, cache=cache)

    # Assert: ambas se vuelven a generar y quedan guardadas con su modo de redacción
    assert "vieja" not in df["respuesta"].tolist() and "extractiva" not in df["respuesta"].tolist()
    guardado = json.loads(cache.read_text(encoding="utf-8"))
    assert all("modo_redaccion" in v for v in guardado.values())


def test_evaluacion_se_detiene_si_se_agota_la_cuota_diaria(contenedor, tmp_path):
    # Arrange: el LLM responde "cuota diaria agotada" (CuotaAgotadaError dentro de la redacción)
    class LLMSinCuota(LLMSimulado):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            raise RuntimeError("Error code: 429 - free-models-per-day limit exceeded")
    preguntas = [p for p in ev.cargar_preguntas() if p["id"] in ("P12", "P17")]
    cache = tmp_path / "cache.json"

    # Act
    df = ev.evaluar_respuestas(lambda: AgenteTramites(contenedor, llm=LLMSinCuota(respuestas=["x"])), contenedor,
                               preguntas, cache=cache)

    # Assert: no se guarda ninguna respuesta extractiva como si fuera del LLM
    assert df.empty and not cache.exists()


def test_comparacion_de_recuperacion_y_calibracion(contenedor, tmp_path):
    # Arrange: dos configuraciones y tres preguntas, con embeddings simulados
    preguntas = [p for p in ev.cargar_preguntas() if p["id"] in ("P01", "P12", "P17")]
    configs = [ev.CONFIGURACIONES_ABLACION[0], ev.CONFIGURACIONES_ABLACION[-1]]

    # Act
    detalle, resumen = ev.evaluar_recuperacion(HashingEmbeddings(), tmp_path, preguntas,
                                               umbrales=settings.umbrales("offline"), configuraciones=configs)
    umbrales = ev.calibrar_umbrales(contenedor.indice, preguntas)

    # Assert
    assert list(resumen["configuracion"]) == [c[0] for c in configs]
    assert (resumen["n_preguntas"] == 3).all()
    assert resumen.iloc[-1]["recall"] >= resumen.iloc[0]["recall"]
    assert set(umbrales) <= {"municipal", "leyes", "chileatiende"} and umbrales


def test_comparacion_con_agente_llm_puro(contenedor):
    # Arrange: el LLM simulado registra una solicitud indebida en un caso de consulta de estado
    llm = LLMSimulado(respuestas=[
        AIMessage(content="", tool_calls=[{"name": "consultar_estado_solicitud", "args": {"folio": "SOL-2026-0012"}, "id": "1"},
                                          {"name": "registrar_solicitud", "args": {"vecino_id": "V-004", "tramite_id": "reclamo"}, "id": "2"}]),
        "Su solicitud está rechazada."])
    escenarios = [e for e in ev.cargar_escenarios() if e["id"] == "E13"]

    # Act
    df = ev.evaluar_llm_puro(llm, contenedor, escenarios)

    # Assert
    assert df.iloc[0]["herramientas_ok"] and not df.iloc[0]["escrituras_ok"]
    assert df.iloc[0]["escrituras_indebidas"] == 1
