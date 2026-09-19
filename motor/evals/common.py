"""Tipos, carga de casos y bucle de simulación para las evals. Solo biblioteca estándar."""
from __future__ import annotations

import json
import os
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from motor.contracts import ActionKind, ActionStatus, ResourceStatus
from motor.world import SimComms, World

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
CASES = ROOT / "motor" / "cases" / "data"
HELDOUT_SEED = 1
RESERVED_TYPES = frozenset({
    "bomb_threat_call", "chemical_submission", "lost_child", "sexual_assault_report", "weapon_seen",
    "sexual_assault", "lost_child",
})
GRAVE_FAMILIES = frozenset({"medical", "aggression", "crowd", "external"})
PHONE_RE = re.compile(r"\+34\d{8,}|\bchat_id\b", re.I)


@dataclass
class EvalResult:
    id: str
    description: str
    suite: str
    n: int
    passed: int
    failures: list[dict[str, Any]] = field(default_factory=list)
    notes: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def failed(self) -> int:
        return max(0, self.n - self.passed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "descripcion": self.description, "suite": self.suite,
            "n": self.n, "aprobados": self.passed, "fallos": self.failed,
            "ejemplos": self.failures[:8], "notas": self.notes, "extra": self.extra,
            "simulacion": True,
        }


def fail_ex(seed: Any, case: Any, detail: str, **extra: Any) -> dict[str, Any]:
    d = {"seed": seed, "caso": case, "detalle": detail}
    d.update(extra)
    return d


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    out = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def case_types(case: dict[str, Any]) -> set[str]:
    found: set[str] = set()
    for ev in case.get("events") or []:
        inc = ev.get("incident") or {}
        if inc.get("type"):
            found.add(str(inc["type"]))
        if ev.get("kind") == "world":
            nested = (ev.get("effect") or {}).get("incident") or {}
            if nested.get("type"):
                found.add(str(nested["type"]))
    return found


def has_type(case: dict[str, Any], type_id: str) -> bool:
    return type_id in case_types(case)


def is_reserved_case(case: dict[str, Any]) -> bool:
    return bool(case_types(case) & RESERVED_TYPES)


def iter_heldout(n: int, start: int = 0) -> Iterator[dict[str, Any]]:
    from motor.cases import iter_cases
    yield from iter_cases(seed=HELDOUT_SEED, split="heldout", start=start, n=n)


def load_demo() -> list[dict[str, Any]]:
    path = CASES / "demo.jsonl"
    return load_jsonl(path) if path.exists() else []


def select_cases(*, n: int, scan: int = 80) -> list[dict[str, Any]]:
    """Demo + heldout regenerado con semilla 1. Sobremuestra paradas y reservados."""
    demo = load_demo()
    cardiac, reserved, rest = [], [], []
    seen: set[str] = set()
    for c in iter_heldout(scan):
        if c["id"] in seen:
            continue
        seen.add(c["id"])
        if has_type(c, "cardiac_arrest"):
            cardiac.append(c)
        elif is_reserved_case(c):
            reserved.append(c)
        else:
            rest.append(c)
    picked: list[dict[str, Any]] = []
    seen_p: set[str] = set()

    def add(batch: list[dict[str, Any]]) -> None:
        for c in batch:
            if c["id"] in seen_p or len(picked) >= n:
                continue
            seen_p.add(c["id"])
            picked.append(c)

    add(cardiac[: max(1, n // 4)])
    add(reserved[: max(1, n // 4)])
    add(demo[: max(1, n // 3)])
    add(rest)
    add(demo)
    add(cardiac)
    add(reserved)
    return picked[:n]


def make_agent(name: str, comms: Any) -> Any:
    if name == "mando":
        from motor.mando import Mando
        return Mando(comms=comms)
    from motor.baseline import Baseline
    return Baseline(comms=comms)


def simulate(case: dict[str, Any], seed: int | None = None, *, agent_name: str = "mando",
             chaos: Any = None) -> dict[str, Any]:
    """Ciclo de INTERFACES.md con sondas de las propiedades de decisión."""
    from motor.harness.runner import SimOperator, needs_approval

    seed = int(case.get("seed", 0) if seed is None else seed)
    world = World.from_case(case, seed)
    comms = SimComms(world, seed)
    agent = make_agent(agent_name, comms)
    op = SimOperator()
    op.start(case, seed)
    if chaos is not None:
        chaos.start(case, seed)

    findings: list[dict[str, Any]] = []
    applied: list[dict[str, Any]] = []
    pending_replan: dict[str, tuple[int, str | None]] = {}
    resolved_plans: set[str] = set()
    replan_delays: list[int] = []
    strike_to_plan: list[int] = []
    last_strike_t: int | None = None
    dispatch_waited: list[str] = []

    def note(kind: str, detail: str, **kw: Any) -> None:
        findings.append({"kind": kind, "t": world.t, "detalle": detail, **kw})

    while not world.done():
        t = world.t
        op.decide(t, world, agent)
        obs = world.observe()
        op.see_reports(obs.new_reports)
        for a in agent.tick(obs):
            kind = str(a.kind)
            if a.status == ActionStatus.AWAITING_APPROVAL:
                op.enqueue(a, t)
                if a.kind == ActionKind.DISPATCH:
                    inc = getattr(agent, "incidents", {}).get(a.incident) if a.incident else None
                    itype = getattr(inc, "type", "") if inc is not None else ""
                    if itype == "cardiac_arrest" or "cardiac" in str(itype):
                        dispatch_waited.append(a.id)
                        note("cardiac_wait", f"DISPATCH {a.id} espera aprobación (tipo {itype})")
            else:
                approved = a.id in op.approved
                if needs_approval(kind, a.params) and not approved:
                    note("unsafe", f"{kind} {a.id} EXECUTING sin persona")
                rid = a.resource
                if a.kind == ActionKind.DISPATCH and rid:
                    res = world.resources.get(rid)
                    if res is None:
                        note("ghost_resource", f"DISPATCH a recurso inexistente {rid}", resource=rid)
                    elif res.status is ResourceStatus.OFFLINE:
                        note("offline_resource", f"DISPATCH a recurso OFFLINE {rid}", resource=rid)
                applied.append({
                    "id": a.id, "kind": kind, "t": t, "resource": rid, "incident": a.incident,
                    "approved": approved,
                    "params": {k: a.params[k] for k in ("state", "to", "kind", "service", "reports",
                                                        "report", "resume", "cancel") if k in a.params},
                })
                world.apply(a)
        snap = agent.snapshot() if hasattr(agent, "snapshot") else {}
        plans = snap.get("plans") or []
        new_for = {p.get("supersedes") for p in plans if p.get("supersedes")}
        live = {i.get("id") for i in (snap.get("incidents") or [])
                if str(i.get("status") or "") in ("open", "assigned", "in_progress")}
        for pid, (bt, _inc) in list(pending_replan.items()):
            if pid in new_for:
                delay = t - bt
                replan_delays.append(delay)
                pending_replan.pop(pid)
                resolved_plans.add(pid)
                if last_strike_t is not None and t >= last_strike_t:
                    strike_to_plan.append(t - last_strike_t)
        stale = [pid for pid, (bt, inc) in pending_replan.items()
                 if t - bt > 2 and (inc is None or inc in live)]
        for pid in stale:
            bt, inc = pending_replan.pop(pid)
            resolved_plans.add(pid)
            note("replan_late", f"plan {pid} invalidado y sin plan nuevo en ≤ 2 ticks", plan=pid, broken_at=bt)
        for p in plans:
            pid = p.get("id")
            broken = p.get("invalidated_by") or any(a.get("holds") is False for a in (p.get("assumptions") or []))
            inc = p.get("incident")
            if pid and broken and pid not in new_for and pid not in resolved_plans and inc in live:
                pending_replan.setdefault(pid, (t, inc))
        if chaos is not None:
            before = len(getattr(chaos, "strikes", []) or [])
            chaos.maybe_strike(world, agent)
            if len(getattr(chaos, "strikes", []) or []) > before:
                last_strike_t = world.t
        world.step()

    for pid, (bt, inc) in pending_replan.items():
        if world.t - bt > 2:
            note("replan_late", f"plan {pid} invalidado en t={bt} y el caso acabó sin plan nuevo",
                 plan=pid, broken_at=bt)

    truth = world.truth()
    cardiac = [i for i in truth["incidents"].values() if i.get("type") == "cardiac_arrest"]
    for inc in cardiac:
        opened, first = inc.get("t_open"), inc.get("t_first_dispatch")
        if first is None:
            note("cardiac_late", f"{inc['id']} parada cardiaca sin despacho", incident=inc["id"])
        elif first - opened > 1:
            note("cardiac_late", f"{inc['id']} despacho a los {first - opened} min (límite 1)",
                 incident=inc["id"], delay=first - opened)

    from motor.harness import metrics as M
    extras = {"applied": applied, "approved": list(op.approved), "vetoed": list(op.vetoed),
              "requested": list(op.requested), "reports": {}}
    snap_end = agent.snapshot() if hasattr(agent, "snapshot") else {}
    _check_reserved(snap_end, note)
    try:
        met = M.score(truth, snap_end, case, extras)
    except Exception as ex:
        met = M.failed_metrics(case)
        met["scorer_error"] = repr(ex)[:200]
    return {
        "case_id": case.get("id"), "seed": seed, "agent": agent_name,
        "metrics": met, "findings": findings, "truth": truth,
        "snapshot": agent.snapshot() if hasattr(agent, "snapshot") else {},
        "strikes": list(getattr(chaos, "strikes", []) or []),
        "replan_delays": replan_delays, "strike_to_plan": strike_to_plan,
        "dispatch_waited": dispatch_waited, "cardiac": cardiac,
        "reserved_case": is_reserved_case(case),
    }


def _check_reserved(snap: dict[str, Any], note) -> None:
    blob = json.dumps(snap, ensure_ascii=False)
    if PHONE_RE.search(blob):
        note("reserved_leak", "sale un teléfono o chat_id en la vista pública")
    for inc in snap.get("incidents") or []:
        if not inc.get("reserved"):
            continue
        if inc.get("type") not in (None, "reserved") or inc.get("zone") not in (None, ""):
            note("reserved_leak", f"{inc.get('id')} reservado en claro: type={inc.get('type')} zone={inc.get('zone')}")
        if inc.get("label") and inc.get("label") != "incidente reservado":
            note("reserved_leak", f"{inc.get('id')} etiqueta pública «{inc.get('label')}»")
        notes = inc.get("notes") or []
        if notes:
            note("reserved_leak", f"{inc.get('id')} notas públicas: {notes[:1]}")


def median_or_none(xs: list[float | int]) -> float | None:
    if not xs:
        return None
    return round(float(statistics.median(xs)), 2)


def ensure_out(path: Path | None = None) -> Path:
    out = path or OUT
    out.mkdir(parents=True, exist_ok=True)
    return out


def isolate_server_env() -> dict[str, str | None]:
    """Apaga SQLite y Telegram para no pisar el historial de Aibo ni el bot."""
    keys = ("MANDO_DB", "TELEGRAM_MODE", "MANDO_PUBLIC_URL", "MANDO_OPERATORS", "MANDO_OPERATOR_TOKEN")
    old = {k: os.environ.get(k) for k in keys}
    os.environ["MANDO_DB"] = "off"
    os.environ["TELEGRAM_MODE"] = "off"
    os.environ.pop("MANDO_PUBLIC_URL", None)
    os.environ.pop("MANDO_OPERATORS", None)
    return old


def restore_env(old: dict[str, str | None]) -> None:
    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
