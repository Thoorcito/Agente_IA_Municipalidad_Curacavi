"""Contenedor de dependencias (composición de la arquitectura hexagonal).

Es el único lugar que conoce TODAS las piezas concretas y las conecta:
    puertos (agente/aplicacion/puertos.py)  <-  adaptadores (agente/adaptadores/salida/...)  según PERSISTENCIA

    PERSISTENCIA=local     -> RegistroSQLite  + IndiceChroma    + SqliteSaver   (Colab, pruebas, venv)
    PERSISTENCIA=postgres  -> RegistroPostgres + IndicePgvector + PostgresSaver (Docker)

El resto del sistema recibe el contenedor ya armado (inyección por constructor): las herramientas,
el orquestador y el controlador nunca crean sus dependencias ni consultan variables globales.

Equivalente en Spring: una clase @Configuration con métodos @Bean y un perfil (local / docker).
"""
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

from langchain_core.documents import Document

from agente.dominio.requisitos import cargar_catalogo
from agente.adaptadores.salida.memoria.ingesta import cargar_documentos, crear_embeddings, fragmentar, textos_casos_historicos
from agente.aplicacion.puertos import BuscadorFuentes, RegistroMunicipal, Reloj
from agente.configuracion import settings


@dataclass
class Contenedor:
    registro: RegistroMunicipal          # memoria de largo plazo
    indice: BuscadorFuentes              # memoria semántica (RAG + casos resueltos)
    requisitos: dict                     # catálogo de trámites (dato de referencia)
    fecha: Reloj = settings.fecha_referencia
    persistencia: str = "local"
    destino_memoria: str | Path | None = None   # dónde guarda el checkpointer (corto plazo)
    # Condiciones del entorno que la demo puede cambiar en vivo (interruptores de la app):
    #   agenda_sin_cupos: la agenda de licencias no tiene horas libres.
    #   cupo_tomado_por_otro: otra persona toma la hora justo cuando el agente intenta reservarla.
    condiciones: dict = field(default_factory=dict)

    def herramientas(self) -> dict[str, list]:
        """Las 17 herramientas conectadas a los puertos de este contenedor."""
        from agente.adaptadores.entrada.herramientas import crear_herramientas

        return crear_herramientas(self)

    def descripcion(self) -> str:
        if self.persistencia == "postgres":
            return "PostgreSQL + pgvector (Docker)"
        return "SQLite + Chroma (local)"


def _adaptadores(persistencia: str, runtime_dir: Path, proveedor: str, embeddings, database_url: str | None):
    """Crea el registro, el índice y el destino del checkpointer según la persistencia elegida."""
    if persistencia == "postgres":
        from agente.adaptadores.salida.postgres.conexion import esperar_base
        from agente.adaptadores.salida.postgres.indice import IndicePgvector
        from agente.adaptadores.salida.postgres.registro import RegistroPostgres

        url = database_url or settings.DATABASE_URL
        if not url:
            raise ValueError("PERSISTENCIA=postgres requiere DATABASE_URL (ver .env.example y docker-compose.yml).")
        esperar_base(url)
        indice = IndicePgvector(url, embeddings, umbrales=settings.umbrales(proveedor), tabla=f"fragmentos_{proveedor}")
        return RegistroPostgres(url), indice, url

    from agente.adaptadores.salida.local.registro_sqlite import RegistroSQLite
    from agente.adaptadores.salida.local.indice_chroma import IndiceChroma

    indice = IndiceChroma(runtime_dir / f"indices_{proveedor}", embeddings, umbrales=settings.umbrales(proveedor))
    return RegistroSQLite(runtime_dir / "municipalidad.sqlite"), indice, runtime_dir / "memoria_conversaciones.sqlite"


def construir_indices(registro: RegistroMunicipal, indice: BuscadorFuentes) -> dict[str, int]:
    """Ingesta RAG completa: documentos -> fragmentos -> índices, más los casos históricos."""
    resumen = indice.construir(fragmentar(cargar_documentos()))
    casos = textos_casos_historicos(registro.todas_las_solicitudes())
    resumen.update(indice.construir({"casos_resueltos": [Document(page_content=t, metadata=m) for t, m in casos]}))
    return resumen


def crear_contenedor(persistencia: str | None = None, runtime_dir: Path | None = None,
                     proveedor_embeddings: str | None = None, reiniciar: bool = False,
                     fecha: Callable[[], date] | None = None, embeddings=None,
                     reiniciar_indices: bool | None = None, database_url: str | None = None) -> Contenedor:
    """Arma el contenedor con los adaptadores de la persistencia elegida.

    reiniciar=True deja la base en su estado inicial (demo) y, salvo reiniciar_indices=False,
    también reconstruye los índices. Si la base o los índices no existen, se crean.
    """
    persistencia = persistencia or settings.PERSISTENCIA
    proveedor = proveedor_embeddings or settings.EMBEDDINGS_PROVIDER
    reiniciar_indices = reiniciar if reiniciar_indices is None else reiniciar_indices
    fecha = fecha or settings.fecha_referencia
    runtime_dir = Path(runtime_dir or settings.RUNTIME_DIR)
    registro, indice, destino = _adaptadores(persistencia, runtime_dir, proveedor,
                                             embeddings or crear_embeddings(proveedor), database_url)
    if reiniciar or not registro.existe():
        registro.inicializar(fecha())
    if reiniciar_indices or not indice.corpus("municipal"):
        construir_indices(registro, indice)
    return Contenedor(registro=registro, indice=indice, requisitos=cargar_catalogo(), fecha=fecha,
                      persistencia=persistencia, destino_memoria=destino)


def crear_agente(contenedor: Contenedor, llm=None, memoria_persistente: bool = False, checkpointer=None):
    """Arma el agente (orquestador LangGraph) con sus herramientas y su memoria de corto plazo.

    memoria_persistente=True guarda las conversaciones en SQLite o PostgreSQL (según el contenedor),
    para retomar un hilo aunque se cierre la app. Si no, quedan en memoria RAM (pruebas).
    """
    from agente.aplicacion.orquestador import AgenteTramites
    from agente.adaptadores.salida.memoria.conversaciones import crear_checkpointer

    if checkpointer is None:
        checkpointer = crear_checkpointer(contenedor.destino_memoria if memoria_persistente else None)
    return AgenteTramites(contenedor, llm=llm, checkpointer=checkpointer)
