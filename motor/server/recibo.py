"""Recibo contrafactual puro: dos copias, misma semilla, máximo 15 minutos.

Retrospectivo: clone conserva los sucesos programados (a diferencia de twin, que
los desconoce). Se fijan las acciones/entradas posteriores observadas, no se vuelve
a optimizar la política en cada rama. Esa condición se publica en cada resultado.
No consulta servicios, no escribe ni modifica el mundo o las acciones recibidas.
"""
from __future__ import annotations

import copy
from typing import Any
from motor.contracts import Action, ActionStatus

MAX_DECISIONS = 10
HORIZON = 15
RELEVANT = {"dispatch", "recall", "reroute", "set_zone", "resupply", "request_external", "evacuate", "stop_show", "broadcast"}


def observe(world: Any) -> dict:
    obs = world.observe()
    return {"t": world.t, "clock": obs.clock.get("hhmm"),
            "density": {k: round(z.density, 6) for k, z in obs.zones.items()},
            "resources": {k: {"status": str(r.status), "zone": r.zone, "task": r.task} for k, r in obs.resources.items()}}


def _apply(world: Any, action: Action) -> None:
    a = copy.deepcopy(action)
    a.status = ActionStatus.EXECUTING
    world.apply(a)


def _roll(world: Any, action: Action | None, minutes: int, later: list[dict]) -> list[dict]:
    w = world.clone()
    if action is not None:
        _apply(w, action)
    frames = []
    for _ in range(minutes):
        for event in later:
            if event["t"] == w.t:
                if "action" in event:
                    _apply(w, event["action"])
                else:
                    w.inject(copy.deepcopy(event["event"]))
        w.step()
        frames.append(observe(w))
    return frames


def _summary(frames: list[dict], action: Action) -> dict:
    if not frames:
        return {"peak": {}, "over5": 0, "arrival": None}
    peaks = {}
    for zone in frames[0]["density"]:
        frame = max(frames, key=lambda f: f["density"].get(zone, 0))
        peaks[zone] = {"density": round(frame["density"][zone], 3), "t": frame["t"], "clock": frame["clock"]}
    # Llegada del recurso a ESTE destino; estar ocupado con otra tarea no cuenta.
    arrival = next((f["t"] for f in frames if (r := f["resources"].get(action.resource))
                    and r["status"] == "busy" and r["zone"] == action.zone), None)
    return {"peak": peaks, "over5": sum(d > 5 for f in frames for d in f["density"].values()), "arrival": arrival}


def calculate(world: Any, action: Action, *, accepted: bool = True, minutes: int = HORIZON,
              later: list[dict] | None = None, observed: list[dict] | None = None) -> dict:
    horizon = max(1, min(HORIZON, int(minutes)))
    horizon = min(horizon, max(0, world.duration - world.t))
    frames = None if observed is None else [f for f in observed if world.t < f["t"] <= world.t + horizon]
    if frames is not None:
        # No rellenar huecos ni fingir seguimiento tras terminar la partida.
        contiguous = []
        for expected, f in enumerate(frames, world.t + 1):
            if f["t"] != expected:
                break
            contiguous.append(f)
        frames = contiguous
        horizon = len(frames)
    later = later or []
    factual = frames if frames is not None else _roll(world, action if accepted else None, horizon, later)
    counter = _roll(world, None if accepted else action, horizon, later)
    actual, alternative = _summary(factual, action), _summary(counter, action)
    changes = [{"zone": z, "actual": p, "counter": alternative["peak"][z],
                "delta": round(alternative["peak"][z]["density"] - p["density"], 3)}
               for z, p in actual["peak"].items()]
    changes.sort(key=lambda c: (-abs(c["delta"]), c["zone"]))
    # Métrica global prédeclarada: minutos-zona >5, después pico global; no escoger solo la zona favorable.
    benefit = alternative["over5"] - actual["over5"]
    if not benefit and changes:
        benefit = round(max(p["density"] for p in alternative["peak"].values()) - max(p["density"] for p in actual["peak"].values()), 3)
    eta = None
    if actual["arrival"] is not None and alternative["arrival"] is not None:
        eta = alternative["arrival"] - actual["arrival"]
        if not benefit:
            benefit = eta
    if abs(benefit) < .05:
        benefit = 0
    gains = [c for c in changes if c["delta"] >= .05]
    losses = [c for c in changes if c["delta"] <= -.05]
    changed = bool(gains or losses) or actual["arrival"] != alternative["arrival"] or benefit != 0
    verdict = "sin_cambio" if not changed else "mejor" if benefit > 0 else "peor" if benefit < 0 else "mixto"
    if gains and losses:
        verdict = "mixto"
    names = {z.id: z.name for z in world.observe().zones.values()}
    es = lambda v: f"{v:.2f}".replace(".", ",")
    lines = []
    # Mostrar al menos una mejora y un perjuicio si los hay, sin ocultar el coste del plan.
    shown = (gains[:2] + losses[:2]) if gains and losses else changes[:3]
    for c in shown:
        if abs(c["delta"]) < .05:
            continue
        p, q = c["actual"], c["counter"]
        when = q["clock"] or f"min {q['t']}"
        branch = "Sin esta decisión" if accepted else "De haberse aprobado"
        lines.append(f"{branch}, {names.get(c['zone'], c['zone'])} habría alcanzado {es(q['density'])} /m² a {when}; "
                     f"{'llegó' if frames is not None else 'rama elegida'} a {es(p['density'])} /m².")
    if eta:
        lines.append(f"{abs(eta)} min {'menos' if eta > 0 else 'más'} hasta la llegada del recurso al destino.")
    elif actual["arrival"] != alternative["arrival"]:
        lines.append("El recurso llegó solo en la rama " + ("elegida" if actual["arrival"] is not None else "alternativa")
                     + f"; la otra no llegó dentro de {horizon} min. Diferencia de tiempo censurada.")
    if not lines:
        lines = ["No cambió nada medible." if not changed else "Cambió la exposición a densidad alta; consultar las cifras."]
    if not horizon:
        verdict, lines = "sin_seguimiento", ["Sin seguimiento posterior: no se puede medir el efecto."]
    return {"id": action.id, "incident": action.incident, "kind": str(action.kind), "t": world.t, "accepted": accepted,
            "N": 1, "minutes": horizon, "censored": horizon < HORIZON, "verdict": verdict,
            "benefit": benefit, "eta_saved_min": eta, "text": " ".join(lines), "changes": changes,
            "actual": actual, "counterfactual": alternative,
            "counter_label": "Sin esta decisión" if accepted else "Si se hubiera aprobado",
            "factual_source": "observado_en_simulador" if frames is not None else "rama_simulada",
            "note": "Simulación · N = 1 par por decisión. Mismo estado inicial del RNG y sucesos del caso; "
                    "órdenes posteriores fijadas. Los efectos no se suman entre decisiones. "
                    "El gemelo conoce la dinámica del simulador; no es un dato de campo."}
