"""Registro acotado y trabajador de recibos. El reloj solo captura y observa; nunca simula."""
from __future__ import annotations

import copy
import threading
from motor.contracts import Action, ActionKind, ActionStatus, Autonomy, Channel
from . import recibo, coordinacion


def action_from_dict(data):
    d = {key: copy.deepcopy(value) for key, value in data.items() if key in Action.__dataclass_fields__}
    d["kind"] = ActionKind(d["kind"])
    d["status"] = ActionStatus(d.get("status", "executing"))
    d["autonomy"] = Autonomy(d.get("autonomy", "auto"))
    if d.get("channel"):
        d["channel"] = Channel(d["channel"])
    return Action(**d)


class ReceiptService:
    def __init__(self):
        self.pending = {}
        self.results = {}
        self.captured = set()
        self.skipped = 0
        self._injections = 0
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._thread = None
        self._closed = threading.Event()

    def capture(self, world, action, *, accepted=True, human=False):
        with self._lock:
            self._effects(world)
            if accepted:
                for row in self.pending.values():
                    if not row.get("ready") and row["action"].id != action.id:
                        row["later"].append({"t": world.t, "action": copy.deepcopy(action)})
            if action.id in self.captured or (not human and str(action.kind) not in recibo.RELEVANT):
                return
            if len(self.captured) >= recibo.MAX_DECISIONS:
                self.skipped += 1
                if not human:
                    return
                # La prioridad depende del orden de captura, NUNCA del tiempo del trabajador.
                victim = next((key for key, row in self.pending.items() if not row["human"]), None)
                if victim is None:
                    return
                self.pending.pop(victim)
                self.results.pop(victim, None)
                self.captured.remove(victim)
            self.captured.add(action.id)
            self.pending[action.id] = {"world": world.clone(), "action": copy.deepcopy(action), "accepted": accepted,
                                       "human": human, "later": [], "frames": []}

    def _effects(self, world):
        for injection in world.injected[self._injections:]:
            if injection["origin"] == "inject":
                for row in self.pending.values():
                    if not row.get("ready"):
                        row["later"].append({"t": injection["t"], "event": copy.deepcopy(injection["effect"])})
        self._injections = len(world.injected)

    def observe(self, world):
        with self._lock:
            self._effects(world)
            frame = None
            for row in self.pending.values():
                if row.get("ready"):
                    continue
                if world.t > row["world"].t:
                    frame = frame or recibo.observe(world)
                    if not row["frames"] or row["frames"][-1]["t"] != frame["t"]:
                        row["frames"].append(frame)
                if world.t >= row["world"].t + recibo.HORIZON or world.done():
                    row["ready"] = True
                    self._wake.set()
            if self._wake.is_set() and self._thread is None:
                self._thread = threading.Thread(target=self._work, name="mando-recibos", daemon=True)
                self._thread.start()

    def _work(self):
        while not self._closed.is_set():
            self._wake.wait(.1)
            with self._lock:
                row = next((r for key, r in self.pending.items() if r.get("ready") and key not in self.results), None)
                if row is None:
                    self._wake.clear()
                    continue
            try:
                result = recibo.calculate(row["world"], row["action"], accepted=row["accepted"],
                                          later=row["later"], observed=row["frames"])
                result["human"] = row["human"]
            except Exception as exc:
                result = {"id": row["action"].id, "incident": row["action"].incident, "N": 1,
                          "verdict": "error", "text": "No se pudo calcular el recibo: " + type(exc).__name__}
            with self._lock:
                if self.pending.get(row["action"].id) is row:
                    self.results[row["action"].id] = result

    def view(self, hidden=()):
        with self._lock:
            items = [copy.deepcopy(row) for row in self.results.values() if row.get("incident") not in hidden]
            pending = len(self.captured) - len(self.results)
        items.sort(key=lambda row: (row.get("t", 0), row["id"]))
        return {"items": items[:recibo.MAX_DECISIONS], "N": len(items), "pending": pending,
                "skipped": self.skipped, "limit": recibo.MAX_DECISIONS, "horizon_min": recibo.HORIZON,
                "note": "Máximo 10 decisiones por informe; se prioriza la supervisión humana. Simulación, no dato de campo."}

    def wait(self, timeout=5):
        import time
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            with self._lock:
                if all(key in self.results for key, r in self.pending.items() if r.get("ready")):
                    return
            self._closed.wait(.01)

    def close(self):
        self._closed.set()
        self._wake.set()
        if self._thread:
            self._thread.join(.3)


def coordination(session, **assumptions):
    with session.lock:
        with session.comms._lock:
            calls = [{key: value for key, value in c.items() if key in ("action_id", "id", "t", "t_end", "channel", "real")}
                     for c in session.comms.calls.values()]
        reports = [{"id": r.id, "t": r.t, "channel": str(r.channel)} for r in session.world.reports if r.id in getattr(session.agent, "_seen_reports", set())]
        return coordinacion.summarize(calls, reports, session.world.t, **assumptions)


def evidence(session, **assumptions):
    with session.lock:
        hidden = {i["id"] for i in session.state().get("incidents", []) if i.get("reserved") or i.get("zone_masked")}
        return {"session_id": session.session_id, "recibos": session.receipts.view(hidden),
                "coordinacion": coordination(session, **assumptions)}
