"""Ataques de Caos al plan actual, aislados de la partida y de comunicaciones reales.

N son extracciones del catálogo contra UN estado, no N eventos de campo. Dos
ramas por ataque (sin/con golpe), operador del harness. CPU cooperativa acotada.
"""
from __future__ import annotations

import copy
import hashlib
import json
import random
import statistics
import threading
import time
from pathlib import Path
from typing import Any

from motor.caos.chaos import catalogue
from motor.contracts import ActionStatus
from motor.harness.metrics import score
from motor.harness.runner import SimOperator, code_fingerprint, needs_approval
from motor.world import SimComms
from .views import Humanizer

HORIZON = 15


def clone_pair(world: Any, agent: Any) -> tuple[Any, Any]:
    w = world.twin()
    comms = SimComms(w, world.seed)
    source_sim = getattr(agent.comms, "sim", agent.comms)
    if isinstance(source_sim, SimComms):
        comms.rng.setstate(source_sim.rng.getstate())
        comms._pending = copy.deepcopy(source_sim._pending)
    memo = {id(world): w, id(agent.comms): comms}
    for key, action in world.live.items():
        if key in w.live:
            memo[id(action)] = w.live[key]
    ag = copy.deepcopy(agent, memo)
    if hasattr(ag, "triage"):
        ag.triage.new_id = lambda: ag.new_id("M")
    if hasattr(ag, "rehearsal"):
        ag.rehearsal.twin = w.twin
    return w, ag


def _checkpoint(world, agent):
    text = json.dumps({"world": world.truth(), "agent": agent.snapshot()}, sort_keys=True, default=str)
    return hashlib.sha256(text.encode()).hexdigest()


def _restore(recipe):
    from .app import Session
    from motor.mando import Mando
    from motor.mando.playbook import Playbook
    from motor.mando.tuning import Params
    session = Session(recipe["case"], seed=recipe["seed"], threaded=False, playbook="seed", local_params=False,
                      replay={"n": 0, "author": "simulacro", "before": {}, "inputs": recipe["inputs"]})
    session.comms.external_ask = None
    session.replay_result = {"snapshot_replay": True}  # reconstruir, no sobrescribir otro test al llegar al final
    session.agent = Mando(playbook=Playbook(recipe["lessons"]), comms=session.comms, twin=lambda: session.world.twin(),
                          params=Params.from_dict(recipe["params"]) if recipe.get("params") else None)
    session._rebuild()
    try:
        while session.world.t < recipe["t"]:
            if session.world.done():
                raise ValueError("El estado guardado está fuera de la duración del caso")
            session.tick()
        session._apply_replay()
        w, ag = clone_pair(session.world, session.agent)
        return w, ag
    finally:
        session.close()


class _Stopped(Exception):
    pass


class Budget:
    def __init__(self, cancel: threading.Event, wall: float = 60, cpu: float = 12):
        self.cancel = cancel
        self.wall = min(60., max(.001, wall))
        self.cpu = min(12., max(.001, cpu))
        self.started, self.cpu_start = time.monotonic(), time.thread_time()

    def check(self):
        used = time.thread_time() - self.cpu_start
        elapsed = time.monotonic() - self.started
        if self.cancel.is_set() or elapsed >= self.wall or used >= self.cpu:
            raise _Stopped()
        # Máximo promedio 25 % de un núcleo; cede también entre ticks del ensayo.
        wait = min(max(0., used * 4 - elapsed), .1, self.wall - elapsed)
        if wait:
            self.cancel.wait(wait)
        if self.cancel.is_set() or time.monotonic() - self.started >= self.wall:
            raise _Stopped()


def _branch(world, agent, effect=None, check=lambda: None):
    w, ag = clone_pair(world, agent)
    start = w.t
    initial = ag.snapshot()
    initial_plans = {p["id"] for p in initial.get("plans", []) if not p.get("invalidated_by")}
    initial_breaks = {e.get("ref") for e in initial.get("log", []) if e.get("kind") == "assumption_broken"}
    initial_over = sum(w.over5)
    operator = SimOperator()
    operator.start({}, w.seed)
    operator.see_reports(w.reports)
    for action in getattr(ag, "actions", {}).values():
        if action.status == ActionStatus.AWAITING_APPROVAL:
            operator.enqueue(action, w.t)
    if effect:
        w.inject(copy.deepcopy(effect))
    applied, decisions, frames = [], [], []
    for _ in range(HORIZON):
        check()
        obs = w.observe()
        operator.see_reports(obs.new_reports)
        before = len(operator.approved), len(operator.vetoed)
        operator.decide(w.t, w, ag)
        decisions += [{"t": w.t, "kind": "approve", "action_id": aid, "ok": True, "note": "operador simulado"}
                      for aid in operator.approved[before[0]:]]
        decisions += [{"t": w.t, "kind": "approve", "action_id": r["id"], "ok": False, "note": r["note"]}
                      for r in operator.vetoed[before[1]:]]
        for a in ag.tick(obs):
            if a.status == ActionStatus.AWAITING_APPROVAL:
                operator.enqueue(a, w.t)
            elif not needs_approval(a.kind, a.params) or a.id in operator.approved:
                applied.append({**a.to_dict(), "t": w.t, "approved": a.id in operator.approved})
                w.apply(a)
        w.step()
        snap = ag.snapshot()
        broken = {p["id"] for p in snap.get("plans", []) if p["id"] in initial_plans and p.get("invalidated_by")}
        replacements = [p for p in snap.get("plans", []) if p.get("supersedes") in broken and not p.get("invalidated_by")]
        executing = {a["id"] for a in snap.get("actions", []) if a.get("status") in ("executing", "done")}
        covered = {p["supersedes"] for p in replacements if any(s in executing for s in p.get("steps", []))}
        frames.append({"minute": w.t - start, "broken": sorted(broken), "covered": sorted(covered),
                       "plans": [{"id": p["id"], "objective": p["objective"] + ": " + "; ".join(
                           a.get("why") or (str(a["kind"]) + " " + str(a.get("resource") or a.get("zone") or ""))
                           for a in snap.get("actions", []) if a["id"] in p.get("steps", [])
                           and a.get("status") in ("executing", "done")), "supersedes": p.get("supersedes")}
                                 for p in replacements]})
    snap = ag.snapshot()
    metrics = score(w.truth(), snap, extras={"applied": applied})
    breaks = {e.get("ref") for e in snap.get("log", []) if e.get("kind") == "assumption_broken"} - initial_breaks
    return {"metrics": metrics, "over5": sum(w.over5) - initial_over, "breaks": sorted(breaks),
            "frames": frames, "decisions": decisions}


def trial(world, agent, effect, *, baseline=None, check=lambda: None):
    base = baseline if baseline is not None else _branch(world, agent, check=check)
    hit = _branch(world, agent, effect, check)
    extra = sorted(set(hit["breaks"]) - set(base["breaks"]))
    extra_critical = max(0, hit["metrics"]["critical_failed"] - base["metrics"]["critical_failed"])
    extra_over = max(0, hit["over5"] - base["over5"])
    broken = bool(extra or extra_critical or extra_over)
    base_broken = {p for f in base["frames"] for p in f["broken"]}
    affected = {p for f in hit["frames"] for p in f["broken"]} - base_broken
    first = next((f for f in hit["frames"] if affected.intersection(f["broken"])), None)
    recovered = next((f for f in hit["frames"] if first and f["minute"] >= first["minute"]
                      and affected <= set(f["covered"])), None)
    names = {z.id: z.name for z in world.observe().zones.values()}
    human = Humanizer(names, {r.id: r.name for r in world.observe().resources.values()})
    plans = list(dict.fromkeys(human(p["objective"]) for f in hit["frames"] for p in f["plans"] if p["supersedes"] in affected and not p["objective"].endswith(": ")))
    return {"broken": broken, "extra_breaks": len(extra), "extra_critical_failed": extra_critical,
            "extra_minutes_over5": extra_over,
            "recovery_min": recovered["minute"] - first["minute"] if recovered and first else None,
            "plans": plans[:3], "error": None, "metrics": hit["metrics"], "decisions": hit["decisions"]}


def summarize(rows: list[dict]) -> dict:
    groups, zones, resources = {}, {}, {}
    n = len(rows)
    for row in rows:
        effect = row.get("effect", {})
        target = effect.get("zone") or effect.get("incident", {}).get("zone") or effect.get("resource") or effect.get("channel") or "recinto"
        variant = ":" + ("wind" if "wind_kmh" in effect else "heat") if effect.get("kind") == "weather" else ""
        if effect.get("kind") == "incident":
            variant = ":" + effect.get("incident", {}).get("type", "")
        key = f"{effect.get('kind')}:{target}{variant}"
        group = groups.setdefault(key, {"key": key, "label": row.get("label", key), "N": n,
                  "exposed_N": 0, "failures": 0, "recoveries": [], "censored_N": 0, "plans": [], "example": None})
        group["exposed_N"] += 1
        if not row.get("broken"):
            continue
        group["failures"] += 1
        group["example"] = row["index"] if group["example"] is None else group["example"]
        if row.get("recovery_min") is not None:
            group["recoveries"].append(row["recovery_min"])
        else:
            group["censored_N"] += 1
        for plan in row.get("plans", []):
            if plan not in group["plans"]:
                group["plans"].append(plan)
        for field, dest in (("zone", zones), ("resource", resources)):
            location = effect.get(field) or (effect.get("incident", {}).get("zone") if field == "zone" else None)
            if location:
                dest[location] = dest.get(location, 0) + 1
    weak = []
    for g in groups.values():
        if not g["failures"]:
            continue
        values = g.pop("recoveries")
        g.update(percent=round(100 * g["failures"] / n, 1) if n else 0,
                 recovery_median_min=statistics.median(values) if values else None, recovery_N=len(values))
        weak.append(g)
    weak.sort(key=lambda g: (-g["failures"], g["key"]))
    return {"N": n, "errors": sum(bool(r.get("error")) for r in rows), "failures": sum(r.get("broken") is True for r in rows),
            "weaknesses": weak[:5], "zones": zones, "resources": resources}


class SimulacroService:
    def __init__(self):
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._thread = None
        self._state = {"status": "idle", "requested_N": 0, "N": 0, "rows": [], **summarize([])}
        self._recipe = None

    def start(self, session, *, n=200, seed=1, wall_limit=60):
        if type(n) is not int or n not in (50, 200, 500) or type(seed) is not int or not 0 <= seed <= 2**31 - 1:
            raise ValueError("N debe ser 50, 200 o 500; semilla entera entre 0 y 2147483647")
        with self._lock:
            if self._thread and self._thread.is_alive():
                raise ValueError("Ya hay un simulacro en curso")
            with session.lock:
                if session.agent_kind != "mando" or not hasattr(session.agent, "playbook"):
                    raise ValueError("El simulacro requiere el planificador Mando")
                w, ag = clone_pair(session.world, session.agent)
                self._recipe = {"case": copy.deepcopy(session.case), "seed": session.seed,
                                "playbook": session.playbook_choice, "inputs": copy.deepcopy(session.inputs),
                                "t": session.world.t, "checkpoint": _checkpoint(w, ag), "params": (session.agent.params.to_dict() if getattr(session.agent, "params", None) else None),
                                "lessons": copy.deepcopy(getattr(session.agent.playbook, "lessons", []))}
                session_id = session.session_id
            self._cancel = threading.Event()
            self._state = {"status": "running", "requested_N": n, "seed": seed, "t": w.t, "session_id": session_id,
                           "case": w.case_id, "code": code_fingerprint(), "rows": [], **summarize([]),
                           "note": "Simulación de un estado del plan. N = ataques muestreados de Caos; no casos independientes. "
                                   "Rotura = supuesto adicional roto, crítico adicional fallido o más minutos-zona >5/m² que sin golpe. "
                                   "Recuperación = plan sustituto en ejecución, no resolución del incidente. Horizonte 15 min. "
                                   "Operador y comunicaciones simulados; sin sucesos futuros del guion. Tope 60 s / 12 s CPU."}
            self._thread = threading.Thread(target=self._run, args=(w, ag, n, seed, wall_limit), daemon=True, name="mando-simulacro")
            self._thread.start()
            return self.status()

    def _run(self, w, ag, n, seed, wall_limit):
        budget = Budget(self._cancel, wall=wall_limit)
        rng = random.Random(seed)
        rows = []
        status = "completed"
        try:
            candidates = catalogue(w, ag.snapshot())
            names = Humanizer({z.id: z.name for z in w.observe().zones.values()}, {r.id: r.name for r in w.observe().resources.values()})
            baseline = _branch(w, ag, check=budget.check)
            for index in range(n):
                budget.check()
                chosen = copy.deepcopy(rng.choice(candidates))
                effect = chosen["effect"]
                if "per_min" in effect:
                    effect["per_min"] = rng.choice((180, 260, 340))
                row = {"index": index, "effect": effect, "label": names(chosen["label"])}
                try:
                    row.update(trial(w, ag, effect, baseline=baseline, check=budget.check))
                except _Stopped:
                    raise
                except Exception as exc:
                    row.update(broken=None, error=type(exc).__name__, recovery_min=None, plans=[])
                rows.append(row)
                with self._lock:
                    self._state.update(summarize(rows), rows=copy.deepcopy(rows))
        except _Stopped:
            status = "cancelled" if self._cancel.is_set() else "limited"
        except Exception as exc:
            status = "error"
            with self._lock:
                self._state["error"] = type(exc).__name__
        with self._lock:
            self._state.update(status=status, elapsed_s=round(time.monotonic()-budget.started, 3),
                               cpu_s=round(time.thread_time()-budget.cpu_start, 3))

    def status(self):
        with self._lock:
            return copy.deepcopy(self._state)

    def cancel(self):
        self._cancel.set()
        return self.status()

    def join(self, timeout=1):
        if self._thread:
            self._thread.join(timeout)

    def close(self):
        self.cancel()
        self.join(1)

    def lock_test(self, index, author="operador", note=""):
        from . import regression_live
        with self._lock:
            row = next((r for r in self._state["rows"] if r["index"] == index), None)
            if not row or not row.get("broken"):
                raise ValueError("Elige un ataque terminado que haya roto el plan")
            recipe = copy.deepcopy(self._recipe)
            restored_world, restored_agent = _restore(recipe)
            if _checkpoint(restored_world, restored_agent) != recipe["checkpoint"]:
                raise ValueError("No se puede bloquear: las entradas guardadas no reproducen este estado del plan. "
                                 "Repite en una sesión simulada reproducible.")
            rec = regression_live.lock(case=recipe["case"], seed=recipe["seed"], playbook=recipe["playbook"],
                                       inputs=recipe["inputs"], metrics=row["metrics"], author=author, t=recipe["t"], note=note)
            path = regression_live.DIR / f"test-{rec['n']:03d}.json"
            saved = json.loads(path.read_text())
            saved["simulacro"] = {**recipe, "effect": row["effect"], "code": self._state["code"], "N": 1,
                                  "before_broken": True, "sampling_seed": self._state["seed"]}
            saved["limits"]["max_plan_breaks"] = 0
            path.write_text(json.dumps(saved, ensure_ascii=False, indent=1), encoding="utf-8")
            return {"ok": True, "n": rec["n"], "author": rec["author"], "simulacro": True}


def run_locked(rec):
    """Recrea el prefijo observado y reensaya el golpe; no sustituye la partida viva."""
    from . import regression_live
    recipe = rec["simulacro"]
    w, ag = _restore(recipe)
    if recipe["code"] == code_fingerprint() and _checkpoint(w, ag) != recipe["checkpoint"]:
        raise ValueError("El prefijo guardado ya no reproduce el estado del plan")
    row = trial(w, ag, recipe["effect"])
    result = {"passed": not row["broken"], "plan_breaks": int(row["broken"]), "N": 1,
              "critical_failed": row["metrics"]["critical_failed"], "unsafe_actions": row["metrics"]["unsafe_actions"]}
    rec["last_run"] = result
    path = regression_live.DIR / f"test-{rec['n']:03d}.json"
    path.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"ok": True, "simulacro": True, "result": result, "n": rec["n"]}
