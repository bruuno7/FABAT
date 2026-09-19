"""Evaluación de supuestos. Un supuesto es un dict `check` con `kind` y sus parámetros:

    zone_occupancy_below   {zone, ratio}                 ocupación/capacidad < ratio
    zone_density_below     {zone, density}               personas/m² < density
    zone_state_is          {zone, state}                 state: «open» o lista de estados válidos
    resource_status_is     {resource, status}            status: valor o lista («en_route», «busy»)
    route_clear            {zones, density}              todas las zonas del camino por debajo de esa densidad
    weather_below          {key, value}                  p. ej. wind_kmh < 60
    supply_above           {zone, flag, value}           p. ej. flags["water_l"] > 200
    action_accepted_within {action, since, minutes}      el equipo aceptó antes de since+minutes
    incident_improving     {incident, since, minutes, baseline, safe}
                           pasado el plazo, la métrica del incidente ha mejorado respecto a `baseline`
                           (o ya está por debajo de `safe`). Si se cumple, la ventana se renueva.

`view` es cualquier objeto con: t, zones, resources, weather, actions, incidents, accepted (ids de
acciones aceptadas) y on_scene(incident_id) -> bool. En la práctica, el propio Mando.
"""
from __future__ import annotations

from typing import Any

from ..contracts import ActionStatus, Assumption, Family, Incident, IncidentStatus

CLOSED = (IncidentStatus.RESOLVED, IncidentStatus.FALSE_ALARM, IncidentStatus.FAILED)
IMPROVE_EPS = 0.02


def metric(inc: Incident, view: Any) -> float | None:
    """Número observable que debe BAJAR si la acción funciona. None = no hay nada que medir."""
    zone = view.zones.get(inc.zone) if inc.zone else None
    if zone is None:
        return None
    if inc.family == Family.CROWD and inc.type != "lost_child":
        return zone.occupancy / zone.capacity if zone.capacity else None
    if inc.family == Family.SUPPLY and "water_l" in zone.flags:
        return -float(zone.flags["water_l"])
    return None


def _as_list(x: Any) -> list[str]:
    return [str(i) for i in x] if isinstance(x, (list, tuple, set, frozenset)) else [str(x)]


def holds(a: Assumption, view: Any) -> bool:
    c = a.check
    kind = c["kind"]
    if kind == "zone_occupancy_below":
        z = view.zones.get(c["zone"])
        return z is None or not z.capacity or z.occupancy / z.capacity < c["ratio"]
    if kind == "zone_density_below":
        z = view.zones.get(c["zone"])
        return z is None or z.density < c["density"]
    if kind == "zone_state_is":
        z = view.zones.get(c["zone"])
        return z is None or z.state in _as_list(c["state"])
    if kind == "resource_status_is":
        r = view.resources.get(c["resource"])
        return r is not None and str(r.status) in _as_list(c["status"])
    if kind == "route_clear":
        limit = c["density"]
        for zid in c["zones"]:
            z = view.zones.get(zid)
            if z is not None and (z.density >= limit or z.state == "closed"):
                return False
        return True
    if kind == "weather_below":
        v = view.weather.get(c["key"])
        return v is None or v < c["value"]
    if kind == "supply_above":
        z = view.zones.get(c["zone"])
        return z is None or c["flag"] not in z.flags or z.flags[c["flag"]] > c["value"]
    if kind == "action_accepted_within":
        act = view.actions.get(c["action"])
        if act is None or act.id in view.accepted:
            return True
        if act.status in (ActionStatus.REJECTED, ActionStatus.FAILED):
            return act.params.get("error") == "comms_down"  # voz caída: antes de darlo por perdido se reintenta por SMS
        return view.t < c["since"] + c["minutes"]
    if kind == "incident_improving":
        inc = view.incidents.get(c["incident"])
        if inc is None or inc.status in CLOSED or view.t < c["since"] + c["minutes"]:
            return True
        value = metric(inc, view)
        if value is None:
            ok = view.on_scene(inc.id)
        else:
            base = c.get("baseline")
            ok = base is None or value <= base - IMPROVE_EPS or (c.get("safe") is not None and value < c["safe"])
        if ok:  # ventana móvil: la siguiente revisión compara con lo de ahora
            c["since"], c["baseline"] = view.t, value
        return ok
    return True  # tipo desconocido: no se puede comprobar, no tira el plan


def blocked_zones(a: Assumption, view: Any) -> list[str]:
    """Zonas que hay que evitar al replanificar porque son las que rompieron el supuesto."""
    c = a.check
    if c["kind"] in ("zone_occupancy_below", "zone_density_below", "zone_state_is", "supply_above"):
        return [c["zone"]]
    if c["kind"] == "route_clear":
        return [z for z in c["zones"] if z in view.zones
                and (view.zones[z].density >= c["density"] or view.zones[z].state == "closed")]
    return []

