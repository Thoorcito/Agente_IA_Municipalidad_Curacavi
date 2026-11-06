-- Se ejecuta UNA sola vez, cuando Docker crea el volumen de la base (primer "docker compose up").
-- Las tablas NO se definen aquí: las crean los adaptadores al arrancar (agent/memory/postgres/),
-- para que el esquema tenga una sola fuente de verdad (el código, cubierto por pruebas).

-- Base principal: extensión de vectores para la memoria semántica (RAG).
CREATE EXTENSION IF NOT EXISTS vector;

-- Base de pruebas: la usan las pruebas de integración (docker compose run --rm tests),
-- así nunca borran los datos de la demo.
CREATE DATABASE curacavi_test;
\connect curacavi_test
CREATE EXTENSION IF NOT EXISTS vector;
