"""Memoria de largo plazo: el "sistema municipal" (solicitudes, bitácora, agenda, notificaciones,
escalamientos, lista de espera y decisiones del agente).

RegistroSQL contiene toda la lógica SQL, escrita una sola vez y común a los dos adaptadores:
- RegistroSQLite (adaptadores/salida/local/registro_sqlite.py): Colab, pruebas y modo sin Docker.
- RegistroPostgres (adaptadores/salida/postgres/registro.py): Docker.

Ambos implementan el puerto RegistroMunicipal (agente/aplicacion/puertos.py). Las fechas se guardan como texto
ISO (AAAA-MM-DD) en las dos bases, para que ambos adaptadores devuelvan exactamente lo mismo.

Privacidad por diseño: no existen columnas de RUT, teléfono ni domicilio.
"""
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

from agente.dominio.modelo import siguiente_folio
from agente.adaptadores.salida.memoria import datos_demo

TABLAS = ["decisiones", "lista_espera", "escalamientos", "notificaciones", "agenda", "bitacora", "solicitudes", "vecinos"]


def esquema(id_autoincremental: str) -> str:
    """DDL común. id_autoincremental cambia según el motor (SQLite / PostgreSQL)."""
    return f"""
CREATE TABLE IF NOT EXISTS vecinos (
    vecino_id TEXT PRIMARY KEY, alias TEXT, canal_preferido TEXT);
CREATE TABLE IF NOT EXISTS solicitudes (
    folio TEXT PRIMARY KEY, vecino_id TEXT, tramite TEXT, tramite_id TEXT, fecha_ingreso TEXT,
    estado TEXT, unidad_responsable TEXT, observacion TEXT, fecha_actualizacion TEXT);
CREATE TABLE IF NOT EXISTS bitacora (
    id {id_autoincremental}, folio TEXT, fecha TEXT, evento TEXT, detalle TEXT, fundamento TEXT);
CREATE TABLE IF NOT EXISTS agenda (
    id {id_autoincremental}, fecha TEXT, hora TEXT, unidad TEXT, tramite_tipo TEXT, estado TEXT, folio TEXT);
CREATE TABLE IF NOT EXISTS notificaciones (
    id {id_autoincremental}, vecino_id TEXT, folio TEXT, fecha TEXT, canal TEXT, mensaje TEXT);
CREATE TABLE IF NOT EXISTS escalamientos (
    id {id_autoincremental}, folio TEXT, fecha TEXT, destino TEXT, motivo TEXT, fundamento TEXT, estado TEXT);
CREATE TABLE IF NOT EXISTS lista_espera (
    id {id_autoincremental}, vecino_id TEXT, tramite_id TEXT, folio TEXT, fecha TEXT);
CREATE TABLE IF NOT EXISTS decisiones (
    id {id_autoincremental}, thread_id TEXT, vecino_id TEXT, fecha TEXT, regla TEXT, accion TEXT, motivo TEXT,
    tramite_id TEXT, folio TEXT);
CREATE INDEX IF NOT EXISTS idx_solicitudes_vecino ON solicitudes (vecino_id);
CREATE INDEX IF NOT EXISTS idx_agenda_disponible ON agenda (tramite_tipo, estado, fecha, hora);
CREATE INDEX IF NOT EXISTS idx_bitacora_folio ON bitacora (folio);
"""


class RegistroSQL:
    """Operaciones del registro municipal en SQL estándar.

    Las subclases solo definen cómo conectarse (_conectar), cómo se escriben los parámetros
    (MARCADOR) y cómo se recrea el esquema (_recrear_esquema). Todo lo demás es común.
    """

    MARCADOR = "?"

    @contextmanager
    def _conectar(self):  # pragma: no cover - lo implementa cada adaptador
        raise NotImplementedError
        yield

    def _recrear_esquema(self, conn) -> None:  # pragma: no cover - lo implementa cada adaptador
        raise NotImplementedError

    def _sql(self, sql: str) -> str:
        return sql if self.MARCADOR == "?" else sql.replace("?", self.MARCADOR)

    def _filas(self, sql: str, params: tuple = ()) -> list[dict]:
        with self._conectar() as conn:
            return [dict(r) for r in conn.execute(self._sql(sql), params).fetchall()]

    def _ejecutar(self, sql: str, params: tuple = ()) -> int:
        """Ejecuta un INSERT ... RETURNING id (o un UPDATE) y devuelve el id o la cantidad de filas."""
        with self._conectar() as conn:
            cur = conn.execute(self._sql(sql), params)
            if "RETURNING" in sql:
                return dict(cur.fetchone())["id"]
            return cur.rowcount

    # --- inicialización -----------------------------------------------------------------------
    def inicializar(self, fecha_ref: date, semilla: int = 42) -> dict:
        """Crea (o recrea) la base desde los CSV y genera la agenda de horas desde fecha_ref."""
        vecinos, solicitudes = datos_demo.leer_vecinos(), datos_demo.leer_solicitudes()
        cupos = datos_demo.generar_cupos(fecha_ref, semilla)
        with self._conectar() as conn:
            self._recrear_esquema(conn)
            cur = conn.cursor()
            cur.executemany(self._sql("INSERT INTO vecinos VALUES (?,?,?)"), vecinos)
            cur.executemany(self._sql("INSERT INTO solicitudes VALUES (?,?,?,?,?,?,?,?,?)"), solicitudes)
            cur.executemany(self._sql("INSERT INTO agenda (fecha, hora, unidad, tramite_tipo, estado) VALUES (?,?,?,?,?)"), cupos)
        return {"solicitudes": len(solicitudes), "cupos": len(cupos)}

    # --- solicitudes ---------------------------------------------------------------------------
    def obtener_solicitud(self, folio: str) -> dict | None:
        filas = self._filas("SELECT * FROM solicitudes WHERE folio = ?", (folio,))
        return filas[0] if filas else None

    def solicitudes_de_vecino(self, vecino_id: str) -> list[dict]:
        return self._filas("SELECT * FROM solicitudes WHERE vecino_id = ? ORDER BY fecha_ingreso DESC, folio DESC", (vecino_id,))

    def todas_las_solicitudes(self) -> list[dict]:
        return self._filas("SELECT * FROM solicitudes ORDER BY folio")

    def registrar_solicitud(self, vecino_id: str, tramite_id: str, tramite: str, unidad: str,
                            estado: str, observacion: str, fecha: date) -> str:
        existentes = [f["folio"] for f in self._filas("SELECT folio FROM solicitudes WHERE folio LIKE ?", (f"SOL-{fecha.year}-%",))]
        folio = siguiente_folio(fecha.year, existentes)
        self._ejecutar("INSERT INTO solicitudes VALUES (?,?,?,?,?,?,?,?,?)",
                       (folio, vecino_id, tramite, tramite_id, fecha.isoformat(), estado, unidad, observacion, fecha.isoformat()))
        self.registrar_bitacora(folio, "registro", f"Solicitud ingresada en estado {estado}", "", fecha)
        return folio

    def actualizar_estado(self, folio: str, estado: str, observacion: str, fundamento: str, fecha: date) -> bool:
        if not self.obtener_solicitud(folio):
            return False
        self._ejecutar("UPDATE solicitudes SET estado = ?, observacion = ?, fecha_actualizacion = ? WHERE folio = ?",
                       (estado, observacion, fecha.isoformat(), folio))
        self.registrar_bitacora(folio, "cambio_estado", f"{estado}: {observacion}", fundamento, fecha)
        return True

    def registrar_bitacora(self, folio: str, evento: str, detalle: str, fundamento: str, fecha: date) -> None:
        self._ejecutar("INSERT INTO bitacora (folio, fecha, evento, detalle, fundamento) VALUES (?,?,?,?,?) RETURNING id",
                       (folio, datetime.combine(fecha, datetime.now().time()).isoformat(timespec="seconds"),
                        evento, detalle, fundamento))

    def bitacora(self, folio: str) -> list[dict]:
        return self._filas("SELECT * FROM bitacora WHERE folio = ? ORDER BY id", (folio,))

    # --- agenda --------------------------------------------------------------------------------
    def cupos_disponibles(self, tramite_tipo: str = "licencias", limite: int = 3) -> list[dict]:
        return self._filas("SELECT * FROM agenda WHERE tramite_tipo = ? AND estado = 'disponible' "
                           "ORDER BY fecha, hora LIMIT ?", (tramite_tipo, limite))

    def reservar_cupo(self, cupo_id: int, folio: str) -> bool:
        """Reserva atómica: el UPDATE solo afecta la fila si sigue disponible. Si dos atenciones
        intentan la misma hora a la vez, solo una obtiene rowcount = 1 (la otra debe replanificar)."""
        return self._ejecutar("UPDATE agenda SET estado = 'reservada', folio = ? WHERE id = ? AND estado = 'disponible'",
                              (folio, cupo_id)) == 1

    def ocupar_cupo(self, cupo_id: int) -> None:
        """Simula que otra persona reservó el cupo (condición cambiante para la demo)."""
        self._ejecutar("UPDATE agenda SET estado = 'reservada', folio = 'OTRO-VECINO' WHERE id = ?", (cupo_id,))

    def reserva_de_folio(self, folio: str) -> dict | None:
        filas = self._filas("SELECT * FROM agenda WHERE folio = ?", (folio,))
        return filas[0] if filas else None

    def agregar_lista_espera(self, vecino_id: str, tramite_id: str, folio: str, fecha: date) -> int:
        return self._ejecutar("INSERT INTO lista_espera (vecino_id, tramite_id, folio, fecha) VALUES (?,?,?,?) RETURNING id",
                              (vecino_id, tramite_id, folio, fecha.isoformat()))

    def lista_espera(self) -> list[dict]:
        return self._filas("SELECT * FROM lista_espera ORDER BY id")

    # --- comunicaciones y escalamientos -------------------------------------------------------
    def registrar_notificacion(self, vecino_id: str, folio: str, mensaje: str, fecha: date) -> int:
        canal = (self._filas("SELECT canal_preferido FROM vecinos WHERE vecino_id = ?", (vecino_id,))
                 or [{"canal_preferido": "correo"}])[0]["canal_preferido"]
        return self._ejecutar("INSERT INTO notificaciones (vecino_id, folio, fecha, canal, mensaje) VALUES (?,?,?,?,?) RETURNING id",
                              (vecino_id, folio, fecha.isoformat(), canal, mensaje))

    def notificaciones(self, vecino_id: str) -> list[dict]:
        return self._filas("SELECT * FROM notificaciones WHERE vecino_id = ? ORDER BY id", (vecino_id,))

    def registrar_escalamiento(self, folio: str, destino: str, motivo: str, fundamento: str, fecha: date) -> int:
        id_ = self._ejecutar("INSERT INTO escalamientos (folio, fecha, destino, motivo, fundamento, estado) "
                             "VALUES (?,?,?,?,?,?) RETURNING id", (folio, fecha.isoformat(), destino, motivo, fundamento, "abierto"))
        self.registrar_bitacora(folio, "escalamiento", f"Escalado a {destino}: {motivo}", fundamento, fecha)
        return id_

    def escalamientos(self, folio: str | None = None) -> list[dict]:
        if folio:
            return self._filas("SELECT * FROM escalamientos WHERE folio = ? ORDER BY id", (folio,))
        return self._filas("SELECT * FROM escalamientos ORDER BY id")

    # --- decisiones del agente (trazabilidad de largo plazo) -----------------------------------
    def registrar_decision(self, thread_id: str, vecino_id: str, regla: str, accion: str, motivo: str,
                           tramite_id: str | None, folio: str | None) -> int:
        return self._ejecutar("INSERT INTO decisiones (thread_id, vecino_id, fecha, regla, accion, motivo, tramite_id, folio)"
                              " VALUES (?,?,?,?,?,?,?,?) RETURNING id",
                              (thread_id, vecino_id, datetime.now().isoformat(timespec="seconds"), regla, accion, motivo,
                               tramite_id, folio))

    def decisiones(self, vecino_id: str | None = None) -> list[dict]:
        if vecino_id:
            return self._filas("SELECT * FROM decisiones WHERE vecino_id = ? ORDER BY id", (vecino_id,))
        return self._filas("SELECT * FROM decisiones ORDER BY id")
