"""Vistas derivadas para la pantalla: funciones puras sobre el `snapshot()` del agente y el estado del mundo.

Todo es tolerante: si Mando todavía no expone `fronts`, `decision_card` o el ensayo, se deriva lo que se pueda de lo
que sí hay, y nunca se inventa una cifra (lo que falta sale como `None`).
"""
from __future__ import annotations

import re
from typing import Any

CLOSED = ("resolved", "false_alarm", "failed")
STATE_ES = {"open": "sin asignar", "assigned": "equipo en camino", "in_progress": "atendido en el sitio",
            "resolved": "resuelto", "false_alarm": "falsa alarma", "failed": "fallido"}
_BARE = ("general", "vip", "pmr", "food", "toilets", "backstage")


class Humanizer:
    """Cambia ids por nombres legibles en cualquier texto que vaya a la pantalla (nada de `front_pit`)."""

    def __init__(self, zones: dict[str, str], resources: dict[str, str]) -> None:
        self.names = {**zones, **resources}
        ids = sorted((k for k in self.names if "_" in k), key=len, reverse=True)
        self._ids = re.compile(r"\b(" + "|".join(map(re.escape, ids)) + r")\b") if ids else None
        bare = [b for b in _BARE if b in zones]
        # ids que también son palabras («general»): solo tras un verbo en mayúsculas o una flecha, como los escribe Mando
        self._bare = re.compile(r"(?<=[A-ZÁÉÍÓÚÑ] |→ )(" + "|".join(bare) + r")\b") if bare else None

    def __call__(self, text: Any) -> Any:
        if not isinstance(text, str) or not text:
            return text
        if self._ids is not None:
            text = self._ids.sub(lambda m: self.names[m.group(1)], text)
        if self._bare is not None:
            text = self._bare.sub(lambda m: self.names[m.group(1)], text)
        return text


def mask_reserved(incidents: list[dict[str, Any]], reports: list[dict[str, Any]], plans: list[dict[str, Any]],
                  log: list[dict[str, Any]]) -> set[str]:
    """Incidentes `reserved: true` (agresión, menores…): en pantalla solo «incidente reservado», sin texto ni zona
    exacta. Se enmascara en el servidor para que el detalle no llegue a ningún navegador."""
    ids = {i["id"] for i in incidents if i.get("reserved")}
    if not ids:
        return ids
    for i in incidents:
        if i["id"] in ids:
            i.update(label="Incidente reservado", type="reserved", zone=None, zone_masked=True, explain="", notes=[])
    for r in reports:
        if r.get("incident") in ids:
            r.update(text="(aviso reservado)", zone_hint=None, source="")
    for p in plans:
        if p.get("incident") in ids:
            p["objective"] = "Incidente reservado: atención discreta"
            for s in p.get("steps", []):
                s.update(why="", reason=None, zone=None)
    for e in log:
        if (e.get("data") or {}).get("incident") in ids or e.get("ref") in ids:
            e["text"] = "Actuación sobre un incidente reservado"
    return ids


def fronts(snap: dict[str, Any], incidents: list[dict[str, Any]], actions: list[dict[str, Any]],
           resources: dict[str, dict[str, Any]], zone_names: dict[str, str], t: int) -> list[dict[str, Any]]:
    """Tablero de frentes: una fila por incidente vivo. Usa `snapshot()["fronts"]` si Mando lo da; si no, lo deriva."""
    given = {}
    for f in snap.get("fronts") or []:
        if isinstance(f, dict):
            given[f.get("incident") or f.get("id")] = f
    out = []
    for i in incidents:
        if i.get("status") in CLOSED:
            continue
        g = given.get(i["id"], {})
        assigned = g.get("team") or g.get("resources") or ([g["resource"]] if g.get("resource") else None) or i.get("assigned") or []
        assigned = [(r.get("resource") or r.get("id") or "") if isinstance(r, dict) else str(r) for r in assigned]  # Mando da {resource, status, eta}
        etas = [resources[r]["eta"] for r in assigned if r in resources and resources[r].get("status") == "en_route" and resources[r].get("eta")]
        mine = [a for a in actions if a.get("incident") == i["id"]]
        why = g.get("why_waiting") or g.get("waiting_why") or g.get("why") or ""
        if not why:
            if any(a.get("status") == "awaiting_approval" for a in mine):
                why = "espera la decisión de una persona"
            elif i.get("waiting"):
                why = "falta " + ", ".join(i["waiting"]) + ": todos ocupados en algo más prioritario"
            elif i.get("hold"):
                why = "sin confirmar: Mando ha preguntado antes de gastar un equipo"
            elif any(a.get("kind") == "ask" and a.get("status") == "executing" for a in mine):
                why = "espera respuesta a una pregunta"
        out.append({
            "id": i["id"], "label": i.get("label") or str(i.get("type", "")).replace("_", " "),
            "zone": i.get("zone"), "zone_name": zone_names.get(i.get("zone") or "", "zona sin confirmar") if not i.get("zone_masked") else "zona reservada",
            "priority": g.get("priority", i.get("priority")), "severity": i.get("severity"),
            "state": STATE_ES.get(str(g.get("state") or g.get("status") or i.get("status")),
                                  str(g.get("state") or g.get("status") or i.get("status"))),
            "resources": [resources.get(r, {}).get("name", r) for r in assigned],
            "eta": g.get("eta", min(etas) if etas else None), "why_waiting": why,
            "new": t - int(i.get("t_open") or 0) <= 3, "life_threat": bool(i.get("life_threat")),
            "unforeseen": any(str(r).startswith("j-") for r in i.get("reports", [])) or i.get("origin") in ("jury", "inject"),
            "reserved": bool(i.get("zone_masked")), "replans": i.get("replans", 0), "reports": len(i.get("reports", [])),
        })
    out.sort(key=lambda f: -(f["priority"] or 0))
    return out


_FIG_ES = {"peak_density": "personas/m² de pico", "minutes_over_4": "min por encima de 4/m²", "minutes_over_5": "min por encima de 5/m²",
           "crush_at_min": "min hasta riesgo de aplastamiento", "critical_failed": "críticos fallidos", "eta": "min de llegada"}


def _branch(x: Any) -> dict[str, Any] | None:
    """Un futuro ENSAYADO. Mando da cifras (`peak_density`, `minutes_over_4`, `crush_at_min`, `minutes`); aquí solo se rotulan."""
    if x is None:
        return None
    if isinstance(x, str):
        return {"text": x, "figures": []}
    if isinstance(x, dict):
        text = x.get("text") or x.get("summary") or x.get("resumen") or ""
        figs = [{"k": _FIG_ES[k], "v": x[k]} for k in _FIG_ES if isinstance(x.get(k), (int, float)) and not isinstance(x.get(k), bool)]
        if not text and x.get("crush_at_min") is not None:
            text = f"riesgo de aplastamiento en {x['crush_at_min']} min"
        return {"text": text, "figures": figs[:3], "horizon_min": x.get("minutes")}
    return {"text": str(x), "figures": []}


def decision_card(action: dict[str, Any], t: int) -> dict[str, Any] | None:
    """Normaliza `params["decision_card"]`: a quién va (cargo y suplente), los dos futuros ENSAYADOS, ventana y escalada."""
    card = (action.get("params") or {}).get("decision_card")
    if not isinstance(card, dict):
        return None
    to = card.get("to") or card.get("recipient") or card.get("addressee") or {}
    if isinstance(to, str):
        to = {"role": to}
    opened = int(card.get("asked_at", card.get("opened_t", action.get("t") or 0)))
    window = card.get("window_min", card.get("window", card.get("ventana_min")))
    escalate = card.get("escalate_t", card.get("escalate_at", card.get("escalation_t")))
    if escalate is None and card.get("escalate_after_min") is not None:
        escalate = opened + int(card["escalate_after_min"])
    deadline = opened + int(window) if window is not None else None
    return {
        "role": to.get("role") or to.get("cargo") or "Director del Plan de Actuación",
        "name": to.get("name") or to.get("nombre"),
        "deputy": to.get("deputy") or to.get("suplente") or card.get("deputy") or card.get("suplente"),
        "if_approved": _branch(card.get("if_approved")), "if_vetoed": _branch(card.get("if_vetoed")),
        "window_min": window, "opened_t": opened, "deadline_t": deadline,
        "remaining_min": None if deadline is None else max(0, deadline - t),
        "escalate_t": escalate, "escalated": card.get("escalated_at") is not None or (escalate is not None and t >= int(escalate)),
        "rehearsed": bool(card.get("rehearsed", card.get("if_approved") is not None)),
        "question": card.get("question") or card.get("pregunta"),
    }


def rehearsal(plan: dict[str, Any], log: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    """La línea del ENSAYO: «todo a Puerta A → 6,4/m² ✗ · reparto A+C → 3,1/m² ✓». La escribe Mando en el plan
    (`rehearsal` / `ensayo`) o en el log; aquí solo se le da forma. Si no hay ensayo, None: no se inventa."""
    raw = plan.get("rehearsal") or plan.get("ensayo") or plan.get("rehearsed")
    if raw is None:
        entry = next((e for e in reversed(log) if (e.get("kind") in ("rehearsal", "ensayo") or (e.get("data") or {}).get("rehearsal"))
                      and ((e.get("data") or {}).get("plan") == plan.get("id") or e.get("ref") == plan.get("id"))), None)
        if entry is not None:
            raw = (entry.get("data") or {}).get("options") or entry.get("text")
    if raw is None:
        return None
    if isinstance(raw, str):
        # Mando lo escribe así: «ENSAYO (12 min) para Puerta B: 60 % a Puerta A → Puerta A 2,1/m² en 12 min ✓ · sin desvío → … ✗»
        head, _, body = raw.partition(": ")
        opts = []
        for part in (body or head).split(" · "):
            ok = True if "✓" in part else False if "✗" in part else None
            label, _, result = part.replace("✓", "").replace("✗", "").strip().partition(" → ")
            opts.append({"label": label.strip(), "value": result.strip() or None, "unit": "", "ok": ok, "chosen": None})
        return opts or None
    if isinstance(raw, dict):
        raw = raw.get("options") or raw.get("opciones") or [raw]
    out = []
    for o in raw:
        if isinstance(o, str):
            out.append({"label": o, "value": None, "ok": None, "chosen": None})
        elif isinstance(o, dict):
            value = next((o[k] for k in ("value", "result", "peak_density", "density", "pico") if o.get(k) is not None), None)
            out.append({"label": str(o.get("label") or o.get("option") or o.get("name") or ""), "value": value,
                        "unit": o.get("unit") or ("/m²" if isinstance(value, (int, float)) else ""),
                        "ok": o.get("ok", o.get("passes")), "chosen": o.get("chosen", o.get("elegida"))})
    return out or None


def score_strikes(strikes: list[dict[str, Any]], truth_incidents: dict[str, dict[str, Any]], t: int, done: bool,
                  grace_min: int = 12) -> dict[str, Any]:
    """Marcador JURADO — MANDO. Un golpe puntúa para el jurado si tras él (y antes del golpe siguiente) falla un
    incidente crítico; para Mando, si pasan `grace_min` minutos (o acaba el caso) sin que eso ocurra."""
    fails = sorted(int(i["t_failed"]) for i in truth_incidents.values()
                   if int(i.get("severity", 0)) >= 8 and str(i.get("status")) == "failed" and i.get("t_failed") is not None)
    jury = mando = 0
    for n, s in enumerate(strikes):
        nxt = strikes[n + 1]["t"] if n + 1 < len(strikes) else 10 ** 9
        hit = any(s["t"] <= f < nxt for f in fails)
        s["outcome"] = "failed" if hit else "absorbed" if (done or t - s["t"] >= grace_min or nxt <= t) else "pending"
        jury += s["outcome"] == "failed"
        mando += s["outcome"] == "absorbed"
    return {"jury": jury, "mando": mando}


def strike_consequences(strikes: list[dict[str, Any]], agent_log: list[dict[str, Any]], plans: list[dict[str, Any]],
                        h: Any = None, window_min: int = 6) -> None:
    """Qué supuesto rompió cada golpe (si alguno) y qué plan nació: el primero roto tras el golpe, dentro de `window_min`
    y antes del golpe siguiente. Es una atribución por tiempo, y así se rotula («tras tu golpe»), no una prueba causal."""
    breaks = [e for e in agent_log if e.get("kind") == "assumption_broken"]
    for n, strike in enumerate(strikes):
        nxt = strikes[n + 1]["t"] if n + 1 < len(strikes) else 10 ** 9
        matching = [e for e in breaks if strike["t"] <= int(e.get("t", -1)) <= strike["t"] + window_min
                    and int(e.get("t", -1)) < nxt]
        broken, new_plans = [], []
        for e in matching:
            data = e.get("data") or {}
            old = data.get("plan")
            m = re.search(r"«([^»]+)»", str(e.get("text", "")))
            text = m.group(1) if m else str(e.get("text", ""))
            broken.append({"assumption_id": data.get("assumption") or e.get("ref"), "t": e.get("t"),
                           "text": h(text) if h else text, "plan": old})
            for p in plans:
                if old and p.get("supersedes") == old and not any(x["id"] == p["id"] for x in new_plans):
                    new_plans.append({"id": p["id"], "objective": h(p.get("objective", "")) if h else p.get("objective"),
                                      "why": h(p.get("why", "")) if h else p.get("why")})
        if matching:
            strike.update(broken=broken, new_plans=new_plans, broke=broken[0],
                          new_plan=new_plans[0]["id"] if new_plans else None)
        strike.setdefault("broken", [])
        strike.setdefault("new_plans", [])
        strike.setdefault("locked_test", None)
        strike["attribution"] = "temporal"
