"""Utilidades para trabajar con cualquier modelo de lenguaje (no dependen del proveedor).

- texto_de: extrae el texto de una respuesta (algunos modelos devuelven una lista de bloques).
- con_reintento: reintenta ante límite por minuto (429) y avisa si la cuota diaria se agotó.
"""
import time


class CuotaAgotadaError(Exception):
    """El proveedor respondió 429 (límite de solicitudes) incluso después de reintentar."""


def texto_de(mensaje) -> str:
    """Extrae el texto de un mensaje (algunos modelos devuelven una lista de bloques)."""
    contenido = getattr(mensaje, "content", mensaje)
    if isinstance(contenido, list):
        return "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in contenido)
    return str(contenido)


def con_reintento(funcion, intentos: int = 3, espera: int = 60):
    """Reintenta ante límite por minuto (429). Si el límite es diario, avisa con CuotaAgotadaError."""
    for intento in range(intentos):
        try:
            return funcion()
        except Exception as e:  # openai.RateLimitError u otro error del proveedor
            mensaje = str(e).lower()
            if "429" not in mensaje and "rate" not in mensaje:
                raise
            if "per-day" in mensaje or "per day" in mensaje or intento == intentos - 1:
                raise CuotaAgotadaError(str(e)) from e
            time.sleep(espera)
