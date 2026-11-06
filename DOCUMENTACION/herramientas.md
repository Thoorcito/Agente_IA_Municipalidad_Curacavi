# Herramientas del agente (17)

Todas están definidas con `@tool` de LangChain en `agente/adaptadores/entrada/herramientas/`. Por eso las puede usar el grafo
(planificador) y también un LLM con *tool calling*. El docstring de cada una es la descripción que lee el modelo.

En la arquitectura hexagonal son **adaptadores de entrada**: se crean con `crear_herramientas(contenedor)` y
reciben sus dependencias por inyección (registro, índice, requisitos, reloj). Por eso "registro municipal" e
"índice" significan PostgreSQL + pgvector en Docker, o SQLite + Chroma en modo local, sin cambiar la herramienta.

## Consulta (7): leen, no modifican

| Herramienta | Entrada | Salida | Fuente de datos |
|---|---|---|---|
| `buscar_informacion_municipal` | consulta, trámite | fragmentos con cita y nivel, o `SIN_RESULTADOS` | índice `municipal` |
| `buscar_normativa_nacional` | consulta, trámite | fragmentos de leyes **por artículo** | índice `leyes` |
| `buscar_orientacion_chileatiende` | consulta, trámite | fragmentos de fichas ChileAtiende | índice `chileatiende` |
| `buscar_casos_similares` | descripción | casos resueltos parecidos | índice `casos_resueltos` |
| `consultar_estado_solicitud` | folio (`SOL-AAAA-NNNN`) | estado, unidad, días hábiles transcurridos (sin datos personales) | registro municipal |
| `consultar_historial_vecino` | vecino_id | solicitudes previas y decisiones del agente | registro municipal |
| `consultar_agenda` | trámite | próximos 3 cupos (solo trámites con hora) | registro municipal |

## Escritura (6): modifican el sistema y dejan bitácora

| Herramienta | Entrada | Efecto |
|---|---|---|
| `registrar_solicitud` | vecino_id, trámite, estado, observación | crea un folio nuevo |
| `actualizar_solicitud` | folio, estado, observación, fundamento | cambia el estado y registra el fundamento |
| `agendar_hora` | folio, cupo_id | reserva la hora; si otra persona la tomó, responde `cupo_tomado` y el agente replanifica |
| `derivar_o_escalar` | folio, destino, motivo, fundamento | abre un escalamiento (ticket) |
| `inscribir_lista_espera` | vecino_id, trámite, folio | inscribe en lista de espera |
| `notificar_vecino` | vecino_id, folio, mensaje | registra la notificación por el canal preferido |

## Razonamiento (4): calculan o comparan

| Herramienta | Entrada | Salida |
|---|---|---|
| `verificar_requisitos` | trámite, documentos declarados | presentados, faltantes con fundamento (legal, municipal u orientativo), etapas |
| `calcular_plazo_habil` | fecha de inicio, días hábiles | vencimiento sin fines de semana ni feriados de Chile (Ley N° 19.880, art. 25) |
| `contrastar_fuentes` | tema, trámite | qué dice cada nivel, si hay diferencias y cuál prevalece |
| `fecha_actual` | — | fecha del sistema |

## Quién usa cada herramienta

- `diagnosticar` usa siempre las de consulta y razonamiento que el caso necesita, para reunir los hechos.
- `ejecutar` usa las de escritura (y las búsquedas, en las preguntas abiertas) en el orden del plan.
- Un agente "LLM puro" (`create_agent`) con las mismas 17 herramientas sirve de comparación en la evaluación.
