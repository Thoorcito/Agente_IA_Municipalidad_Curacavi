"""Herramientas de CONSULTA: leen información, nunca modifican el sistema.

En la arquitectura hexagonal, cada herramienta (@tool de LangChain) es un ADAPTADOR DE ENTRADA:
es la puerta por la que el agente (o un LLM con tool calling) usa el sistema. Las herramientas no
crean sus dependencias: las reciben del contenedor (inyección por constructor), igual que un
@RestController de Spring recibe sus servicios.

Las tres búsquedas documentales están separadas por tipo de fuente para que el agente (y el
vecino) sepan siempre si la información viene de la ley, de la municipalidad o de ChileAtiende.
"""
from typing import TYPE_CHECKING

from langchain_core.tools import tool

from agente.dominio import citas as cat
from agente.dominio.modelo import Cupo, Solicitud, normalizar_folio
from agente.dominio.plazos import dias_habiles_entre, parsear_fecha

if TYPE_CHECKING:
    from agente.configuracion.contenedor import Contenedor


def crear_herramientas_consulta(ctx: "Contenedor") -> list:
    """Crea las 7 herramientas de consulta conectadas a los puertos del contenedor."""

    def _buscar(coleccion: str, consulta: str, tramite: str) -> dict:
        """Búsqueda común: devuelve fragmentos con su cita canónica, o SIN_RESULTADOS."""
        resultados = ctx.indice.buscar(coleccion, consulta, tramite=tramite or None)
        if not resultados:
            return {"sin_resultados": True, "mensaje": f"SIN_RESULTADOS en {coleccion}: no hay información relevante."}
        for r in resultados:
            r["cita"] = cat.formatear_cita(r["fuente_id"], r.get("articulo"), r.get("pagina"))
            r["nivel_normativo"] = cat.TITULOS_SECCION[cat.fuente(r["fuente_id"])["nivel"]]
        return {"sin_resultados": False, "resultados": resultados}

    @tool
    def buscar_informacion_municipal(consulta: str, tramite: str = "") -> dict:
        """Busca en la INFORMACIÓN MUNICIPAL de Curacaví: guías de trámites (requisitos, costos, horarios,
        lugar), página de patentes y el procedimiento interno de atención (documento simulado).
        Es información que aplica la norma; no es una ley."""
        return _buscar("municipal", consulta, tramite)

    @tool
    def buscar_normativa_nacional(consulta: str, tramite: str = "") -> dict:
        """Busca en las LEYES nacionales (textos refundidos, por artículo): Ley 19.880 (procedimiento
        administrativo y plazos), Ley 18.695 (municipalidades), D.L. 3.063 (rentas municipales: permiso de
        circulación, patentes, derechos) y Ley 18.290 (tránsito y licencias)."""
        return _buscar("leyes", consulta, tramite)

    @tool
    def buscar_orientacion_chileatiende(consulta: str, tramite: str = "") -> dict:
        """Busca en las fichas de CHILEATIENDE (orientación general nacional, no normativa) sobre permiso
        de circulación y licencias de conducir."""
        return _buscar("chileatiende", consulta, tramite)

    @tool
    def buscar_casos_similares(descripcion: str) -> dict:
        """Busca casos ya resueltos parecidos al actual (memoria episódica del agente)."""
        resultados = ctx.indice.buscar("casos_resueltos", descripcion, k=3)
        return {"casos": [{"texto": r["texto"], "similitud": r["similitud"]} for r in resultados]}

    @tool
    def consultar_estado_solicitud(folio: str) -> dict:
        """Consulta el estado de una solicitud por su folio (formato SOL-AAAA-NNNN). Entrega solo datos
        públicos del trámite: nunca RUT, teléfono, domicilio ni datos de la persona."""
        folio_n = normalizar_folio(folio)
        if not folio_n:
            return {"encontrado": False, "mensaje": "Folio con formato inválido. Use SOL-AAAA-NNNN."}
        fila = ctx.registro.obtener_solicitud(folio_n)
        if not fila:
            return {"encontrado": False, "folio": folio_n, "mensaje": f"No existe la solicitud {folio_n}."}
        sol, hoy = Solicitud.desde_registro(fila), ctx.fecha()
        return {"encontrado": True, "folio": sol.folio, "tramite": sol.tramite, "tramite_id": sol.tramite_id,
                "fecha_ingreso": sol.fecha_ingreso, "estado": sol.estado.value, "abierta": sol.abierta,
                "unidad": sol.unidad_responsable, "observacion": sol.observacion,
                "ultima_actualizacion": sol.fecha_actualizacion,
                "dias_habiles_desde_ingreso": dias_habiles_entre(parsear_fecha(sol.fecha_ingreso), hoy),
                "dias_habiles_desde_actualizacion": dias_habiles_entre(parsear_fecha(sol.fecha_actualizacion), hoy)}

    @tool
    def consultar_historial_vecino(vecino_id: str) -> dict:
        """Devuelve el historial del vecino (seudónimo V-NNN): solicitudes anteriores con su estado y las
        decisiones que el agente tomó antes. Permite reconocer rechazos u observaciones previas."""
        solicitudes = [{k: x[k] for k in ("folio", "tramite", "tramite_id", "fecha_ingreso", "estado", "observacion")}
                       for x in ctx.registro.solicitudes_de_vecino(vecino_id)]
        decisiones = ctx.registro.decisiones(vecino_id)
        return {"vecino_id": vecino_id, "solicitudes": solicitudes, "n_decisiones_previas": len(decisiones),
                "ultima_decision": decisiones[-1] if decisiones else None}

    @tool
    def consultar_agenda(tramite_id: str) -> dict:
        """Consulta las próximas horas disponibles para trámites que requieren hora (licencias de conducir)."""
        tramite = ctx.requisitos.get(tramite_id, {})
        if not tramite.get("requiere_hora"):
            return {"requiere_hora": False, "cupos": []}
        filas = [] if ctx.condiciones.get("agenda_sin_cupos") else ctx.registro.cupos_disponibles("licencias", limite=3)
        cupos = [Cupo.desde_registro(f) for f in filas]
        return {"requiere_hora": True, "cupos": [{"cupo_id": c.cupo_id, "fecha": c.fecha, "hora": c.hora} for c in cupos],
                "regla_atencion": "Martes a viernes y segundo sábado de cada mes, 08:30 a 13:30; reservar con 20 días de anticipación",
                "fuente": cat.formatear_cita("guia_licencias")}

    return [buscar_informacion_municipal, buscar_normativa_nacional, buscar_orientacion_chileatiende,
            buscar_casos_similares, consultar_estado_solicitud, consultar_historial_vecino, consultar_agenda]
