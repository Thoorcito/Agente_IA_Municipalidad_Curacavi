"""ADAPTADORES DOCKER: PostgreSQL 16 + extensión pgvector.

Una sola base de datos guarda las tres memorias del agente:
- largo plazo: tablas del registro municipal (RegistroPostgres),
- semántica: tabla de fragmentos con su vector y su índice de texto completo (IndicePgvector),
- corto plazo: checkpoints de LangGraph por hilo de conversación (PostgresSaver).

Se activan con PERSISTENCIA=postgres y DATABASE_URL (ver docker-compose.yml).
"""
