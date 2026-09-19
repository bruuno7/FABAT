"""Informe posterior, para leer en diez segundos: qué pasó, qué decidió Mando, qué supuestos se
rompieron, QUÉ HIZO MAL y qué cambiaría. `build(mando)` devuelve el dict; `render(dict)` el texto.

`would_change` son lecciones candidatas en el formato de `playbook.py` (sin validar: las valida el revisor).
"""
from __future__ import annotations

from typing import Any

from ..contracts import ActionKind, ActionStatus, IncidentStatus
from .planner import DEST_RATIO, es, label

SLOW_FIRST_ACTION = 2   # minutos hasta la primera acción que ya cuentan como tiempo perdido en algo grave


def build(mando: Any) -> dict[str, Any]:
    incidents = list(mando.incidents.values())
    by_status: dict[str, int] = {}
    for i in incidents:
        by_status[str(i.status)] = by_status.get(str(i.status), 0) + 1

    decisions = [{"t": e.t, "text": e.text} for e in mando.log if e.kind == "plan"]
    broken = []
    for e in mando.log:
        if e.kind == "assumption_broken":
            check = e.data.get("check", {})
            broken.append({"t": e.t, "plan": e.data.get("plan"), "incident": e.data.get("incident"), "text": e.text,
                           "kind": check.get("kind"), "zone": check.get("zone"),
                           "self_inflicted": check.get("own_action") is not None})

    mistakes: list[dict[str, Any]] = []
    for i in incidents:
        m = mando.meta[i.id]
        if m.origin == "pattern":
            continue
        first = m.first_action_t
        if i.severity >= 7 and i.status != IncidentStatus.FALSE_ALARM:
            if first is None:
                mistakes.append({"kind": "never_acted", "incident": i.id, "minutes": mando.t - i.t_open,
                                 "text": f"{i.id} ({label(i)}, gravedad {i.severity}) se quedó sin ninguna acción"})
            elif first - i.t_open > SLOW_FIRST_ACTION:
                mistakes.append({"kind": "slow_first_action", "incident": i.id, "minutes": first - i.t_open,
                                 "text": f"{i.id} ({label(i)}): {first - i.t_open} min hasta la primera acción"})
    for e in mando.log:
        if e.data.get("wasted"):
            mistakes.append({"kind": "wasted_dispatch", "incident": e.data.get("incident"), "minutes": None, "text": e.text})
    failed = [a for a in mando.actions.values() if a.kind == ActionKind.DISPATCH
              and a.status in (ActionStatus.REJECTED, ActionStatus.FAILED)]
    for a in failed:
        nxt = min((b.t for b in mando.actions.values() if b.kind == ActionKind.DISPATCH and b.incident == a.incident
                   and b.t > a.t), default=None)
        lost = (nxt - a.t) if nxt is not None else None
        mistakes.append({"kind": "dispatch_failed", "incident": a.incident, "minutes": lost,
                         "text": f"{a.resource} no fue a {a.incident} ({a.params.get('error', a.status)})"
                                 + (f": {lost} min perdidos hasta el siguiente" if lost is not None else ": sin relevo")})
    for b in broken:
        if b["self_inflicted"]:
            mistakes.append({"kind": "self_inflicted", "incident": b["incident"], "minutes": None,
                             "text": f"el desvío de Mando contribuyó a saturar {b['zone']} (t={b['t']})"})
    for iid, kinds in mando._waiting.items():
        i = mando.incidents[iid]
        mistakes.append({"kind": "queued", "incident": iid, "minutes": mando.t - i.t_open,
                         "text": f"{iid} ({label(i)}) sigue esperando {', '.join(kinds)}"})

    would_change: list[dict[str, Any]] = list(mando.lesson_candidates)
    n = len(would_change)
    for b in broken:
        if b["kind"] == "zone_occupancy_below" and b["self_inflicted"]:
            inc = mando.incidents.get(b["incident"])
            n += 1
            would_change.append({
                "id": f"C-{n:03d}", "when": {"type": inc.type if inc else None, "zone": inc.zone if inc else None},
                "then": {"assumption_threshold": {"zone_occupancy_below": {"ratio": round(DEST_RATIO - 0.1, 2)}}},
                "text": f"desviar desde {inc.zone if inc else '?'} con más margen: {b['zone']} se saturó con el umbral actual",
                "source": "informe de Mando", "evidence_n": 1})
    rejected_by: dict[str, int] = {}
    for a in failed:
        rejected_by[a.resource] = rejected_by.get(a.resource, 0) + 1
    for rid, k in sorted(rejected_by.items()):
        if k >= 2:
            n += 1
            would_change.append({"id": f"C-{n:03d}", "when": {}, "then": {"forbid_action": {"kind": "dispatch", "resource": rid}},
                                 "text": f"{rid} falló {k} veces: no contar con él sin confirmar antes",
                                 "source": "informe de Mando", "evidence_n": k})

    lost = sum(x["minutes"] or 0 for x in mistakes if x["kind"] in ("slow_first_action", "dispatch_failed"))
    return {
        "t_end": mando.t, "incidents_total": len(incidents), "incidents_by_status": by_status,
        "counters": dict(mando.counters), "decisions": decisions, "assumptions_broken": broken,
        "mistakes": mistakes, "minutes_lost": lost, "would_change": would_change,
        "lessons_applied": dict(mando.lessons_applied),
    }


def render(r: dict[str, Any]) -> str:
    c = r["counters"]
    st = r["incidents_by_status"]
    lines = [
        f"INFORME DE MANDO · {r['t_end']} min",
        f"Qué pasó: {c['reports']} avisos → {r['incidents_total']} incidentes ({c['merges']} avisos fundidos, "
        f"{c['false_alarms']} falsas alarmas, {c['patterns']} patrones). Resueltos {st.get('resolved', 0)}, "
        f"abiertos {st.get('open', 0) + st.get('assigned', 0) + st.get('in_progress', 0)}.",
        f"Qué decidió: {len(r['decisions'])} planes, {c['replans']} replanificaciones, {c['recalls']} recursos retirados "
        f"a algo más grave, {c['asks']} preguntas, {c['approvals']} aprobaciones pedidas ({c['vetoes']} vetadas).",
    ]
    if r["assumptions_broken"]:
        lines.append(f"Supuestos rotos ({len(r['assumptions_broken'])}):")
        lines += [f"  · t={b['t']} {b['text'][:150]}" for b in r["assumptions_broken"][:5]]
    else:
        lines.append("Supuestos rotos: ninguno.")
    if r["mistakes"]:
        lines.append(f"Qué hice mal ({len(r['mistakes'])}; {es(r['minutes_lost'], 0)} min perdidos):")
        lines += [f"  · {x['text'][:150]}" for x in r["mistakes"][:6]]
    else:
        lines.append("Qué hice mal: nada medible en esta ejecución.")
    if r["would_change"]:
        lines.append("Qué cambiaría (lecciones candidatas):")
        lines += [f"  · {x['id']}: {x['text'][:140]}" for x in r["would_change"][:5]]
    if r["lessons_applied"]:
        lines.append("Lecciones del manual aplicadas: " + ", ".join(f"{k} ×{v}" for k, v in sorted(r["lessons_applied"].items())))
    return "\n".join(lines)


def report(mando: Any) -> tuple[str, dict[str, Any]]:
    data = build(mando)
    return render(data), data
