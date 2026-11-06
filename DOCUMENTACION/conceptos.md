# Glosario de conceptos aplicados

Cada término indica **qué es**, en palabras simples, y **dónde se aplica** en este repositorio. Las rutas de código
son relativas a `APP_AGENTE_CURACAVI/`. Una prueba (`tests/test_documentacion.py`) verifica que los archivos y
funciones citados aquí existan.

## 1. RAG: recuperación y generación aumentada

El agente no responde "de memoria": primero **recupera** fragmentos de las fuentes y luego el modelo **genera** la
respuesta usando solo esos fragmentos.

```
Documentos (PDF/MD) → limpieza → chunks → embeddings → pgvector (Docker) o Chroma (local) → búsqueda híbrida + umbral → fragmentos etiquetados → LLM → validación de citas
```

| Término | Qué es | Dónde se aplica |
|---|---|---|
| RAG (Retrieval-Augmented Generation) | Técnica que combina búsqueda en documentos con generación de texto para que el modelo responda con información verificable | Flujo completo: `agente/adaptadores/salida/local/indice_chroma.py` (recuperación) y `agente/aplicacion/redaccion.py` (generación) |
| Carga de documentos | Leer cada PDF por página, conservando de qué fuente y página viene el texto | `agente/adaptadores/salida/memoria/ingesta.py` → `cargar_documentos()` |
| Limpieza de texto | Quitar encabezados, pies de página y anotaciones al margen que ensucian la búsqueda | `agente/adaptadores/salida/memoria/ingesta.py` → `limpiar_texto_ley()` |
| Chunk (fragmento) | Trozo de texto que se indexa por separado. Si es muy grande mezcla temas; si es muy chico pierde contexto | `agente/adaptadores/salida/memoria/ingesta.py` → `fragmentar()`; tamaños en `agente/configuracion/settings.py` |
| chunk_size / chunk_overlap | Largo máximo del fragmento (800 caracteres) y solape entre fragmentos vecinos (120), para no cortar un requisito a la mitad | `agente/configuracion/settings.py` → `CHUNK_SIZE`, `CHUNK_OVERLAP` |
| Fragmentación por artículo | Las leyes se cortan donde empieza cada "Artículo N", así cada fragmento se puede citar por número de artículo | `agente/adaptadores/salida/memoria/ingesta.py` → `_dividir_ley_por_articulo()` |
| Acotar el corpus | Indexar solo los artículos pertinentes al caso, para que las leyes completas no tapen a las guías prácticas | `data/catalogo_fuentes.json` (campo `articulos_pertinentes`) |
| Metadatos | Datos que acompañan a cada fragmento: fuente, página, artículo, nivel normativo y trámite | `agente/adaptadores/salida/memoria/ingesta.py` → `fragmentar()` |
| Embedding | Vector de números que representa el significado de un texto. Textos parecidos quedan cerca | `agente/adaptadores/salida/memoria/ingesta.py` → `crear_embeddings()` |
| Modelo de embeddings local | MiniLM multilingüe, de 384 dimensiones, que corre en el computador: sin clave ni cuota | `agente/configuracion/settings.py` → `EMBEDDING_MODEL_LOCAL`, `EMBEDDING_DIM` |
| Normalización de vectores | Llevar los vectores a largo 1, para que la similitud coseno sea comparable entre textos | `agente/adaptadores/salida/memoria/ingesta.py` → `crear_embeddings()` (`normalize_embeddings`) |
| Base de datos vectorial | Almacén que guarda los embeddings y encuentra los más cercanos a una consulta | `agente/adaptadores/salida/postgres/indice.py` → `IndicePgvector` (Docker); `agente/adaptadores/salida/local/indice_chroma.py` → `IndiceChroma` (local) |
| Colección / índice | Grupo separado de fragmentos. Aquí hay cuatro: leyes, municipal, chileatiende y casos_resueltos | `agente/configuracion/settings.py` → `COLECCIONES` |
| Similitud coseno | Mide qué tan parecidos son dos vectores (1 = igual). pgvector (operador `<=>`) y Chroma entregan la distancia (1 − similitud) | `agente/adaptadores/salida/postgres/indice.py` → `IndicePgvector.buscar()` |
| Top-k | Cuántos fragmentos se devuelven por búsqueda (k = 4) | `agente/configuracion/settings.py` → `TOP_K` |
| Umbral de similitud | Valor mínimo para aceptar un fragmento. Si nada lo supera, se responde SIN_RESULTADOS en vez de inventar | `agente/configuracion/settings.py` → `umbrales()` |
| Umbral por índice | Cada colección tiene su propio umbral, porque sus similitudes se distribuyen distinto | `agente/configuracion/settings.py` → `UMBRALES_INICIALES`; data/umbrales.json (se crea al calibrar) |
| Calibración del umbral | Elegir el umbral con datos: el que mejor separa preguntas del caso de preguntas ajenas | `agente/adaptadores/entrada/evaluacion.py` → `calibrar_umbrales()` |
| BM25 | Búsqueda clásica por palabras exactas, ponderando las palabras poco frecuentes. Encuentra "SOAP" o "artículo 25" | `agente/adaptadores/salida/local/indice_chroma.py` → `IndiceChroma.buscar()` (rank_bm25, adaptador local) |
| Búsqueda de texto completo | Equivalente de BM25 dentro de PostgreSQL: `tsvector` con raíces en español e índice GIN | `agente/adaptadores/salida/postgres/indice.py` → `IndicePgvector.buscar()` |
| Tokenización y *stemming* | Separar en palabras, quitar tildes y palabras vacías, y recortar ("renovar" y "renovación" quedan parecidas) | `agente/dominio/texto.py` → `tokenizar()` |
| Búsqueda híbrida | Combinar la búsqueda por significado (vectorial) con la búsqueda por palabras (BM25 o texto completo) | `agente/adaptadores/salida/memoria/busqueda_hibrida.py` → `fusionar()` |
| RRF (Reciprocal Rank Fusion) | Forma de unir dos rankings sumando 1/(60 + posición) | `agente/configuracion/settings.py` → `RRF_K` |
| Priorización por trámite | Subir en el ranking los fragmentos del trámite que se está consultando | `agente/configuracion/settings.py` → `BOOST_TRAMITE` |
| Contexto aumentado | Los fragmentos recuperados se agregan al prompt para que el modelo responda con ellos | `agente/aplicacion/redaccion.py` → `_respuesta_consulta_llm()` |
| Respuesta extractiva | Respuesta armada con las frases más relevantes de los fragmentos, sin LLM. Es el respaldo si el modelo falla | `agente/aplicacion/redaccion.py` → `_respuesta_consulta_extractiva()` |
| Alucinación | Cuando el modelo afirma algo que no está en las fuentes (por ejemplo, el título de una ley) | Se previene con el umbral, el prompt y `agente/dominio/citas.py` → `validar_citas()` |

## 2. Modelos de lenguaje y prompts

| Término | Qué es | Dónde se aplica |
|---|---|---|
| LLM | Modelo de lenguaje que entiende y genera texto. Aquí, un modelo gratuito de OpenRouter | `agente/adaptadores/salida/llm/cliente.py` → `crear_llm()` |
| OpenRouter | Servicio que da acceso a muchos modelos (varios gratuitos) con una sola clave | `agente/configuracion/settings.py` → `OPENROUTER_BASE_URL` |
| API compatible con OpenAI | OpenRouter y Google aceptan el mismo formato de llamada, así que basta cambiar la URL | `agente/adaptadores/salida/llm/cliente.py` → `crear_llm()` (ChatOpenAI) |
| Temperatura | Qué tan "creativo" es el modelo. Baja (0,1) da respuestas más estables | `agente/configuracion/settings.py` → `TEMPERATURE` |
| System prompt | Instrucciones fijas que definen el rol, las reglas y el formato del asistente | `agente/aplicacion/redaccion.py` → `PROMPT_CONSULTA` |
| Zero-shot estructurado | Prompt sin ejemplos, pero con secciones claras: rol, reglas y formato | `agente/aplicacion/redaccion.py` → `PROMPT_CONSULTA` |
| Few-shot | Incluir ejemplos de respuesta ideal en el prompt. Aquí, uno sobre un tema distinto al de las pruebas | `agente/aplicacion/redaccion.py` → `PROMPT_CONSULTA` (bloque EJEMPLO) |
| Salida estructurada | Pedirle al modelo una respuesta con un esquema fijo (pydantic) en vez de texto libre | `agente/aplicacion/nlu.py` → `PercepcionLLM` |
| Tool calling | Capacidad del modelo de pedir que se ejecute una herramienta con ciertos argumentos | `agente/adaptadores/entrada/evaluacion.py` → `evaluar_llm_puro()`; prueba en el notebook (sección 4) |
| PAL (Program-Aided Language) | Los cálculos los hace el código, no el modelo. Ejemplo: días hábiles con feriados | `agente/adaptadores/entrada/herramientas/razonamiento.py` → `calcular_plazo_habil()` |
| Inyección de prompts | Intento de que el modelo ignore sus reglas ("olvida tus instrucciones…") | `agente/aplicacion/nlu.py` → `PATRON_INYECCION`; regla R1 |
| Límite de cuota (429) | El proveedor rechaza llamadas cuando se supera el límite por minuto o por día | `agente/aplicacion/llm_utilidades.py` → `con_reintento()`, `CuotaAgotadaError` |

## 3. Agente y orquestación

| Término | Qué es | Dónde se aplica |
|---|---|---|
| Agente de IA | Sistema que percibe, decide un plan, usa herramientas y actúa sobre un entorno, no solo responde | `agente/aplicacion/orquestador.py` → `AgenteTramites` |
| LangGraph | Framework para construir agentes como grafos con estado, ciclos y pausas | `agente/aplicacion/orquestador.py` → `construir_grafo()` |
| Grafo de estados | Nodos (pasos) unidos por aristas. Las aristas condicionales eligen el siguiente paso según el estado | `agente/aplicacion/orquestador.py` → `construir_grafo()` (`add_conditional_edges`) |
| Estado | Datos compartidos que cada nodo lee y actualiza | `agente/aplicacion/orquestador.py` → `EstadoAgente` |
| Reductor | Regla para combinar una actualización con el estado anterior (por ejemplo, agregar a una lista) | `agente/aplicacion/orquestador.py` → `acumular()` |
| Herramienta (tool) | Función que el agente puede ejecutar. Su docstring es el contrato que lee el modelo | `agente/adaptadores/entrada/herramientas/__init__.py` → `crear_herramientas()` |
| Herramientas de consulta, escritura y razonamiento | Leen información; modifican el sistema; o calculan y comparan | `agente/adaptadores/entrada/herramientas/consulta.py`, `agente/adaptadores/entrada/herramientas/escritura.py`, `agente/adaptadores/entrada/herramientas/razonamiento.py` |
| Percepción (NLU) | Entender el mensaje: intención, trámite, folio, documentos y riesgos | `agente/aplicacion/nlu.py` → `percibir()` |
| Planificador | Decide la acción y arma el plan de pasos a partir de los hechos | `agente/dominio/planner.py` → `decidir()` |
| Reglas priorizadas | Se evalúan en orden y gana la primera que se cumple | `agente/dominio/planner.py` → `REGLAS` |
| Función pura | Con la misma entrada siempre da la misma salida y no toca la base de datos. Por eso es fácil de probar | `agente/dominio/planner.py` → `decidir()` |
| Plan-and-execute | Primero se arma un plan completo y después se ejecuta paso a paso | `agente/aplicacion/orquestador.py` (nodos planificar y ejecutar) |
| Replanificación | Si una condición cambia durante la ejecución, se vuelve a diagnosticar y se arma un plan nuevo | `agente/aplicacion/orquestador.py` (arista ejecutar → diagnosticar) |
| Humano en el ciclo | El agente se detiene y espera la aprobación de una persona antes de una acción sensible | `agente/aplicacion/orquestador.py` (nodo aprobacion con interrupt) → `AgenteTramites.resolver_aprobacion()` |
| ReAct / agente "LLM puro" | Agente en que el modelo razona y elige herramientas en un ciclo. Se usa como comparación | `agente/adaptadores/entrada/evaluacion.py` → `evaluar_llm_puro()` |
| Diseño híbrido | Reglas en código para decidir; LLM solo para lenguaje. Más exacto y no depende de la cuota | `agente/aplicacion/orquestador.py`, `agente/dominio/planner.py`, `agente/aplicacion/redaccion.py` |
| Límite de recursión | Tope de pasos del grafo, para evitar ciclos infinitos | `agente/aplicacion/orquestador.py` → `AgenteTramites` (`recursion_limit`) |
| Guardrails | Protecciones: rechazar pedidos de datos personales y de cambio de reglas, y derivar lo que no es municipal | `agente/dominio/planner.py` → reglas R1 y R2 |

## 4. Memoria

| Término | Qué es | Dónde se aplica |
|---|---|---|
| Memoria de corto plazo | Lo que el agente recuerda de una conversación: trámite en curso, documentos y folio | `agente/adaptadores/salida/memoria/conversaciones.py` |
| Checkpointer | Guarda el estado del grafo después de cada paso. En PostgreSQL o SQLite sobrevive al cierre de la app | `agente/adaptadores/salida/memoria/conversaciones.py` → `crear_checkpointer()` |
| thread_id (hilo) | Identificador de una conversación (el "N° de atención" de la app) | `agente/aplicacion/orquestador.py` → `AgenteTramites.conversar()` |
| Resumen de conversación | Los mensajes antiguos se condensan, así la conversación no crece sin límite | `agente/aplicacion/resumen.py` → `resumir()` |
| Memoria de largo plazo | Lo que persiste entre sesiones y vecinos: solicitudes, bitácora, agenda y decisiones | `agente/adaptadores/salida/memoria/registro_sql.py` → `RegistroSQL`; `agente/adaptadores/salida/postgres/registro.py` → `RegistroPostgres` |
| Operación atómica | Reservar una hora solo si sigue libre, en una sola instrucción, para que dos personas no la tomen | `agente/adaptadores/salida/memoria/registro_sql.py` → `RegistroSQL.reservar_cupo()` |
| Memoria semántica | Conocimiento indexado por significado (fragmentos de fuentes) | `agente/adaptadores/salida/local/indice_chroma.py` → `IndiceChroma` |
| Memoria episódica | Casos ya resueltos que se guardan y se recuperan cuando llega uno parecido | `agente/adaptadores/salida/local/indice_chroma.py` → `IndiceChroma.agregar()`; `agente/adaptadores/entrada/herramientas/consulta.py` → `buscar_casos_similares()` |
| Seudonimización | Identificar al vecino con un código (V-001) en vez de datos personales | `data/vecinos.csv` |

## 5. Fuentes y marco normativo

| Término | Qué es | Dónde se aplica |
|---|---|---|
| Catálogo de fuentes | Fuente única de títulos oficiales, niveles y formas de citar | `data/catalogo_fuentes.json`; `agente/dominio/citas.py` → `catalogo()` |
| Jerarquía normativa | La ley prevalece sobre la información municipal y la orientación | `DOCUMENTACION/marco_normativo.md` |
| Texto refundido | Versión que reúne una ley con sus modificaciones; se cita con su número propio (por ejemplo, DFL N° 1/2006) | `data/catalogo_fuentes.json` |
| Cita canónica | Cita escrita por el código según el tipo de fuente (por artículo o por página) | `agente/dominio/citas.py` → `formatear_cita()` |
| Etiquetas de cita | [L] ley, [N] norma municipal, [M] información municipal, [O] ChileAtiende, [S] simulado | `agente/dominio/citas.py` → `etiquetar()` |
| Validación de citas | Revisar que cada cita exista entre lo recuperado y que no se nombren leyes inventadas | `agente/dominio/citas.py` → `validar_citas()` |
| Contraste de fuentes | Comparar fechas y plazos entre niveles y explicar cuál prevalece | `agente/dominio/citas.py` → `contrastar()`; herramienta `agente/adaptadores/entrada/herramientas/razonamiento.py` → `contrastar_fuentes()` |
| Días hábiles | Días sin sábados, domingos ni festivos (Ley N° 19.880, art. 25) | `agente/dominio/plazos.py` → `sumar_dias_habiles()` |
| Plazo legal vs. interno | El legal lo fija una ley; el interno es una política de atención (aquí, simulada) | `agente/dominio/planner.py` → `evaluar_plazo()` |

## 6. Evaluación

| Término | Qué es | Dónde se aplica |
|---|---|---|
| Conjunto de prueba | Preguntas con su respuesta de referencia y sus fuentes esperadas | `data/eval/preguntas.json` |
| Escenario | Conversación con la decisión y las herramientas que se esperan | `data/eval/escenarios.json` |
| Ablación (antes/después) | Agregar una mejora a la vez para medir cuánto aporta cada una | `agente/adaptadores/entrada/evaluacion.py` → `CONFIGURACIONES_ABLACION` |
| Recall@k | Porcentaje de las fuentes esperadas que aparecen entre los k primeros resultados | `agente/adaptadores/entrada/evaluacion.py` → `evaluar_recuperacion()` |
| Hit rate | Si al menos una fuente esperada fue recuperada | `agente/adaptadores/entrada/evaluacion.py` → `evaluar_recuperacion()` |
| MRR | Qué tan arriba aparece la primera fuente correcta (1 = primera posición) | `agente/adaptadores/entrada/evaluacion.py` → `evaluar_recuperacion()` |
| Rechazo de preguntas ajenas | Que una pregunta que no es del caso no recupere nada | `agente/adaptadores/entrada/evaluacion.py` → `CONSULTAS_NEGATIVAS` |
| Exactitud de decisión | Porcentaje de escenarios con la regla y la acción esperadas | `agente/adaptadores/entrada/evaluacion.py` → `evaluar_escenarios()` |
| LLM como juez | Un modelo distinto evalúa las respuestas del agente | `agente/adaptadores/entrada/evaluacion.py` → `juzgar()` |
| Arnés de evaluación (*harness*) | Código que ejecuta al agente automáticamente con casos de prueba y compara lo que hizo con lo esperado | `agente/adaptadores/entrada/evaluacion.py` → `evaluar_escenarios()` |
| Correctness | ¿La respuesta coincide con la de referencia? | `agente/adaptadores/entrada/evaluacion.py` → `PROMPT_JUEZ` |
| Faithfulness | ¿Todo lo afirmado está respaldado por lo recuperado? | `agente/adaptadores/entrada/evaluacion.py` → `PROMPT_JUEZ` |
| Métricas deterministas | Calculadas por código, sin LLM: cita válida, tipo de fuente, privacidad, herramienta correcta | `agente/adaptadores/entrada/evaluacion.py` → `metricas_deterministas()` |
| Caché de evaluación | Guardar respuestas ya evaluadas para no repetir llamadas y repartir la ejecución en varios días | `agente/adaptadores/entrada/evaluacion.py` → `evaluar_respuestas()` |
| Latencia | Tiempo de respuesta por turno | `agente/aplicacion/orquestador.py` → `AgenteTramites.conversar()` (`latencia_s`) |
| Trazabilidad | Poder reconstruir qué hizo el agente y por qué: traza por turno, bitácora por folio y, opcionalmente, LangSmith | `agente/aplicacion/orquestador.py` (`traza`); `agente/adaptadores/salida/memoria/registro_sql.py` → `RegistroSQL.bitacora()` |

## 7. Ingeniería y pruebas

| Término | Qué es | Dónde se aplica |
|---|---|---|
| Fuente única de verdad | Un solo lugar define modelos y parámetros; el resto de los documentos los toma de ahí | `agente/configuracion/settings.py` → `ficha_tecnica()`; `scripts/ficha_tecnica.py` |
| Variables de entorno (.env) | Configuración y claves fuera del código; nunca se suben al repositorio | `.env.example`; `agente/configuracion/settings.py` |
| Modo offline | Funcionamiento sin LLM ni descargas. Sirve para pruebas y como plan B de la demo | `agente/configuracion/settings.py` → `LLM_PROVIDER`, `EMBEDDINGS_PROVIDER` |
| Prueba unitaria | Verifica una pieza aislada (una herramienta, una regla) | `tests/test_herramientas.py`, `tests/test_nlu_y_planner.py` |
| Prueba de extremo a extremo | Recorre el grafo completo con un escenario real | `tests/test_agente.py` |
| Patrón AAA | Cada prueba separa Arrange (preparar), Act (ejecutar) y Assert (verificar) | Todas las pruebas de `tests/` |
| Mock / doble de prueba | Objeto que reemplaza a uno real (LLM, embeddings) para probar sin internet y con resultados repetibles | `tests/conftest.py` → `LLMSimulado`; `agente/adaptadores/salida/memoria/ingesta.py` → `HashingEmbeddings` |
| Fixture | Preparación reutilizable para varias pruebas (base de datos limpia, agente listo) | `tests/conftest.py` |
| Cobertura de código | Porcentaje de líneas ejecutadas por las pruebas; la meta mínima es 80 % | `pyproject.toml` (pytest-cov) |
| Test de coherencia documental | Falla si la documentación contradice al código | `tests/test_documentacion.py` |
| Interfaz Streamlit | Aplicación web escrita solo en Python; aquí es solo la vista | `app.py` |
| Prueba de contrato | La misma batería de pruebas corre contra los dos adaptadores de un puerto (SQLite y PostgreSQL) | `tests/integracion/test_contrato_adaptadores.py` |
| Cobertura | Porcentaje del código que ejecutan las pruebas (meta: 80 %) | `pyproject.toml` (pytest-cov) |

## 8. Arquitectura de software (hexagonal, DDD y Docker)

El código está organizado como una **arquitectura hexagonal** (puertos y adaptadores) con ideas de **DDD**
(diseño guiado por el dominio). Las equivalencias con Spring (Java) ayudan a ubicar cada pieza.

| Término | Qué es | Dónde se aplica |
|---|---|---|
| Arquitectura hexagonal | El núcleo (reglas del negocio) no depende de la tecnología de afuera; la tecnología se conecta por puertos | `agente/aplicacion/puertos.py`, `agente/configuracion/contenedor.py`; diagrama en `DOCUMENTACION/arquitectura.md` |
| Dominio | Las reglas del negocio municipal, sin frameworks ni bases de datos (≈ clases de dominio en Spring) | `agente/dominio/modelo.py`, `agente/dominio/planner.py` |
| Entidad | Objeto con identidad propia que protege sus reglas. La solicitud se identifica por su folio | `agente/dominio/modelo.py` → `Solicitud.cambiar_estado()` |
| Objeto de valor | Valor sin identidad propia, definido por su contenido: estado, folio, cupo | `agente/dominio/modelo.py` → `EstadoSolicitud`, `Cupo`, `normalizar_folio()` |
| Servicio de dominio | Lógica del negocio que no pertenece a una sola entidad: decidir qué hacer, contar plazos | `agente/dominio/planner.py` → `decidir()`; `agente/dominio/plazos.py` |
| Regla de dependencia | El dominio no importa LangChain, SQLite, PostgreSQL ni Chroma; una prueba lo verifica | `tests/test_arquitectura.py` |
| Puerto | Interfaz que el núcleo necesita del exterior (≈ interfaz `Repository`) | `agente/aplicacion/puertos.py` → `RegistroMunicipal`, `BuscadorFuentes` |
| Adaptador de salida | Implementación concreta de un puerto con una tecnología (≈ `@Repository`) | `agente/adaptadores/salida/postgres/registro.py` → `RegistroPostgres`; `agente/adaptadores/salida/local/registro_sqlite.py` → `RegistroSQLite` |
| Adaptador de entrada | Por donde se usa el sistema: interfaz, herramientas, scripts (≈ `@RestController`) | `agente/adaptadores/entrada/controlador.py` → `ControladorAtencion`; `agente/adaptadores/entrada/herramientas/__init__.py` → `crear_herramientas()` |
| Controlador | Recibe las acciones de la interfaz y las delega al agente; la vista no conoce la base de datos | `agente/adaptadores/entrada/controlador.py` → `ControladorAtencion.enviar_mensaje()` |
| Inyección de dependencias | Cada pieza recibe lo que necesita por su constructor, en vez de crearlo o buscarlo en una variable global | `agente/configuracion/contenedor.py` → `crear_agente()`; `agente/aplicacion/orquestador.py` → `AgenteTramites` |
| Contenedor (composición) | Único lugar que conoce las piezas concretas y las conecta (≈ `@Configuration` con perfiles) | `agente/configuracion/contenedor.py` → `crear_contenedor()` |
| Dos adaptadores, un puerto | Local (SQLite + Chroma) para Colab y pruebas; PostgreSQL + pgvector para Docker. El agente no cambia | `agente/configuracion/settings.py` → `PERSISTENCIA` |
| PostgreSQL | Base de datos relacional con transacciones; aquí guarda las tres memorias del agente | `agente/adaptadores/salida/postgres/registro.py` → `RegistroPostgres` |
| pgvector | Extensión de PostgreSQL que guarda vectores y busca por distancia coseno (`<=>`) | `agente/adaptadores/salida/postgres/indice.py` → `IndicePgvector` |
| Índice HNSW | Índice de vecinos cercanos aproximados para buscar vectores rápido | `agente/adaptadores/salida/postgres/indice.py` → `IndicePgvector._crear_tabla()` |
| Pool de conexiones | Conexiones abiertas que se reutilizan entre operaciones (más rápido y seguro con varios hilos) | `agente/adaptadores/salida/postgres/conexion.py` → `pool()` |
| Transacción y concurrencia | Si dos atenciones piden la misma hora a la vez, solo una la obtiene | `tests/integracion/test_contrato_adaptadores.py` → `test_dos_atenciones_simultaneas_no_reservan_la_misma_hora()` |
| Docker | Empaqueta la aplicación con todo lo que necesita, para que corra igual en cualquier computador | `Dockerfile` |
| Docker Compose | Levanta varios contenedores juntos (agente + base de datos) con un comando | `docker-compose.yml` |
| Volumen | Carpeta administrada por Docker donde los datos sobreviven a reinicios (base y modelo descargado) | `docker-compose.yml` (`pgdata`, `modelos`) |

## 9. Alternativas consideradas (no usadas en la versión final)

| Término | Qué es | Por qué no se usa |
|---|---|---|
| FAISS | Base vectorial en memoria, muy rápida | pgvector y Chroma permiten agregar casos uno a uno (memoria episódica) y filtrar por metadatos |
| Memoria de ventana | Recordar solo los últimos N turnos | Pierde el inicio de una conversación larga; se reemplazó por un resumen |
| Cadena RAG fija (RunnableSequence) | Pipeline fijo: buscar y luego generar | No permite decidir, escribir ni replanificar; el grafo sí |
| Embeddings en la nube | Embeddings por API con cuota diaria | La cuota limita la indexación; el modelo local no tiene límite |
| Streaming | Mostrar la respuesta mientras se genera | Las respuestas de trámites se arman con plantillas (son instantáneas); se puede agregar para preguntas abiertas |
