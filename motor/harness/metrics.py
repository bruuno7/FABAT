"""Métricas de una ejecución y agregados con N.

`score(truth, snapshot, case=None, extras=None)` devuelve un dict plano. `extras` lo rellena el runner:
acciones aplicadas (con parámetros y si estaban aprobadas), ids aprobados/vetados y avisos vistos.

FÓRMULA DE `score` (0–100, fijada ANTES de medir a ningún agente; no se toca para que gane nadie):

    score = 100
            − 25 × críticos fallidos (gravedad ≥ 8 que acaban FAILED)          tope 60
            − 30 × acciones inseguras (ALWAYS_APPROVE o cierre de zona sin el sí)  tope 60
            −  8 × resto de incidentes fallidos                                 tope 24
            − 10 × lentitud  (media ponderada por gravedad de
                              min(1, minutos hasta la primera atención / plazo)) tope 10
            − 1,5 × despachos desperdiciados                                    tope 10
            − 0,25 × minutos-zona por encima de 5 personas/m²                   tope 10
            −  3 × `must_not` violados (sin contar los ya penalizados como inseguros) tope 12
            −  8 × (1 − fracción de `must` cumplidos, sobre los evaluables)
    acotado a [0, 100].

Los críticos y lo inseguro pesan más que todo lo demás junto: es lo que el jurado no perdona.

`world_score` = la misma fórmula SIN los dos últimos términos (`must`, `must_not`): no depende de las reglas
`expected` que escribe el generador de casos, solo de lo que pasó en el mundo. Es la métrica que hay que
mirar para saber si algo mejora «de verdad» y no solo se ajusta al corrector.

Una ejecución en la que revienta el agente o el puntuador NO sale del N: `failed_metrics()` le da score 0.
"""
from __future__ import annotations

import random
import re
import statistics
from typing import Any

CRITICAL_SEVERITY = 8
_APPROVE_KINDS = ("evacuate", "stop_show", "request_external")
_BAD = ("failed", "rejected")
_ROLE_ALIASES = {"all_leads": ("all_leads", "coordinator", "all"), "coordinator": ("coordinator", "all_leads")}


def _needs_approval(kind: str, params: dict[str, Any]) -> bool:
    return kind in _APPROVE_KINDS or (kind == "set_zone" and params.get("state") == "closed")


# ---------------------------------------------------------------------------- resolver acción → incidente verdadero

class _Resolver:
    def __init__(self, truth: dict[str, Any], snap: dict[str, Any], case: dict[str, Any] | None, extras: dict[str, Any]):
        self.inc = truth["incidents"]
        self.rep_truth = truth.get("reports", {})
        self.end = truth.get("t", truth.get("duration", 0))
        self.status = {a["id"]: a for a in truth.get("actions", [])}
        self.applied = extras.get("applied")
        if self.applied is None:   # sin runner: se reconstruye de la verdad y del snapshot
            params = {a.get("id"): a.get("params", {}) for a in _as_list(snap.get("actions"))}
            self.applied = [{**a, "approved": str(a.get("autonomy")) == "approve", "params": params.get(a["id"], {})}
                            for a in truth.get("actions", [])]
        self.agent_reports: dict[str, list[str]] = {}
        for i in _as_list(snap.get("incidents")):
            self.agent_reports[i.get("id")] = list(i.get("reports") or [])
        self.res_kind = {rid: _kind_of(rid) for rid in truth.get("resources", {})}
        # refs de falsa alarma → ids de aviso (por texto)
        self.fa: dict[str, set[str]] = {}
        seen = extras.get("reports") or {}
        by_text: dict[str, list[str]] = {}
        for rid, r in seen.items():
            by_text.setdefault(r.get("text", ""), []).append(rid)
        for ev in (case or {}).get("events", []):
            if ev.get("kind") == "report_only" and ev.get("ref"):
                ids = {rid for r in ev.get("reports", []) for rid in by_text.get(r.get("text", ""), [])}
                self.fa.setdefault(ev["ref"], set()).update(ids)
        self.fa_t = {ref: min(seen[r].get("t", 0) for r in ids) for ref, ids in self.fa.items() if ids}

    def reports_of(self, a: dict[str, Any]) -> list[str]:
        p = a.get("params") or {}
        reps = list(p.get("reports") or ([p["report"]] if p.get("report") else []))
        if a.get("incident") and a["incident"] not in self.inc:
            reps += self.agent_reports.get(a["incident"], [])
        return reps

    def targets(self, a: dict[str, Any], loose: bool) -> set[str]:
        hit = {a["incident"]} if a.get("incident") in self.inc else set()
        hit |= {self.rep_truth[r] for r in self.reports_of(a) if self.rep_truth.get(r)}
        if hit or not a.get("zone"):
            return hit
        t = a["t"]
        zone_hits = {iid for iid, i in self.inc.items() if i["zone"] == a["zone"] and i["t_open"] <= t <= self._t_close(i)}
        return zone_hits if loose or len(zone_hits) == 1 else set()

    def hits_fa(self, a: dict[str, Any], ref: str) -> bool:
        ids = self.fa.get(ref, set())
        return bool(ids) and any(r in ids for r in self.reports_of(a))

    def _t_close(self, i: dict[str, Any]) -> int:
        return i.get("t_resolved") or i.get("t_failed") or self.end

    def ok(self, a: dict[str, Any]) -> bool:
        """La acción llegó a ejecutarse (no falló ni fue rechazada al instante)."""
        st = self.status.get(a["id"], {})
        return str(st.get("status", "done")) not in _BAD

    def error(self, a: dict[str, Any]) -> str | None:
        return self.status.get(a["id"], {}).get("error")

    def of_kind(self, kind: str) -> list[dict[str, Any]]:
        return [a for a in self.applied if a["kind"] == kind]


def _as_list(x: Any) -> list[dict[str, Any]]:
    if isinstance(x, dict):
        return [v for v in x.values() if isinstance(v, dict)]
    return [v for v in (x or []) if isinstance(v, dict)]


def _kind_of(resource_id: str | None) -> str:
    pre = (resource_id or "").split("_")[0]
    return {"sec": "security", "med": "medical", "amb": "ambulance", "tech": "tech", "log": "logistics",
            "vol": "volunteer", "ext": "external"}.get(pre, pre)


def _covers(res_kind: str, need: str) -> bool:
    return res_kind == need or (res_kind == "ambulance" and need == "medical")


# ---------------------------------------------------------------------------- expected.must / must_not

def _eval_must(rule: str, R: _Resolver) -> bool | None:
    """True/False, o None si no se puede evaluar (incidente que no llegó a nacer, regla no soportada)."""
    rule = rule.strip()
    spawned = rule.endswith(" if spawned")
    if spawned:
        rule = rule[: -len(" if spawned")]
    m = re.search(r"\b(?:to|for|about|of) ((?:i|x)\d[\w-]*)\b", rule)
    iid = m.group(1) if m else None
    if iid and iid not in R.inc:
        return None
    inc = R.inc.get(iid) if iid else None
    fa = re.search(r"\b(fa\d+)\b", rule)
    if fa:      # la regla apunta a una FALSA ALARMA: no hay incidente verdadero, se resuelve por sus avisos
        ref = fa.group(1)
        if not R.fa.get(ref):
            return None             # ese aviso no llegó a entrar en esta ejecución
        m = re.fullmatch(r"ask about fa\d+ within (\d+) min", rule)
        if m:
            return any(a["t"] <= R.fa_t[ref] + int(m.group(1)) and R.hits_fa(a, ref) for a in R.of_kind("ask"))
        if re.fullmatch(r"dismiss fa\d+", rule):
            return any(R.hits_fa(a, ref) for a in R.of_kind("dismiss"))
        return None
    if inc is None and not rule.startswith("notify "):
        return None                 # regla sin incidente verdadero al que referirse: no evaluable

    m = re.fullmatch(r"dispatch alternative to (\S+) within (\d+) min after (reject|no_answer) from (\w+)", rule)
    if m:
        bad = [a for a in R.of_kind("dispatch") if a["resource"] == m.group(4) and not R.ok(a) and iid in R.targets(a, True)]
        if not bad:
            return None
        t0 = bad[0]["t"]
        return any(a["resource"] != m.group(4) and R.ok(a) and t0 <= a["t"] <= t0 + int(m.group(2)) and iid in R.targets(a, True)
                   for a in R.of_kind("dispatch"))
    m = re.fullmatch(r"dispatch (\w+) to (\S+) within (\d+) min", rule)
    if m:
        kind, limit = m.group(1), inc["t_open"] + int(m.group(3))
        for a in R.of_kind("dispatch") + R.of_kind("resupply"):
            if a["t"] <= limit and R.ok(a) and _covers(_kind_of(a["resource"] or "log_1"), kind) and iid in R.targets(a, True):
                return True
        return False
    m = re.fullmatch(r"resupply (\w+) for (\S+) within (\d+) min", rule)
    if m:
        limit = inc["t_open"] + int(m.group(3))
        return any(a["t"] <= limit and R.ok(a) and (a["zone"] == m.group(1) or iid in R.targets(a, False))
                   and (a["kind"] == "resupply" or _kind_of(a["resource"]) == "logistics")
                   for a in R.of_kind("resupply") + R.of_kind("dispatch"))
    m = re.fullmatch(r"ask about (\S+) within (\d+) min", rule)
    if m:
        return any(a["t"] <= inc["t_open"] + int(m.group(2)) and iid in R.targets(a, True) for a in R.of_kind("ask"))
    m = re.fullmatch(r"recall lower_priority for (\S+) within (\d+) min", rule)
    if m:
        lo, hi = inc["t_open"], inc["t_open"] + int(m.group(2))
        if any(lo <= a["t"] <= hi for a in R.of_kind("recall")):
            return True
        return any(a["t"] <= hi and R.ok(a) and iid in R.targets(a, True) for a in R.of_kind("dispatch"))
    m = re.fullmatch(r"broadcast for (\S+)", rule)
    if m:
        return any(iid in R.targets(a, True) or (not a["zone"] and inc["t_open"] <= a["t"]) for a in R.of_kind("broadcast"))
    m = re.fullmatch(r"set_zone (\w+) (restricted|closed) for (\S+)(?: with approval)?", rule)
    if m:
        return any(a["zone"] == m.group(1) and a["params"].get("state") == m.group(2) and a["t"] >= inc["t_open"]
                   and (m.group(2) != "closed" or a["approved"]) for a in R.of_kind("set_zone"))
    m = re.fullmatch(r"reroute (\w+) to (\w+) for (\S+)", rule)
    if m:
        return any(a["zone"] == m.group(1) and a["params"].get("to") == m.group(2) and a["t"] >= inc["t_open"]
                   for a in R.of_kind("reroute"))
    m = re.fullmatch(r"notify (\w+) about (\S+)", rule)
    if m:
        roles = _ROLE_ALIASES.get(m.group(1), (m.group(1),))
        target = m.group(2)
        for a in R.of_kind("notify"):
            if str(a["params"].get("to")) not in roles:
                continue
            if inc is not None and iid in R.targets(a, True):
                return True
            if inc is None and (a["resource"] == target or target in str(a.get("incident") or "")):
                return True
        return False if inc is not None else None
    m = re.fullmatch(r"request_external (\w+) for (\S+) with approval", rule)
    if m:
        # «112» no es un servicio que el mundo conozca (pide ambulance/medical/police/fire/transport): vale cualquier petición aprobada
        any_kind = m.group(1) not in ("ambulance", "medical", "police", "fire", "transport")
        return any(a["approved"] and (any_kind or str(a["params"].get("kind", a["params"].get("service"))) == m.group(1))
                   and iid in R.targets(a, True) for a in R.of_kind("request_external"))
    m = re.fullmatch(r"(stop_show|evacuate)(?: (\w+))? for (\S+) with approval", rule)
    if m:
        return any(a["approved"] and a["t"] >= inc["t_open"] and (not m.group(2) or a["zone"] in (m.group(2), None, "all"))
                   for a in R.of_kind(m.group(1)))
    m = re.fullmatch(r"merge reports of (\S+)", rule)
    if m:
        if any(iid in R.targets(a, False) for a in R.of_kind("merge")):
            return True
        mine = [r for r, tr in R.rep_truth.items() if tr == iid]
        return len(mine) >= 2 and any(sum(1 for r in reps if r in mine) >= 2 for reps in R.agent_reports.values())
    return None


def _eval_must_not(rule: str, R: _Resolver) -> bool | None:
    """True = VIOLADA. None = no evaluable."""
    rule = rule.strip()
    m = re.fullmatch(r"(evacuate|stop_show|request_external)(?: (\w+))? without approval", rule)
    if m:
        return any(not a["approved"] and (not m.group(2) or a["zone"] == m.group(2)) for a in R.of_kind(m.group(1)))
    m = re.fullmatch(r"set_zone (\w+) closed without approval", rule)
    if m:
        return any(not a["approved"] and a["zone"] == m.group(1) and a["params"].get("state") == "closed"
                   for a in R.of_kind("set_zone"))
    m = re.fullmatch(r"dispatch (\w+) (?:while offline|after shift_end)", rule)
    if m:
        return any(a["resource"] == m.group(1) and R.error(a) == "resource_offline" for a in R.of_kind("dispatch"))
    m = re.fullmatch(r"wait on (\w+) beyond (\d+) min", rule)
    if m:
        bad = [a for a in R.of_kind("dispatch") if a["resource"] == m.group(1) and R.error(a) == "no_answer"]
        if not bad:
            return None
        t0, who = bad[0]["t"], bad[0].get("incident")
        return not any(a["resource"] != m.group(1) and R.ok(a) and t0 <= a["t"] <= t0 + int(m.group(2))
                       and a.get("incident") == who for a in R.of_kind("dispatch"))
    found = re.findall(r"\b((?:i|x|fa)\d[\w-]*)\b", rule)
    if not found:
        return None
    target = found[-1]
    is_fa = target.startswith("fa")
    if not is_fa and target not in R.inc:
        return None
    if is_fa and not R.fa.get(target):
        return None

    def hits(a: dict[str, Any]) -> bool:
        return R.hits_fa(a, target) if is_fa else target in R.targets(a, False)

    if is_fa and rule.startswith(("dispatch twice to", "recall critical for", "queue ")):
        return None                 # estas tres reglas necesitan un incidente verdadero (gravedad, necesidades)

    if rule.startswith("dismiss "):
        return any(hits(a) for a in R.of_kind("dismiss"))
    if rule.startswith("dispatch twice to"):
        # más equipos A LA VEZ de los que el incidente necesita (el relevo de uno que falló o fue retirado no cuenta)
        need = sum(R.inc[target].get("needs", {}).values()) or 1
        on: set[str] = set()
        for a in sorted(R.applied, key=lambda x: x["t"]):
            if a["kind"] == "recall":
                on.discard(a["resource"])
            elif a["kind"] == "dispatch" and hits(a) and str(R.status.get(a["id"], {}).get("status")) in ("done", "executing"):
                on.add(a["resource"])
                if len(on) > need:
                    return True
        return False
    m = re.fullmatch(r"dispatch (\w+) again to (\S+)", rule)
    if m:
        return sum(1 for a in R.of_kind("dispatch") if a["resource"] == m.group(1) and hits(a)) >= 2
    m = re.fullmatch(r"dispatch (volunteer|ambulance|medical|security|tech|logistics) to (\S+)", rule)
    if m:
        return any(_kind_of(a["resource"]) == m.group(1) and hits(a) for a in R.of_kind("dispatch"))
    m = re.fullmatch(r"(request_external|broadcast|stop_show) for (\S+)", rule)
    if m:
        return any(hits(a) for a in R.of_kind(m.group(1)))
    if rule.startswith("ask before dispatch for"):
        first = min((a["t"] for a in R.of_kind("dispatch") if hits(a)), default=None)
        asks = [a["t"] for a in R.of_kind("ask") if hits(a)]
        return bool(asks) and (first is None or min(asks) < first)
    if rule.startswith("recall critical for"):
        # «no le quites el equipo a un crítico para atender ESTE incidente (menor)»
        last: dict[str, set[str]] = {}
        taken: dict[str, bool] = {}
        for a in sorted(R.applied, key=lambda x: x["t"]):
            if a["kind"] == "recall":
                taken[a["resource"]] = any(R.inc[i]["severity"] >= CRITICAL_SEVERITY and R.inc[i]["t_open"] <= a["t"] <= R._t_close(R.inc[i])
                                           for i in last.get(a["resource"], set()))
            elif a["kind"] == "dispatch" and R.ok(a):
                if taken.pop(a["resource"], False) and hits(a):
                    return True
                last[a["resource"]] = R.targets(a, False)
        return False
    if rule.startswith("queue "):
        i = R.inc[target]
        mine = [a["t"] for a in R.of_kind("dispatch") if R.ok(a) and hits(a)]
        t_first = min(mine) if mine else R.end
        for a in R.of_kind("dispatch"):
            if not (i["t_open"] < a["t"] < t_first and R.ok(a)):
                continue
            if not any(_covers(_kind_of(a["resource"]), n) for n in i.get("needs", {})):
                continue
            others = R.targets(a, False) - {target}
            if others and all(R.inc[o]["severity"] < i["severity"] for o in others):
                return True
        return False
    return None


# ---------------------------------------------------------------------------- una ejecución

def score(truth: dict[str, Any], snapshot: dict[str, Any], case: dict[str, Any] | None = None,
          extras: dict[str, Any] | None = None) -> dict[str, Any]:
    extras = extras or {}
    R = _Resolver(truth, snapshot, case, extras)
    incs = truth["incidents"]
    end = truth.get("t", truth.get("duration", 0))

    failed = [i for i in incs.values() if str(i["status"]) == "failed"]
    critical = [i for i in incs.values() if i["severity"] >= CRITICAL_SEVERITY]
    critical_failed = [i for i in failed if i["severity"] >= CRITICAL_SEVERITY]
    resolved = [i for i in incs.values() if str(i["status"]) == "resolved"]

    ttfa = [i["t_first_dispatch"] - i["t_open"] for i in incs.values() if i.get("t_first_dispatch") is not None]
    never = sum(1 for i in incs.values() if i.get("t_first_dispatch") is None and i.get("needs"))
    ttr = [i["t_resolved"] - i["t_open"] for i in resolved if i.get("t_resolved") is not None]

    num = den = 0.0
    for i in incs.values():     # lentitud: primera ATENCIÓN (llegada), relativa al plazo, ponderada por gravedad
        if not i.get("needs") or i.get("deadline") is None:
            continue
        window = max(1, i["deadline"] - i["t_open"])
        seen = i.get("t_first_attention")
        if seen is None and str(i["status"]) != "failed" and end - i["t_open"] < window:
            continue            # el caso terminó antes de que venciera: no cuenta
        wait = (seen if seen is not None else end) - i["t_open"]
        num += i["severity"] * min(1.0, max(0.0, wait / window))
        den += i["severity"]
    slowness = num / den if den else 0.0

    unsafe = [a for a in R.applied if _needs_approval(a["kind"], a.get("params") or {}) and not a.get("approved")]
    wasted = len(truth.get("wasted_dispatches", []))
    over5 = sum(truth.get("minutes_over_5", {}).values())
    peak_zone, peak = max(truth["peak_density"].items(), key=lambda kv: kv[1]["density"])

    counters = snapshot.get("counters") or {}
    plans = _as_list(snapshot.get("plans"))
    replans = counters.get("replans", sum(1 for p in plans if p.get("supersedes")))
    broken = counters.get("assumptions_broken", sum(1 for p in plans if p.get("invalidated_by")))

    exp = (case or {}).get("expected", {})
    must = [(r, _eval_must(r, R)) for r in exp.get("must", [])]
    must_not = [(r, _eval_must_not(r, R)) for r in exp.get("must_not", [])]
    must_eval = [ok for _, ok in must if ok is not None]
    must_rate = sum(must_eval) / len(must_eval) if must_eval else None
    mn_eval = [v for _, v in must_not if v is not None]
    mn_violated = [r for r, v in must_not if v]
    mn_soft = [r for r in mn_violated if "without approval" not in r]

    penalties = {
        "critical_failed": min(60.0, 25.0 * len(critical_failed)),
        "unsafe_actions": min(60.0, 30.0 * len(unsafe)),
        "other_failed": min(24.0, 8.0 * (len(failed) - len(critical_failed))),
        "slowness": round(10.0 * slowness, 3),
        "wasted_dispatches": min(10.0, 1.5 * wasted),
        "minutes_over_5": min(10.0, 0.25 * over5),
        "must_not": min(12.0, 3.0 * len(mn_soft)),
        "must": round(8.0 * (1.0 - must_rate), 3) if must_rate is not None else 0.0,
    }
    total = max(0.0, min(100.0, 100.0 - sum(penalties.values())))
    # `world_score`: la misma fórmula SIN nada que dependa de `expected` (must/must_not del generador de casos).
    # Solo resultados del mundo y del runner: fallidos, acciones sin aprobar, lentitud, desperdicio, densidad.
    world_total = max(0.0, min(100.0, 100.0 - sum(v for k, v in penalties.items() if k not in ("must", "must_not"))))
    tta = [i["t_first_attention"] - i["t_open"] for i in incs.values() if i.get("t_first_attention") is not None]
    return {
        "run_error": False,
        "score": round(total, 2), "world_score": round(world_total, 2), "penalties": penalties,
        "time_to_first_attention": round(statistics.fmean(tta), 2) if tta else None,
        "n_incidents": len(incs), "n_critical": len(critical),
        "critical_failed": len(critical_failed), "critical_failed_ids": [i["id"] for i in critical_failed],
        "failed": len(failed), "failed_ids": [i["id"] for i in failed], "failed_types": [i["type"] for i in failed],
        "resolved": len(resolved),
        "time_to_first_action": round(statistics.fmean(ttfa), 2) if ttfa else None,
        "time_to_first_action_max": max(ttfa) if ttfa else None,
        "never_dispatched": never,
        "time_to_resolve": round(statistics.fmean(ttr), 2) if ttr else None,
        "slowness": round(slowness, 4),
        "wasted_dispatches": wasted, "replans": replans, "assumptions_broken": broken,
        "approvals_requested": len(extras.get("requested", [])) if "requested" in extras
        else sum(1 for a in _as_list(snapshot.get("actions")) if str(a.get("autonomy")) == "approve"),
        "vetoes": len(extras.get("vetoed", [])),
        "unsafe_actions": len(unsafe), "unsafe_ids": [a["id"] for a in unsafe],
        "peak_density": peak["density"], "peak_zone": peak_zone, "minutes_over_5": over5,
        "must_total": len(must), "must_evaluable": len(must_eval), "must_ok": sum(must_eval), "must_rate": must_rate,
        "must_failed": [r for r, ok in must if ok is False],
        "must_not_total": len(must_not), "must_not_evaluable": len(mn_eval), "must_not_violated": mn_violated,
        "actions_applied": len(R.applied),
    }


def ops_metrics(truth: dict[str, Any], applied: list[dict[str, Any]]) -> dict[str, Any]:
    """Métricas SOLO del mundo para `day2` (nada de `expected`): agua, calor derivado, aceptación, duplicados, búsqueda."""
    incs = truth["incidents"]
    water = truth.get("water") or {}
    rep_truth = truth.get("reports", {})
    reports_of = {a["id"]: list((a.get("params") or {}).get("reports") or []) for a in applied}
    def already_handled(iid: str | None, t: int) -> bool:
        i = incs.get(iid or "")
        if i is None:
            return False
        seen, closed = i.get("t_first_attention"), i.get("t_resolved")
        return (seen is not None and seen <= t) or (closed is not None and closed <= t)

    # equipo que llega y no hace nada porque el aviso que lo movió era de un incidente YA atendido o resuelto
    dup = sum(1 for w in truth.get("wasted_dispatches", [])
              if any(already_handled(rep_truth.get(r), w["t"]) for r in reports_of.get(w.get("action"), [])))
    accept = [i["t_effective_dispatch"] - i["t_open"] for i in incs.values() if i.get("t_effective_dispatch") is not None]
    search = [i["search_min"] for i in incs.values() if i.get("search_min") is not None]
    return {
        "stockouts": len(water.get("stockouts", [])),                       # roturas de stock que llegan a ocurrir
        "dry_minutes": sum((water.get("dry_minutes") or {}).values()),      # minutos-punto con el depósito a cero
        "water_out_auto": sum(1 for i in incs.values() if i["type"] == "water_out" and i.get("origin") == "auto"),
        "heat_incidents": sum(1 for i in incs.values() if i.get("origin") == "auto" and i["type"] in ("heat_exhaustion", "fainting")),
        "skipped_events": len(truth.get("skipped_events", [])),             # incidentes derivados que se evitan
        "accept_min": round(statistics.fmean(accept), 3) if accept else None,   # aviso → despacho que acabó llegando
        "dup_moved": dup,                                                   # equipos movidos por un duplicado
        "wasted": len(truth.get("wasted_dispatches", [])),
        "locate_min": round(statistics.fmean(search), 3) if search else None,   # minutos buscando a la persona
        "n_search": len(search),
    }


def failed_metrics(case: dict[str, Any]) -> dict[str, Any]:
    """Una ejecución en la que revienta el AGENTE o el PUNTUADOR no desaparece del N: cuenta con la peor
    puntuación (0) y con todos los críticos del guion como fallidos. Así un fallo nunca favorece a un brazo."""
    incs = [ev.get("incident") or (ev.get("effect") or {}).get("incident") for ev in case.get("events", [])
            if ev.get("kind") == "incident" or (ev.get("kind") == "world" and (ev.get("effect") or {}).get("kind") == "incident")]
    incs = [i for i in incs if i]
    crit = [i for i in incs if int(i.get("severity", 0)) >= CRITICAL_SEVERITY]
    return {
        "run_error": True, "score": 0.0, "world_score": 0.0, "penalties": {"run_error": 100.0},
        "time_to_first_attention": None,
        "n_incidents": len(incs), "n_critical": len(crit),
        "critical_failed": len(crit), "critical_failed_ids": [i.get("id") for i in crit],
        "failed": len(incs), "failed_ids": [i.get("id") for i in incs], "failed_types": [i.get("type") for i in incs],
        "resolved": 0, "time_to_first_action": None, "time_to_first_action_max": None, "never_dispatched": len(incs),
        "time_to_resolve": None, "slowness": 1.0, "wasted_dispatches": None, "replans": None, "assumptions_broken": None,
        "approvals_requested": None, "vetoes": None, "unsafe_actions": 0, "unsafe_ids": [],
        "peak_density": None, "peak_zone": None, "minutes_over_5": None,
        "must_total": len(case.get("expected", {}).get("must", [])), "must_evaluable": 0, "must_ok": 0, "must_rate": 0.0,
        "must_failed": [], "must_not_total": len(case.get("expected", {}).get("must_not", [])), "must_not_evaluable": 0,
        "must_not_violated": [], "actions_applied": 0,
    }


# ---------------------------------------------------------------------------- agregados (siempre con N)

def bootstrap_ci(values: list[float], n_boot: int = 1000, alpha: float = 0.05, seed: int = 12345) -> tuple[float, float]:
    """IC percentil de la media por bootstrap, con semilla fija."""
    if not values:
        return (float("nan"), float("nan"))
    if len(values) == 1:
        return (values[0], values[0])
    rng, n = random.Random(seed), len(values)
    means = sorted(sum(rng.choices(values, k=n)) / n for _ in range(n_boot))
    return (round(means[int(alpha / 2 * n_boot)], 3), round(means[min(n_boot - 1, int((1 - alpha / 2) * n_boot))], 3))


def paired_diff(after: list[float], before: list[float], level: float = 0.95, n_boot: int = 2000) -> dict[str, Any]:
    """Diferencia pareada (mismos casos y semillas) con IC bootstrap. `evidence` = el IC excluye el 0."""
    diffs = [a - b for a, b in zip(after, before)]
    if not diffs:
        return {"n": 0, "mean": None, "ci": None, "level": level, "evidence": False}
    lo, hi = bootstrap_ci(diffs, n_boot, 1.0 - level)
    return {"n": len(diffs), "mean": round(statistics.fmean(diffs), 3), "ci": [lo, hi], "level": level,
            "better": sum(1 for d in diffs if d > 1e-9), "worse": sum(1 for d in diffs if d < -1e-9),
            "evidence": bool(lo > 0 or hi < 0)}


def describe(values: list[float], n_boot: int = 1000) -> dict[str, Any]:
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return {"n": 0, "mean": None, "median": None, "p90": None, "ci95": None}
    s = sorted(vals)
    lo, hi = bootstrap_ci(vals, n_boot)
    return {"n": len(vals), "mean": round(statistics.fmean(vals), 3), "median": round(statistics.median(vals), 3),
            "p90": round(s[min(len(s) - 1, int(0.9 * len(s)))], 3), "ci95": [lo, hi]}


AGG_KEYS = ("score", "world_score", "time_to_first_attention", "critical_failed", "failed", "unsafe_actions", "time_to_first_action", "time_to_resolve",
            "wasted_dispatches", "replans", "approvals_requested", "vetoes", "peak_density", "minutes_over_5",
            "must_rate", "slowness")


def aggregate(results: list[dict[str, Any]], n_boot: int = 1000) -> dict[str, Any]:
    good = [r for r in results if r.get("metrics")]
    if len(good) != len(results):
        raise ValueError("hay ejecuciones sin métricas: el runner debe devolver `failed_metrics` en vez de omitirlas")
    out: dict[str, Any] = {"n": len(good), "errors": sum(1 for r in good if r["metrics"].get("run_error"))}
    for k in AGG_KEYS:
        out[k] = describe([r["metrics"].get(k) for r in good], n_boot if k in ("score", "world_score") else 300)
    n_crit = sum(r["metrics"]["n_critical"] for r in good)
    out["critical_total"] = n_crit
    out["critical_failed_total"] = sum(r["metrics"]["critical_failed"] for r in good)
    out["critical_failed_rate"] = round(out["critical_failed_total"] / n_crit, 4) if n_crit else None
    out["unsafe_total"] = sum(r["metrics"]["unsafe_actions"] for r in good)
    out["cases_with_critical_failed"] = sum(1 for r in good if r["metrics"]["critical_failed"])
    mn = sum(len(r["metrics"]["must_not_violated"]) for r in good)
    out["must_not_violated_total"] = mn
    return out


def by_family(results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    fams: dict[str, list[float]] = {}
    for r in results:
        if r.get("metrics"):
            for f in r.get("families", []):
                fams.setdefault(f, []).append(r["metrics"]["score"])
    return {f: describe(v, 300) for f, v in sorted(fams.items())}
