"""«¿Y si…?»: la persona del centro de control propone una alternativa y la VE en el gemelo antes de decidir.

La acción candidata se aplica a `world.twin()` (copia del estado de ahora, sin futuro), se avanza `minutes` y se devuelve
la serie minuto a minuto. NUNCA toca el mundo real. El gemelo lleva su propia semilla derivada de (semilla, minuto):
misma pregunta en el mismo minuto = misma respuesta.
"""
from __future__ import annotations

from typing import Any

from motor.contracts import Action, ActionKind, ActionStatus

SAFE, HIGH, CRUSH = 4.0, 5.0, 6.5
ALLOWED = {"reroute": ActionKind.REROUTE, "set_zone": ActionKind.SET_ZONE, "stop_show": ActionKind.STOP_SHOW,
           "broadcast": ActionKind.BROADCAST}
STOP_WATCH = ("front_pit", "general", "gate_a", "gate_b", "gate_c", "exit_transport")


def candidate(d: dict[str, Any], zones: set[str], t: int, action_id: str = "WHATIF") -> Action:
    """Valida la acción candidata. Lanza ValueError con un texto que entiende una persona."""
    kind = ALLOWED.get(str(d.get("kind") or ""))
    if kind is None:
        raise ValueError("kind debe ser reroute, set_zone, stop_show o broadcast")
    zone = d.get("zone")
    params: dict[str, Any] = {}
    if kind in (ActionKind.REROUTE, ActionKind.SET_ZONE, ActionKind.BROADCAST) and zone not in zones:
        raise ValueError("zona desconocida")
    if kind == ActionKind.REROUTE:
        if d.get("cancel"):
            params["cancel"] = True
        else:
            if d.get("to") not in zones or d.get("to") == zone:
                raise ValueError("destino del desvío desconocido")
            try:
                params.update(to=d["to"], fraction=max(0.05, min(1.0, float(d.get("fraction", 0.5)))))
            except (TypeError, ValueError):
                raise ValueError("fraction debe ser un número entre 0 y 1")
    elif kind == ActionKind.SET_ZONE:
        if d.get("state") not in ("open", "restricted", "closed"):
            raise ValueError("state debe ser open, restricted o closed")
        params["state"] = d["state"]
    elif kind == ActionKind.BROADCAST:
        params["message"] = str(d.get("message") or "Por favor, no avancen hacia esta zona.")[:160]
    return Action(id=action_id, kind=kind, t=t, zone=zone if kind != ActionKind.STOP_SHOW else None, params=params,
                  status=ActionStatus.EXECUTING, why="ensayo del operador")


def _run(world: Any, action: Action | None, minutes: int) -> dict[str, list[float]]:
    tw = world.twin()
    if action is not None:
        tw.apply(action)
    series: dict[str, list[float]] = {}
    for _ in range(minutes):
        tw.step()
        for z in tw.observe().zones.values():
            series.setdefault(z.id, []).append(round(z.occupancy / z.area_m2, 3) if z.area_m2 else 0.0)
    return series


def _summary(series: dict[str, list[float]], watch: list[str]) -> dict[str, Any]:
    peak_zone = max(watch, key=lambda z: max(series[z]))
    crush = {z: next(i + 1 for i, d in enumerate(series[z]) if d > CRUSH) for z in watch if any(d > CRUSH for d in series[z])}
    return {"series": {z: series[z] for z in watch}, "peak_density": round(max(series[peak_zone]), 2), "peak_zone": peak_zone,
            "peak_at_min": series[peak_zone].index(max(series[peak_zone])) + 1,
            "minutes_over_4": sum(1 for z in watch for d in series[z] if d > SAFE),
            "minutes_over_5": sum(1 for z in watch for d in series[z] if d > HIGH),
            "crush_risk": bool(crush), "crush_at_min": crush}


def rehearse(world: Any, d: dict[str, Any], zone_names: dict[str, str]) -> dict[str, Any]:
    minutes = max(12, min(15, int(d.get("minutes") or 15)))
    action = candidate(d, set(zone_names), world.t)
    base, alt = _run(world, None, minutes), _run(world, action, minutes)
    named = [z for z in (d.get("zone"), d.get("to")) if z in base]
    if action.kind == ActionKind.STOP_SHOW:
        named = [z for z in STOP_WATCH if z in base]
    # además de las zonas nombradas, las dos donde más cambia algo: un desvío suele hacer daño donde nadie miraba
    moved = sorted((z for z in base if z not in named), key=lambda z: -max(abs(a - b) for a, b in zip(alt[z], base[z])))
    watch = named + [z for z in moved[:2] if max(abs(a - b) for a, b in zip(alt[z], base[z])) > 0.05]
    a, b = _summary(alt, watch), _summary(base, watch)
    better = (a["crush_risk"], a["minutes_over_4"], a["peak_density"]) < (b["crush_risk"], b["minutes_over_4"], b["peak_density"])
    same = (a["crush_risk"], a["minutes_over_4"], a["peak_density"]) == (b["crush_risk"], b["minutes_over_4"], b["peak_density"])
    return {"t": world.t, "minutes": minutes, "action": {"kind": str(action.kind), "zone": action.zone, **action.params},
            "zones": {z: zone_names.get(z, z) for z in watch}, "thresholds": {"safe": SAFE, "high": HIGH, "crush": CRUSH},
            "mando": b, "alternative": a, "verdict": "igual" if same else "mejor" if better else "peor",
            "note": "Ensayo en el gemelo: estado de ahora, sin futuro. No cambia nada en el recinto."}
