"""Controlador de atención: punto de entrada de la interfaz (ADAPTADOR DE ENTRADA).

La vista (app.py, Streamlit) solo llama a estos métodos: no conoce el grafo, la base de datos ni
los índices. Si mañana la interfaz fuera una API REST o un bot de WhatsApp, se escribiría otro
adaptador de entrada que use este mismo controlador.

Equivalente en Spring: un @RestController delgado que delega en el servicio de aplicación.
"""
from agente.configuracion.contenedor import Contenedor
from agente.dominio.planner import TABLA_REGLAS
from agente.configuracion import settings


class ControladorAtencion:
    def __init__(self, contenedor: Contenedor, agente):
        self.contenedor = contenedor
        self.agente = agente

    # --- conversación ---------------------------------------------------------------------------
    def enviar_mensaje(self, texto: str, hilo: str, vecino_id: str) -> dict:
        """Procesa un mensaje del vecino y devuelve el resultado del turno (decisión, plan, traza...)."""
        return self.agente.conversar(texto, hilo, vecino_id)

    def resolver_aprobacion(self, hilo: str, aprobado: bool) -> dict:
        """Reanuda un hilo pausado con la decisión del funcionario (humano en el ciclo)."""
        return self.agente.resolver_aprobacion(hilo, aprobado)

    def conversacion(self, hilo: str) -> dict:
        """Estado guardado del hilo: mensajes, resumen y memoria de trabajo (corto plazo)."""
        return self.agente.estado(hilo)

    # --- consultas para el panel ------------------------------------------------------------------
    def solicitudes_del_vecino(self, vecino_id: str) -> list[dict]:
        return [{k: s[k] for k in ("folio", "tramite", "estado", "fecha_ingreso")}
                for s in self.contenedor.registro.solicitudes_de_vecino(vecino_id)]

    def notificaciones(self, vecino_id: str, ultimas: int = 3) -> list[dict]:
        return self.contenedor.registro.notificaciones(vecino_id)[-ultimas:]

    @staticmethod
    def reglas() -> list[tuple]:
        return TABLA_REGLAS

    def info_sistema(self) -> dict:
        return {"modelo": f"OpenRouter · {settings.LLM_MODEL}" if self.agente.llm else "sin LLM (respuestas con plantillas)",
                "persistencia": self.contenedor.descripcion(), "fecha": self.contenedor.fecha().isoformat()}

    # --- condiciones de la demo -------------------------------------------------------------------
    def fijar_condiciones(self, agenda_sin_cupos: bool, cupo_tomado_por_otro: bool) -> None:
        """Interruptores de la demo: agenda vacía y "otra persona toma la hora al agendar"."""
        c = self.contenedor.condiciones
        c["agenda_sin_cupos"] = agenda_sin_cupos
        if cupo_tomado_por_otro:
            c.setdefault("cupo_tomado_por_otro", True)
        else:
            c.pop("cupo_tomado_por_otro", None)

    def reiniciar_demo(self) -> None:
        """Deja el registro municipal en su estado inicial (las conversaciones guardadas no se borran)."""
        self.contenedor.registro.inicializar(self.contenedor.fecha())
