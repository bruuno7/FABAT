"""Fachada del ledger: misma API, una sola SQLite en ``memoria_db``."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from . import memoria_db, privacy


def default_path() -> Path:
    return memoria_db.ledger_path()


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
        self._store = memoria_db.open_store(self.path)
        self._warn = self._store.warning

    @classmethod
    def open(cls, path: Path | str | None = None) -> "Ledger":
        return cls(Path(path) if path else None)

    @property
    def enabled(self) -> bool:
        return self._store.enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._store.enabled = bool(value)

    @property
    def warning(self) -> str:
        return self._store.warning or self._warn

    def close(self) -> None:
        self._store.release()

    def _exec(self, fn, default=None):
        if not self.enabled:
            return default
        out = self._store.write(fn)
        if not self._store.enabled:
            self._warn = self._store.warning
        return default if out is None and default is not None else out

    def session_start(self, session_id: str, *, case_id: str = "", voice_mode: str = "",
                      speed: float = 1.0, comms_mode: str = "sim") -> None:
        def go(db: sqlite3.Connection) -> None:
            db.execute(
                "INSERT OR REPLACE INTO sessions(session_id, started_at, case_id, voice_mode, speed, comms_mode) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, time.time(), case_id or None, voice_mode or None, float(speed), comms_mode or None),
            )
        self._exec(go)

    def append_event(self, session_id: str, event_type: str, action_id: str | None = None,
                     payload: dict[str, Any] | None = None, *,
                     aviso_id: str | None = None, incidente_id: str | None = None,
                     plan_id: str | None = None, accion_id: str | None = None,
                     llamada_id: str | None = None) -> None:
        body = json.dumps(_scrub_payload(payload), ensure_ascii=False, default=str)
        accion = accion_id or action_id

        def go(db: sqlite3.Connection) -> None:
            db.execute(
                "INSERT INTO events(session_id, ts_unix, event_type, action_id, payload_json, "
                "aviso_id, incidente_id, plan_id, accion_id, llamada_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (session_id, time.time(), event_type, action_id, body,
                 aviso_id, incidente_id, plan_id, accion, llamada_id),
            )
        self._exec(go)

    def upsert_episode(self, session_id: str, action_id: str, *, kind: str = "", zone: str = "",
                       resource: str = "", resource_kind: str = "", real: bool = False,
                       result: str | None = None,
                       eta_min: float | None = None, fell_back: bool = False,
                       answer_ms: float | None = None, hook_rtt_ms: float | None = None,
                       text: str = "", t: int | None = None, seed: int | None = None) -> None:
        if not action_id:
            return

        def go(db: sqlite3.Connection) -> None:
            db.execute(
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
        self._exec(go)

    def save_cerebro_episode(self, session_id: str, episode_id: str, *, tipo: str = "", zona: str = "",
                             franja: str = "", entrada: dict | None = None, contexto: dict | None = None,
                             razonamiento: str = "", decision: dict | None = None, acciones: list | None = None,
                             respuestas: dict | None = None, resultado: dict | None = None,
                             tiempos: dict | None = None, agente: str = "",
                             confianza: float | None = None, supuestos: list | None = None) -> str:
        """Episodio de un agente. Append-only: mismo id se ignora."""
        if not episode_id:
            return episode_id
        entrada = _scrub_payload(entrada)
        contexto = _scrub_payload(contexto)
        decision = _scrub_payload(decision)
        acciones = privacy.scrub(acciones or [])
        respuestas = _scrub_payload(respuestas)
        resultado = _scrub_payload(resultado)
        tiempos = tiempos if isinstance(tiempos, dict) else {}
        supuestos = privacy.scrub(supuestos or [])
        blob = " ".join(str(x) for x in (
            tipo, zona, franja, razonamiento, agente,
            json.dumps(entrada, ensure_ascii=False, default=str),
            json.dumps(decision, ensure_ascii=False, default=str),
            json.dumps(resultado, ensure_ascii=False, default=str),
        )).lower()[:4000]

        def go(db: sqlite3.Connection) -> None:
            db.execute(
                "INSERT OR IGNORE INTO cerebro_episodes(id, session_id, ts_unix, tipo, zona, franja, "
                "entrada_json, contexto_json, razonamiento, decision_json, acciones_json, respuestas_json, "
                "resultado_json, tiempos_json, texto_busqueda, agente, confianza, supuestos_json) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (episode_id, session_id, time.time(), tipo or None, zona or None, franja or None,
                 json.dumps(entrada, ensure_ascii=False, default=str),
                 json.dumps(contexto, ensure_ascii=False, default=str),
                 _truncate_text(razonamiento, 800) or None,
                 json.dumps(decision, ensure_ascii=False, default=str),
                 json.dumps(acciones, ensure_ascii=False, default=str),
                 json.dumps(respuestas, ensure_ascii=False, default=str),
                 json.dumps(resultado, ensure_ascii=False, default=str),
                 json.dumps(tiempos, ensure_ascii=False, default=str),
                 blob, (agente or "")[:40] or None, confianza,
                 json.dumps(supuestos, ensure_ascii=False, default=str)),
            )
        self._exec(go)
        return episode_id

    def search_cerebro(self, *, tipo: str = "", zona: str = "", franja: str = "",
                       texto: str = "", limit: int = 8) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        limit = max(1, min(20, int(limit or 8)))
        clauses, args = ["1=1"], []
        if tipo:
            clauses.append("tipo = ?")
            args.append(tipo)
        if zona:
            clauses.append("zona = ?")
            args.append(zona)
        if franja:
            clauses.append("franja = ?")
            args.append(franja)
        if texto:
            clauses.append("texto_busqueda LIKE ?")
            args.append(f"%{str(texto).lower()[:120]}%")
        args.append(limit)

        def go(db: sqlite3.Connection) -> list:
            return db.execute(
                "SELECT id, session_id, ts_unix, tipo, zona, franja, razonamiento, decision_json, "
                "acciones_json, resultado_json, agente, confianza, supuestos_json FROM cerebro_episodes WHERE "
                + " AND ".join(clauses) + " ORDER BY ts_unix DESC LIMIT ?",
                args,
            ).fetchall()

        rows = self._exec(go, default=[]) or []
        out = []
        for row in rows:
            try:
                decision = json.loads(row[7] or "{}")
            except ValueError:
                decision = {}
            try:
                acciones = json.loads(row[8] or "[]")
            except ValueError:
                acciones = []
            try:
                resultado = json.loads(row[9] or "{}")
            except ValueError:
                resultado = {}
            try:
                supuestos = json.loads(row[12] or "[]") if len(row) > 12 else []
            except ValueError:
                supuestos = []
            out.append({
                "id": row[0], "tipo": row[3], "zona": row[4], "franja": row[5],
                "razonamiento": row[6], "decision": decision, "acciones": acciones, "resultado": resultado,
                "agente": row[10] if len(row) > 10 else None,
                "confianza": row[11] if len(row) > 11 else None,
                "supuestos": supuestos,
                "que_se_hizo": (decision.get("porque") if isinstance(decision, dict) else None) or row[6] or "",
                "como_acabo": resultado.get("texto") if isinstance(resultado, dict) else "",
            })
        return out

    def get_cerebro_episode(self, episode_id: str) -> dict[str, Any] | None:
        if not self.enabled or not episode_id:
            return None

        def go(db: sqlite3.Connection):
            return db.execute(
                "SELECT id, session_id, tipo, zona, franja, entrada_json, contexto_json, razonamiento, "
                "decision_json, acciones_json, resultado_json, tiempos_json, agente, confianza, supuestos_json "
                "FROM cerebro_episodes WHERE id = ?",
                (episode_id,),
            ).fetchone()

        row = self._exec(go)
        if not row:
            return None

        def js(idx: int, default: str) -> Any:
            try:
                return json.loads(row[idx] or default)
            except ValueError:
                return json.loads(default)

        return {
            "id": row[0], "session_id": row[1], "tipo": row[2], "zona": row[3], "franja": row[4],
            "entrada": js(5, "{}"), "contexto": js(6, "{}"), "razonamiento": row[7],
            "decision": js(8, "{}"), "acciones": js(9, "[]"), "resultado": js(10, "{}"),
            "tiempos": js(11, "{}"), "agente": row[12], "confianza": row[13], "supuestos": js(14, "[]"),
        }

    def list_cerebro_episodes(self, *, session_id: str = "", limit: int = 40) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        limit = max(1, min(80, int(limit or 40)))

        def go(db: sqlite3.Connection) -> list:
            if session_id:
                return db.execute(
                    "SELECT id FROM cerebro_episodes WHERE session_id = ? ORDER BY ts_unix DESC LIMIT ?",
                    (session_id, limit),
                ).fetchall()
            return db.execute(
                "SELECT id FROM cerebro_episodes ORDER BY ts_unix DESC LIMIT ?", (limit,),
            ).fetchall()

        rows = self._exec(go, default=[]) or []
        out = []
        for row in rows:
            ep = self.get_cerebro_episode(row[0])
            if ep:
                out.append(ep)
        return out

    def upsert_leccion(self, lesson_id: str, texto: str, *, evidencia: dict | None = None,
                       estado: str = "propuesta", tipo: str = "", zona: str = "", by: str = "",
                       n: int = 0, para_agente: str = "") -> dict[str, Any]:
        if not lesson_id:
            return {"id": lesson_id, "ok": False, "enabled": self.enabled}
        estado = estado if estado in ("propuesta", "aprobada", "rechazada", "revocada") else "propuesta"
        evidencia = _scrub_payload(evidencia)
        n = int(evidencia.get("n") or n or 0) if isinstance(evidencia, dict) else int(n or 0)
        dest = (para_agente or "").strip().lower()[:40] or None

        def go(db: sqlite3.Connection) -> dict[str, Any]:
            db.execute(
                "INSERT INTO cerebro_lecciones(id, ts_unix, texto, evidencia_json, estado, tipo, zona, by_who, n, "
                "para_agente, revocada) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0) "
                "ON CONFLICT(id) DO UPDATE SET texto=excluded.texto, evidencia_json=excluded.evidencia_json, "
                "estado=excluded.estado, tipo=COALESCE(excluded.tipo, cerebro_lecciones.tipo), "
                "zona=COALESCE(excluded.zona, cerebro_lecciones.zona), by_who=excluded.by_who, n=excluded.n, "
                "para_agente=COALESCE(excluded.para_agente, cerebro_lecciones.para_agente)",
                (lesson_id, time.time(), _truncate_text(texto, 400),
                 json.dumps(evidencia, ensure_ascii=False, default=str), estado,
                 tipo or None, zona or None, (by or "")[:40] or None, n, dest),
            )
            return {"id": lesson_id, "ok": True, "estado": estado, "n": n, "para_agente": dest}

        out = self._exec(go)
        if not out:
            return {"id": lesson_id, "ok": False, "enabled": self.enabled}
        return out

    def list_lecciones(self, *, estado: str | None = None, tipo: str = "", zona: str = "",
                       limit: int = 20, para_agente: str | None = None,
                       incluir_globales: bool = True) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        clauses, args = [], []
        if estado:
            clauses.append("estado = ?")
            args.append(estado)
        if estado != "revocada":
            clauses.append("COALESCE(revocada, 0) = 0")
        if not clauses:
            clauses.append("1=1")
        if tipo:
            clauses.append("(tipo IS NULL OR tipo = '' OR tipo = ?)")
            args.append(tipo)
        if zona:
            clauses.append("(zona IS NULL OR zona = '' OR zona = ?)")
            args.append(zona)
        dest = (para_agente or "").strip().lower()
        if dest:
            if incluir_globales:
                clauses.append("(para_agente IS NULL OR para_agente = '' OR para_agente = ?)")
            else:
                clauses.append("para_agente = ?")
            args.append(dest)
        args.append(max(1, min(50, int(limit or 20))))

        def go(db: sqlite3.Connection) -> list:
            return db.execute(
                "SELECT id, ts_unix, texto, evidencia_json, estado, tipo, zona, by_who, n, para_agente "
                "FROM cerebro_lecciones WHERE " + " AND ".join(clauses) + " ORDER BY ts_unix DESC LIMIT ?",
                args,
            ).fetchall()

        rows = self._exec(go, default=[]) or []
        out = []
        for row in rows:
            try:
                evidencia = json.loads(row[3] or "{}")
            except ValueError:
                evidencia = {}
            out.append({"id": row[0], "texto": row[2], "evidencia": evidencia, "estado": row[4],
                        "tipo": row[5], "zona": row[6], "by": row[7], "n": row[8],
                        "para_agente": row[9] if len(row) > 9 else None})
        return out

    def decide_leccion(self, lesson_id: str, approve: bool, by: str = "",
                       revocar: bool = False) -> dict[str, Any] | None:
        def go(db: sqlite3.Connection) -> dict[str, Any] | None:
            row = db.execute(
                "SELECT id, texto, evidencia_json, estado, tipo, zona, n, para_agente FROM cerebro_lecciones WHERE id = ?",
                (lesson_id,),
            ).fetchone()
            if row is None:
                return None
            if revocar:
                estado, flag = "revocada", 1
            else:
                estado, flag = ("aprobada" if approve else "rechazada"), 0
            db.execute(
                "UPDATE cerebro_lecciones SET estado = ?, by_who = ?, revocada = ? WHERE id = ?",
                (estado, (by or "")[:40] or None, flag, lesson_id),
            )
            try:
                evidencia = json.loads(row[2] or "{}")
            except ValueError:
                evidencia = {}
            return {"id": row[0], "texto": row[1], "evidencia": evidencia, "estado": estado,
                    "tipo": row[4], "zona": row[5], "n": row[6],
                    "para_agente": row[7] if len(row) > 7 else None, "ok": True}

        return self._exec(go)

    def save_pizarra(self, mid: str, *, de: str, para: str, incidente: str = "", tipo: str = "",
                     texto: str = "", datos: dict | None = None, confianza: float | None = None,
                     enlaza: str = "", gravedad: str = "", session_id: str = "",
                     ts_unix: float | None = None) -> dict[str, Any]:
        datos = _scrub_payload(datos)
        ts = float(ts_unix if ts_unix is not None else time.time())

        def go(db: sqlite3.Connection) -> dict[str, Any]:
            db.execute(
                "INSERT INTO pizarra(id, ts_unix, session_id, de, para, incidente, tipo, texto, datos_json, "
                "confianza, enlaza, gravedad, resuelta) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0)",
                (mid, ts, session_id or None, de, para, incidente or None, tipo,
                 _truncate_text(texto, 400) or None,
                 json.dumps(datos, ensure_ascii=False, default=str), confianza,
                 enlaza or None, gravedad or None),
            )
            return {"id": mid, "ok": True}

        return self._exec(go) or {"id": mid, "ok": False}

    def leer_pizarra(self, *, incidente: str = "", para: str = "", limit: int = 50,
                     enlaza: str = "") -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        clauses, args = ["1=1"], []
        if incidente:
            clauses.append("(incidente IS NULL OR incidente = '' OR incidente = ?)")
            args.append(incidente)
        if enlaza:
            clauses.append("enlaza = ?")
            args.append(enlaza)
        args.append(max(1, min(200, int(limit or 50))))

        def go(db: sqlite3.Connection) -> list:
            return db.execute(
                "SELECT id, ts_unix, de, para, incidente, tipo, texto, datos_json, confianza, enlaza, "
                "gravedad, resuelta FROM pizarra WHERE " + " AND ".join(clauses) +
                " ORDER BY ts_unix DESC LIMIT ?",
                args,
            ).fetchall()

        rows = self._exec(go, default=[]) or []
        out = []
        for row in rows:
            try:
                datos = json.loads(row[7] or "{}")
            except ValueError:
                datos = {}
            item = {"id": row[0], "ts": row[1], "de": row[2], "para": row[3], "incidente": row[4],
                    "tipo": row[5], "texto": row[6], "datos": datos, "confianza": row[8],
                    "enlaza": row[9], "gravedad": row[10], "resuelta": bool(row[11])}
            out.append(item)
        dest = (para or "").strip().lower()
        if dest and dest != "todos":
            def _rank(m: dict[str, Any]) -> int:
                d = str(m.get("para") or "").lower()
                if d == dest:
                    return 0
                if d in ("todos", ""):
                    return 1
                return 2
            out.sort(key=lambda m: (_rank(m), -float(m.get("ts") or 0)))
        return out

    def resolver_pizarra(self, mid: str) -> None:
        def go(db: sqlite3.Connection) -> None:
            db.execute("UPDATE pizarra SET resuelta = 1 WHERE id = ?", (mid,))
        self._exec(go)

    def confianza_get(self, agente: str, familia: str = "") -> dict[str, Any] | None:
        if not self.enabled:
            return None

        def go(db: sqlite3.Connection) -> Any:
            if familia:
                return db.execute(
                    "SELECT agente, familia, aciertos, n, puntuacion, tendencia FROM agente_confianza "
                    "WHERE agente = ? AND familia = ?", (agente, familia)).fetchone()
            return db.execute(
                "SELECT agente, familia, aciertos, n, puntuacion, tendencia FROM agente_confianza "
                "WHERE agente = ?", (agente,)).fetchall()

        return self._exec(go)

    def confianza_todas(self) -> list[dict[str, Any]]:
        if not self.enabled:
            return []

        def go(db: sqlite3.Connection) -> list:
            return db.execute(
                "SELECT agente, familia, aciertos, n, puntuacion, tendencia FROM agente_confianza "
                "ORDER BY agente, familia").fetchall()

        rows = self._exec(go, default=[]) or []
        return [{"agente": r[0], "familia": r[1], "aciertos": r[2], "n": r[3],
                 "puntuacion": r[4], "tendencia": r[5]} for r in rows]

    def confianza_put(self, agente: str, familia: str, aciertos: float, n: int,
                      puntuacion: float, tendencia: str = "") -> None:
        def go(db: sqlite3.Connection) -> None:
            db.execute(
                "INSERT INTO agente_confianza(agente, familia, aciertos, n, puntuacion, tendencia, ts_unix) "
                "VALUES (?,?,?,?,?,?,?) ON CONFLICT(agente, familia) DO UPDATE SET "
                "aciertos=excluded.aciertos, n=excluded.n, puntuacion=excluded.puntuacion, "
                "tendencia=excluded.tendencia, ts_unix=excluded.ts_unix",
                (agente, familia, float(aciertos), int(n), float(puntuacion), tendencia or None, time.time()),
            )
        self._exec(go)

    def adaptacion_append(self, eid: str, *, clase: str, valor: str = "", porque: str = "",
                          datos: dict | None = None, session_id: str = "") -> None:
        datos = _scrub_payload(datos)

        def go(db: sqlite3.Connection) -> None:
            db.execute(
                "INSERT OR REPLACE INTO adaptacion_eventos(id, ts_unix, session_id, clase, valor, porque, datos_json) "
                "VALUES (?,?,?,?,?,?,?)",
                (eid, time.time(), session_id or None, clase, valor or None,
                 _truncate_text(porque, 400) or None,
                 json.dumps(datos, ensure_ascii=False, default=str)),
            )
        self._exec(go)

    def adaptacion_list(self, *, clase: str = "", limit: int = 40) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        clauses, args = ["1=1"], []
        if clase:
            clauses.append("clase = ?")
            args.append(clase)
        args.append(max(1, min(100, int(limit or 40))))

        def go(db: sqlite3.Connection) -> list:
            return db.execute(
                "SELECT id, ts_unix, clase, valor, porque, datos_json FROM adaptacion_eventos WHERE "
                + " AND ".join(clauses) + " ORDER BY ts_unix DESC LIMIT ?", args).fetchall()

        rows = self._exec(go, default=[]) or []
        out = []
        for row in rows:
            try:
                datos = json.loads(row[5] or "{}")
            except ValueError:
                datos = {}
            out.append({"id": row[0], "ts": row[1], "clase": row[2], "valor": row[3],
                        "porque": row[4], "datos": datos})
        return out

    def prompt_proponer(self, pid: str, agente: str, cuerpo: str, *, version: int = 0,
                        diff: str = "", evidencia: dict | None = None, n: int = 0,
                        sustituye: str = "") -> dict[str, Any]:
        evidencia = _scrub_payload(evidencia)

        def go(db: sqlite3.Connection) -> dict[str, Any]:
            ver = version
            if not ver:
                row = db.execute("SELECT COALESCE(MAX(version), 0) FROM prompt_versiones WHERE agente = ?",
                                 (agente,)).fetchone()
                ver = int(row[0] or 0) + 1
            db.execute(
                "INSERT INTO prompt_versiones(id, agente, version, cuerpo, diff, evidencia_json, n, estado, "
                "activa, by_who, ts_unix, sustituye) VALUES (?,?,?,?,?,?,?,'propuesta',0,NULL,?,?)",
                (pid, agente, ver, cuerpo, diff or None,
                 json.dumps(evidencia, ensure_ascii=False, default=str), int(n), time.time(),
                 sustituye or None),
            )
            return {"id": pid, "ok": True, "estado": "propuesta", "version": ver, "agente": agente}

        return self._exec(go) or {"id": pid, "ok": False}

    def prompt_decidir(self, pid: str, *, aprobar: bool, by: str = "", activar: bool = True) -> dict[str, Any] | None:
        def go(db: sqlite3.Connection) -> dict[str, Any] | None:
            row = db.execute("SELECT id, agente, version, estado, sustituye FROM prompt_versiones WHERE id = ?",
                             (pid,)).fetchone()
            if row is None:
                return None
            estado = "aprobada" if aprobar else "rechazada"
            db.execute("UPDATE prompt_versiones SET estado = ?, by_who = ? WHERE id = ?",
                       (estado, (by or "")[:40] or None, pid))
            if aprobar and activar:
                db.execute("UPDATE prompt_versiones SET activa = 0 WHERE agente = ?", (row[1],))
                db.execute("UPDATE prompt_versiones SET activa = 1 WHERE id = ?", (pid,))
            return {"id": pid, "ok": True, "estado": estado, "agente": row[1], "version": row[2],
                    "activa": bool(aprobar and activar)}

        return self._exec(go)

    def prompt_revertir(self, agente: str, *, by: str = "") -> dict[str, Any] | None:
        def go(db: sqlite3.Connection) -> dict[str, Any] | None:
            actual = db.execute(
                "SELECT id, version FROM prompt_versiones WHERE agente = ? AND activa = 1",
                (agente,)).fetchone()
            if actual is None:
                return None
            prev = db.execute(
                "SELECT id, version FROM prompt_versiones WHERE agente = ? AND estado = 'aprobada' "
                "AND id != ? ORDER BY version DESC LIMIT 1", (agente, actual[0])).fetchone()
            db.execute("UPDATE prompt_versiones SET activa = 0, estado = 'revertida', by_who = ? WHERE id = ?",
                       ((by or "")[:40] or None, actual[0]))
            if prev is None:
                return {"id": actual[0], "ok": True, "activa": None, "agente": agente,
                        "texto": "sin versión anterior; se vuelve al fichero"}
            db.execute("UPDATE prompt_versiones SET activa = 1 WHERE id = ?", (prev[0],))
            return {"id": prev[0], "ok": True, "activa": prev[0], "agente": agente, "version": prev[1]}

        return self._exec(go)

    def prompt_activo(self, agente: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None

        def go(db: sqlite3.Connection) -> Any:
            return db.execute(
                "SELECT id, agente, version, cuerpo, estado, n FROM prompt_versiones "
                "WHERE agente = ? AND activa = 1 AND estado = 'aprobada' LIMIT 1",
                (agente,)).fetchone()

        row = self._exec(go)
        if not row:
            return None
        return {"id": row[0], "agente": row[1], "version": row[2], "cuerpo": row[3],
                "estado": row[4], "n": row[5]}

    def prompt_listar(self, agente: str = "") -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        clauses, args = ["1=1"], []
        if agente:
            clauses.append("agente = ?")
            args.append(agente)

        def go(db: sqlite3.Connection) -> list:
            return db.execute(
                "SELECT id, agente, version, diff, n, estado, activa, by_who, ts_unix FROM prompt_versiones WHERE "
                + " AND ".join(clauses) + " ORDER BY agente, version DESC", args).fetchall()

        rows = self._exec(go, default=[]) or []
        return [{"id": r[0], "agente": r[1], "version": r[2], "diff": r[3], "n": r[4],
                 "estado": r[5], "activa": bool(r[6]), "by": r[7], "ts": r[8]} for r in rows]

    def aporte_get(self, agente: str, familia: str) -> tuple[int, int]:
        def go(db: sqlite3.Connection) -> Any:
            return db.execute(
                "SELECT n, cambios FROM especialista_aporte WHERE agente = ? AND familia = ?",
                (agente, familia)).fetchone()
        row = self._exec(go)
        return (int(row[0]), int(row[1])) if row else (0, 0)

    def aporte_put(self, agente: str, familia: str, n: int, cambios: int) -> None:
        def go(db: sqlite3.Connection) -> None:
            db.execute(
                "INSERT INTO especialista_aporte(agente, familia, n, cambios) VALUES (?,?,?,?) "
                "ON CONFLICT(agente, familia) DO UPDATE SET n=excluded.n, cambios=excluded.cambios",
                (agente, familia, int(n), int(cambios)))
        self._exec(go)

    def stats(self) -> dict[str, Any]:
        base: dict[str, Any] = {
            "enabled": self.enabled,
            "path": str(self.path),
            "warning": self.warning or None,
            "sessions": 0,
            "events": 0,
            "episodes": 0,
            "real_ok": 0,
            "fallbacks": 0,
            "by_kind": {},
        }
        if not self.enabled:
            return base

        def go(db: sqlite3.Connection) -> dict[str, Any]:
            cur = db.cursor()
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
            return base

        return self._exec(go, default=base) or base

    def contacts_slice(self, *, real_only: bool = False) -> dict[str, Any]:
        contacts: dict[str, Any] = {}
        if not self.enabled:
            return {"contacts": contacts, "n_episodes": 0}

        def go(db: sqlite3.Connection) -> list:
            q = ("SELECT action_id, kind, resource, resource_kind, real, result, fell_back, eta_min "
                 "FROM episodes WHERE resource IS NOT NULL AND resource != ''")
            if real_only:
                q += " AND real=1"
            return db.execute(q).fetchall()

        rows = self._exec(go, default=[]) or []
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
    import argparse
    p = argparse.ArgumentParser(prog="motor.server.ledger", description="Auditoría SQLite local de llamadas")
    p.add_argument("cmd", choices=("stats", "export"), help="stats = totales; export = → memory.day1.json")
    p.add_argument("--path", default="", help="ruta del .sqlite (o MANDO_DB / MANDO_LEDGER_PATH)")
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
