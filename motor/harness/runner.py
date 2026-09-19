"""Ejecuta casos sin pantalla siguiendo el ciclo de INTERFACES.md, con operador simulado.

    run_case(case, agent_factory, seed, chaos=None, operator=None) -> RunResult
    run_many(cases, agent_factory, workers=N, chaos="none|random|smart", label=...) -> list[RunResult]

Determinista: mismo caso + misma semilla + mismo agente + mismo adversario = mismo resultado.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from motor.contracts import ALWAYS_APPROVE, Action, ActionKind, ActionStatus
from motor.world import SimComms, World

from . import metrics as M

RUNS_DIR = Path(os.environ.get("MOTOR_HARNESS_RUNS") or (Path(__file__).resolve().parent / "runs"))
_ACTIVE = ("open", "assigned", "in_progress")


def needs_approval(kind: Any, params: dict[str, Any] | None) -> bool:
    """Lo que SIEMPRE exige el sí de una persona: ALWAYS_APPROVE y cerrar una zona."""
    k = str(kind)
    if any(k == str(x) for x in ALWAYS_APPROVE):
        return True
    return k == str(ActionKind.SET_ZONE) and (params or {}).get("state") == "closed"


FINGERPRINT_DIRS = ("world", "mando", "baseline", "caos", "harness")


def code_fingerprint(root: Path | None = None) -> str:
    """Huella (sha256 recortado) del código que se mide: todos los `.py` y `.json` de primer nivel de
    `motor/{world,mando,baseline,caos,harness}` más `contracts.py`. No entran tests, datos ni salidas.
    Cada ejecución y cada informe la guardan; `learn` y `curve` abortan si cambia entre rondas."""
    import hashlib
    root = root or Path(__file__).resolve().parent.parent
    h = hashlib.sha256()
    files = [root / "contracts.py"]
    for folder in FINGERPRINT_DIRS:
        # `memory.*.json` y `params.*.json` son DATOS que escribe `day2` (memoria observada y cambios aprobados), no
        # código: no entran en la huella; `day2.json` guarda su propio hash de los parámetros con que midió cada brazo.
        files += [f for f in sorted((root / folder).glob("*")) if f.suffix in (".py", ".json")
                  and not f.name.startswith(("test_", "memory.", "params."))]
    for f in files:
        if f.exists():
            h.update(f"{f.parent.name}/{f.name}".encode())
            h.update(f.read_bytes())
    return h.hexdigest()[:12]


_LOADED_FP: str | None = None


def loaded_fingerprint() -> str:
    """Huella tomada la primera vez que se pide en este proceso (≈ el código que está cargado)."""
    global _LOADED_FP
    if _LOADED_FP is None:
        _LOADED_FP = code_fingerprint()
    return _LOADED_FP


# ---------------------------------------------------------------------------- fábrica de agentes

@dataclass
class AgentFactory:
    """Fábrica serializable (multiprocessing): nombre del agente + lecciones del manual (+ ensayo previo)."""
    name: str = "mando"
    lessons: list[dict[str, Any]] | None = None     # None o [] = manual vacío (ronda 0)
    twin: bool = False                              # pasar a Mando `twin=lambda: world.twin()` (gemelo SIN futuro)
    params: dict[str, Any] | None = None            # `Params.to_dict()`; None = Mando sin parámetros operativos
    memory: bool = False                            # enganchar una `OperationalMemory` (sale en `detail["memory"]`)

    def twin_available(self) -> bool:
        """¿Existen `World.twin` y el parámetro `twin` de Mando? Nunca se usa `clone()`: conoce el futuro."""
        import inspect
        from motor.mando import Mando
        return hasattr(World, "twin") and "twin" in inspect.signature(Mando.__init__).parameters

    def __call__(self, comms: Any) -> Any:
        if self.name == "mando":
            from motor.mando import Mando
            from motor.mando.playbook import Playbook
            playbook = Playbook([json.loads(json.dumps(x)) for x in (self.lessons or [])])
            if self.params is not None or self.memory:
                from motor.mando.memory import OperationalMemory
                from motor.mando.tuning import Params
                world = comms.world
                return Mando(playbook=playbook, comms=comms, twin=(lambda: world.twin()) if self.twin else None,
                             params=Params.from_dict(self.params) if self.params is not None else None,
                             memory=OperationalMemory() if self.memory else None)
            if self.twin:
                if not self.twin_available():
                    raise RuntimeError("se pidió ensayo previo y no existen World.twin o Mando(twin=...)")
                world = comms.world
                return Mando(playbook=playbook, comms=comms, twin=lambda: world.twin())
            return Mando(playbook=playbook, comms=comms)
        from motor.baseline import Baseline, BaselinePlus
        if self.name == "baseline":
            return Baseline(comms=comms)
        if self.name == "baseline_plus":
            return BaselinePlus(comms=comms)
        raise ValueError(f"agente desconocido: {self.name}")


# ---------------------------------------------------------------------------- operador simulado

class SimOperator:
    """La persona del centro de control, simulada: decide cada petición tras 1–3 min.

    Ve lo que vería en cámaras (la verdad del mundo en ese minuto). Aprueba lo razonable:
      · EVACUATE / SET_ZONE closed: incidente activo de gravedad ≥ 7 en la zona, o zona ≥ 5 personas/m².
      · STOP_SHOW: incidente activo de gravedad ≥ 8 en foso/pista, o foso ≥ 5/m².
      · REQUEST_EXTERNAL: incidente activo de gravedad ≥ 6 al que apunte la acción (por aviso o por zona).
      · lo que el caso declara correcto en `expected.must` («evacuate Z for i3 with approval»).
    Veta lo que viola `expected.must_not` («stop_show for i2», «request_external for fa1») y lo que no tiene
    nada real detrás. Cualquier otra cosa que el agente quiera consultar, la aprueba.
    """

    def __init__(self, min_delay: int = 1, max_delay: int = 3) -> None:
        self.min_delay, self.max_delay = min_delay, max_delay
        self.start({}, 0)

    def start(self, case: dict[str, Any], seed: int) -> None:
        self.rng = random.Random((int(seed) * 1000003) ^ 0x0BEA7)
        self.case = case
        self.pending: dict[str, tuple[int, Action]] = {}
        self.approved: list[str] = []
        self.vetoed: list[dict[str, Any]] = []
        self.requested: list[str] = []
        exp = case.get("expected", {}) if case else {}
        self.must, self.must_not = list(exp.get("must", [])), list(exp.get("must_not", []))
        self.fa_texts: dict[str, set[str]] = {}
        for ev in (case.get("events", []) if case else []):
            if ev.get("kind") == "report_only" and str(ev.get("ref", "")).startswith("fa"):
                self.fa_texts.setdefault(ev["ref"], set()).update(r.get("text", "") for r in ev.get("reports", []))
        self.report_text: dict[str, str] = {}

    def see_reports(self, reports: Iterable[Any]) -> None:
        for r in reports:
            self.report_text[r.id] = r.text

    def enqueue(self, a: Action, t: int) -> None:
        if a.id not in self.pending and a.id not in self.approved and a.id not in self.requested:
            self.requested.append(a.id)
            self.pending[a.id] = (t + self.rng.randint(self.min_delay, self.max_delay), a)

    def decide(self, t: int, world: Any, agent: Any) -> None:
        for aid in [k for k, (due, _) in self.pending.items() if due <= t]:
            _, a = self.pending.pop(aid)
            if a.status != ActionStatus.AWAITING_APPROVAL:
                continue
            ok, note = self.judge(a, world, agent)
            if ok:
                self.approved.append(aid)
            else:
                self.vetoed.append({"id": aid, "kind": str(a.kind), "zone": a.zone, "t": t, "note": note})
            agent.approve(aid, ok, note)

    # -- juicio ---------------------------------------------------------------
    def _targets(self, a: Action, truth_inc: dict[str, Any], rep_truth: dict[str, Any], agent: Any) -> tuple[set[str], set[str]]:
        """(incidentes verdaderos activos a los que apunta, refs de falsa alarma a las que apunta)."""
        reps = list(a.params.get("reports") or ([a.params["report"]] if a.params.get("report") else []))
        if a.incident and a.incident not in truth_inc:
            reps += _agent_incident_reports(agent, a.incident)
        hit = {a.incident} if a.incident in truth_inc else set()
        hit |= {rep_truth[r] for r in reps if rep_truth.get(r)}
        fas = {ref for ref, texts in self.fa_texts.items() for r in reps if self.report_text.get(r) in texts}
        zone = a.zone or a.params.get("zone")
        if not hit and zone:
            hit = {iid for iid, inc in truth_inc.items() if inc["zone"] == zone}
        return {i for i in hit if i in truth_inc and str(truth_inc[i]["status"]) in _ACTIVE}, fas

    def judge(self, a: Action, world: Any, agent: Any) -> tuple[bool, str]:
        truth = world.truth()          # lo que la persona ve en cámaras; solo se consulta al decidir
        incidents = truth["incidents"]
        hit, fas = self._targets(a, incidents, truth["reports"], agent)
        kind = str(a.kind)
        for rule in self.must_not:
            m = re.fullmatch(r"(\w+) for (\w+)", rule)
            if m and m.group(1) == kind and (m.group(2) in hit or (m.group(2) in fas and not hit)):
                return False, f"no procede: {rule}"
        for rule in self.must:
            m = re.match(r"(evacuate|stop_show|request_external|set_zone)\b(.*?) for (\w+) with approval", rule)
            if m and m.group(1) == kind and m.group(3) in hit:
                return True, "procede según el protocolo del caso"
        sev = max((incidents[i]["severity"] for i in hit), default=0)
        zone = a.zone or a.params.get("zone")

        def dens(z: Any) -> float:
            try:
                return world.density(z)
            except (KeyError, TypeError):
                return 0.0
        if kind in ("evacuate", "set_zone"):
            ok = sev >= 7 or dens(zone) >= 5.0
        elif kind == "stop_show":
            ok = sev >= 8 or dens("front_pit") >= 5.0
        elif kind == "request_external":
            ok = sev >= 6
        else:
            ok = True
        return ok, ("" if ok else "no veo nada que lo justifique")


def _agent_incident_reports(agent: Any, incident_id: str) -> list[str]:
    inc = getattr(agent, "incidents", {}).get(incident_id) if isinstance(getattr(agent, "incidents", None), dict) else None
    if inc is not None and hasattr(inc, "reports"):
        return list(inc.reports)
    tk = getattr(agent, "tickets", {}).get(incident_id) if hasattr(agent, "tickets") else None
    return list(tk["reports"]) if tk else []


# ---------------------------------------------------------------------------- una ejecución

@dataclass
class RunResult:
    case_id: str
    seed: int
    agent: str
    chaos: str
    metrics: dict[str, Any]
    families: list[str] = field(default_factory=list)
    difficulty: int = 0
    split: str = ""
    strikes: list[dict[str, Any]] = field(default_factory=list)
    vetoes: list[dict[str, Any]] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)     # verdad resumida + log recortado
    wall_ms: float = 0.0
    code: str = ""                                           # huella del código con que se midió

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


def _record(a: Action, t: int, approved: bool) -> dict[str, Any]:
    p = a.params
    return {"id": a.id, "kind": str(a.kind), "t": t, "zone": a.zone or p.get("zone"), "resource": a.resource,
            "incident": a.incident, "approved": approved,
            "params": {k: p[k] for k in ("state", "to", "kind", "service", "reports", "report", "resume", "cancel")
                       if k in p}}


def run_case(case: dict[str, Any], agent_factory: Callable[[Any], Any], seed: int | None = None,
             chaos: Any = None, operator: SimOperator | None = None, detail: bool = True) -> RunResult:
    t0 = time.perf_counter()
    seed = int(case.get("seed", 0) if seed is None else seed)
    world = World.from_case(case, seed)
    comms = SimComms(world, seed)
    agent = agent_factory(comms)
    op = operator or SimOperator()
    op.start(case, seed)
    if chaos is not None:
        chaos.start(case, seed)
    applied: list[dict[str, Any]] = []
    reports: dict[str, dict[str, Any]] = {}
    while not world.done():
        op.decide(world.t, world, agent)
        obs = world.observe()
        op.see_reports(obs.new_reports)
        for r in obs.new_reports:
            reports.setdefault(r.id, {"t": r.t, "text": r.text, "channel": str(r.channel), "zone_hint": r.zone_hint})
        for a in agent.tick(obs):
            if a.status == ActionStatus.AWAITING_APPROVAL:
                op.enqueue(a, world.t)
            else:
                applied.append(_record(a, world.t, a.id in op.approved))
                world.apply(a)
        if chaos is not None:
            chaos.maybe_strike(world, agent)
        world.step()
    truth, snap = world.truth(), agent.snapshot()
    extras = {"applied": applied, "approved": list(op.approved), "vetoed": list(op.vetoed),
              "requested": list(op.requested), "reports": reports}
    met = M.score(truth, snap, case, extras)
    strikes = list(getattr(chaos, "strikes", [])) if chaos is not None else []
    arm = getattr(agent_factory, "name", None) or getattr(agent, "name", type(agent).__name__.lower())
    res = RunResult(case.get("id", "?"), seed, arm + ("_twin" if getattr(agent_factory, "twin", False) else ""),
                    getattr(chaos, "name", "none") if chaos is not None else "none", met,
                    list(case.get("families", [])), int(case.get("difficulty", 0)), case.get("split", ""),
                    strikes, list(op.vetoed))
    if detail:
        res.detail = _detail(truth, snap, applied)
    res.detail["ops"] = M.ops_metrics(truth, applied)
    memory = getattr(agent, "memory", None)
    if memory is not None:
        memory.end_run()
        res.detail["memory"] = memory.to_dict()
    if isinstance(snap.get("params"), dict):
        res.detail["params_applied"] = dict(snap["params"].get("applied") or {})
    res.wall_ms = round((time.perf_counter() - t0) * 1000, 2)
    res.code = loaded_fingerprint()
    return res


def _detail(truth: dict[str, Any], snap: dict[str, Any], applied: list[dict[str, Any]], max_log: int = 80) -> dict[str, Any]:
    """Verdad y log del agente, recortados para que 1.000 ejecuciones no pesen cientos de MB."""
    incidents = {iid: {k: (str(v) if k in ("family", "status") else v) for k, v in inc.items()
                       if k in ("family", "type", "zone", "severity", "t_open", "deadline", "needs", "status", "origin",
                                "t_first_dispatch", "t_first_attention", "t_resolved", "t_failed")}
                 for iid, inc in truth["incidents"].items()}
    log = [e for e in snap.get("log", []) if e.get("kind") != "report"]
    if len(log) > max_log:
        log = log[:max_log // 2] + [{"t": -1, "kind": "…", "text": f"({len(log) - max_log} entradas omitidas)"}] + log[-max_log // 2:]
    log = [{"t": e.get("t"), "kind": e.get("kind"), "text": str(e.get("text", ""))[:160], "ref": e.get("ref")} for e in log]
    peak = max(truth["peak_density"].items(), key=lambda kv: kv[1]["density"])
    rep_truth = truth.get("reports", {})
    agent_incidents = [{"id": i.get("id"), "type": i.get("type"), "family": str(i.get("family", "")), "zone": i.get("zone"),
                        "severity": i.get("severity"), "status": str(i.get("status", "")), "replans": i.get("replans"),
                        "truth": sorted({rep_truth[r] for r in (i.get("reports") or []) if rep_truth.get(r)})}
                       for i in M._as_list(snap.get("incidents"))][:60]
    lessons = snap.get("lessons") if isinstance(snap.get("lessons"), dict) else {}
    return {"incidents": incidents, "agent_incidents": agent_incidents,
            "lesson_candidates": list(lessons.get("candidates", []))[:20], "peak": {"zone": peak[0], **peak[1]},
            "wasted": truth["wasted_dispatches"][:20], "injected": [e for e in truth["injected"] if e.get("origin") == "inject"],
            "n_applied": len(applied), "log": log, "counters": snap.get("counters", {}),
            "lessons_applied": (snap.get("lessons") or {}).get("applied", {}) if isinstance(snap.get("lessons"), dict) else {}}


# ---------------------------------------------------------------------------- muchas ejecuciones

def load_cases(path: str | Path, n: int | None = None, offset: int = 0) -> list[dict[str, Any]]:
    out = []
    with open(path, encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            if i < offset or not line.strip():
                continue
            out.append(json.loads(line))
            if n is not None and len(out) >= n:
                break
    return out


def make_chaos(kind: str | None, budget: int = 3, lookahead: int = 15) -> Any:
    if not kind or kind == "none":
        return None
    from motor.caos import Chaos, RandomChaos
    return Chaos(budget=budget, lookahead=lookahead) if kind == "smart" else RandomChaos(budget=budget)


def _job(args: tuple) -> dict[str, Any]:
    case, factory, chaos_kind, budget, lookahead, detail = args
    try:
        return run_case(case, factory, None, make_chaos(chaos_kind, budget, lookahead), None, detail).to_dict()
    except Exception as ex:
        # Si revienta el agente, el mundo o el PUNTUADOR, la ejecución NO desaparece del N: cuenta con la peor
        # puntuación para ese brazo y queda marcada (`metrics.run_error`, `error`, `traceback`).
        import traceback
        return RunResult(case.get("id", "?"), int(case.get("seed", 0)), getattr(factory, "name", "?"), chaos_kind or "none",
                         M.failed_metrics(case), list(case.get("families", [])), int(case.get("difficulty", 0)),
                         case.get("split", ""), code=loaded_fingerprint()).to_dict() \
            | {"error": repr(ex), "traceback": traceback.format_exc()[-1500:]}


def case_signature(cases: list[dict[str, Any]]) -> str:
    """Firma del CONTENIDO de los casos (no solo id y semilla): si alguien regenera los ficheros de casos con los
    mismos ids, la firma cambia y dos mediciones dejan de ser comparables."""
    import hashlib
    h = hashlib.sha256()
    for c in cases:
        h.update(json.dumps(c, sort_keys=True, ensure_ascii=False).encode())
    return h.hexdigest()[:16]


def assert_same_cases(arms: dict[str, list[dict[str, Any]]], cases: list[dict[str, Any]]) -> str:
    """Aborta si algún brazo no tiene EXACTAMENTE los mismos casos y semillas que `cases`. Devuelve la firma."""
    want = [(c["id"], int(c.get("seed", 0))) for c in cases]
    for name, results in arms.items():
        got = [(r["case_id"], int(r["seed"])) for r in results]
        if got != want:
            missing = sorted(set(want) - set(got))[:5]
            raise SystemExit(f"ABORTADO: el brazo «{name}» tiene N={len(got)} y se esperaban N={len(want)} con los mismos "
                             f"casos y semillas (faltan p. ej. {missing}). No se comparan brazos con conjuntos distintos.")
        if any(not r.get("metrics") for r in results):
            raise SystemExit(f"ABORTADO: el brazo «{name}» tiene ejecuciones sin métricas.")
    return case_signature(cases)


def run_many(cases: list[dict[str, Any]], agent_factory: AgentFactory, workers: int | None = None,
             chaos: str | None = None, label: str | None = None, budget: int = 3, lookahead: int = 15,
             detail: bool | None = None) -> list[dict[str, Any]]:
    """Ejecuta en paralelo y devuelve los resultados EN EL ORDEN de `cases` (dicts de RunResult).
    Con `label`, guarda cada ejecución en `runs/<label>/<agente>__<caso>.json` y un `_index.json`."""
    workers = workers or os.cpu_count() or 4
    detail = bool(label) if detail is None else detail
    loaded_fingerprint()
    # Se importa TODO en el proceso padre antes de bifurcar: así un `learn` entero mide una sola versión
    # del código aunque alguien esté editando motor/mando/ mientras tanto.
    import motor.baseline  # noqa: F401
    import motor.caos  # noqa: F401
    if getattr(agent_factory, "name", "") == "mando":
        import motor.mando  # noqa: F401
        import motor.mando.playbook  # noqa: F401
    jobs = [(c, agent_factory, chaos, budget, lookahead, detail) for c in cases]
    if workers <= 1 or len(jobs) < 4:
        results = [_job(j) for j in jobs]
    else:
        with mp.get_context("spawn" if os.name == "nt" else "fork").Pool(workers) as pool:
            results = pool.map(_job, jobs, chunksize=max(1, len(jobs) // (workers * 8)))
    if label:
        save_runs(results, label)
    return results


def save_runs(results: list[dict[str, Any]], label: str) -> Path:
    out = RUNS_DIR / re.sub(r"[^\w.-]+", "_", label)
    out.mkdir(parents=True, exist_ok=True)
    index = []
    for r in results:
        name = f"{r['agent']}__{r['case_id']}.json"
        (out / name).write_text(json.dumps(r, ensure_ascii=False, default=str), encoding="utf-8")
        index.append({"file": name, "case_id": r["case_id"], "seed": r["seed"], "agent": r["agent"], "chaos": r["chaos"],
                      "score": r["metrics"].get("score"), "critical_failed": r["metrics"].get("critical_failed"),
                      "unsafe_actions": r["metrics"].get("unsafe_actions"), "error": r.get("error")})
    (out / "_index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    return out
