"""Ledger SQLite append-only: auditoría durable de llamadas HappyRobot / sim.

No es la fuente de verdad del mundo (eso sigue siendo el simulador determinista).
Si el fichero no es escribible, degrada en silencio: la demo no se tumba.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from . import privacy

DEFAULT_REL = Path("motor/server/data/ledger.sqlite")
_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  session_id TEXT PRIMARY KEY,
  started_at REAL NOT NULL,
  case_id TEXT,
  voice_mode TEXT,
  speed REAL,
  comms_mode TEXT
);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  ts_unix REAL NOT NULL,
  event_type TEXT NOT NULL,
  action_id TEXT,
  payload_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS episodes (
  action_id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  kind TEXT,
  zone TEXT,
  resource TEXT,
  resource_kind TEXT,
  real INTEGER NOT NULL DEFAULT 0,
  result TEXT,
  eta_min REAL,
  fell_back INTEGER NOT NULL DEFAULT 0,
  answer_ms REAL,
  hook_rtt_ms REAL,
  closed_at REAL NOT NULL,
  text_scrubbed TEXT,
  t INTEGER,
  seed INTEGER
);
CREATE INDEX IF NOT EXISTS idx_events_session_ts ON events(session_id, ts_unix);
CREATE INDEX IF NOT EXISTS idx_episodes_kind_result ON episodes(kind, result);
CREATE INDEX IF NOT EXISTS idx_episodes_real_fb ON episodes(real, fell_back);
"""


def default_path() -> Path:
    raw = (os.environ.get("MANDO_LEDGER_PATH") or "").strip()
    if raw:
        p = Path(raw)
        return p if p.is_absolute() else Path.cwd() / p
    # Bajo unittest/pytest nunca escribir en el ledger de producción: patch.dict(..., clear=True)
    # borra MANDO_LEDGER_PATH y el fallback caería al fichero real.
    if "unittest" in sys.modules or "pytest" in sys.modules:
        return Path(tempfile.gettempdir()) / f"mando-ledger-test-{os.getpid()}.sqlite"
    # Preferir junto al paquete si cwd no es la raíz FABAT.
    here = Path(__file__).resolve().parent / "data" / "ledger.sqlite"
    return here


def _scrub_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return {}
    clean = privacy.scrub(dict(payload))
    return clean if isinstance(clean, dict) else {"value": clean}


def _truncate_text(text: Any, n: int = 160) -> str:
    s = privacy.scrub(str(text or ""))
    if not isinstance(s, str):
        s = str(s)
    return s[:n]


class Ledger:
    """Escritura best-effort. `enabled=False` → todos los métodos son no-ops seguros."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_path()
        self.enabled = False
        self._lock = threading.RLock()
        self._db: sqlite3.Connection | None = None
        self._warn = ""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(str(self.path), check_same_thread=False, timeout=5.0)
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(_SCHEMA)
            # Migración suave si el fichero ya existía sin columnas nuevas
            cols = {r[1] for r in db.execute("PRAGMA table_info(episodes)").fetchall()}
            for col, decl in (("resource_kind", "TEXT"), ("t", "INTEGER"), ("seed", "INTEGER")):
                if col not in cols:
                    db.execute(f"ALTER TABLE episodes ADD COLUMN {col} {decl}")
            db.commit()
            # Probar escritura
            db.execute("INSERT INTO sessions(session_id, started_at) VALUES (?, ?)",
                       ("__probe__", time.time()))
            db.execute("DELETE FROM sessions WHERE session_id = ?", ("__probe__",))
            db.commit()
            self._db = db
            self.enabled = True
        except (OSError, sqlite3.Error) as ex:
            self._warn = f"{type(ex).__name__}: {ex}"
            if self._db is not None:
                try:
                    self._db.close()
                except sqlite3.Error:
                    pass
                self._db = None
            self.enabled = False

    @classmethod
    def open(cls, path: Path | str | None = None) -> "Ledger":
        return cls(Path(path) if path else None)

    @property
    def warning(self) -> str:
        return self._warn

    def close(self) -> None:
        with self._lock:
            if self._db is not None:
                try:
                    self._db.close()
                except sqlite3.Error:
                    pass
                self._db = None
            self.enabled = False

    def session_start(self, session_id: str, *, case_id: str = "", voice_mode: str = "",
                      speed: float = 1.0, comms_mode: str = "sim") -> None:
        if not self.enabled or self._db is None:
            return
        with self._lock:
            try:
                self._db.execute(
                    "INSERT OR REPLACE INTO sessions(session_id, started_at, case_id, voice_mode, speed, comms_mode) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (session_id, time.time(), case_id or None, voice_mode or None, float(speed), comms_mode or None),
                )
                self._db.commit()
            except sqlite3.Error as ex:
                self._warn = f"session_start: {ex}"
                self.enabled = False

    def append_event(self, session_id: str, event_type: str, action_id: str | None = None,
                     payload: dict[str, Any] | None = None) -> None:
        if not self.enabled or self._db is None:
            return
        body = json.dumps(_scrub_payload(payload), ensure_ascii=False, default=str)
        with self._lock:
            try:
                self._db.execute(
                    "INSERT INTO events(session_id, ts_unix, event_type, action_id, payload_json) VALUES (?, ?, ?, ?, ?)",
                    (session_id, time.time(), event_type, action_id, body),
                )
                self._db.commit()
            except sqlite3.Error as ex:
                self._warn = f"append_event: {ex}"
                self.enabled = False

    def upsert_episode(self, session_id: str, action_id: str, *, kind: str = "", zone: str = "",
                       resource: str = "", resource_kind: str = "", real: bool = False,
                       result: str | None = None,
                       eta_min: float | None = None, fell_back: bool = False,
                       answer_ms: float | None = None, hook_rtt_ms: float | None = None,
                       text: str = "", t: int | None = None, seed: int | None = None) -> None:
        if not self.enabled or self._db is None or not action_id:
            return
        with self._lock:
            try:
                self._db.execute(
                    "INSERT INTO episodes(action_id, session_id, kind, zone, resource, resource_kind, real, result, eta_min, "
                    "fell_back, answer_ms, hook_rtt_ms, closed_at, text_scrubbed, t, seed) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(action_id) DO UPDATE SET "
                    "session_id=excluded.session_id, kind=COALESCE(excluded.kind, episodes.kind), "
                    "zone=COALESCE(excluded.zone, episodes.zone), "
                    "resource=COALESCE(excluded.resource, episodes.resource), "
                    "resource_kind=COALESCE(excluded.resource_kind, episodes.resource_kind), "
                    "real=excluded.real, result=COALESCE(excluded.result, episodes.result), "
                    "eta_min=COALESCE(excluded.eta_min, episodes.eta_min), "
                    "fell_back=excluded.fell_back, "
                    "answer_ms=COALESCE(excluded.answer_ms, episodes.answer_ms), "
                    "hook_rtt_ms=COALESCE(excluded.hook_rtt_ms, episodes.hook_rtt_ms), "
                    "closed_at=excluded.closed_at, "
                    "text_scrubbed=COALESCE(excluded.text_scrubbed, episodes.text_scrubbed), "
                    "t=COALESCE(excluded.t, episodes.t), "
                    "seed=COALESCE(excluded.seed, episodes.seed)",
                    (action_id, session_id, kind or None, zone or None, resource or None,
                     resource_kind or None,
                     1 if real else 0, result, eta_min, 1 if fell_back else 0,
                     answer_ms, hook_rtt_ms, time.time(), _truncate_text(text) or None,
                     t, seed),
                )
                self._db.commit()
            except sqlite3.Error as ex:
                self._warn = f"upsert_episode: {ex}"
                self.enabled = False

    def stats(self) -> dict[str, Any]:
        """Totales para doctor / API. Si está degradado, lo dice sin lanzar."""
        base: dict[str, Any] = {
            "enabled": self.enabled,
            "path": str(self.path),
            "warning": self._warn or None,
            "sessions": 0,
            "events": 0,
            "episodes": 0,
            "real_ok": 0,
            "fallbacks": 0,
            "by_kind": {},
        }
        if not self.enabled or self._db is None:
            return base
        with self._lock:
            try:
                cur = self._db.cursor()
                base["sessions"] = cur.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
                base["events"] = cur.execute("SELECT COUNT(*) FROM events").fetchone()[0]
                base["episodes"] = cur.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
                base["real_ok"] = cur.execute(
                    "SELECT COUNT(*) FROM episodes WHERE real=1 AND fell_back=0 AND result IS NOT NULL"
                ).fetchone()[0]
                base["fallbacks"] = cur.execute(
                    "SELECT COUNT(*) FROM episodes WHERE fell_back=1"
                ).fetchone()[0]
                rows = cur.execute(
                    "SELECT kind, COUNT(*) FROM episodes GROUP BY kind ORDER BY COUNT(*) DESC"
                ).fetchall()
                base["by_kind"] = {str(k or "unknown"): int(n) for k, n in rows}
            except sqlite3.Error as ex:
                base["warning"] = str(ex)
                base["enabled"] = False
        return base

    def contacts_slice(self, *, real_only: bool = False) -> dict[str, Any]:
        """Agregados compatibles con `OperationalMemory.data['contacts']` a partir de episodios.

        Solo cuenta despachos/recall/resupply (voz a un recurso). ASK/NOTIFY no entran en contact_order.
        """
        contacts: dict[str, Any] = {}
        if not self.enabled or self._db is None:
            return {"contacts": contacts, "n_episodes": 0}
        with self._lock:
            try:
                cur = self._db.cursor()
                q = ("SELECT action_id, kind, resource, resource_kind, real, result, fell_back, eta_min "
                     "FROM episodes WHERE resource IS NOT NULL AND resource != ''")
                if real_only:
                    q += " AND real=1"
                rows = cur.execute(q).fetchall()
            except sqlite3.Error:
                return {"contacts": contacts, "n_episodes": 0}
        voice_kinds = {"dispatch", "recall", "resupply"}
        n = 0
        for _aid, kind, resource, resource_kind, real, result, fell_back, eta_min in rows:
            k = str(kind or "").lower()
            if k not in voice_kinds:
                continue
            rid = str(resource)
            n += 1
            rk = str(resource_kind or "unknown")
            c = contacts.setdefault(rid, {"kind": rk, "channels": {}, "lost_min": []})
            if c.get("kind") in (None, "", "unknown") and rk != "unknown":
                c["kind"] = rk
            ch = c["channels"].setdefault("voice", {"sent": 0, "accept": 0, "reject": 0, "no_answer": 0,
                                                    "accept_min": []})
            ch["sent"] += 1
            res = str(result or "").lower()
            if fell_back or res in ("no_answer", "unclear", "missed", "busy", "failed", ""):
                ch["no_answer"] += 1
                c["lost_min"].append(1)
            elif res == "reject":
                ch["reject"] += 1
                c["lost_min"].append(1)
            elif res == "accept":
                ch["accept"] += 1
                try:
                    mins = int(float(eta_min)) if eta_min is not None else 1
                except (TypeError, ValueError):
                    mins = 1
                ch["accept_min"].append(max(1, mins))
            else:
                ch["no_answer"] += 1
                c["lost_min"].append(1)
            _ = real
        return {"contacts": contacts, "n_episodes": n}

    def export_to_memory(self, path: Path | str | None = None, *, real_only: bool = False,
                         merge: bool = True) -> dict[str, Any]:
        """Escribe/mezcla contactos del ledger en `memory.day1.json` (formato OperationalMemory).

        No lanza harness ni aprueba params: solo materia prima para `tuning.propose`.
        """
        from motor.mando.memory import OperationalMemory, DEFAULT_PATH

        out_path = Path(path) if path else DEFAULT_PATH
        slice_ = self.contacts_slice(real_only=real_only)
        part = {"version": 1, "runs": 1 if slice_["n_episodes"] else 0, "minutes_observed": 0,
                "contacts": slice_["contacts"]}
        if merge and out_path.exists():
            try:
                base = OperationalMemory.load(out_path)
            except (OSError, ValueError, KeyError, TypeError):
                base = OperationalMemory()
            merged = OperationalMemory.merge([base.to_dict(), part])
        else:
            merged = OperationalMemory()
            if part["contacts"]:
                merged.data["contacts"] = part["contacts"]
                merged.data["runs"] = max(1, int(part["runs"]))
        source = {"from": "ledger", "ledger_path": str(self.path), "n_episodes": slice_["n_episodes"],
                  "real_only": real_only, "merge": merge}
        saved = merged.save(out_path, source=source)
        return {"ok": True, "path": str(saved), "n_episodes": slice_["n_episodes"],
                "resources": len(slice_["contacts"]), "stats": self.stats()}


def open_ledger(path: Path | str | None = None) -> Ledger:
    return Ledger.open(path)


def main(argv: list[str] | None = None) -> int:
    """CLI: `python -m motor.server.ledger stats|export [--real-only] [--no-merge]`."""
    import argparse
    p = argparse.ArgumentParser(prog="motor.server.ledger", description="Auditoría SQLite local de llamadas")
    p.add_argument("cmd", choices=("stats", "export"), help="stats = totales; export = → memory.day1.json")
    p.add_argument("--path", default="", help="ruta del .sqlite (o MANDO_LEDGER_PATH)")
    p.add_argument("--memory", default="", help="ruta de memory.day1.json")
    p.add_argument("--real-only", action="store_true", help="solo episodios real=1")
    p.add_argument("--no-merge", action="store_true", help="sustituye contactos en vez de sumar")
    args = p.parse_args(argv)
    led = open_ledger(args.path or None)
    if args.cmd == "stats":
        st = led.stats()
        print(json.dumps(st, ensure_ascii=False, indent=2))
        led.close()
        return 0
    out = led.export_to_memory(args.memory or None, real_only=args.real_only, merge=not args.no_merge)
    led.close()
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
