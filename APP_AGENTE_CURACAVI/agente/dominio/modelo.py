"""Modelo de dominio: entidades y objetos de valor del sistema de trámites.

- EstadoSolicitud: los estados posibles y qué transiciones están permitidas.
- Solicitud: entidad identificada por su folio. Encapsula las reglas sobre su propio estado.
- Folio: objeto de valor (formato SOL-AAAA-NNNN) con su normalización y su secuencia.
- Cupo: una hora de atención de la agenda.

Privacidad por diseño: ninguna entidad tiene RUT, teléfono ni domicilio. El vecino se identifica
con un seudónimo (V-001, V-002...).
"""
import re
from dataclasses import asdict, dataclass
from datetime import date
from enum import Enum


class EstadoSolicitud(str, Enum):
    INGRESADA = "Ingresada"
    EN_REVISION = "En revisión"
    OBSERVADA = "Observada"
    APROBADA = "Aprobada"
    RECHAZADA = "Rechazada"
    CERRADA = "Cerrada"

    @property
    def abierto(self) -> bool:
        """Una solicitud abierta todavía corre plazo (para la municipalidad o para el vecino)."""
        return self in ESTADOS_ABIERTOS

    def puede_pasar_a(self, nuevo: "EstadoSolicitud") -> bool:
        """Una solicitud cerrada (aprobada, rechazada o cerrada) ya no cambia de estado."""
        return self.abierto or nuevo == self


ESTADOS_ABIERTOS = (EstadoSolicitud.INGRESADA, EstadoSolicitud.EN_REVISION, EstadoSolicitud.OBSERVADA)
ESTADOS_RESUELTOS = (EstadoSolicitud.APROBADA, EstadoSolicitud.RECHAZADA, EstadoSolicitud.CERRADA)


class TransicionInvalida(ValueError):
    """Se intentó cambiar el estado de una solicitud que ya está resuelta."""


@dataclass
class Solicitud:
    folio: str
    vecino_id: str
    tramite: str
    tramite_id: str
    fecha_ingreso: str
    estado: EstadoSolicitud
    unidad_responsable: str
    observacion: str
    fecha_actualizacion: str

    @classmethod
    def desde_registro(cls, fila: dict) -> "Solicitud":
        """Construye la entidad desde la fila que entrega cualquier repositorio (SQLite o Postgres)."""
        return cls(**{**{k: fila[k] for k in cls.__dataclass_fields__}, "estado": EstadoSolicitud(fila["estado"])})

    @property
    def abierta(self) -> bool:
        return self.estado.abierto

    def cambiar_estado(self, nuevo: str, observacion: str, fecha: date) -> None:
        """Aplica la regla de transición; lanza TransicionInvalida si no está permitida."""
        destino = EstadoSolicitud(nuevo)
        if not self.estado.puede_pasar_a(destino):
            raise TransicionInvalida(f"La solicitud {self.folio} está «{self.estado.value}» y no puede pasar a «{destino.value}».")
        self.estado, self.observacion, self.fecha_actualizacion = destino, observacion, fecha.isoformat()

    def a_dict(self) -> dict:
        return {**asdict(self), "estado": self.estado.value}


PATRON_FOLIO = re.compile(r"SOL[\s_-]*(\d{4})[\s_-]*(\d{1,4})", re.IGNORECASE)


def normalizar_folio(texto: str) -> str | None:
    """Reconoce 'SOL-2026-0012', 'sol 2026 12' o 'folio SOL_2026_0012' -> 'SOL-2026-0012'."""
    m = PATRON_FOLIO.search(texto or "")
    return f"SOL-{m.group(1)}-{int(m.group(2)):04d}" if m else None


def siguiente_folio(anio: int, folios_existentes: list[str]) -> str:
    """Siguiente correlativo del año: SOL-2026-0030 -> SOL-2026-0031."""
    numeros = [int(f.split("-")[-1]) for f in folios_existentes if f.startswith(f"SOL-{anio}-")]
    return f"SOL-{anio}-{max(numeros, default=0) + 1:04d}"


@dataclass(frozen=True)
class Cupo:
    cupo_id: int
    fecha: str
    hora: str

    @classmethod
    def desde_registro(cls, fila: dict) -> "Cupo":
        return cls(cupo_id=fila["id"], fecha=fila["fecha"], hora=fila["hora"])


def es_segundo_sabado(d: date) -> bool:
    return d.weekday() == 5 and 8 <= d.day <= 14


def dia_de_atencion_licencias(d: date) -> bool:
    """Guía municipal de licencias: martes a viernes y los segundos sábados de cada mes."""
    return d.weekday() in (1, 2, 3, 4) or es_segundo_sabado(d)


# Nombre del trámite en el registro -> identificador interno usado por requisitos.json
TRAMITE_ID = {
    "Renovación permiso de circulación": "permiso_circulacion",
    "Primera licencia de conducir clase B": "primera_licencia_b",
    "Renovación licencia de conducir": "renovacion_licencia",
    "Patente comercial provisoria": "patente_comercial",
    "Patente comercial definitiva": "patente_comercial",
    "Reclamo por atención": "reclamo",
}
