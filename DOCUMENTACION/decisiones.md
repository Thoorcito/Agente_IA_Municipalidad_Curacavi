# Decisiones de diseño

| Requerimiento | Decisión | Alternativa descartada | Por qué |
|---|---|---|---|
| Orquestar un flujo de varias etapas con pausas y retornos | **LangGraph** (`StateGraph`) sobre LangChain 1.x | `AgentExecutor` de LangChain 0.3 | El grafo explícito permite volver a planificar, pausar con `interrupt` y guardar el estado por hilo. AgentExecutor y ConversationBufferMemory quedaron como legado. |
| Decidir de forma correcta y explicable | Planner de **reglas priorizadas** + LLM solo para lenguaje | Que el LLM decida todo | Las reglas se prueban una a una y dejan fundamento. Un modelo gratuito puede omitir pasos o escribir donde no debe (se mide en la evaluación). |
| Retomar trámites entre sesiones | **Checkpointer** de LangGraph por `thread_id` (PostgreSQL en Docker, SQLite en local) | Memoria solo en RAM | Sobrevive al cierre de la app. |
| Conversaciones largas | **Resumen** de mensajes antiguos (sobre 8) | Ventana fija de pocos turnos | Una ventana corta pierde el inicio de la conversación; el resumen conserva trámite, folio y pendientes. |
| Historial del vecino y trazabilidad | **PostgreSQL** (SQLite en local) con bitácora por folio | Archivos CSV | Escrituras atómicas (por ejemplo, reservar una hora aunque dos atenciones la pidan a la vez) y consultas por vecino. |
| Recuperar normas sin que las leyes tapen a las guías | **Índices separados** (leyes, municipal, ChileAtiende) y leyes **acotadas por artículo** | Un índice externo con leyes completas | Las leyes completas generan muchos más fragmentos que las fichas prácticas. |
| Encontrar por significado y por palabra exacta | **Búsqueda híbrida** vectorial + palabras (texto completo de PostgreSQL o BM25), fusión RRF | Solo vectorial | "SOAP", "UTM" o "artículo 25" se encuentran mejor por palabra exacta. |
| Evitar contexto irrelevante | **Umbral por índice**, calibrado con datos | Umbral global fijo | Cada índice tiene su propia distribución de similitudes. |
| Citar sin inventar | **Etiquetas + catálogo + validador** | Pedirle al LLM que escriba la cita | El LLM puede equivocar títulos y números de ley; el código no. |
| Embeddings sin costo ni cuota | **MiniLM multilingüe local** (384 dim.) | Embeddings en la nube con cuota diaria | Sin límite diario, en español y reproducible. |
| Base vectorial | **pgvector** en PostgreSQL (Docker) y **Chroma** (local y Colab) | FAISS | Permiten agregar casos resueltos uno a uno (memoria episódica) y filtrar por metadatos. pgvector deja vectores, registro y conversaciones en una sola base. |
| LLM | **OpenRouter** (modelo gratuito) | Modelos de pago | Costo cero. El diseño híbrido tolera fallas del modelo gratuito. |
| Evaluador independiente | Modelo de **otra empresa** que el agente: `recursive/flint-v1.0` (OpenRouter). Se intentó Gemini, pero la clave del equipo no tiene nivel gratuito (403) | El mismo modelo del agente | Evita que el modelo se evalúe a sí mismo. Proveedor y modelo configurables (`JUEZ_PROVIDER`, `JUEZ_MODEL`). |
| Escalamientos con criterio humano | **Aprobación humana** (`interrupt`) | Escalar automáticamente | Un escalamiento compromete a la institución; lo confirma un funcionario. |
| Interfaz para la demo | **Streamlit** | React + API | Solo Python, rápido de construir; suficiente para un prototipo. |
| Privacidad | **Seudónimos** (V-001) y herramientas sin datos personales | Guardar RUT | El caso no requiere identificar a la persona. |
| Organización del código | **Arquitectura hexagonal**: dominio puro, puertos (`Protocol`) y adaptadores | Módulos que acceden directo a la base | Las reglas se prueban sin base de datos ni LLM, y la persistencia se cambia sin tocar el agente (22/22 escenarios con ambos adaptadores). |
| Entregar dependencias | **Inyección por constructor** desde un contenedor (`agente/configuracion/contenedor.py`) | Variable global con los servicios (*service locator*) | Cada pieza declara lo que necesita; las pruebas pueden pasar dobles de prueba. |
| Reglas de la solicitud | **Entidad** `Solicitud` con sus transiciones de estado | Validar en cada herramienta | Una solicitud resuelta no se reabre, venga el cambio de donde venga. |
| Persistencia de producción | **PostgreSQL 16 + pgvector** | SQLite | Transacciones con bloqueo por fila, búsqueda de texto completo en español y un solo motor para las tres memorias. |
| Portabilidad | **Docker Compose** (agente + base) | Instalar Python y dependencias en cada PC | Un comando levanta todo igual en Windows, Mac o Linux; el venv queda como plan B. |
| Colab y pruebas sin Docker | Se conserva el **adaptador local** (SQLite + Chroma) | Usar solo PostgreSQL | Colab no ejecuta Docker; con hexagonal basta cambiar `PERSISTENCIA`. |
