"""Caos: adversario con presupuesto limitado de golpes. Ataca el MUNDO, no la conversación.

Cada golpe es un efecto `world` de INTERFACES.md (lo mismo que `World.inject`). Para elegir el peor
golpe en el peor momento, Caos clona el mundo y el agente, aplica el golpe en el clon y simula
`lookahead` minutos; el daño estimado es la diferencia de `harm()` con y sin golpe. Los supuestos
vivos de los planes (`agent.snapshot()["plans"][].assumptions`) generan candidatos dirigidos:
si el plan depende de «gate_a por debajo del 80 %», Caos mete gente por gate_a.

Caos ve el futuro del guion del caso (los clones comparten los eventos programados): es el autor
del escenario, no un jugador limpio. El agente nunca ve nada de esto.
"""
from __future__ import annotations

import copy
import json
import random
from typing import Any

from motor.contracts import ActionStatus, LogEntry

_ACTIVE = ("open", "assigned", "in_progress")
_GATES = ("gate_a", "gate_b", "gate_c", "front_pit", "exit_transport")


# ---------------------------------------------------------------------------- daño

def harm(truth: dict[str, Any]) -> float:
    """Daño acumulado en un mundo (más es peor). Misma idea que el `score`, pero sensible a lo que
    todavía no ha fallado: un crítico sin atender a punto de vencer ya cuenta."""
    t, total = truth["t"], 0.0
    for inc in truth["incidents"].values():
        sev, status = inc["severity"], str(inc["status"])
        if status == "failed":
            total += (8 + sev) * (2.5 if sev >= 8 else 1.0)
        elif status in ("open", "assigned") and inc.get("needs"):
            window = max(1, (inc.get("deadline") or (inc["t_open"] + 30)) - inc["t_open"])
            total += 0.5 * sev * min(1.0, (t - inc["t_open"]) / window)
        elif status == "in_progress":
            total += 0.05 * sev
    total += 0.3 * sum(truth["minutes_over_5"].values())
    peak = max(v["density"] for v in truth["peak_density"].values())
    total += 3.0 * max(0.0, peak - 5.0)
    return total


def rollout(world: Any, agent: Any, minutes: int, effect: dict[str, Any] | None = None) -> float:
    """Clona mundo y agente, aplica `effect` y simula. Si el agente no se puede copiar, simula el
    mundo solo (los recursos ya en marcha siguen su curso): re-simulación barata."""
    w = world.clone()
    ag = None
    if agent is not None:
        try:
            memo: dict[int, Any] = {id(world): w}
            for k, a in world.live.items():           # las acciones vivas del clon son las del agente clonado
                if k in w.live:
                    memo[id(a)] = w.live[k]
            ag = copy.deepcopy(agent, memo)
            # Mando guarda `lambda: self.new_id("M")` en su triaje: deepcopy no copia funciones, así que el
            # clon seguiría gastando los ids del agente REAL. Se reengancha al clon (ver out/BUGS.md).
            tri = getattr(ag, "triage", None)
            if tri is not None and hasattr(tri, "new_id") and hasattr(ag, "new_id"):
                tri.new_id = lambda _ag=ag: _ag.new_id("M")
            rehearsal = getattr(ag, "rehearsal", None)
            if rehearsal is not None and rehearsal.twin is not None:
                # deepcopy conserva las lambdas: el ensayo debe partir del mundo de ESTE rollout.
                rehearsal.twin = w.twin
        except Exception:
            ag = None
    if effect is not None:
        w.inject(json.loads(json.dumps(effect)))
    waiting: dict[str, int] = {}
    end = min(w.duration, w.t + minutes)
    while w.t < end:
        if ag is not None:
            for aid in [k for k, due in waiting.items() if due <= w.t]:
                del waiting[aid]
                ag.approve(aid, True, "")
            for a in ag.tick(w.observe()):
                if a.status == ActionStatus.AWAITING_APPROVAL:
                    waiting.setdefault(a.id, w.t + 2)
                else:
                    w.apply(a)
        w.step()
    return harm(w.truth())


# ---------------------------------------------------------------------------- catálogo de golpes

def _strike(effect: dict[str, Any], why: str, label: str, rank: int, assumption: str | None = None) -> dict[str, Any]:
    return {"effect": effect, "why": why, "label": label, "rank": rank, "assumption": assumption}


def catalogue(world: Any, snapshot: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Golpes candidatos ahora mismo, de más a menos dirigidos (`rank` 0 = apunta a un supuesto vivo)."""
    obs = world.observe()
    t, zones, res = obs.t, obs.zones, obs.resources
    out: list[dict[str, Any]] = []
    snap = snapshot or {}

    # 0 · supuestos vivos de los planes del agente
    plans = snap.get("plans") or []
    plans = list(plans.values()) if isinstance(plans, dict) else plans
    for p in plans:
        if not p.get("live", p.get("invalidated_by") is None):
            continue
        for a in p.get("assumptions", []):
            if not a.get("holds", True):
                continue
            c, text = a.get("check", {}), a.get("text", "")
            kind, because = c.get("kind"), f"el plan {p.get('id')} depende de «{text}»"
            if kind in ("zone_occupancy_below", "zone_density_below") and c.get("zone") in zones:
                z = c["zone"]
                out.append(_strike({"kind": "zone_inflow", "zone": z, "per_min": 260, "n": 12,
                                    "reason": "llegada inesperada de público"},
                                   f"meto 260 personas/min en {z} porque {because}", f"Oleada en {z}", 0, a.get("id")))
            elif kind == "zone_state_is" and c.get("zone") in zones:
                out.append(_strike({"kind": "zone_state", "zone": c["zone"], "state": "closed", "reason": "cierre imprevisto"},
                                   f"cierro {c['zone']} porque {because}", f"Cerrar {c['zone']}", 0, a.get("id")))
            elif kind == "resource_status_is" and c.get("resource") in res:
                r = c["resource"]
                out.append(_strike({"kind": "resource_offline", "resource": r, "n": 25, "reason": "baja imprevista"},
                                   f"dejo fuera a {r} porque {because}", f"{r} fuera de servicio", 0, a.get("id")))
            elif kind == "route_clear":
                for z in c.get("zones", [])[:1]:
                    if z in zones:
                        out.append(_strike({"kind": "zone_inflow", "zone": z, "per_min": 300, "n": 10,
                                            "reason": "la ruta se llena de gente"},
                                           f"lleno {z}, que es la ruta de {c.get('resource', 'el equipo')}, porque {because}",
                                           f"Bloquear ruta por {z}", 0, a.get("id")))
            elif kind == "weather_below":
                key = c.get("key", "wind_kmh")
                out.append(_strike({"kind": "weather", key: float(c.get("value", 60)) + 15, "rain": True, "alert": "roja"},
                                   f"subo {key} por encima de {c.get('value')} porque {because}", "Tormenta", 0, a.get("id")))
            elif kind == "supply_above" and c.get("zone") in zones:
                out.append(_strike({"kind": "zone_flag", "zone": c["zone"], "flag": c.get("flag", "water_l"), "value": 0},
                                   f"dejo {c['zone']} a cero porque {because}", f"{c['zone']} sin suministro", 0, a.get("id")))
            elif kind == "action_accepted_within":
                act = next((x for x in (snap.get("actions") or []) if x.get("id") == c.get("action")), None)
                if act and act.get("resource") in res and str(act.get("status")) in ("executing", "proposed"):
                    r = act["resource"]
                    out.append(_strike({"kind": "resource_no_answer", "resource": r, "n": 8},
                                       f"{r} deja de contestar porque {because}", f"{r} no contesta", 0, a.get("id")))

    # 1 · recursos que están cubriendo algo ahora mismo
    by_kind: dict[str, list[Any]] = {}
    for r in res.values():
        by_kind.setdefault(str(r.kind), []).append(r)
    for r in res.values():
        st = str(r.status)
        if st in ("en_route", "busy") and r.task:
            peers = [x for x in by_kind[str(r.kind)] if str(x.status) == "available"]
            only = "es el único recurso que lo cubre" if not peers else f"quedan {len(peers)} de su tipo libres"
            out.append(_strike({"kind": "resource_offline", "resource": r.id, "n": 25, "reason": "baja imprevista"},
                               f"golpeo {r.id} porque está {'de camino a' if st == 'en_route' else 'atendiendo'} {r.task} y {only}",
                               f"{r.id} fuera de servicio", 1 if not peers else 2))
    for kind, group in by_kind.items():
        free = [x for x in group if str(x.status) == "available"]
        if len(free) == 1 and kind in ("medical", "ambulance", "security"):
            r = free[0]
            out.append(_strike({"kind": "resource_rejects", "resource": r.id, "n": 12},
                               f"{r.id} rechazará lo que le manden: es el último {kind} libre", f"{r.id} rechaza", 2))
            out.append(_strike({"kind": "resource_no_answer", "resource": r.id, "n": 8},
                               f"{r.id} no contestará: es el último {kind} libre", f"{r.id} no contesta", 2))

    # 2 · incidente grave nuevo cuando no queda nadie
    free_med = [x for x in res.values() if str(x.kind) in ("medical", "ambulance") and str(x.status) == "available"]
    far = max(("front_pit", "general", "food", "gate_b", "vip"), key=lambda z: zones[z].density if z in zones else 0)
    why = "todos los sanitarios están ocupados" if not free_med else f"solo quedan {len(free_med)} sanitarios libres"
    out.append(_strike({"kind": "incident",
                        "incident": {"family": "medical", "type": "cardiac_arrest", "zone": far, "severity": 9,
                                     "deadline": t + 8, "needs": {"medical": 1}},
                        "reports": [{"channel": "radio", "source": "seguridad", "lang": "es", "zone_hint": far,
                                     "text": f"Persona inconsciente que no respira en {zones[far].name}. Necesito sanitarios ya."}]},
                       f"abro una parada cardiaca en {far} (la zona más densa) porque {why}", f"Parada cardiaca en {far}",
                       1 if not free_med else 3))
    free_sec = [x for x in res.values() if str(x.kind) == "security" and str(x.status) == "available"]
    if len(free_sec) <= 1:
        out.append(_strike({"kind": "incident",
                            "incident": {"family": "aggression", "type": "weapon_seen", "zone": "general", "severity": 9,
                                         "deadline": t + 10, "needs": {"security": 2}},
                            "reports": [{"channel": "radio", "source": "jefe seguridad 4", "lang": "es", "zone_hint": "general",
                                         "text": "Varón con una navaja en la pista general, hay gente corriendo. Necesito apoyo de seguridad."}]},
                           f"arma blanca en la pista porque solo queda {len(free_sec)} equipo de seguridad libre",
                           "Arma blanca en pista", 2))

    # 3 · multitud
    hot = sorted((z for z in _GATES if z in zones), key=lambda z: -(zones[z].occupancy / (zones[z].capacity or 1)))
    for z in hot[:2]:
        ratio = zones[z].occupancy / (zones[z].capacity or 1)
        out.append(_strike({"kind": "zone_inflow", "zone": z, "per_min": 260, "n": 15, "reason": "llegan lanzaderas a la vez"},
                           f"meto 260 personas/min en {z} porque ya está al {ratio:.0%} de su capacidad", f"Oleada en {z}", 3))
    amb = next((r for r in res.values() if str(r.kind) == "ambulance"), None)
    if amb is not None and str(amb.status) == "en_route":
        out.append(_strike({"kind": "zone_state", "zone": "corridor_s", "state": "closed", "reason": "vehículo averiado"},
                           f"cierro corridor_s porque es la ruta de {amb.id}, que va de camino a {amb.task}",
                           "Cerrar ruta de ambulancia", 1))

    # 4 · infraestructura, tiempo, comunicaciones, transporte
    temp = obs.weather.get("temp_c", 25)
    for z in ("water_n", "water_s"):
        if z in zones and zones[z].flags.get("water_l", 0) > 0 and temp >= 30:
            out.append(_strike({"kind": "zone_flag", "zone": z, "flag": "water_l", "value": 0},
                               f"agua a cero en {z} con {temp} °C", f"{z} sin agua", 4))
    if "food" in zones and zones["food"].flags.get("power", True) is not False:
        out.append(_strike({"kind": "zone_flag", "zone": "food", "flag": "power", "value": False},
                           "apagón en restauración: la gente se va a pista y foso", "Apagón en restauración", 4))
    if obs.weather.get("wind_kmh", 0) < 60:
        out.append(_strike({"kind": "weather", "wind_kmh": 75, "rain": True, "alert": "roja"},
                           "tormenta con rachas de 75 km/h: riesgo en estructuras", "Tormenta", 4))
    if temp < 39:
        out.append(_strike({"kind": "weather", "temp_c": 41, "alert": "roja"}, "41 °C: más golpes de calor y más consumo de agua",
                           "Ola de calor", 5))
    busy_talk = sum(1 for r in res.values() if str(r.status) == "en_route")
    out.append(_strike({"kind": "comms_down", "channel": "voice", "n": 10},
                       f"cae el canal de voz 10 min ({busy_talk} equipos en movimiento dependen de él)", "Voz caída", 4))
    out.append(_strike({"kind": "comms_down", "channel": "radio", "n": 10}, "cae la radio 10 min: los avisos del personal llegan tarde",
                       "Radio caída", 5))
    if obs.clock.get("show_phase") in ("egress", "headliner"):
        out.append(_strike({"kind": "transport_cut", "n": 30}, "corte de metro y lanzaderas en plena salida", "Corte de transporte", 3))

    seen, uniq = set(), []
    for s in sorted(out, key=lambda s: s["rank"]):
        key = json.dumps(s["effect"], sort_keys=True, ensure_ascii=False)
        if key not in seen:
            seen.add(key)
            uniq.append(s)
    return uniq


# ---------------------------------------------------------------------------- adversarios

class Chaos:
    """Adversario inteligente. `budget` golpes por ejecución, `lookahead` minutos de simulación."""

    name = "smart"

    def __init__(self, budget: int = 3, lookahead: int = 15, min_gap: int = 4, every: int = 2,
                 max_candidates: int = 12, bar: float = 14.0, seed: int = 0) -> None:
        self.budget, self.lookahead, self.min_gap, self.every = budget, lookahead, min_gap, every
        self.max_candidates, self.bar = max_candidates, bar
        self.start({}, seed)

    def start(self, case: dict[str, Any], seed: int) -> None:
        self.left = self.budget
        self.rng = random.Random((int(seed) * 7919) ^ 0xCA05)
        self.strikes: list[dict[str, Any]] = []
        self.log: list[LogEntry] = []
        self._last = -10 ** 6

    def suggest(self, world: Any, agent: Any, top: int | None = None) -> list[dict[str, Any]]:
        """Consola del adversario: golpes ordenados por daño estimado (mayor primero).
        Cada elemento: effect (listo para `world.inject`), label, why, damage, assumption."""
        try:
            snap = agent.snapshot() if agent is not None else None
        except Exception:
            snap = None
        cands = catalogue(world, snap)[: self.max_candidates]
        if not cands:
            return []
        base = rollout(world, agent, self.lookahead)
        for c in cands:
            c["damage"] = round(rollout(world, agent, self.lookahead, c["effect"]) - base, 2)
        cands.sort(key=lambda c: (-c["damage"], c["rank"]))
        return cands[:top] if top else cands

    def _threshold(self, world: Any) -> float:
        """Listón para golpear ya: alto al principio (≈ provocar un fallo), cae según se acaba el tiempo."""
        usable = max(1, world.duration - self.lookahead)
        remaining = usable - world.t
        if remaining <= self.left * self.min_gap:
            return 0.5                                  # o se usa o se pierde
        return max(0.5, self.bar * remaining / usable)

    def maybe_strike(self, world: Any, agent: Any) -> dict[str, Any] | None:
        t = world.t
        if self.left <= 0 or t - self._last < self.min_gap or t % self.every or t >= world.duration - 2:
            return None
        ranked = self.suggest(world, agent)
        if not ranked or ranked[0]["damage"] < self._threshold(world):
            return None
        return self._hit(world, ranked[0], [{"label": c["label"], "damage": c["damage"]} for c in ranked[1:4]])

    def strike(self, world: Any, choice: dict[str, Any]) -> dict[str, Any]:
        """Golpe elegido a mano (el jurado, desde la consola). No gasta presupuesto."""
        return self._hit(world, choice, [], spend=False)

    def _hit(self, world: Any, c: dict[str, Any], alternatives: list[dict[str, Any]], spend: bool = True) -> dict[str, Any]:
        world.inject(json.loads(json.dumps(c["effect"])))
        if spend:
            self.left -= 1
        self._last = world.t
        rec = {"t": world.t, "effect": c["effect"], "label": c["label"], "why": c["why"],
               "damage_est": c.get("damage"), "assumption": c.get("assumption"), "alternatives": alternatives,
               "budget_left": self.left}
        self.strikes.append(rec)
        dmg = f" (daño estimado {c['damage']:+.1f} en {self.lookahead} min)" if c.get("damage") is not None else ""
        self.log.append(LogEntry(world.t, "chaos", f"Caos: {c['why']}{dmg}", None, rec))
        return rec


class RandomChaos(Chaos):
    """Mismo catálogo y mismo presupuesto, pero golpe y momento al azar (con semilla). Es el control."""

    name = "random"

    def start(self, case: dict[str, Any], seed: int) -> None:
        super().start(case, seed)
        duration = int(case.get("duration_min", 60)) if case else 60
        hi = max(3, duration - 5)
        self._when = sorted(self.rng.sample(range(2, hi), min(self.budget, hi - 2)))

    def maybe_strike(self, world: Any, agent: Any) -> dict[str, Any] | None:
        if self.left <= 0 or not self._when or world.t < self._when[0]:
            return None
        self._when.pop(0)
        cands = catalogue(world, None)
        if not cands:
            return None
        c = dict(self.rng.choice(cands))
        c["why"] = "al azar: " + c["why"]
        return self._hit(world, c, [])
