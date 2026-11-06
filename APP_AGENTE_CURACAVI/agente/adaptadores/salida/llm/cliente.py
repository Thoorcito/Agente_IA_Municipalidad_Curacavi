"""ADAPTADOR del puerto ModeloLenguaje: conexión a los modelos (agente y evaluador).

Ambos proveedores exponen una API compatible con OpenAI, por lo que se usa ChatOpenAI cambiando
la URL base: OpenRouter para el agente y para el evaluador (juez, de otra empresa); Google AI Studio si el
juez es Gemini (JUEZ_PROVIDER=google).
"""
import os

from agente.configuracion import settings


def crear_llm(modelo: str | None = None, proveedor: str = "openrouter", temperature: float | None = None,
              max_tokens: int | None = None, timeout: int = 90):
    """Crea un ChatOpenAI apuntando a OpenRouter o a Google AI Studio."""
    from langchain_openai import ChatOpenAI

    if proveedor == "google":
        clave, url, headers = os.getenv("GEMINI_API_KEY", ""), settings.GOOGLE_BASE_URL, None
        modelo = modelo or settings.GEMINI_MODEL
    else:
        clave, url = os.getenv("OPENROUTER_API_KEY", ""), settings.OPENROUTER_BASE_URL
        headers = {"HTTP-Referer": "http://localhost:8501", "X-Title": "Agente de Tramites Curacavi"}
        modelo = modelo or settings.LLM_MODEL
    if not clave:
        raise ValueError(f"Falta la clave del proveedor {proveedor} (revise su archivo .env o el notebook).")
    # OpenRouter acepta "reasoning.effort" para los modelos que razonan (los demás lo ignoran).
    extra = {"reasoning": {"effort": settings.LLM_REASONING_EFFORT}} \
        if proveedor == "openrouter" and settings.LLM_REASONING_EFFORT else None
    return ChatOpenAI(model=modelo, api_key=clave, base_url=url, default_headers=headers,
                      temperature=settings.TEMPERATURE if temperature is None else temperature,
                      max_tokens=max_tokens or settings.LLM_MAX_TOKENS, timeout=timeout, max_retries=2,
                      extra_body=extra)


def llm_del_agente():
    """LLM que usa el agente, o None en modo offline (el agente funciona igual, con plantillas)."""
    if settings.LLM_PROVIDER == "offline":
        return None
    return crear_llm()


def crear_juez():
    """Evaluador (LLM-as-judge) configurado en settings: un modelo de otra empresa que el agente (OpenRouter o Gemini)."""
    return crear_llm(settings.JUEZ_MODEL, proveedor=settings.JUEZ_PROVIDER, temperature=0.0, max_tokens=settings.LLM_MAX_TOKENS)
