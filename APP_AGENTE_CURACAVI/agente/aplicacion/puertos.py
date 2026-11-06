"""PUERTOS de la arquitectura hexagonal: lo que el agente necesita del mundo exterior.

Un puerto es una interfaz (aquí, typing.Protocol). El núcleo (dominio + orquestador + herramientas)
solo conoce estos contratos; no sabe si detrás hay SQLite, PostgreSQL, Chroma o pgvector.
Cada adaptador de agente/adaptadores/salida/ implementa los puertos con una tecnología concreta.

Equivalente en Spring: las interfaces `...Repository` y `...Port` que el @Service recibe por
constructor, cuya implementación elige la configuración (@Configuration / perfiles).

| Puerto                  | Adaptador local (Colab y pruebas) | Adaptador Docker              |
|-------------------------|-----------------------------------|-------------------------------|
| RegistroMunicipal       | RegistroSQLite                    | RegistroPostgres              |
| BuscadorFuentes         | IndiceChroma (Chroma + BM25)      | IndicePgvector (pgvector + texto completo) |
| Memoria de conversación | SqliteSaver de LangGraph          | PostgresSaver de LangGraph    |
| ModeloLenguaje          | ChatOpenAI (OpenRouter) o None    | ChatOpenAI (OpenRouter) o None |
| Reloj                   | fecha del sistema o fija          | fecha del sistema o fija      |
"""
from datetime import date
from typing import Any, Callable, Protocol, runtime_checkable

# El reloj es una función sin argumentos que devuelve "hoy". Inyectarlo permite fijar la fecha en
# demos y pruebas, sin tocar el código que calcula plazos.
Reloj = Callable[[], date]


@runtime_checkable
class RepositorioSolicitudes(Protocol):
    """Solicitudes (folios) y su bitácora."""

    def existe(self) -> bool: ...
    def inicializar(self, fecha_ref: date) -> dict: ...
    def obtener_solicitud(self, folio: str) -> dict | None: ...
    def solicitudes_de_vecino(self, vecino_id: str) -> list[dict]: ...
    def todas_las_solicitudes(self) -> list[dict]: ...
    def registrar_solicitud(self, vecino_id: str, tramite_id: str, tramite: str, unidad: str,
                            estado: str, observacion: str, fecha: date) -> str: ...
    def actualizar_estado(self, folio: str, estado: str, observacion: str, fundamento: str, fecha: date) -> bool: ...
    def registrar_bitacora(self, folio: str, evento: str, detalle: str, fundamento: str, fecha: date) -> None: ...
    def bitacora(self, folio: str) -> list[dict]: ...


@runtime_checkable
class AgendaAtencion(Protocol):
    """Horas de atención y lista de espera."""

    def cupos_disponibles(self, tramite_tipo: str = "licencias", limite: int = 3) -> list[dict]: ...
    def reservar_cupo(self, cupo_id: int, folio: str) -> bool: ...
    def ocupar_cupo(self, cupo_id: int) -> None: ...
    def reserva_de_folio(self, folio: str) -> dict | None: ...
    def agregar_lista_espera(self, vecino_id: str, tramite_id: str, folio: str, fecha: date) -> int: ...
    def lista_espera(self) -> list[dict]: ...


@runtime_checkable
class Comunicaciones(Protocol):
    """Notificaciones al vecino y escalamientos a funcionarios."""

    def registrar_notificacion(self, vecino_id: str, folio: str, mensaje: str, fecha: date) -> int: ...
    def notificaciones(self, vecino_id: str) -> list[dict]: ...
    def registrar_escalamiento(self, folio: str, destino: str, motivo: str, fundamento: str, fecha: date) -> int: ...
    def escalamientos(self, folio: str | None = None) -> list[dict]: ...


@runtime_checkable
class BitacoraDecisiones(Protocol):
    """Registro de cada decisión del agente (trazabilidad de largo plazo)."""

    def registrar_decision(self, thread_id: str, vecino_id: str, regla: str, accion: str, motivo: str,
                           tramite_id: str | None, folio: str | None) -> int: ...
    def decisiones(self, vecino_id: str | None = None) -> list[dict]: ...


@runtime_checkable
class RegistroMunicipal(RepositorioSolicitudes, AgendaAtencion, Comunicaciones, BitacoraDecisiones, Protocol):
    """Memoria de largo plazo completa. Un adaptador puede implementar los cuatro puertos a la vez
    (una sola base de datos), pero cada herramienta depende solo del que usa."""


@runtime_checkable
class BuscadorFuentes(Protocol):
    """Memoria semántica: índices de documentos por colección y búsqueda híbrida con umbral."""

    def construir(self, colecciones: dict[str, list]) -> dict[str, int]: ...
    def agregar(self, coleccion: str, texto: str, metadata: dict) -> str: ...
    def corpus(self, coleccion: str) -> list[dict]: ...
    def conteo(self) -> dict[str, int]: ...
    def buscar(self, coleccion: str, consulta: str, k: int = 4, tramite: str | None = None,
               hibrida: bool = True, umbral: float | None = None, boost: bool = True) -> list[dict]: ...


@runtime_checkable
class ModeloLenguaje(Protocol):
    """Lo que el agente usa de un LLM. Cualquier chat model de LangChain cumple este contrato."""

    def invoke(self, entrada: Any, *args, **kwargs) -> Any: ...
    def with_structured_output(self, esquema: Any, **kwargs) -> Any: ...
