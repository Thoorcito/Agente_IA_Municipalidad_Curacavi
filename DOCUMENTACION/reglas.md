# Planificación y toma de decisiones

El planificador (`agente/dominio/planner.py`, capa de dominio) es una **función pura**: recibe los hechos que reunió el agente y
devuelve una decisión con su plan de pasos. Las reglas se evalúan de arriba hacia abajo y gana **la primera
que se cumple**. Lo más delicado va primero (seguridad, casos que no son municipales y plazos vencidos);
el flujo normal va al final.

| # | Regla | Condición | Acción | Plan (herramientas de escritura) |
|---|---|---|---|---|
| R1 | Seguridad y privacidad | Intento de cambiar las instrucciones o pedido de datos de terceros | `rechazar_solicitud_riesgosa` | — (si hay folio, informa solo su estado público) |
| R2 | Fuera del alcance municipal | Trámite de otro organismo | `derivar_institucion_externa` | — |
| R3 | Plazo vencido | Consulta por un folio abierto cuyo plazo (interno, municipal o legal) venció | `escalar_por_plazo` **con aprobación humana** | `derivar_o_escalar` → `notificar_vecino` |
| R4 | Consulta de estado | Consulta por folio sin plazo vencido de la municipalidad | `informar_estado` | — |
| R5 | Consulta de información | Pregunta sobre requisitos, costos, plazos o normas | `responder_consulta` | búsquedas por fuente (+ `contrastar_fuentes` y `calcular_plazo_habil` si corresponde) |
| R6 | Faltan antecedentes | Trámite iniciado con documentos obligatorios faltantes | `solicitar_antecedentes` | `registrar_solicitud` (Observada) → `notificar_vecino` |
| R7 | Sin horas disponibles | Trámite completo que requiere hora y no hay cupos | `inscribir_lista_espera` | `registrar_solicitud` → `inscribir_lista_espera` → `notificar_vecino` |
| R8 | Reingreso con historial | Trámite completo de un vecino con rechazo u observación previa del mismo trámite | `reingreso_guiado` | `registrar_solicitud` → (`agendar_hora`) → `notificar_vecino` |
| R9 | Trámite estándar | Trámite completo | `registrar_tramite` | `registrar_solicitud` → (`agendar_hora`) → `notificar_vecino` |
| R10 | Aclarar solicitud | No se reconoce trámite ni consulta | `pedir_aclaracion` | — |

## Por qué este orden

- **R1 antes que todo**: una pregunta puede mencionar un folio y a la vez pedir el RUT de otra persona. La
  protección de datos manda.
- **R3 antes que R4**: si el plazo de la municipalidad venció, informar el estado no basta; hay que escalar.
  Si el plazo vencido es el del vecino (estado *Observada*), no se escala: se informa (R4).
- **R6 antes que R7, R8 y R9**: si faltan documentos no tiene sentido agendar ni reingresar.
- **R7 antes que R8 y R9**: sin horas, el trámite no puede completarse como estándar.

## Condiciones cambiantes y replanificación

1. El plan se arma con la agenda consultada en `diagnosticar`.
2. Si al ejecutar `agendar_hora` la hora ya fue tomada por otra persona, el ejecutor detiene el plan y el grafo
   vuelve a `diagnosticar` (nueva consulta de agenda) y a `planificar`.
3. Como el folio ya existe, el nuevo plan **actualiza** en vez de registrar de nuevo, y reserva otro cupo.
   Si ya no hay cupos, aplica R7 (lista de espera).
4. Se permiten hasta 2 replanificaciones por turno, para evitar ciclos.

## Humano en el ciclo

Las decisiones con `requiere_aprobacion` (escalamientos) pausan el grafo con `interrupt()` de LangGraph. El
estado queda guardado en el checkpointer hasta que un funcionario aprueba o rechaza desde la app
(`resolver_aprobacion`). Si rechaza, el agente solo informa el estado.

## Plazos: no todos son iguales

`evaluar_plazo()` indica qué tipo de plazo aplica y con qué fundamento:

| Situación | Plazo | Tipo | Fundamento |
|---|---|---|---|
| Reclamo OIRS abierto | 10 días hábiles | interno (procedimiento simulado) | Procedimiento interno simulado + cómputo Ley N° 19.880, art. 25 |
| Patente comercial | 10 días | informado por la guía municipal (no precisa si son hábiles) | Guía de patentes |
| Solicitud *Observada* | 5 días (corren para el vecino) | legal | Ley N° 19.880, art. 31 |
| Otros trámites | 6 meses | legal máximo | Ley N° 19.880, art. 27 |
