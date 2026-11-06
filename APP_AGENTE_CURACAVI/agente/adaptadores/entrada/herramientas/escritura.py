"""Herramientas de ESCRITURA: modifican el sistema municipal (registro de largo plazo).

Cada escritura deja rastro en la bitácora del folio con su fundamento, para que cualquier
funcionario pueda reconstruir qué hizo el agente y por qué. Las reglas sobre el estado de una
solicitud las aplica la entidad de dominio Solicitud (no la base de datos).
"""
from typing import TYPE_CHECKING

from langchain_core.tools import tool

from agente.dominio.modelo import Solicitud, TransicionInvalida

if TYPE_CHECKING:
    from agente.configuracion.contenedor import Contenedor


def crear_herramientas_escritura(ctx: "Contenedor") -> list:
    """Crea las 6 herramientas de escritura conectadas a los puertos del contenedor."""

    @tool
    def registrar_solicitud(vecino_id: str, tramite_id: str, estado: str = "Ingresada", observacion: str = "") -> dict:
        """Ingresa una nueva solicitud y devuelve su folio (SOL-AAAA-NNNN). estado: Ingresada u Observada."""
        tramite = ctx.requisitos.get(tramite_id)
        if not tramite:
            return {"ok": False, "error": f"Trámite desconocido: {tramite_id}"}
        folio = ctx.registro.registrar_solicitud(vecino_id, tramite_id, tramite["nombre"], tramite["unidad"], estado,
                                                 observacion or "Ingresada por el asistente digital.", ctx.fecha())
        return {"ok": True, "folio": folio, "estado": estado, "unidad": tramite["unidad"]}

    @tool
    def actualizar_solicitud(folio: str, estado: str, observacion: str, fundamento: str = "") -> dict:
        """Cambia el estado de una solicitud y lo registra en la bitácora con su fundamento.
        Una solicitud aprobada, rechazada o cerrada ya no puede cambiar de estado."""
        fila = ctx.registro.obtener_solicitud(folio)
        if not fila:
            return {"ok": False, "error": f"No existe {folio}"}
        solicitud = Solicitud.desde_registro(fila)
        try:
            solicitud.cambiar_estado(estado, observacion, ctx.fecha())   # regla de dominio
        except (TransicionInvalida, ValueError) as e:
            return {"ok": False, "error": str(e)}
        ctx.registro.actualizar_estado(folio, solicitud.estado.value, observacion, fundamento, ctx.fecha())
        return {"ok": True, "folio": folio, "estado": solicitud.estado.value}

    @tool
    def agendar_hora(folio: str, cupo_id: int) -> dict:
        """Reserva una hora de atención para el folio. Si otra persona la tomó antes, devuelve ok=False
        con motivo 'cupo_tomado' y el agente debe replanificar."""
        # Condición cambiante de la demo: otra persona reserva el cupo justo antes que el agente.
        if ctx.condiciones.pop("cupo_tomado_por_otro", False):
            ctx.registro.ocupar_cupo(cupo_id)
        if not ctx.registro.reservar_cupo(cupo_id, folio):
            return {"ok": False, "motivo": "cupo_tomado", "cupo_id": cupo_id}
        reserva = ctx.registro.reserva_de_folio(folio)
        ctx.registro.registrar_bitacora(folio, "agenda", f"Hora reservada {reserva['fecha']} {reserva['hora']}", "", ctx.fecha())
        return {"ok": True, "folio": folio, "fecha": reserva["fecha"], "hora": reserva["hora"]}

    @tool
    def derivar_o_escalar(folio: str, destino: str, motivo: str, fundamento: str) -> dict:
        """Deriva o escala un caso a una unidad o funcionario (por ejemplo, la OIRS o la jefatura de la
        unidad) dejando el motivo y su fundamento normativo."""
        ticket = ctx.registro.registrar_escalamiento(folio, destino, motivo, fundamento, ctx.fecha())
        return {"ok": True, "ticket": ticket, "folio": folio, "destino": destino}

    @tool
    def inscribir_lista_espera(vecino_id: str, tramite_id: str, folio: str) -> dict:
        """Inscribe al vecino en la lista de espera cuando no hay horas disponibles."""
        id_ = ctx.registro.agregar_lista_espera(vecino_id, tramite_id, folio, ctx.fecha())
        ctx.registro.registrar_bitacora(folio, "lista_espera", "Inscrito en lista de espera por falta de cupos", "", ctx.fecha())
        return {"ok": True, "posicion": id_, "folio": folio}

    @tool
    def notificar_vecino(vecino_id: str, folio: str, mensaje: str) -> dict:
        """Envía (simula) una notificación al vecino por su canal preferido y la deja registrada."""
        id_ = ctx.registro.registrar_notificacion(vecino_id, folio, mensaje, ctx.fecha())
        return {"ok": True, "notificacion": id_}

    return [registrar_solicitud, actualizar_solicitud, agendar_hora, derivar_o_escalar, inscribir_lista_espera,
            notificar_vecino]
