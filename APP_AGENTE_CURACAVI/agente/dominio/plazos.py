"""Plazos en días hábiles (dominio).

Ley N° 19.880, art. 25: los plazos de días son hábiles (se excluyen sábados, domingos y festivos)
y se cuentan desde el día siguiente. El cálculo se hace en Python: el LLM nunca cuenta días.
"""
from datetime import date, datetime, timedelta

import holidays

DIAS_SEMANA = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def parsear_fecha(texto: str) -> date:
    """Acepta AAAA-MM-DD o DD/MM/AAAA (o DD-MM-AAAA)."""
    texto = texto.strip()
    for formato in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            continue
    raise ValueError(f"Fecha no reconocida: {texto!r}. Use AAAA-MM-DD o DD/MM/AAAA.")


def _feriados(anios: set[int]):
    return holidays.country_holidays("CL", years=sorted(anios))


def sumar_dias_habiles(inicio: date, dias: int) -> tuple[date, list[str]]:
    """Cuenta desde el día siguiente saltando fines de semana y feriados.

    Devuelve (fecha de vencimiento, feriados omitidos en el camino).
    """
    feriados = _feriados({inicio.year, inicio.year + 1})
    actual, contados, omitidos = inicio, 0, []
    while contados < dias:
        actual += timedelta(days=1)
        if actual.weekday() >= 5:
            continue
        if actual in feriados:
            omitidos.append(f"{actual.isoformat()} ({feriados.get(actual)})")
            continue
        contados += 1
    return actual, omitidos


def dias_habiles_entre(desde: date, hasta: date) -> int:
    """Días hábiles transcurridos después de 'desde' y hasta 'hasta' (inclusive)."""
    if hasta <= desde:
        return 0
    feriados = _feriados({desde.year, hasta.year})
    n, actual = 0, desde
    while actual < hasta:
        actual += timedelta(days=1)
        if actual.weekday() < 5 and actual not in feriados:
            n += 1
    return n


def sumar_meses(base: date, meses: int) -> date:
    """Suma meses calendario (día acotado a 28 para que siempre exista en el mes de destino)."""
    return date(base.year + (base.month + meses - 1) // 12, (base.month + meses - 1) % 12 + 1, min(base.day, 28))
