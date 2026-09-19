"""Una sola SQLite de MANDO: historial, ledger, episodios de agentes y lecciones.

Ruta: ``MANDO_DB`` (defecto ``motor/server/data/mando.db``). ``MANDO_LEDGER_PATH`` se
acepta si ``MANDO_DB`` no está. ``MANDO_DB=off`` apaga el historial; el ledger sigue
si hay ruta propia. Un solo hilo escritor, cola acotada: si el disco falla, el reloj sigue.
"""
from __future__ import annotations

import csv
from contextlib import closing
import hashlib
import io
import json
import logging
import os
import queue
import sqlite3
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Callable

from . import privacy


DEFAULT_PATH = Path(__file__).resolve().parent / "data" / "mando.db"
SCHEMA_VERSION = 3
_STOP = object()
_SECRET_KEYS = ("token", "secret", "phone", "telefono", "teléfono", "contact", "number")
_LOG = logging.getLogger(__name__)
_STORES: dict[str, "Store"] = {}
_STORES_LOCK = threading.Lock()


def configured_path(value: str | Path | None = None) -> Path | None:
    """Ruta del historial. ``None`` si ``MANDO_DB=off``."""
    if value is not None:
        raw = str(value)
        return None if raw.strip().lower() == "off" else Path(raw).expanduser()
    db = (os.environ.get("MANDO_DB") or "").strip()
    if db.lower() == "off":
        return None
    if db:
        return Path(db).expanduser()
    led = (os.environ.get("MANDO_LEDGER_PATH") or "").strip()
    if led:
        return Path(led).expanduser()
    if "unittest" in sys.modules or "pytest" in sys.modules:
        return Path(tempfile.gettempdir()) / f"mando-ledger-test-{os.getpid()}.sqlite"
    return DEFAULT_PATH


def ledger_path(value: str | Path | None = None) -> Path:
    """Ruta del ledger (mismo fichero que el historial cuando MANDO_DB apunta a un archivo)."""
    if value is not None:
        return Path(str(value)).expanduser()
    db = (os.environ.get("MANDO_DB") or "").strip()
    if db and db.lower() != "off":
        return Path(db).expanduser()
    led = (os.environ.get("MANDO_LEDGER_PATH") or "").strip()
    if led:
        return Path(led).expanduser()
    if "unittest" in sys.modules or "pytest" in sys.modules:
        return Path(tempfile.gettempdir()) / f"mando-ledger-test-{os.getpid()}.sqlite"
    return DEFAULT_PATH


def resolve_path(value: str | Path | None = None) -> Path | None:
    """La ruta única que debe usar el proceso, o None si el historial está apagado y no hay ledger."""
    if value is not None:
        raw = str(value)
        return None if raw.strip().lower() == "off" else Path(raw).expanduser()
    db = (os.environ.get("MANDO_DB") or "").strip()
    if db.lower() == "off":
        led = (os.environ.get("MANDO_LEDGER_PATH") or "").strip()
        return Path(led).expanduser() if led else None
    if db:
        return Path(db).expanduser()
    led = (os.environ.get("MANDO_LEDGER_PATH") or "").strip()
    if led:
        return Path(led).expanduser()
    if "unittest" in sys.modules or "pytest" in sys.modules:
        return Path(tempfile.gettempdir()) / f"mando-ledger-test-{os.getpid()}.sqlite"
    return DEFAULT_PATH


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _text(value: Any) -> str | None:
    return None if value is None else str(value)


def _json(value: Any) -> str:
    return json.dumps(privacy.scrub(_scrub(value)), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), default=str)


def _scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _scrub(v) for k, v in value.items()
                if not any(secret in str(k).lower() for secret in _SECRET_KEYS)}
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    if isinstance(value, tuple):
        return [_scrub(item) for item in value]
    return value


def _items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [dict(item, id=item.get("id", key)) if isinstance(item, dict) else {"id": key, "value": item}
                for key, item in value.items()]
    return []


def _id(item: dict[str, Any], *names: str, fallback: str) -> str:
    return str(next((item[name] for name in names if item.get(name) not in (None, "")), fallback))


def _migrate(db: sqlite3.Connection) -> None:
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA journal_mode = WAL")
    version = int(db.execute("PRAGMA user_version").fetchone()[0])
    if version >= SCHEMA_VERSION:
        return
    db.executescript("""
        CREATE TABLE IF NOT EXISTS escenas (
            id TEXT PRIMARY KEY, caso TEXT, semilla INTEGER, inicio TEXT NOT NULL,
            fin TEXT, fin_min INTEGER, modo_comunicaciones TEXT
        );
        CREATE TABLE IF NOT EXISTS avisos (
            escena_id TEXT NOT NULL, id TEXT NOT NULL, minuto INTEGER, canal TEXT,
            fuente TEXT, via TEXT, texto TEXT, zona TEXT, incidente_id TEXT,
            PRIMARY KEY (escena_id, id), FOREIGN KEY (escena_id) REFERENCES escenas(id)
        );
        CREATE TABLE IF NOT EXISTS incidentes (
            escena_id TEXT NOT NULL, id TEXT NOT NULL, familia TEXT, tipo TEXT,
            etiqueta TEXT, zona TEXT, gravedad INTEGER, prioridad REAL, estado TEXT,
            apertura_min INTEGER, primera_accion_min INTEGER, cierre_min INTEGER,
            reservado INTEGER NOT NULL DEFAULT 0, json TEXT,
            PRIMARY KEY (escena_id, id), FOREIGN KEY (escena_id) REFERENCES escenas(id)
        );
        CREATE TABLE IF NOT EXISTS aviso_incidente (
            escena_id TEXT NOT NULL, aviso_id TEXT NOT NULL, incidente_id TEXT NOT NULL,
            fuente TEXT, canal TEXT,
            PRIMARY KEY (escena_id, aviso_id, incidente_id),
            FOREIGN KEY (escena_id) REFERENCES escenas(id)
        );
        CREATE TABLE IF NOT EXISTS planes (
            escena_id TEXT NOT NULL, id TEXT NOT NULL, incidente_id TEXT, version INTEGER,
            objetivo TEXT, porque TEXT, sustituye_a TEXT, estado TEXT, minuto INTEGER, json TEXT,
            PRIMARY KEY (escena_id, id), FOREIGN KEY (escena_id) REFERENCES escenas(id)
        );
        CREATE TABLE IF NOT EXISTS supuestos (
            escena_id TEXT NOT NULL, plan_id TEXT NOT NULL, id TEXT NOT NULL, texto TEXT,
            estado TEXT, rotura_min INTEGER, json TEXT,
            PRIMARY KEY (escena_id, plan_id, id), FOREIGN KEY (escena_id) REFERENCES escenas(id)
        );
        CREATE TABLE IF NOT EXISTS acciones (
            escena_id TEXT NOT NULL, id TEXT NOT NULL, incidente_id TEXT, plan_id TEXT,
            tipo TEXT, destinatario TEXT, zona TEXT, autonomia TEXT, estado TEXT,
            inicio_min INTEGER, ultimo_min INTEGER, fin_min INTEGER, porque TEXT, json TEXT,
            PRIMARY KEY (escena_id, id), FOREIGN KEY (escena_id) REFERENCES escenas(id)
        );
        CREATE TABLE IF NOT EXISTS llamadas (
            escena_id TEXT NOT NULL, id TEXT NOT NULL, accion_id TEXT, incidente_id TEXT,
            workflow TEXT, destinatario TEXT, resultado TEXT, motivo TEXT,
            latencia_ms REAL, run_id TEXT, inicio_min INTEGER, fin_min INTEGER, json TEXT,
            PRIMARY KEY (escena_id, id), FOREIGN KEY (escena_id) REFERENCES escenas(id)
        );
        CREATE TABLE IF NOT EXISTS decisiones (
            escena_id TEXT NOT NULL, id TEXT NOT NULL, accion_id TEXT, resultado TEXT,
            operador TEXT, papel TEXT, nota TEXT, minuto INTEGER, latencia_s REAL,
            futuro_aprobar_json TEXT, futuro_vetar_json TEXT, json TEXT,
            PRIMARY KEY (escena_id, id), FOREIGN KEY (escena_id) REFERENCES escenas(id)
        );
        CREATE TABLE IF NOT EXISTS previsiones (
            escena_id TEXT NOT NULL, id TEXT NOT NULL, zona TEXT, recurso TEXT, metrica TEXT,
            umbral REAL, eta_min REAL, estado TEXT, minuto INTEGER, json TEXT,
            PRIMARY KEY (escena_id, id), FOREIGN KEY (escena_id) REFERENCES escenas(id)
        );
        CREATE TABLE IF NOT EXISTS partes_personal (
            escena_id TEXT NOT NULL, id TEXT NOT NULL, unidad TEXT, incidente_id TEXT,
            estado TEXT, zona TEXT, texto TEXT, minuto INTEGER, canal TEXT, json TEXT,
            PRIMARY KEY (escena_id, id), FOREIGN KEY (escena_id) REFERENCES escenas(id)
        );
        CREATE TABLE IF NOT EXISTS operadores (
            escena_id TEXT NOT NULL, id TEXT NOT NULL, nombre TEXT, papel TEXT,
            incidente_id TEXT, ultimo_min INTEGER, json TEXT,
            PRIMARY KEY (escena_id, id), FOREIGN KEY (escena_id) REFERENCES escenas(id)
        );
        CREATE TABLE IF NOT EXISTS servicios_muestras (
            escena_id TEXT NOT NULL, servicio TEXT NOT NULL, minuto INTEGER NOT NULL,
            estado TEXT, latencia_ms REAL, json TEXT,
            PRIMARY KEY (escena_id, servicio, minuto), FOREIGN KEY (escena_id) REFERENCES escenas(id)
        );
        CREATE TABLE IF NOT EXISTS golpes (
            escena_id TEXT NOT NULL, id TEXT NOT NULL, minuto INTEGER, origen TEXT,
            etiqueta TEXT, efecto TEXT, resultado TEXT, json TEXT,
            PRIMARY KEY (escena_id, id), FOREIGN KEY (escena_id) REFERENCES escenas(id)
        );
        CREATE TABLE IF NOT EXISTS eventos (
            escena_id TEXT NOT NULL, huella TEXT NOT NULL, minuto INTEGER, tipo TEXT,
            referencia TEXT, texto TEXT, datos_json TEXT,
            PRIMARY KEY (escena_id, huella), FOREIGN KEY (escena_id) REFERENCES escenas(id)
        );
        CREATE INDEX IF NOT EXISTS idx_avisos_escena_minuto ON avisos(escena_id, minuto);
        CREATE INDEX IF NOT EXISTS idx_incidentes_filtros ON incidentes(escena_id, estado, familia, zona, apertura_min);
        CREATE INDEX IF NOT EXISTS idx_planes_incidente ON planes(escena_id, incidente_id, version);
        CREATE INDEX IF NOT EXISTS idx_acciones_recurso ON acciones(escena_id, destinatario, inicio_min);
        CREATE INDEX IF NOT EXISTS idx_llamadas_incidente ON llamadas(escena_id, incidente_id, inicio_min);
        CREATE INDEX IF NOT EXISTS idx_decisiones_minuto ON decisiones(escena_id, minuto);
        CREATE INDEX IF NOT EXISTS idx_previsiones_estado ON previsiones(escena_id, estado);
        CREATE INDEX IF NOT EXISTS idx_partes_unidad ON partes_personal(escena_id, unidad, minuto);
        CREATE INDEX IF NOT EXISTS idx_servicios_minuto ON servicios_muestras(escena_id, servicio, minuto);
        CREATE INDEX IF NOT EXISTS idx_eventos_minuto ON eventos(escena_id, minuto);
    """)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY, started_at REAL NOT NULL, case_id TEXT,
            voice_mode TEXT, speed REAL, comms_mode TEXT
        );
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
            ts_unix REAL NOT NULL, event_type TEXT NOT NULL, action_id TEXT,
            payload_json TEXT NOT NULL DEFAULT '{}',
            aviso_id TEXT, incidente_id TEXT, plan_id TEXT, accion_id TEXT, llamada_id TEXT
        );
        CREATE TABLE IF NOT EXISTS episodes (
            action_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, kind TEXT, zone TEXT,
            resource TEXT, resource_kind TEXT, real INTEGER NOT NULL DEFAULT 0, result TEXT,
            eta_min REAL, fell_back INTEGER NOT NULL DEFAULT 0, answer_ms REAL, hook_rtt_ms REAL,
            closed_at REAL NOT NULL, text_scrubbed TEXT, t INTEGER, seed INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_events_session_ts ON events(session_id, ts_unix);
        CREATE INDEX IF NOT EXISTS idx_events_corr ON events(incidente_id, accion_id);
        CREATE INDEX IF NOT EXISTS idx_episodes_kind_result ON episodes(kind, result);
        CREATE INDEX IF NOT EXISTS idx_episodes_real_fb ON episodes(real, fell_back);
        CREATE TABLE IF NOT EXISTS cerebro_episodes (
            id TEXT PRIMARY KEY, session_id TEXT NOT NULL, ts_unix REAL NOT NULL,
            tipo TEXT, zona TEXT, franja TEXT,
            entrada_json TEXT NOT NULL DEFAULT '{}', contexto_json TEXT NOT NULL DEFAULT '{}',
            razonamiento TEXT, decision_json TEXT NOT NULL DEFAULT '{}',
            acciones_json TEXT NOT NULL DEFAULT '[]', respuestas_json TEXT NOT NULL DEFAULT '{}',
            resultado_json TEXT NOT NULL DEFAULT '{}', tiempos_json TEXT NOT NULL DEFAULT '{}',
            texto_busqueda TEXT, agente TEXT, confianza REAL,
            supuestos_json TEXT NOT NULL DEFAULT '[]'
        );
        CREATE INDEX IF NOT EXISTS idx_cerebro_tipo_zona ON cerebro_episodes(tipo, zona);
        CREATE INDEX IF NOT EXISTS idx_cerebro_franja ON cerebro_episodes(franja);
        CREATE INDEX IF NOT EXISTS idx_cerebro_texto ON cerebro_episodes(texto_busqueda);
        CREATE INDEX IF NOT EXISTS idx_cerebro_agente ON cerebro_episodes(agente);
        CREATE TABLE IF NOT EXISTS cerebro_lecciones (
            id TEXT PRIMARY KEY, ts_unix REAL NOT NULL, texto TEXT NOT NULL,
            evidencia_json TEXT NOT NULL DEFAULT '{}', estado TEXT NOT NULL,
            tipo TEXT, zona TEXT, by_who TEXT, n INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_cerebro_lecciones_estado ON cerebro_lecciones(estado);
        CREATE TABLE IF NOT EXISTS pizarra (
            id TEXT PRIMARY KEY, ts_unix REAL NOT NULL, session_id TEXT,
            de TEXT NOT NULL, para TEXT NOT NULL, incidente TEXT, tipo TEXT NOT NULL,
            texto TEXT, datos_json TEXT NOT NULL DEFAULT '{}', confianza REAL,
            enlaza TEXT, gravedad TEXT, resuelta INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_pizarra_incidente ON pizarra(incidente, ts_unix);
        CREATE INDEX IF NOT EXISTS idx_pizarra_para ON pizarra(para, ts_unix);
        CREATE TABLE IF NOT EXISTS agente_confianza (
            agente TEXT NOT NULL, familia TEXT NOT NULL,
            aciertos REAL NOT NULL DEFAULT 0, n INTEGER NOT NULL DEFAULT 0,
            puntuacion REAL NOT NULL DEFAULT 0.5, tendencia TEXT,
            ts_unix REAL NOT NULL, PRIMARY KEY (agente, familia)
        );
        CREATE TABLE IF NOT EXISTS adaptacion_eventos (
            id TEXT PRIMARY KEY, ts_unix REAL NOT NULL, session_id TEXT,
            clase TEXT NOT NULL, valor TEXT, porque TEXT,
            datos_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_adaptacion_clase ON adaptacion_eventos(clase, ts_unix);
        CREATE TABLE IF NOT EXISTS prompt_versiones (
            id TEXT PRIMARY KEY, agente TEXT NOT NULL, version INTEGER NOT NULL,
            cuerpo TEXT NOT NULL, diff TEXT, evidencia_json TEXT NOT NULL DEFAULT '{}',
            n INTEGER NOT NULL DEFAULT 0, estado TEXT NOT NULL,
            activa INTEGER NOT NULL DEFAULT 0, by_who TEXT, ts_unix REAL NOT NULL,
            sustituye TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_prompt_agente ON prompt_versiones(agente, version);
        CREATE TABLE IF NOT EXISTS especialista_aporte (
            agente TEXT NOT NULL, familia TEXT NOT NULL,
            n INTEGER NOT NULL DEFAULT 0, cambios INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (agente, familia)
        );
    """)
    _ensure_column(db, "events", "aviso_id", "TEXT")
    _ensure_column(db, "events", "incidente_id", "TEXT")
    _ensure_column(db, "events", "plan_id", "TEXT")
    _ensure_column(db, "events", "accion_id", "TEXT")
    _ensure_column(db, "events", "llamada_id", "TEXT")
    _ensure_column(db, "episodes", "resource_kind", "TEXT")
    _ensure_column(db, "episodes", "t", "INTEGER")
    _ensure_column(db, "episodes", "seed", "INTEGER")
    _ensure_column(db, "cerebro_episodes", "agente", "TEXT")
    _ensure_column(db, "cerebro_episodes", "confianza", "REAL")
    _ensure_column(db, "cerebro_episodes", "supuestos_json", "TEXT")
    _ensure_column(db, "cerebro_lecciones", "para_agente", "TEXT")
    _ensure_column(db, "cerebro_lecciones", "revocada", "INTEGER")
    db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    db.commit()


def _ensure_column(db: sqlite3.Connection, table: str, column: str, decl: str) -> None:
    cols = {r[1] for r in db.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


class _SqlJob:
    def __init__(self, fn: Callable[[sqlite3.Connection], Any]) -> None:
        self.fn = fn
        self.event = threading.Event()
        self.result: Any = None
        self.error: BaseException | None = None


class Store:
    """Un fichero, un hilo escritor, cola acotada. Si falla, los productores no lanzan."""

    def __init__(self, path: Path | None, *, queue_size: int = 16,
                 on_warning: Callable[[str], None] | None = None) -> None:
        self.path = path
        self.dropped = 0
        self.errors = 0
        self.enabled = False
        self.closed = False
        self.warning = ""
        self.refcount = 0
        self.host: Any = None
        self._warning = on_warning
        self._queue: queue.Queue[Any] = queue.Queue(maxsize=max(1, int(queue_size)))
        self._lifecycle = threading.Lock()
        self._ready = threading.Event()
        self._previous: dict[tuple[str, str, str], str] = {}
        self._last_scene: str | None = None
        self._last_minute: int | None = None
        self._thread: threading.Thread | None = None
        if path is None:
            self._ready.set()
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.warning = f"{type(exc).__name__}: {exc}"
            self._ready.set()
            return
        self._thread = threading.Thread(target=self._run, name="mando-sqlite", daemon=True)
        self._thread.start()
        self._ready.wait(5)

    def attach(self, *, on_warning: Callable[[str], None] | None = None, host: Any = None) -> None:
        if on_warning is not None:
            self._warning = on_warning
            if self.errors and self.warning:
                try:
                    on_warning(f"Historial SQLite no disponible: {self.warning}")
                except Exception:
                    pass
        if host is not None:
            self.host = host

    def offer(self, state: dict[str, Any]) -> None:
        with self._lifecycle:
            if self.closed or self.path is None or not isinstance(state, dict):
                return
            try:
                snapshot = json.loads(json.dumps(state, ensure_ascii=False, default=str))
                session = snapshot.get("session") if isinstance(snapshot.get("session"), dict) else {}
                self._last_scene = str(session.get("id") or "") or self._last_scene
                self._last_minute = int(snapshot.get("t") or 0)
                try:
                    self._queue.put_nowait(snapshot)
                except queue.Full:
                    try:
                        self._queue.get_nowait()
                        self._queue.task_done()
                        self.dropped += 1
                    except queue.Empty:
                        pass
                    self._queue.put_nowait(snapshot)
            except Exception as exc:
                self._fail(exc)

    def write(self, fn: Callable[[sqlite3.Connection], Any], *, timeout: float = 5.0) -> Any:
        if self.path is None or self.closed or not self.enabled:
            return None
        job = _SqlJob(fn)
        try:
            self._queue.put(job, timeout=min(1.0, timeout))
        except queue.Full:
            self.dropped += 1
            self._fail(RuntimeError("cola SQLite llena"))
            return None
        if not job.event.wait(timeout):
            self._fail(TimeoutError("escritura SQLite sin respuesta"))
            return None
        if job.error is not None:
            self._fail(job.error)
            self.enabled = False
            return None
        return job.result

    def release(self) -> None:
        with self._lifecycle:
            self.refcount = max(0, self.refcount - 1)
            if self.refcount > 0 or self.closed:
                return
            self.closed = True
            thread = self._thread
        if thread is None:
            self._forget()
            return
        deadline = time.monotonic() + 5
        while thread.is_alive() and time.monotonic() < deadline:
            try:
                self._queue.put(_STOP, timeout=min(0.05, max(0.001, deadline - time.monotonic())))
                break
            except queue.Full:
                continue
        thread.join(timeout=5)
        if thread.is_alive():
            self._fail(RuntimeError("el hilo SQLite no terminó en 5 s"))
        self._forget()

    def _forget(self) -> None:
        if self.path is None:
            return
        key = str(self.path)
        with _STORES_LOCK:
            if _STORES.get(key) is self:
                _STORES.pop(key, None)

    def _warn(self, message: str) -> None:
        _LOG.warning(message)
        if self._warning is not None:
            try:
                self._warning(message)
            except Exception:
                _LOG.exception("falló el callback de aviso de SQLite")

    def _fail(self, exc: BaseException) -> None:
        self.errors += 1
        self.warning = f"{type(exc).__name__}: {exc}"
        self._warn(f"Historial SQLite no disponible: {type(exc).__name__}: {exc}")

    def _run(self) -> None:
        assert self.path is not None
        db: sqlite3.Connection | None = None
        try:
            db = sqlite3.connect(str(self.path), timeout=5.0)
            _migrate(db)
            db.execute("INSERT INTO sessions(session_id, started_at) VALUES (?, ?)",
                       ("__probe__", time.time()))
            db.execute("DELETE FROM sessions WHERE session_id = ?", ("__probe__",))
            db.commit()
            self.enabled = True
            self._ready.set()
            while True:
                item = self._queue.get()
                try:
                    if item is _STOP:
                        if self._last_scene:
                            db.execute("UPDATE escenas SET fin=?, fin_min=COALESCE(?, fin_min) WHERE id=?",
                                       (_now(), self._last_minute, self._last_scene))
                            db.commit()
                        return
                    if isinstance(item, _SqlJob):
                        try:
                            item.result = item.fn(db)
                            db.commit()
                        except Exception as exc:
                            db.rollback()
                            item.error = exc
                        finally:
                            item.event.set()
                        continue
                    host = self.host
                    if host is not None:
                        host._record(db, item)
                    elif isinstance(item, dict):
                        continue
                except Exception as exc:
                    if db is not None:
                        db.rollback()
                    self._previous.clear()
                    self._fail(exc)
                finally:
                    self._queue.task_done()
        except Exception as exc:
            self.enabled = False
            self._fail(exc)
            self._ready.set()
        finally:
            self._ready.set()
            if db is not None:
                db.close()


def open_store(path: str | Path | None, *, queue_size: int = 16,
               on_warning: Callable[[str], None] | None = None, host: Any = None) -> Store:
    if path is None:
        st = Store(None, queue_size=queue_size, on_warning=on_warning)
        st.refcount += 1
        st.host = host
        return st
    key = str(Path(path))
    with _STORES_LOCK:
        st = _STORES.get(key)
        if st is None or st.closed:
            st = Store(Path(path), queue_size=queue_size, on_warning=on_warning)
            _STORES[key] = st
        else:
            st.attach(on_warning=on_warning, host=host)
        if host is not None:
            st.host = host
        st.refcount += 1
        return st


class Recorder:
    """Escritor no bloqueante; no importa ni inspecciona objetos del motor."""

    def __init__(self, path: str | Path | None = None, *, queue_size: int = 16,
                 on_warning: Callable[[str], None] | None = None) -> None:
        self.path = configured_path(path)
        self._store = open_store(self.path, queue_size=queue_size, on_warning=on_warning, host=self)
        self._warning = on_warning
        self._previous = self._store._previous
        self._last_scene = None
        self._last_minute = None

    @property
    def dropped(self) -> int:
        return self._store.dropped

    @dropped.setter
    def dropped(self, value: int) -> None:
        self._store.dropped = value

    @property
    def errors(self) -> int:
        return self._store.errors

    @errors.setter
    def errors(self, value: int) -> None:
        self._store.errors = value

    @property
    def enabled(self) -> bool:
        return self.path is not None

    def offer(self, state: dict[str, Any]) -> None:
        """Acepta una instantánea sin esperar al disco y sin propagar ningún error."""
        self._store.host = self
        self._store.offer(state)
        self._last_scene = self._store._last_scene
        self._last_minute = self._store._last_minute

    def close(self) -> None:
        scene, minute = self._store._last_scene, self._store._last_minute
        if scene and self.path is not None and self._store.enabled:
            def _fin(db: sqlite3.Connection) -> None:
                db.execute("UPDATE escenas SET fin=?, fin_min=COALESCE(?, fin_min) WHERE id=?",
                           (_now(), minute, scene))
            self._store.write(_fin)
        self._store.release()

    def _changed(self, scene: str, table: str, key: str, values: tuple[Any, ...]) -> bool:
        marker = _json(values)
        cache_key = (scene, table, key)
        if self._previous.get(cache_key) == marker:
            return False
        self._previous[cache_key] = marker
        return True

    def _upsert(self, db: sqlite3.Connection, table: str, columns: tuple[str, ...],
                values: tuple[Any, ...], conflict: tuple[str, ...], *, scene: str, key: str,
                updates: tuple[str, ...] | None = None, preserve: tuple[str, ...] = ()) -> None:
        if not self._changed(scene, table, key, values):
            return
        update_columns = updates if updates is not None else tuple(c for c in columns if c not in conflict)
        setters = [f"{column}=COALESCE({table}.{column},excluded.{column})"
                   if column in preserve else f"{column}=excluded.{column}"
                   for column in update_columns]
        sql = (f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)}) "
               f"ON CONFLICT ({','.join(conflict)}) DO UPDATE SET " + ",".join(setters))
        db.execute(sql, values)

    def _record(self, db: sqlite3.Connection, state: dict[str, Any]) -> None:
        session = state.get("session") if isinstance(state.get("session"), dict) else {}
        scene = str(session.get("id") or "")
        if not scene:
            raise ValueError("el estado público no contiene session.id")
        minute = int(state.get("t") or 0)
        db.execute("""INSERT INTO escenas(id,caso,semilla,inicio,fin,fin_min,modo_comunicaciones)
                      VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                      caso=excluded.caso,semilla=excluded.semilla,fin_min=excluded.fin_min,
                      modo_comunicaciones=excluded.modo_comunicaciones,
                      fin=CASE WHEN ? THEN excluded.fin ELSE escenas.fin END""",
                   (scene, _text(session.get("case")), session.get("seed"), _now(),
                    _now() if session.get("done") else None, minute, _text(session.get("comms_mode")),
                    bool(session.get("done"))))
        incidents = {str(item.get("id")): item for item in _items(state.get("incidents")) if item.get("id")}
        reports = {str(item.get("id")): item for item in _items(state.get("reports")) if item.get("id")}
        reserved_reports = {str(rid) for item in incidents.values() if item.get("reserved")
                            for rid in item.get("reports", [])}

        for iid, item in incidents.items():
            safe = dict(_scrub(item))
            if item.get("reserved"):
                safe.update(label="Incidente reservado", type="reserved", zone=None, explain="")
            values = (scene, iid, _text(safe.get("family")), _text(safe.get("type")),
                      _text(safe.get("label")), _text(safe.get("zone")), safe.get("severity"),
                      safe.get("priority"), _text(safe.get("status")), safe.get("t_open"),
                      safe.get("first_action_t", safe.get("t_first_dispatch")), safe.get("t_closed", safe.get("t_end")),
                      int(bool(item.get("reserved"))), _json(safe))
            self._upsert(db, "incidentes",
                         ("escena_id", "id", "familia", "tipo", "etiqueta", "zona", "gravedad", "prioridad",
                          "estado", "apertura_min", "primera_accion_min", "cierre_min", "reservado", "json"),
                         values, ("escena_id", "id"), scene=scene, key=iid)

        for rid, item in reports.items():
            safe = dict(_scrub(item))
            if rid in reserved_reports:
                safe.update(text="(aviso reservado)", zone_hint=None, source="")
            incident_id = _text(safe.get("incident"))
            values = (scene, rid, safe.get("t"), _text(safe.get("channel")), _text(safe.get("source")),
                      _text(safe.get("via")), _text(safe.get("text")), _text(safe.get("zone_hint")), incident_id)
            self._upsert(db, "avisos",
                         ("escena_id", "id", "minuto", "canal", "fuente", "via", "texto", "zona", "incidente_id"),
                         values, ("escena_id", "id"), scene=scene, key=rid)
            if incident_id:
                link = (scene, rid, incident_id, _text(safe.get("source")), _text(safe.get("channel")))
                self._upsert(db, "aviso_incidente",
                             ("escena_id", "aviso_id", "incidente_id", "fuente", "canal"), link,
                             ("escena_id", "aviso_id", "incidente_id"), scene=scene, key=f"{rid}:{incident_id}")
        for iid, item in incidents.items():
            for rid in item.get("reports", []):
                report = reports.get(str(rid), {})
                link = (scene, str(rid), iid, _text(report.get("source")), _text(report.get("channel")))
                self._upsert(db, "aviso_incidente",
                             ("escena_id", "aviso_id", "incidente_id", "fuente", "canal"), link,
                             ("escena_id", "aviso_id", "incidente_id"), scene=scene, key=f"{rid}:{iid}")

        for pos, item in enumerate(_items(state.get("plans"))):
            pid = _id(item, "id", fallback=f"plan-{pos}")
            values = (scene, pid, _text(item.get("incident")), item.get("version"), _text(item.get("objective")),
                      _text(item.get("why")), _text(item.get("supersedes")), _text(item.get("status")),
                      item.get("t", item.get("created_t")), _json(item))
            self._upsert(db, "planes",
                         ("escena_id", "id", "incidente_id", "version", "objetivo", "porque", "sustituye_a",
                          "estado", "minuto", "json"), values, ("escena_id", "id"), scene=scene, key=pid)
            for n, assumption in enumerate(_items(item.get("assumptions"))):
                aid = _id(assumption, "id", fallback=f"{pid}-u-{n}")
                valid = assumption.get("valid", assumption.get("state") not in ("broken", "roto", False))
                broken = assumption.get("broken_t", assumption.get("t_broken", assumption.get("rotura_min")))
                status = "vigente" if valid and broken is None else "roto"
                avalues = (scene, pid, aid, _text(assumption.get("text")), status, broken, _json(assumption))
                self._upsert(db, "supuestos",
                             ("escena_id", "plan_id", "id", "texto", "estado", "rotura_min", "json"), avalues,
                             ("escena_id", "plan_id", "id"), scene=scene, key=f"{pid}:{aid}")

        actions = _items(state.get("actions"))
        action_by_id = {str(item.get("id")): item for item in actions if item.get("id")}
        for pos, item in enumerate(actions):
            aid = _id(item, "id", fallback=f"action-{pos}")
            status = _text(item.get("status"))
            end = item.get("t_end", minute if status in ("done", "resolved", "rejected", "failed", "cancelled") else None)
            values = (scene, aid, _text(item.get("incident")), _text(item.get("plan")),
                      _text(item.get("kind", item.get("type"))), _text(item.get("resource", item.get("to"))),
                      _text(item.get("zone")), _text(item.get("autonomy")), status, item.get("t"),
                      minute, end, _text(item.get("why", (item.get("params") or {}).get("reason"))), _json(item))
            self._upsert(db, "acciones",
                         ("escena_id", "id", "incidente_id", "plan_id", "tipo", "destinatario", "zona",
                          "autonomia", "estado", "inicio_min", "ultimo_min", "fin_min", "porque", "json"),
                         values, ("escena_id", "id"), scene=scene, key=aid, preserve=("fin_min",))

        calls = state.get("calls", {})
        calls = calls.get("calls", []) if isinstance(calls, dict) else calls
        for pos, item in enumerate(_items(calls)):
            aid = _text(item.get("action_id"))
            cid = _id(item, "id", "call_id", fallback=aid or f"call-{pos}")
            raw_result = str(item.get("result") or "").lower()
            result = {"accept": "ACEPTA", "accepted": "ACEPTA", "acepta": "ACEPTA",
                      "reject": "RECHAZA", "rejected": "RECHAZA", "rechaza": "RECHAZA",
                      "no_answer": "SIN_RESPUESTA", "sin respuesta": "SIN_RESPUESTA"}.get(raw_result,
                                                                                       raw_result.upper() or None)
            latency = item.get("turn_latency_ms", item.get("latency_ms", item.get("hook_rtt_ms")))
            values = (scene, cid, aid, _text(item.get("incident")), _text(item.get("workflow")),
                      _text(item.get("to", item.get("resource"))), result,
                      _text(item.get("reason", item.get("text"))), latency,
                      _text(item.get("hr_run_id", item.get("run_id"))), item.get("t"), item.get("t_end"), _json(item))
            self._upsert(db, "llamadas",
                         ("escena_id", "id", "accion_id", "incidente_id", "workflow", "destinatario",
                          "resultado", "motivo", "latencia_ms", "run_id", "inicio_min", "fin_min", "json"),
                         values, ("escena_id", "id"), scene=scene, key=cid)

        self._record_operators_and_decisions(db, scene, minute, state.get("operators"), state.get("decisions"),
                                             action_by_id)
        self._record_forecasts(db, scene, minute, state.get("forecasts"))
        self._record_parts(db, scene, state)
        self._record_services(db, scene, minute, state)
        self._record_strikes(db, scene, state.get("strikes"))
        self._record_events(db, scene, state.get("log"))
        db.commit()

    def _record_operators_and_decisions(self, db: sqlite3.Connection, scene: str, minute: int,
                                        operators: Any, decisions: Any,
                                        actions: dict[str, dict[str, Any]]) -> None:
        view = operators if isinstance(operators, dict) else {}
        people: dict[str, dict[str, Any]] = {}
        for row in _items(view.get("presence")):
            person = row.get("operator") if isinstance(row.get("operator"), dict) else row
            oid = _id(person, "id", fallback=_id(person, "name", fallback="operador"))
            people[oid] = dict(person, incident=row.get("incident"))
        events = _items(view.get("events"))
        for event in events:
            person = event.get("operator") if isinstance(event.get("operator"), dict) else {}
            if person:
                oid = _id(person, "id", fallback=_id(person, "name", fallback="operador"))
                people[oid] = dict(person, incident=event.get("ref"))
        for oid, person in people.items():
            values = (scene, oid, _text(person.get("name")), _text(person.get("role", person.get("papel"))),
                      _text(person.get("incident")), minute, _json(person))
            self._upsert(db, "operadores",
                         ("escena_id", "id", "nombre", "papel", "incidente_id", "ultimo_min", "json"), values,
                         ("escena_id", "id"), scene=scene, key=oid)

        direct = _items(decisions)
        candidates = direct + [event for event in events if any(word in str(event.get("verb", "")).lower()
                                                                 for word in ("apro", "veta", "corrige"))]
        for pos, item in enumerate(candidates):
            person = item.get("operator") if isinstance(item.get("operator"), dict) else {}
            action_id = _text(item.get("action", item.get("action_id", item.get("ref"))))
            did = _id(item, "id", fallback=str(item.get("seq") or f"{action_id or 'decision'}-{pos}"))
            verb = str(item.get("result", item.get("decision", item.get("verb", "")))).lower()
            if any(word in verb for word in ("apro", "accept", "sí", "si")):
                result = "APROBAR"
            elif any(word in verb for word in ("veta", "reject", "no")):
                result = "VETAR"
            else:
                result = verb.upper()
            card = ((actions.get(action_id or "", {}).get("params") or {}).get("decision_card") or
                    item.get("card") or {})
            values = (scene, did, action_id, result, _text(person.get("name", item.get("operator_name"))),
                      _text(person.get("role", item.get("role", item.get("papel")))),
                      _text(item.get("note", item.get("nota"))), item.get("t", item.get("minute")),
                      item.get("real_s", item.get("latency_s")), _json(card.get("if_approved")),
                      _json(card.get("if_vetoed")), _json(item))
            self._upsert(db, "decisiones",
                         ("escena_id", "id", "accion_id", "resultado", "operador", "papel", "nota",
                          "minuto", "latencia_s", "futuro_aprobar_json", "futuro_vetar_json", "json"),
                         values, ("escena_id", "id"), scene=scene, key=did)

    def _record_forecasts(self, db: sqlite3.Connection, scene: str, minute: int, forecasts: Any) -> None:
        states = {"forecast": "PREVISTO", "predicted": "PREVISTO", "previsto": "PREVISTO",
                  "avoided": "EVITADO", "evitado": "EVITADO", "fulfilled": "CUMPLIDO",
                  "cumplido": "CUMPLIDO", "missed": "NO_CUMPLIDO", "no_cumplido": "NO_CUMPLIDO"}
        for pos, item in enumerate(_items(forecasts)):
            fid = _id(item, "id", fallback=f"forecast-{pos}")
            status = states.get(str(item.get("status", item.get("state", "previsto"))).lower(),
                                str(item.get("status", item.get("state", "PREVISTO"))).upper())
            values = (scene, fid, _text(item.get("zone")), _text(item.get("resource")),
                      _text(item.get("metric", item.get("kind"))), item.get("threshold"),
                      item.get("eta_min", item.get("eta")), status,
                      item.get("created_t", item.get("t", minute)), _json(item))
            self._upsert(db, "previsiones",
                         ("escena_id", "id", "zona", "recurso", "metrica", "umbral", "eta_min",
                          "estado", "minuto", "json"), values, ("escena_id", "id"), scene=scene, key=fid)

    def _record_parts(self, db: sqlite3.Connection, scene: str, state: dict[str, Any]) -> None:
        parts = _items(state.get("partes_personal", state.get("staff_reports")))
        parts += [item for item in _items(state.get("log")) if item.get("kind") == "staff_status"]
        for pos, item in enumerate(parts):
            pid = _id(item, "id", "ref", fallback=f"staff-{item.get('t', 0)}-{pos}")
            values = (scene, pid, _text(item.get("unit_id", item.get("unit"))),
                      _text(item.get("incident", item.get("incident_id"))), _text(item.get("status")),
                      _text(item.get("zone")), _text(item.get("text")), item.get("t", item.get("minute")),
                      _text(item.get("channel")), _json(item))
            self._upsert(db, "partes_personal",
                         ("escena_id", "id", "unidad", "incidente_id", "estado", "zona", "texto",
                          "minuto", "canal", "json"), values, ("escena_id", "id"), scene=scene, key=pid)

    def _record_services(self, db: sqlite3.Connection, scene: str, minute: int, state: dict[str, Any]) -> None:
        rows: list[tuple[str, Any]] = []
        health = state.get("service_health")
        if isinstance(health, dict):
            down = health.get("comms_down")
            if isinstance(down, dict):
                rows += [(str(name), {"state": "caído" if value else "operativo"}) for name, value in down.items()]
            rows += [(str(name), value) for name, value in health.items() if name != "comms_down"]
        happy = state.get("happyrobot")
        if isinstance(happy, dict):
            rows += [(str(name), value) for name, value in happy.items()]
        rows += [(_id(item, "service", "workflow", "channel", "id", fallback=f"service-{n}"), item)
                 for n, item in enumerate(_items(state.get("services")))]
        for name, raw in rows:
            item = raw if isinstance(raw, dict) else {"state": raw}
            status = item.get("state", item.get("status", "operativo" if raw is False else raw))
            latency = item.get("latency_ms", item.get("hook_rtt_ms", item.get("turn_latency_ms")))
            values = (scene, name, minute, _text(status), latency, _json(item))
            self._upsert(db, "servicios_muestras",
                         ("escena_id", "servicio", "minuto", "estado", "latencia_ms", "json"), values,
                         ("escena_id", "servicio", "minuto"), scene=scene, key=f"{name}:{minute}")

    def _record_strikes(self, db: sqlite3.Connection, scene: str, strikes: Any) -> None:
        for pos, item in enumerate(_items(strikes)):
            gid = _id(item, "id", fallback=f"strike-{pos}")
            values = (scene, gid, item.get("t"), _text(item.get("origin")), _text(item.get("label")),
                      _text((item.get("effect") or {}).get("kind") if isinstance(item.get("effect"), dict)
                            else item.get("effect")), _text(item.get("outcome", item.get("result"))), _json(item))
            self._upsert(db, "golpes",
                         ("escena_id", "id", "minuto", "origen", "etiqueta", "efecto", "resultado", "json"),
                         values, ("escena_id", "id"), scene=scene, key=gid)

    def _record_events(self, db: sqlite3.Connection, scene: str, log: Any) -> None:
        seen: dict[str, int] = {}
        for item in _items(log):
            safe = _scrub(item)
            base = _json({"t": safe.get("t"), "kind": safe.get("kind"), "ref": safe.get("ref"),
                          "text": safe.get("text"), "data": safe.get("data")})
            seen[base] = seen.get(base, 0) + 1
            fingerprint = hashlib.sha256(f"{base}#{seen[base]}".encode()).hexdigest()[:24]
            values = (scene, fingerprint, safe.get("t"), _text(safe.get("kind")), _text(safe.get("ref")),
                      _text(safe.get("text")), _json(safe.get("data", safe)))
            self._upsert(db, "eventos",
                         ("escena_id", "huella", "minuto", "tipo", "referencia", "texto", "datos_json"),
                         values, ("escena_id", "huella"), scene=scene, key=fingerprint)


class History:
    """Consultas de solo lectura; todos los valores externos usan parámetros SQLite."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = configured_path(path)

    @property
    def enabled(self) -> bool:
        return self.path is not None

    def _connect(self) -> sqlite3.Connection:
        if self.path is None:
            raise RuntimeError("Historial desactivado con MANDO_DB=off")
        db = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        return db

    @staticmethod
    def _rows(cursor: sqlite3.Cursor) -> list[dict[str, Any]]:
        return [dict(row) for row in cursor.fetchall()]

    def scenes(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as db:
            return self._rows(db.execute("SELECT * FROM escenas ORDER BY inicio DESC, id DESC"))

    def incidents(self, *, scene: str | None = None, status: str | None = None,
                  family: str | None = None, zone: str | None = None,
                  since: int | None = None, until: int | None = None, q: str | None = None,
                  page: int = 1, size: int = 50) -> dict[str, Any]:
        where, args = [], []
        for column, value in (("escena_id", scene), ("estado", status), ("familia", family), ("zona", zone)):
            if value not in (None, ""):
                where.append(f"{column}=?")
                args.append(value)
        if since is not None:
            where.append("apertura_min>=?")
            args.append(int(since))
        if until is not None:
            where.append("apertura_min<=?")
            args.append(int(until))
        if q:
            where.append("(etiqueta LIKE ? ESCAPE '\\' OR tipo LIKE ? ESCAPE '\\' OR id LIKE ? ESCAPE '\\')")
            escaped = str(q).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            args.extend([f"%{escaped}%"] * 3)
        clause = " WHERE " + " AND ".join(where) if where else ""
        page, size = max(1, int(page)), max(1, min(200, int(size)))
        with closing(self._connect()) as db:
            total = int(db.execute("SELECT count(*) FROM incidentes" + clause, args).fetchone()[0])
            items = self._rows(db.execute(
                "SELECT * FROM incidentes" + clause + " ORDER BY apertura_min DESC, id DESC LIMIT ? OFFSET ?",
                [*args, size, (page - 1) * size]))
        return {"items": items, "total": total, "page": page, "size": size, "pages": (total + size - 1) // size}

    def incident(self, scene: str | None, incident_id: str) -> dict[str, Any]:
        with closing(self._connect()) as db:
            if scene is None:
                row = db.execute("""SELECT i.* FROM incidentes i JOIN escenas e ON e.id=i.escena_id
                                    WHERE i.id=? ORDER BY e.inicio DESC LIMIT 1""", (incident_id,)).fetchone()
            else:
                row = db.execute("SELECT * FROM incidentes WHERE escena_id=? AND id=?",
                                 (scene, incident_id)).fetchone()
            if row is None:
                raise KeyError(incident_id)
            incident = dict(row)
            scene = incident["escena_id"]
            reports = self._rows(db.execute("""SELECT a.* FROM avisos a JOIN aviso_incidente x
                                               ON x.escena_id=a.escena_id AND x.aviso_id=a.id
                                               WHERE x.escena_id=? AND x.incidente_id=? ORDER BY a.minuto,a.id""",
                                            (scene, incident_id)))
            plans = self._rows(db.execute("SELECT * FROM planes WHERE escena_id=? AND incidente_id=? ORDER BY version,id",
                                          (scene, incident_id)))
            for plan in plans:
                plan["assumptions"] = self._rows(db.execute(
                    "SELECT * FROM supuestos WHERE escena_id=? AND plan_id=? ORDER BY id", (scene, plan["id"])))
            calls = self._rows(db.execute("SELECT * FROM llamadas WHERE escena_id=? AND incidente_id=? ORDER BY inicio_min,id",
                                          (scene, incident_id)))
            action_ids = [row["id"] for row in db.execute(
                "SELECT id FROM acciones WHERE escena_id=? AND incidente_id=?", (scene, incident_id))]
            placeholders = ",".join("?" for _ in action_ids)
            decisions = self._rows(db.execute(
                f"SELECT * FROM decisiones WHERE escena_id=? AND accion_id IN ({placeholders}) ORDER BY minuto,id",
                [scene, *action_ids])) if action_ids else []
            escaped_id = incident_id.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            timeline = self._rows(db.execute(
                """SELECT minuto,tipo,referencia,texto,datos_json FROM eventos
                   WHERE escena_id=? AND (referencia=? OR datos_json LIKE ? ESCAPE '\\')
                   ORDER BY minuto,huella""",
                (scene, incident_id, f'%"incident":"{escaped_id}"%')))
        return {"incident": incident, "reports": reports, "plans": plans, "calls": calls,
                "decisions": decisions, "timeline": timeline}

    def decisions(self, scene: str | None = None) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM decisiones", []
        if scene:
            sql, args = sql + " WHERE escena_id=?", [scene]
        with closing(self._connect()) as db:
            return self._rows(db.execute(sql + " ORDER BY minuto DESC,id DESC", args))

    def resources(self, scene: str | None = None) -> list[dict[str, Any]]:
        where, args = (" WHERE escena_id=?", [scene]) if scene else ("", [])
        with closing(self._connect()) as db:
            return self._rows(db.execute(
                """SELECT escena_id,destinatario AS recurso,count(*) AS acciones,
                          min(inicio_min) AS desde_min,max(COALESCE(fin_min,ultimo_min)) AS hasta_min,
                          sum(max(0,COALESCE(fin_min,ultimo_min)-COALESCE(inicio_min,ultimo_min))) AS ocupado_min
                   FROM acciones""" + where +
                " GROUP BY escena_id,destinatario ORDER BY ocupado_min DESC,recurso", args))

    def services(self, scene: str | None = None) -> list[dict[str, Any]]:
        where, args = (" WHERE escena_id=?", [scene]) if scene else ("", [])
        with closing(self._connect()) as db:
            return self._rows(db.execute(
                "SELECT * FROM servicios_muestras" + where + " ORDER BY minuto DESC,servicio", args))

    def summary(self, scene: str | None = None) -> dict[str, Any]:
        where, args = (" WHERE escena_id=?", [scene]) if scene else ("", [])
        with closing(self._connect()) as db:
            db.execute("BEGIN")
            incidents = self._rows(db.execute(
                "SELECT familia,gravedad,apertura_min,primera_accion_min FROM incidentes" + where, args))
            decisions = self._rows(db.execute("SELECT latencia_s FROM decisiones" + where, args))
            calls = self._rows(db.execute("SELECT resultado FROM llamadas" + where, args))
            forecasts = self._rows(db.execute("SELECT estado FROM previsiones" + where, args))
        return self._summary_rows(incidents, decisions, calls, forecasts)

    @staticmethod
    def _summary_rows(incidents: list[dict[str, Any]], decisions: list[dict[str, Any]],
                      calls: list[dict[str, Any]], forecasts: list[dict[str, Any]]) -> dict[str, Any]:
        by_family: dict[str, int] = {}
        by_severity: dict[str, int] = {}
        first = []
        for item in incidents:
            family = item["familia"] or "sin_familia"
            by_family[family] = by_family.get(family, 0) + 1
            severity = str(item["gravedad"] if item["gravedad"] is not None else "sin_gravedad")
            by_severity[severity] = by_severity.get(severity, 0) + 1
            if item["primera_accion_min"] is not None and item["apertura_min"] is not None:
                first.append(item["primera_accion_min"] - item["apertura_min"])
        decision_values = [item["latencia_s"] for item in decisions if item.get("latencia_s") is not None]
        call_results = [item.get("resultado") for item in calls]
        forecast_states = [item.get("estado") for item in forecasts]
        checked = [status for status in forecast_states if status in ("CUMPLIDO", "NO_CUMPLIDO")]
        return {
            "incidentes": {"por_familia": by_family, "por_gravedad": by_severity, "n": len(incidents)},
            "primera_accion_mediana_min": {"value": float(median(first)) if first else None, "n": len(first)},
            "decision_humana_mediana_s": {
                "value": float(median(decision_values)) if decision_values else None, "n": len(decision_values)},
            "llamadas": {"aceptadas": call_results.count("ACEPTA"), "rechazadas": call_results.count("RECHAZA"),
                         "sin_respuesta": call_results.count("SIN_RESPUESTA"), "n": len(call_results)},
            "previsiones_acertadas": {"value": (checked.count("CUMPLIDO") / len(checked)) if checked else None,
                                      "n": len(checked)},
        }

    def _export_rows(self, scene: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        with closing(self._connect()) as db:
            scene_row = db.execute("SELECT * FROM escenas WHERE id=?", (scene,)).fetchone()
            if scene_row is None:
                raise KeyError(scene)
            incidents = self._rows(db.execute(
                "SELECT * FROM incidentes WHERE escena_id=? ORDER BY apertura_min,id", (scene,)))
        return dict(scene_row), incidents

    def export_json(self, scene: str) -> str:
        tables = ("avisos", "aviso_incidente", "planes", "supuestos", "acciones", "llamadas",
                  "decisiones", "previsiones", "partes_personal", "operadores",
                  "servicios_muestras", "golpes", "eventos")
        with closing(self._connect()) as db:
            db.execute("BEGIN")
            scene_row = db.execute("SELECT * FROM escenas WHERE id=?", (scene,)).fetchone()
            if scene_row is None:
                raise KeyError(scene)
            payload = {
                "scene": dict(scene_row),
                "incidents": self._rows(db.execute(
                    "SELECT * FROM incidentes WHERE escena_id=? ORDER BY apertura_min,id", (scene,))),
            }
            for table in tables:
                payload[table] = self._rows(db.execute(
                    f"SELECT * FROM {table} WHERE escena_id=?", (scene,)))
            payload["summary"] = self._summary_rows(
                payload["incidents"], payload["decisiones"], payload["llamadas"], payload["previsiones"])
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def export_csv(self, scene: str) -> str:
        _, rows = self._export_rows(scene)
        output = io.StringIO()
        columns = ("escena_id", "id", "familia", "tipo", "etiqueta", "zona", "gravedad", "prioridad",
                   "estado", "apertura_min", "primera_accion_min", "cierre_min")
        writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        return output.getvalue()
