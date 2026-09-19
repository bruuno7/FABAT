"""El bucle que aprende: de un lote de ejecuciones a lecciones VALIDADAS para el manual de Mando.

Determinista y sin LLM. Tres pasos:

1. `analyze`   agrupa los fallos del lote de ANÁLISIS por tipo de incidente (en el vocabulario del
               agente, que es con el que encaja `when.type`): críticos fallidos, lentitud, `must`
               incumplidos, `must_not` violados, vetos del operador, zonas por encima de 5/m².
2. `propose`   convierte cada patrón con evidencia suficiente en lecciones candidatas con el formato de
               `motor/mando/playbook.py` (priority_boost, prefer_resource, pre_action, forbid_action,
               assumption_threshold). Cada una lleva `evidence_n` y `evidence_cases`.
3. `validate`  validación cruzada simple: la candidata se prueba en casos de VALIDACIÓN (la otra mitad de
               train, que no motivó la lección) donde puede dispararse. Entra solo si el IC bootstrap al 99 % de
               la diferencia PAREADA (mismos casos y semillas, con y sin la lección) queda entero por encima de 0,
               y ni `unsafe_actions` ni los críticos fallidos empeoran. 99 % y no 95 % porque en cada ronda se
               prueban decenas de candidatas. Se anota además si los IC NO pareados de antes y después se solapan
               (criterio más duro, casi nunca se cumple con efectos de décimas).
               Aceptación voraz: cada lección se valida sobre el manual que ya incluye las anteriores.

Cada lección lleva `basis`: de dónde sale la señal.
    "world"     resultados del mundo: críticos fallidos, fallidos, lentitud, zonas por encima de 5/m².
    "operator"  vetos de la persona del centro de control.
    "grader"    reglas `expected.must`/`must_not` del generador de casos. OJO: una lección «notify X» que solo
                recupera una regla `must` es AJUSTE AL CORRECTOR, no aprendizaje sobre el mundo. Por eso `learn`
                mide dos pistas: «mundo» (sin lecciones `grader`, validadas con `world_score`) y «todo».

`heldout` no se toca aquí nunca.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable

from . import metrics as M
from .runner import AgentFactory, run_many

MIN_EVIDENCE = 4          # nada de lecciones sacadas de un solo caso
MIN_GAIN = 0.0            # además del IC: ganancia media mínima (0 = basta con que el IC excluya el 0)
CI_LEVEL = 0.99           # nivel del IC pareado que debe excluir el 0 para aceptar una lección
MAX_VALIDATION = 400      # casos de validación por candidata
MIN_VALIDATION = 8        # con menos casos donde pueda dispararse, la mejora es ruido: se rechaza
_ID = re.compile(r"\b((?:i|x)\d[\w-]*)\b")


@dataclass
class Verdict:
    lesson: dict[str, Any]
    accepted: bool
    reason: str
    n_validation: int = 0
    before: dict[str, Any] = field(default_factory=dict)
    after: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"lesson": self.lesson, "accepted": self.accepted, "reason": self.reason,
                "n_validation": self.n_validation, "before": self.before, "after": self.after}


# ---------------------------------------------------------------------------- 1 · análisis

def _agent_types(result: dict[str, Any]) -> dict[str, list[tuple[str, str]]]:
    """incidente verdadero -> [(tipo, familia)] con que lo abrió el agente."""
    out: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for ai in result.get("detail", {}).get("agent_incidents", []):
        for tid in ai.get("truth", []):
            out[tid].append((ai.get("type"), ai.get("family")))
    return out


def analyze(results: list[dict[str, Any]], cases: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Patrones de fallo con sus casos. Clave = (patrón, tipo del agente | tipo verdadero, detalle)."""
    pat: dict[tuple, set[str]] = defaultdict(set)
    seen_type: Counter = Counter()
    for r in results:
        m, d = r.get("metrics"), r.get("detail", {})
        if not m:
            continue
        cid, truth_inc, a_types = r["case_id"], d.get("incidents", {}), _agent_types(r)

        def types_of(iid: str) -> list[tuple[str, str]]:
            return a_types.get(iid) or [(None, str(truth_inc.get(iid, {}).get("family", "")))]

        for iid, inc in truth_inc.items():
            for ty, fam in types_of(iid):
                seen_type[(ty, fam)] += 1
            if str(inc.get("status")) == "failed":
                tag = "critical_failed" if inc["severity"] >= M.CRITICAL_SEVERITY else "failed"
                for ty, fam in types_of(iid):
                    pat[(tag, ty, fam, json.dumps(sorted(inc.get("needs", {}))))].add(cid)
                if iid not in a_types:
                    pat[("not_recognized", None, str(inc.get("family")), inc.get("type"))].add(cid)
            elif inc.get("deadline") and inc.get("t_first_attention") is not None:
                window = max(1, inc["deadline"] - inc["t_open"])
                if (inc["t_first_attention"] - inc["t_open"]) / window > 0.7:
                    for ty, fam in types_of(iid):
                        pat[("slow", ty, fam, "")].add(cid)
        for rule in m.get("must_failed", []):
            ids = _ID.findall(rule)
            generic = _ID.sub("#", rule).replace(" if spawned", "")
            generic = re.sub(r"within \d+ min", "within N min", generic)
            for ty, fam in (types_of(ids[-1]) if ids else [(None, "")]):
                pat[("must", ty, fam, generic)].add(cid)
        for rule in m.get("must_not_violated", []):
            ids = _ID.findall(rule)
            for ty, fam in (types_of(ids[-1]) if ids else [(None, "")]):
                pat[("must_not", ty, fam, _ID.sub("#", rule))].add(cid)
        for cand in d.get("lesson_candidates", []):
            when, forbid = cand.get("when", {}), cand.get("then", {}).get("forbid_action", {})
            pat[("veto", when.get("type"), "", json.dumps(forbid, sort_keys=True))].add(cid)
        if m.get("minutes_over_5", 0) > 0:
            for ai in d.get("agent_incidents", []):
                if ai.get("family") == "crowd":
                    pat[("over5", ai.get("type"), "crowd", "")].add(cid)
    return {"patterns": {k: sorted(v) for k, v in pat.items()}, "seen": seen_type}


def top_failures(results: list[dict[str, Any]], cases: dict[str, dict[str, Any]], k: int = 5) -> list[dict[str, Any]]:
    """Los k fallos más frecuentes, legibles, para el informe."""
    an = analyze(results, cases)
    rows = []
    for (tag, ty, fam, detail), cids in an["patterns"].items():
        if tag in ("veto", "over5"):
            continue
        rows.append({"pattern": tag, "agent_type": ty, "family": fam, "detail": detail, "n_cases": len(cids),
                     "examples": cids[:3]})
    rows.sort(key=lambda r: (-r["n_cases"], r["pattern"], str(r["agent_type"])))
    return rows[:k]


# ---------------------------------------------------------------------------- 2 · candidatas

def _when(ty: str | None, fam: str | None) -> dict[str, Any] | None:
    if ty:
        return {"type": ty}
    if fam:
        return {"family": fam}
    return None


def propose(analysis: dict[str, Any], min_evidence: int = MIN_EVIDENCE) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def add(when: dict[str, Any] | None, then: dict[str, Any], text: str, cids: list[str], source: str) -> None:
        if when is None or len(cids) < min_evidence:
            return
        basis = {"must incumplido": "grader", "must_not violado": "grader", "veto del operador": "operator"}.get(source, "world")
        out.append({"when": when, "then": then, "text": text, "source": source, "basis": basis,
                    "evidence_n": len(cids), "evidence_cases": cids[:25]})

    for (tag, ty, fam, detail), cids in analysis["patterns"].items():
        what = ty or fam or "?"
        if tag == "critical_failed":
            for boost in (1.0, 2.0):
                add(_when(ty, fam), {"priority_boost": boost},
                    f"«{what}» falló siendo crítico en {len(cids)} casos: prioridad +{boost:g}", cids, "críticos fallidos")
            needs = json.loads(detail)
            if "ambulance" in needs or "medical" in needs:
                add(_when(ty, fam), {"priority_boost": 1.0, "prefer_resource": "ambulance"},
                    f"«{what}» crítico fallido en {len(cids)} casos: prioridad +1 y se prefiere la ambulancia", cids,
                    "críticos fallidos")
        elif tag == "failed":
            add(_when(ty, fam), {"priority_boost": 0.5}, f"«{what}» pasó de plazo en {len(cids)} casos: prioridad +0,5", cids,
                "incidentes fallidos")
        elif tag == "slow":
            add(_when(ty, fam), {"priority_boost": 0.5},
                f"«{what}» se atendió con más del 70 % del plazo gastado en {len(cids)} casos: prioridad +0,5", cids, "tiempos largos")
        elif tag == "must":
            m = re.fullmatch(r"broadcast for #", detail)
            if m:
                add(_when(ty, fam), {"pre_action": {"kind": "broadcast", "params": {"message": "Atención: seguid las indicaciones del personal."}}},
                    f"en «{what}» faltó el aviso por megafonía en {len(cids)} casos: se avisa antes de planificar", cids, "must incumplido")
            m = re.fullmatch(r"notify (\w+) about #", detail)
            if m:
                add(_when(ty, fam), {"pre_action": {"kind": "notify", "params": {"to": m.group(1), "message": f"Aviso de {what}"}}},
                    f"en «{what}» no se avisó a {m.group(1)} en {len(cids)} casos: se le avisa siempre", cids, "must incumplido")
            m = re.fullmatch(r"set_zone (\w+) restricted for #", detail)
            if m:
                add({**(_when(ty, fam) or {}), "zone": m.group(1)}, {"pre_action": {"kind": "set_zone", "zone": m.group(1), "params": {"state": "restricted"}}},
                    f"en «{what}» en {m.group(1)} faltó restringir la zona en {len(cids)} casos", cids, "must incumplido")
            m = re.fullmatch(r"reroute (\w+) to (\w+) for #", detail)
            if m:
                add({**(_when(ty, fam) or {}), "zone": m.group(1)}, {"pre_action": {"kind": "reroute", "zone": m.group(1), "params": {"to": m.group(2)}}},
                    f"en «{what}» faltó desviar {m.group(1)} → {m.group(2)} en {len(cids)} casos", cids, "must incumplido")
            if detail.startswith("dispatch ") and "within N min" in detail:
                add(_when(ty, fam), {"priority_boost": 1.0},
                    f"«{what}»: el despacho llegó fuera de plazo en {len(cids)} casos: prioridad +1", cids, "must incumplido")
        elif tag == "must_not":
            m = re.fullmatch(r"(broadcast|request_external|stop_show) for #", detail)
            if m:
                add(_when(ty, fam), {"forbid_action": {"kind": m.group(1)}},
                    f"en «{what}» «{m.group(1)}» estaba contraindicado y se hizo en {len(cids)} casos: no se propone", cids, "must_not violado")
        elif tag == "veto":
            forbid = json.loads(detail)
            add(_when(ty, None), {"forbid_action": forbid},
                f"el operador vetó «{forbid.get('kind')}» en «{what}» {len(cids)} veces: no se vuelve a proponer", cids, "veto del operador")
        elif tag == "over5":
            for ratio in (0.75, 0.65):
                add(_when(ty, fam), {"assumption_threshold": {"zone_occupancy_below": {"ratio": ratio}}},
                    f"«{what}»: hubo zonas por encima de 5/m² en {len(cids)} casos: el destino de un desvío debe quedar por debajo del {ratio:.0%}",
                    cids, "replanificación tardía")
    # más evidencia primero; a igualdad, orden estable por texto
    out.sort(key=lambda c: (-c["evidence_n"], c["text"]))
    uniq, seen = [], set()
    for c in out:
        key = json.dumps([c["when"], c["then"]], sort_keys=True)
        if key not in seen:
            seen.add(key)
            uniq.append(c)
    return uniq


# ---------------------------------------------------------------------------- 3 · validación

def _affects(lesson: dict[str, Any], case: dict[str, Any], type_map: dict[str, set[str]]) -> bool:
    """¿Puede dispararse la lección en este caso? `type_map`: tipo del agente -> tipos verdaderos vistos."""
    when = lesson.get("when", {})
    fams, types = set(case.get("families", [])), set()
    for ev in case.get("events", []):
        inc = ev.get("incident") or (ev.get("effect", {}).get("incident") if ev.get("kind") == "world" else None)
        if inc:
            types.add(inc.get("type"))
            fams.add(inc.get("family"))
    if "type" in when:
        wanted = when["type"] if isinstance(when["type"], list) else [when["type"]]
        true_types = set().union(*(type_map.get(w, {w}) for w in wanted))
        return bool(types & true_types)
    if "family" in when:
        return when["family"] in fams
    return True


def _summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(results) or 1      # las ejecuciones rotas cuentan (score 0): nunca salen del N
    return {"n": len(results), "score": round(sum(r["metrics"]["score"] for r in results) / n, 3),
            "world_score": round(sum(r["metrics"].get("world_score", r["metrics"]["score"]) for r in results) / n, 3),
            "critical_failed": sum(r["metrics"]["critical_failed"] for r in results),
            "unsafe_actions": sum(r["metrics"]["unsafe_actions"] for r in results),
            "errors": sum(1 for r in results if r["metrics"].get("run_error"))}


class Reviewer:
    """Revisor determinista. `runner` es inyectable para los tests."""

    def __init__(self, agent: str = "mando", min_evidence: int = MIN_EVIDENCE, min_gain: float = MIN_GAIN,
                 max_validation: int = MAX_VALIDATION, max_candidates: int = 40, workers: int | None = None,
                 min_validation: int = MIN_VALIDATION, metric: str = "score",
                 bases: tuple[str, ...] = ("world", "operator", "grader"), ci_level: float = CI_LEVEL,
                 runner: Callable[..., list[dict[str, Any]]] | None = None) -> None:
        self.metric, self.bases, self.ci_level = metric, tuple(bases), ci_level
        self.agent, self.min_evidence, self.min_gain = agent, min_evidence, min_gain
        self.max_validation, self.max_candidates, self.workers = max_validation, max_candidates, workers
        self.min_validation = min_validation
        self.runner = runner or (lambda cases, lessons: run_many(cases, AgentFactory(self.agent, lessons), self.workers, detail=False))

    def validate(self, lesson: dict[str, Any], playbook: list[dict[str, Any]], validation: list[dict[str, Any]],
                 type_map: dict[str, set[str]] | None = None) -> Verdict:
        cases = [c for c in validation if _affects(lesson, c, type_map or {})][: self.max_validation]
        if len(cases) < self.min_validation:
            return Verdict(lesson, False, f"solo {len(cases)} casos de validación donde puede dispararse (mínimo {self.min_validation})", len(cases))
        before_runs = self.runner(cases, playbook)
        after_runs = self.runner(cases, playbook + [lesson])
        before, after = _summary(before_runs), _summary(after_runs)
        key = self.metric
        xb = [r["metrics"].get(key, r["metrics"]["score"]) for r in before_runs]
        xa = [r["metrics"].get(key, r["metrics"]["score"]) for r in after_runs]
        diff = M.paired_diff(xa, xb, self.ci_level)
        ci_b, ci_a = M.bootstrap_ci(xb, 500), M.bootstrap_ci(xa, 500)
        after.update(metric=key, paired=diff, unpaired_ci95={"before": list(ci_b), "after": list(ci_a)},
                     unpaired_no_overlap=bool(ci_a[0] > ci_b[1]))
        gain, n = diff["mean"], len(cases)
        ci_txt = f"IC {int(self.ci_level * 100)} % pareado [{diff['ci'][0]:+.2f}, {diff['ci'][1]:+.2f}]"
        if after["errors"] > before["errors"]:
            ok, why = False, "rompe ejecuciones"
        elif after["unsafe_actions"] > before["unsafe_actions"]:
            ok, why = False, f"empeora unsafe_actions ({before['unsafe_actions']} → {after['unsafe_actions']})"
        elif after["critical_failed"] > before["critical_failed"]:
            ok, why = False, f"empeora los críticos fallidos ({before['critical_failed']} → {after['critical_failed']})"
        elif not (diff["ci"][0] > 0 and gain >= self.min_gain):
            ok, why = False, f"no mejora la validación: {gain:+.2f} en {key}, {ci_txt} incluye el 0 (N={n})"
        else:
            ok, why = True, (f"mejora la validación {gain:+.2f} en {key}, {ci_txt} (N={n}; {diff['better']} casos mejor, "
                             f"{diff['worse']} peor) sin empeorar críticos ni seguridad")
        return Verdict(lesson, ok, why, len(cases), before, after)

    def review(self, results: list[dict[str, Any]], analysis_cases: list[dict[str, Any]],
               validation_cases: list[dict[str, Any]], playbook: list[dict[str, Any]], round_no: int = 1) -> dict[str, Any]:
        """`results`: ejecuciones (con `detail`) de `analysis_cases` con el manual actual."""
        by_id = {c["id"]: c for c in analysis_cases}
        results = [r for r in results if r["case_id"] in by_id]
        analysis = analyze(results, by_id)
        type_map: dict[str, set[str]] = defaultdict(set)
        for r in results:
            truth_inc = r.get("detail", {}).get("incidents", {})
            for ai in r.get("detail", {}).get("agent_incidents", []):
                for tid in ai.get("truth", []):
                    if tid in truth_inc and ai.get("type"):
                        type_map[ai["type"]].add(truth_inc[tid]["type"])
        have = {json.dumps([l.get("when"), l.get("then")], sort_keys=True) for l in playbook}
        candidates = [c for c in propose(analysis, self.min_evidence)
                      if c["basis"] in self.bases
                      and json.dumps([c["when"], c["then"]], sort_keys=True) not in have][: self.max_candidates]
        accepted, verdicts = list(playbook), []
        for c in candidates:
            lesson = {**c, "id": f"R{round_no}-{len(verdicts) + 1:03d}"}
            if any(_conflicts(lesson, l) for l in accepted[len(playbook):]):
                verdicts.append(Verdict(lesson, False, "otra lección de esta ronda ya cubre el mismo caso"))
                continue
            v = self.validate(lesson, accepted, validation_cases, type_map)
            verdicts.append(v)
            if v.accepted:
                lesson["validation"] = {"n": v.n_validation, "metric": self.metric, "before": v.before[self.metric],
                                        "after": v.after[self.metric], "paired": v.after["paired"],
                                        "unpaired_no_overlap": v.after["unpaired_no_overlap"]}
                accepted.append(lesson)
        return {"playbook": accepted, "new": accepted[len(playbook):], "verdicts": [v.to_dict() for v in verdicts],
                "n_patterns": len(analysis["patterns"]), "n_candidates": len(candidates)}


def _conflicts(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Misma condición y misma palanca (p. ej. dos `priority_boost` para el mismo tipo)."""
    return a.get("when") == b.get("when") and set(a.get("then", {})) & set(b.get("then", {})) \
        and not ({"pre_action"} >= (set(a.get("then", {})) & set(b.get("then", {}))))


class LLMReviewer(Reviewer):
    """GANCHO, sin implementar a propósito: aquí NO se llama a ninguna API.

    Idea: sustituir `propose()` por un modelo que lea los logs de los casos fallidos (`detail.log`) y
    redacte lecciones en el mismo formato JSON. Todo lo demás se hereda tal cual: la lección del modelo
    pasa por la MISMA validación cruzada y se rechaza si no mejora o si toca críticos/seguridad, de modo
    que un modelo que alucine no puede estropear el manual. Para activarlo: implementar
    `draft_lessons(failures: list[dict]) -> list[dict]` con el cliente que se elija y llamarlo desde
    `review()` en lugar de `propose()`."""

    def draft_lessons(self, failures: list[dict[str, Any]]) -> list[dict[str, Any]]:
        raise NotImplementedError("LLMReviewer es un gancho documentado: no llama a ninguna API")
