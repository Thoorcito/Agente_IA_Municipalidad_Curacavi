"""Adaptadores de SALIDA: implementan los puertos con una tecnología concreta.

postgres/ (Docker) · local/ (SQLite + Chroma) · llm/ (OpenRouter; Gemini opcional) · memoria/ (lógica común:
SQL del registro, ingesta RAG, búsqueda híbrida, checkpointer). Equivalente en Spring: @Repository.
"""
