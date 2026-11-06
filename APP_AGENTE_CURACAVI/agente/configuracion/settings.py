"""Configuración central del agente.

Este archivo es la ÚNICA fuente de verdad para modelos, dimensiones, umbrales y rutas.
README, diagramas, notebook e informe toman estos valores de aquí (ver scripts/ficha_tecnica.py),
y la prueba tests/test_documentacion.py falla si algún documento nombra un modelo distinto.

Todo valor puede cambiarse con variables de entorno (archivo .env), sin tocar el código.
"""
import json
import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

# Estructura del repositorio:
#   <raíz>/README.md · docker-compose.yml · .env
#   <raíz>/APP_AGENTE_CURACAVI/   código (BASE_DIR)
#   <raíz>/DOCUMENTACION/         informe, presentación, notebook y documentos técnicos
#   <raíz>/EVIDENCIAS_TEST/       capturas, diagramas, pruebas y evaluaciones
BASE_DIR = Path(__file__).resolve().parents[2]          # APP_AGENTE_CURACAVI
REPO_DIR = BASE_DIR.parent                              # raíz del repositorio
README = REPO_DIR / "README.md"
DOCUMENTACION_DIR = REPO_DIR / "DOCUMENTACION"
EVIDENCIAS_DIR = REPO_DIR / "EVIDENCIAS_TEST"

# Las claves se leen del .env de la raíz del repositorio (el mismo que usa Docker). En Colab se ingresan
# con getpass. Si existe un .env dentro de APP_AGENTE_CURACAVI, también se lee (sin pisar lo anterior).
load_dotenv(REPO_DIR / ".env")
load_dotenv(BASE_DIR / ".env")

# --- Organización -----------------------------------------------------------------------------
MUNICIPALIDAD = "Municipalidad de Curacaví"

# --- Rutas ------------------------------------------------------------------------------------
DATA_DIR = BASE_DIR / "data"
FUENTES_DIR = DATA_DIR / "fuentes"                  # documentos originales (PDF / MD)
CATALOGO_FUENTES = DATA_DIR / "catalogo_fuentes.json"
REQUISITOS = DATA_DIR / "requisitos.json"
SOLICITUDES_CSV = DATA_DIR / "solicitudes.csv"
VECINOS_CSV = DATA_DIR / "vecinos.csv"
EVAL_DIR = DATA_DIR / "eval"
RUNTIME_DIR = Path(os.getenv("RUNTIME_DIR", DATA_DIR / "runtime"))   # se regenera; no va al repo
EVIDENCE_DIR = EVIDENCIAS_DIR / "evaluaciones"         # resultados de scripts/evaluar.py y del notebook

# --- Persistencia (arquitectura hexagonal: se elige el adaptador, el agente no cambia) -------------
# "local":    SQLite + Chroma en RUNTIME_DIR. Para Google Colab, las pruebas y el modo venv.
# "postgres": PostgreSQL 16 + pgvector. Es lo que usa Docker Compose (ver docker-compose.yml).
PERSISTENCIA = os.getenv("PERSISTENCIA", "local")
DATABASE_URL = os.getenv("DATABASE_URL", "")

# --- Modelos ----------------------------------------------------------------------------------
# LLM_PROVIDER: "openrouter" usa el modelo gratuito de OpenRouter; "offline" no llama a ningún LLM
# (respuestas con plantillas). El modo offline sirve para tests, capturas y como plan B de la demo.
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openrouter")
LLM_MODEL = os.getenv("LLM_MODEL", "nvidia/nemotron-3.5-super-vl:free")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
TEMPERATURE = 0.1
# Los modelos "de razonamiento" (p. ej. Nemotron) piensan antes de escribir y ese razonamiento cuenta dentro
# de max_tokens: con un límite bajo se quedan sin espacio y devuelven el texto vacío (finish_reason=length).
# Por eso el límite es amplio y se pide un razonamiento corto ("low"); deje LLM_REASONING_EFFORT vacío para no enviarlo.
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "4000"))
LLM_REASONING_EFFORT = os.getenv("LLM_REASONING_EFFORT", "low")

# El evaluador (juez) es un modelo DISTINTO del agente y de OTRA empresa, para que el agente no se evalúe a sí mismo.
# Por defecto: recursive/flint (OpenRouter), porque la clave de Gemini del equipo no tiene nivel gratuito (error 403).
# Con una clave de Gemini con nivel gratuito: JUEZ_PROVIDER=google y JUEZ_MODEL=<modelo Gemini>.
JUEZ_PROVIDER = os.getenv("JUEZ_PROVIDER", "openrouter")
JUEZ_MODEL = os.getenv("JUEZ_MODEL", "recursive/flint-v1.0:free")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")   # modelo por defecto si se usa Google AI Studio
GOOGLE_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

# --- Embeddings -------------------------------------------------------------------------------
# "local": modelo multilingüe de sentence-transformers que corre en la máquina (sin cuota ni clave).
# "offline": embeddings por hashing de palabras (sin descargas). Solo para tests y modo sin internet.
EMBEDDINGS_PROVIDER = os.getenv("EMBEDDINGS_PROVIDER", "local")
EMBEDDING_MODEL_LOCAL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EMBEDDING_DIM = 384

# --- Recuperación (RAG) -----------------------------------------------------------------------
CHUNK_SIZE = 800          # un artículo de ley o un bloque de requisitos cabe completo
CHUNK_OVERLAP = 120       # 15 % de solape para no cortar requisitos
MIN_CARACTERES_CHUNK = 50
TOP_K = 4
COLECCIONES = ["municipal", "leyes", "chileatiende", "casos_resueltos"]
RRF_K = 60                # constante de Reciprocal Rank Fusion (vectorial + BM25)
BOOST_TRAMITE = 1.5       # prioriza fragmentos del trámite consultado

# Umbrales de similitud POR ÍNDICE. Valores iniciales; scripts/eval_retrieval.py los recalibra con
# las preguntas de prueba y los guarda en data/umbrales.json, que tiene prioridad si existe.
UMBRALES_INICIALES = {
    "local": {"municipal": 0.35, "leyes": 0.40, "chileatiende": 0.35, "casos_resueltos": 0.45},
    "offline": {"municipal": 0.25, "leyes": 0.25, "chileatiende": 0.25, "casos_resueltos": 0.30},
}
UMBRALES_PATH = DATA_DIR / "umbrales.json"


def umbrales(proveedor: str | None = None) -> dict:
    """Devuelve los umbrales por índice del proveedor de embeddings (calibrados si existen)."""
    proveedor = proveedor or EMBEDDINGS_PROVIDER
    valores = dict(UMBRALES_INICIALES.get(proveedor, UMBRALES_INICIALES["local"]))
    if UMBRALES_PATH.exists():
        calibrados = json.loads(UMBRALES_PATH.read_text(encoding="utf-8")).get(proveedor, {})
        valores.update(calibrados)
    return valores


# --- Reglas de negocio ------------------------------------------------------------------------
PLAZO_OIRS_DIAS_HABILES = 10       # plazo INTERNO (procedimiento simulado) para responder reclamos
PLAZO_SUBSANAR_DIAS = 5            # Ley 19.880, art. 31: plazo para subsanar una solicitud incompleta
PLAZO_PATENTE_DIAS = 10            # guía municipal de patentes: "10 días para otorgamiento"
PLAZO_MAXIMO_PROCEDIMIENTO_MESES = 6   # Ley 19.880, art. 27
DIAS_ANTICIPACION_HORA = 20        # guía de licencias: reservar con 20 días de anticipación

# --- Control del agente -----------------------------------------------------------------------
MAX_REPLANIFICACIONES = 2          # evita ciclos infinitos de replanificación
MENSAJES_ANTES_DE_RESUMIR = 8      # sobre este número, la conversación antigua se resume
APROBACION_HUMANA = os.getenv("APROBACION_HUMANA", "true").lower() == "true"


def fecha_referencia() -> date:
    """Fecha "de hoy" del agente. FECHA_REFERENCIA (AAAA-MM-DD) permite fijarla en demos y tests."""
    valor = os.getenv("FECHA_REFERENCIA")
    return date.fromisoformat(valor) if valor else date.today()


def ficha_tecnica() -> dict:
    """Resumen de la configuración que se publica igual en README, notebook e informe."""
    return {
        "LLM del agente": f"{LLM_MODEL} (OpenRouter, nivel gratuito)",
        "Evaluador (juez)": f"{JUEZ_MODEL} ({'Google AI Studio' if JUEZ_PROVIDER == 'google' else 'OpenRouter, otra empresa que el agente'})",
        "Embeddings": f"{EMBEDDING_MODEL_LOCAL} (local, {EMBEDDING_DIM} dimensiones)",
        "Arquitectura": "Hexagonal: dominio, puertos y adaptadores intercambiables",
        "Persistencia (Docker)": "PostgreSQL 16 + pgvector: registro, vectores y memoria de conversaciones",
        "Persistencia (local y Colab)": "SQLite + Chroma",
        "Colecciones del RAG": "municipal, leyes, chileatiende, casos_resueltos",
        "Recuperación": f"Híbrida vectorial + palabras (RRF k={RRF_K}), top-k {TOP_K}, umbral por índice",
        "Fragmentación": f"{CHUNK_SIZE} caracteres, solape {CHUNK_OVERLAP}, corte por artículo",
        "Framework": "LangGraph + LangChain 1.x",
        "Memoria corto plazo": "Checkpointer de LangGraph (PostgreSQL o SQLite) + resumen de conversación",
        "Memoria largo plazo": "Registro municipal: solicitudes, bitácora, agenda, notificaciones, decisiones",
        "Temperatura": TEMPERATURE,
    }
