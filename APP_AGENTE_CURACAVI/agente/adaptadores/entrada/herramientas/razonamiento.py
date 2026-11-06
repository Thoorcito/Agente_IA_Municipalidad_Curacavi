"""Herramientas de RAZONAMIENTO: calculan o comparan, sin escribir en el sistema.

- fecha_actual y calcular_plazo_habil: cálculo exacto en Python (el LLM no cuenta días).
- verificar_requisitos: compara lo que el vecino dice tener con la lista de requisitos y separa
  el requisito legal del antecedente que pide la municipalidad.
- contrastar_fuentes: compara lo que dicen la ley, la municipalidad y ChileAtiende sobre un tema
  y explica cuál prevalece.

La lógica vive en el dominio (agente/dominio/); la herramienta solo la conecta con los puertos.
"""
from typing import TYPE_CHECKING

from langchain_core.tools import tool

from agente.dominio import citas as cat
from agente.dominio import requisitos as req
from agente.dominio.plazos import DIAS_SEMANA, parsear_fecha, sumar_dias_habiles

if TYPE_CHECKING:
    from agente.configuracion.contenedor import Contenedor


def crear_herramientas_razonamiento(ctx: "Contenedor") -> list:
    """Crea las 4 herramientas de razonamiento conectadas a los puertos del contenedor."""

    @tool
    def fecha_actual() -> dict:
        """Entrega la fecha de hoy del sistema municipal. Úsala antes de calcular plazos relativos a "hoy"."""
        hoy = ctx.fecha()
        return {"fecha": hoy.isoformat(), "dia_semana": DIAS_SEMANA[hoy.weekday()]}

    @tool
    def calcular_plazo_habil(fecha_inicio: str, dias_habiles: int) -> dict:
        """Calcula la fecha de vencimiento de un plazo en días hábiles (sin sábados, domingos ni feriados
        de Chile), contando desde el día siguiente a fecha_inicio. fecha_inicio: AAAA-MM-DD o DD/MM/AAAA."""
        try:
            inicio = parsear_fecha(fecha_inicio)
        except ValueError as e:
            return {"error": str(e)}
        vencimiento, omitidos = sumar_dias_habiles(inicio, int(dias_habiles))
        return {"fecha_inicio": inicio.isoformat(), "dias_habiles": int(dias_habiles),
                "vencimiento": vencimiento.isoformat(), "dia_semana": DIAS_SEMANA[vencimiento.weekday()],
                "feriados_omitidos": omitidos, "fundamento": cat.formatear_cita("ley_19880", "25")}

    @tool
    def verificar_requisitos(tramite_id: str, documentos_declarados: list[str]) -> dict:
        """Compara los documentos que el vecino declara tener con los requisitos del trámite.
        tramite_id: permiso_circulacion, primera_licencia_b, renovacion_licencia, patente_comercial o reclamo.
        documentos_declarados: ids de requisito o frases ("tengo el SOAP y la revisión técnica").
        Devuelve presentados, faltantes (con su fundamento legal, municipal u orientativo) y etapas."""
        return req.verificar(ctx.requisitos, tramite_id, documentos_declarados)

    @tool
    def contrastar_fuentes(tema: str, tramite_id: str = "") -> dict:
        """Compara lo que dicen sobre un mismo tema la ley (normativa nacional), la municipalidad
        (información municipal) y ChileAtiende (orientación). Detecta diferencias en fechas y plazos y
        explica cuál fuente prevalece. Úsala cuando la pregunta sea sobre plazos, fechas o requisitos."""
        resultados = {c: ctx.indice.buscar(c, tema, k=4, tramite=tramite_id or None)
                      for c in ("leyes", "municipal", "chileatiende")}
        unidad = ctx.requisitos.get(tramite_id, {}).get("unidad", "la unidad municipal responsable")
        return cat.contrastar(resultados, tema, unidad)

    return [fecha_actual, calcular_plazo_habil, verificar_requisitos, contrastar_fuentes]
