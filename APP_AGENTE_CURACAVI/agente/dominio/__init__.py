"""Capa de DOMINIO (centro de la arquitectura hexagonal).

Aquí viven las reglas del negocio municipal: qué es una solicitud y sus estados, cómo se cuentan
los plazos hábiles, qué requisitos exige cada trámite, cómo se cita cada tipo de fuente y qué
decide el agente ante cada situación (planner).

Regla de dependencia: este paquete NO importa LangChain, LangGraph, SQLite, PostgreSQL ni Chroma.
Solo usa Python estándar, la librería `holidays` (feriados de Chile) y datos de referencia
de solo lectura (catálogo de fuentes). Por eso se prueba sin base de datos, sin red y sin LLM.

Equivalente en Spring: las clases de dominio (@Entity, value objects y servicios de dominio)
que no conocen controladores ni repositorios concretos.
"""
