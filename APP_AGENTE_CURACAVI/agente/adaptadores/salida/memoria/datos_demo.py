"""Datos iniciales de la demo, comunes a SQLite y PostgreSQL.

- vecinos.csv y solicitudes.csv: datos simulados, sin datos personales (seudónimos V-NNN).
- Agenda de licencias: desde hoy + 20 días (anticipación exigida por la guía municipal) durante
  30 días, en los días de atención. Un 70 % de las horas ya está reservado (semilla fija), para que
  la agenda se parezca a la real y las pruebas sean reproducibles.
"""
import csv
import random
from datetime import date, timedelta
from pathlib import Path

from agente.dominio.modelo import TRAMITE_ID, dia_de_atencion_licencias
from agente.configuracion import settings

UNIDAD_TRANSITO = "Dirección de Tránsito y Transporte Público"
HORAS_ATENCION = ["08:30", "09:00", "09:30", "10:00", "10:30", "11:00", "11:30", "12:00", "12:30", "13:00"]


def leer_vecinos(ruta: Path = settings.VECINOS_CSV) -> list[tuple]:
    with open(ruta, encoding="utf-8") as fh:
        return [(v["vecino_id"], v["alias"], v["canal_preferido"]) for v in csv.DictReader(fh)]


def leer_solicitudes(ruta: Path = settings.SOLICITUDES_CSV) -> list[tuple]:
    """Filas en el orden de la tabla solicitudes (la fecha de actualización parte igual a la de ingreso)."""
    with open(ruta, encoding="utf-8") as fh:
        return [(s["folio"], s["vecino_id"], s["tramite"], TRAMITE_ID.get(s["tramite"], "otro"), s["fecha_ingreso"],
                 s["estado"], s["unidad_responsable"], s["observacion"], s["fecha_ingreso"]) for s in csv.DictReader(fh)]


def generar_cupos(fecha_ref: date, semilla: int = 42) -> list[tuple]:
    """Cupos (fecha, hora, unidad, tipo de trámite, estado) de la agenda de licencias."""
    azar = random.Random(semilla)
    inicio = fecha_ref + timedelta(days=settings.DIAS_ANTICIPACION_HORA)
    cupos = []
    for i in range(30):
        d = inicio + timedelta(days=i)
        if not dia_de_atencion_licencias(d):
            continue
        for hora in HORAS_ATENCION:
            estado = "reservada" if azar.random() < 0.7 else "disponible"
            cupos.append((d.isoformat(), hora, UNIDAD_TRANSITO, "licencias", estado))
    return cupos
