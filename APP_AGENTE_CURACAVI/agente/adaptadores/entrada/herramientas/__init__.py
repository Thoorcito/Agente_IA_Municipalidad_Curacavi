"""Catálogo de herramientas del agente, agrupadas por tipo (consulta, escritura y razonamiento).

Las herramientas se crean con crear_herramientas(contenedor): cada una queda conectada a los
puertos (registro, índice, requisitos, reloj) de ESE contenedor. Así el mismo código funciona con
SQLite + Chroma (local) o con PostgreSQL + pgvector (Docker), y en las pruebas con dobles de prueba.
"""
from typing import TYPE_CHECKING

from agente.adaptadores.entrada.herramientas.consulta import crear_herramientas_consulta
from agente.adaptadores.entrada.herramientas.escritura import crear_herramientas_escritura
from agente.adaptadores.entrada.herramientas.razonamiento import crear_herramientas_razonamiento

if TYPE_CHECKING:
    from agente.configuracion.contenedor import Contenedor

# Nombres por tipo (documentación, pruebas y clasificación de cada llamada en la traza).
NOMBRES_POR_TIPO = {
    "consulta": ["buscar_informacion_municipal", "buscar_normativa_nacional", "buscar_orientacion_chileatiende",
                 "buscar_casos_similares", "consultar_estado_solicitud", "consultar_historial_vecino", "consultar_agenda"],
    "escritura": ["registrar_solicitud", "actualizar_solicitud", "agendar_hora", "derivar_o_escalar",
                  "inscribir_lista_espera", "notificar_vecino"],
    "razonamiento": ["fecha_actual", "calcular_plazo_habil", "verificar_requisitos", "contrastar_fuentes"],
}
TIPO_DE = {nombre: tipo for tipo, nombres in NOMBRES_POR_TIPO.items() for nombre in nombres}


def crear_herramientas(ctx: "Contenedor") -> dict[str, list]:
    """Devuelve {"consulta": [...], "escritura": [...], "razonamiento": [...]} listas para usar."""
    return {"consulta": crear_herramientas_consulta(ctx), "escritura": crear_herramientas_escritura(ctx),
            "razonamiento": crear_herramientas_razonamiento(ctx)}


def todas(por_tipo: dict[str, list]) -> list:
    return [h for lista in por_tipo.values() for h in lista]
