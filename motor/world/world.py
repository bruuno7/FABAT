"""Simulador determinista del «Festival Abierto». Implementa `WorldAPI` (motor/contracts.py).

Tick = 1 minuto. Todo el azar sale de `random.Random(seed)`; nunca se mira el reloj.
El estado vive en listas indexadas por zona (barato de clonar); los objetos `Zone` se
construyen solo en `observe()`.
"""
from __future__ import annotations

import copy
import heapq
import json
import math
import random
from bisect import bisect_right
from functools import lru_cache
from pathlib import Path
from typing import Any

from motor.contracts import (
    Action, ActionKind, ActionStatus, Channel, Family, Incident, IncidentStatus,
    Observation, Report, Resource, ResourceKind, ResourceStatus, Zone,
)

_DIR = Path(__file__).parent
_DAY = 1440
_DAY_START = 360  # el día de festival va de 06:00 a 06:00
_TERMINAL = (ActionStatus.DONE, ActionStatus.REJECTED, ActionStatus.FAILED, ActionStatus.CANCELLED)
_ACTIVE = (IncidentStatus.OPEN, IncidentStatus.ASSIGNED, IncidentStatus.IN_PROGRESS)
_EFFECT_META = ("kind", "zone", "id", "flag", "value", "reason", "n", "ticks", "duration", "t", "origin")


@lru_cache(maxsize=8)
def _load(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_festival(path: str | Path | None = None) -> dict[str, Any]:
    """Devuelve el recinto (cacheado: no lo mutes)."""
    return _load(str(path or _DIR / "festival.json"))


def _hhmm_to_min(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


class _Phase:
    __slots__ = ("name", "profile", "weights", "arrive", "share", "arrived_before", "attendance",
                 "leaving", "day", "new_day", "start", "end")


class _Layout:
    """Todo lo estático, precalculado una vez por recinto y compartido entre mundos y clones."""

    def __init__(self, fest: dict[str, Any]):
        self.fest = fest
        self.params = fest["params"]
        zs = fest["zones"]
        self.n = len(zs)
        self.ids = [z["id"] for z in zs]
        self.idx = {z: i for i, z in enumerate(self.ids)}
        self.names = [z["name"] for z in zs]
        self.kinds = [z["kind"] for z in zs]
        self.area = [float(z["area_m2"]) for z in zs]
        self.capacity = [int(z["capacity"]) for z in zs]
        self.comfort = [float(z.get("comfort_d", 3.0)) for z in zs]
        self.vehicle = [bool(z.get("vehicle_transit", True)) for z in zs]  # ¿puede cruzarla un vehículo?
        by_kind = self.params.get("sensor_density_by_kind", {})
        self.sensor_d = [float(z.get("sensor_d", by_kind.get(z["kind"], self.params["sensor_density"]))) for z in zs]
        self.entry = [float(z.get("entry_per_min", 0)) for z in zs]
        self.exit_rate = [float(z.get("exit_per_min", 0)) for z in zs]
        self.is_gate = [z["kind"] == "gate" for z in zs]
        self.gates = [i for i in range(self.n) if self.is_gate[i]]
        share = [float(z.get("gate_share", 0)) for z in zs]
        tot = sum(share[g] for g in self.gates) or 1.0
        self.gate_share = [s / tot for s in share]
        self.main_gate = max(self.gates, key=lambda g: share[g])
        self.exits = [i for i in range(self.n) if self.exit_rate[i] > 0]
        self.flags0 = [dict(z.get("flags", {})) for z in zs]
        self.water = [i for i in range(self.n) if "water_l" in self.flags0[i]]
        self.powered = [i for i in range(self.n) if self.kinds[i] == "food"]
        self.struct = [i for i in range(self.n) if "structure_ok" in self.flags0[i]]
        self.crush = {self.idx[z] for z in self.params["crush_zones"]}
        self.no_spont = {i for i in range(self.n) if self.kinds[i] in ("medical", "backstage")}
        self.transport = self.idx.get("exit_transport", -1)
        self.general = self.idx["general"]
        self.front = self.idx["front_pit"]
        self.stages = frozenset(i for i, k in enumerate(self.kinds) if k == "stage_front")
        self.external_entry = self.idx[fest.get("external_entry", "exit_transport")]

        # grafo: `adj` para recursos (todas las aristas), `edges` para la multitud
        self.adj: list[list[tuple[int, float]]] = [[] for _ in range(self.n)]
        self.neighbors: list[list[str]] = [[] for _ in range(self.n)]
        self.minutes: dict[tuple[int, int], float] = {}
        crowd = []
        for e in fest["edges"]:
            a, b, m = self.idx[e["a"]], self.idx[e["b"]], float(e["minutes"])
            self.adj[a].append((b, m)); self.adj[b].append((a, m))
            self.neighbors[a].append(e["b"]); self.neighbors[b].append(e["a"])
            self.minutes[(a, b)] = self.minutes[(b, a)] = m
            if not e.get("staff_only"):
                crowd.append((a, b, float(e.get("flow_per_min", 300))))
        deg = [0] * self.n
        for a, b, _ in crowd:
            deg[a] += 1; deg[b] += 1
        self.crowd_nb: list[list[int]] = [[] for _ in range(self.n)]
        # Zonas de paso (pasillos y pista) cargan con el exceso en tránsito; el resto son destinos:
        # solo se llenan hasta lo que pide el programa y solo sueltan lo que les sobra.
        transit = [k in ("corridor", "general") for k in self.kinds]
        self.edges: list[tuple[int, int, float, float, int]] = []  # (a, b, tope, conductancia, destinos: 0|1=a|2=b|3)
        self.gate_edges: list[tuple[int, int, float, float]] = []  # (interior, puerta, tope, conductancia)
        self.gate_inner: dict[int, list[int]] = {g: [] for g in self.gates}
        for a, b, cap in crowd:
            self.crowd_nb[a].append(b); self.crowd_nb[b].append(a)
            c = 0.5 / max(deg[a], deg[b])
            if self.is_gate[a] or self.is_gate[b]:
                g, inner = (a, b) if self.is_gate[a] else (b, a)
                self.gate_inner[g].append(inner)
                self.gate_edges.append((inner, g, cap, c))
            else:
                self.edges.append((a, b, cap, c, (0 if transit[a] else 1) + (0 if transit[b] else 2)))

        prof = {name: self._weights(w) for name, w in fest["profiles"].items()}
        self.evac_weights = prof[fest["program"].get("evacuation_profile", "egress")]
        self.timeline: list[_Phase] = []
        for di, day in enumerate(fest["program"]["days"]):
            raw = sorted(day["phases"], key=lambda p: (_hhmm_to_min(p["start"]) - _DAY_START) % _DAY)
            acc = 0.0
            for k, p in enumerate(raw):
                ph = _Phase()
                ph.name, ph.profile, ph.weights = p["name"], p["profile"], prof[p["profile"]]
                ph.day, ph.new_day = di + 1, k == 0
                ph.start = di * _DAY + _DAY_START + (_hhmm_to_min(p["start"]) - _DAY_START) % _DAY
                ph.share, ph.arrived_before, ph.attendance = float(p.get("arrive_share", 0)), acc, int(day["attendance"])
                ph.leaving = bool(p.get("leaving", False))
                acc += ph.share
                self.timeline.append(ph)
        for k, ph in enumerate(self.timeline):
            ph.end = self.timeline[k + 1].start if k + 1 < len(self.timeline) else 10 ** 9
            ph.arrive = ph.attendance * ph.share / (ph.end - ph.start) if ph.share else 0.0
        self.starts = [ph.start for ph in self.timeline]

    def _weights(self, w: dict[str, float]) -> list[float]:
        tot = sum(w.values()) or 1.0
        return [w.get(z, 0.0) / tot for z in self.ids]


_LAYOUTS: dict[int, _Layout] = {}


def _layout(fest: dict[str, Any]) -> _Layout:
    lay = _LAYOUTS.get(id(fest))
    if lay is None or lay.fest is not fest:
        lay = _LAYOUTS[id(fest)] = _Layout(fest)
    return lay


def _covers(kind: ResourceKind, need: str) -> bool:
    return kind.value == need or (kind is ResourceKind.AMBULANCE and need == "medical")


class World:
    """Estado verdadero del festival. Mando solo debe ver `observe()`."""

    t: int

    # ------------------------------------------------------------------ construcción

    @classmethod
    def from_case(cls, case: dict[str, Any], seed: int | None = None,
                  festival: dict[str, Any] | None = None) -> "World":
        return cls(_layout(festival or load_festival()), case, case.get("seed", 0) if seed is None else seed)

    def __init__(self, layout: _Layout, case: dict[str, Any], seed: int):
        L = self.L = layout
        P = self.P = layout.params
        self.case_id = case.get("id", "")
        self.seed = seed
        self.rng = random.Random(seed)
        self.t = 0
        self.duration = int(case.get("duration_min", 90))
        m = _hhmm_to_min(case.get("start_hhmm", "18:00"))
        if m < _DAY_START:  # madrugada: pertenece a la noche del mismo día de festival
            m += _DAY
        self.abs0 = (int(case.get("day", 1)) - 1) * _DAY + m
        init = case.get("initial", {})
        self.spontaneous = bool(init.get("spontaneous", True))
        # Capa de «operación real», OPCIONAL (`initial.ops`): sin ella nada cambia. Son parámetros del recinto que el
        # agente NO conoce de antemano y solo puede estimar observando: lo que tarda de verdad cada reposición, quién
        # coge el teléfono y cuánto cuesta encontrar a alguien en una zona amplia sin un punto concreto.
        self.ops: dict[str, Any] = dict(init.get("ops") or {})
        self.dry_minutes: dict[int, int] = {}         # minutos con el depósito a cero, por punto de agua
        self.stockouts: list[dict[str, Any]] = []     # roturas de stock que llegaron a ocurrir

        self.occ = [0] * L.n
        self.state = ["open"] * L.n
        self.flags = [dict(f) for f in L.flags0]
        self.population = int(L.fest["attendance"])
        self.outside = self.population
        self.exited = 0
        self.injected_people = 0
        self.backlog = 0
        self.carry: dict[int, float] = {}
        self.weather = dict(L.fest.get("weather", {}))
        self.weather.update(init.get("weather", {}))

        self.resources: dict[str, Resource] = {
            r["id"]: Resource(r["id"], ResourceKind(r["kind"]), r["name"], r["zone"], contact=r.get("contact", ""),
                              shift_ends=r.get("shift_ends"))
            for r in L.fest["resources"]}
        self.travel: dict[str, dict[str, Any]] = {}   # recurso en ruta
        self.timed: dict[str, dict[str, Any]] = {}    # recurso ocupado con tarea de duración fija
        self.incidents: dict[str, Incident] = {}
        self.records: dict[str, dict[str, Any]] = {}  # tiempos verdaderos por incidente
        self.active: list[str] = []
        self.reports: list[Report] = []
        self.report_truth: dict[str, str | None] = {}
        self.held: list[Report] = []                  # avisos retenidos por canal caído
        self.live: dict[str, Action] = {}             # acciones en EXECUTING
        self.action_log: dict[str, dict[str, Any]] = {}
        self.injected: list[dict[str, Any]] = []
        self.wasted: list[dict[str, Any]] = []
        self.skipped: list[dict[str, Any]] = []       # eventos condicionales que no llegaron a ocurrir

        self.reroutes: dict[int, tuple[int, float, int | None]] = {}
        self.broadcasts: dict[int, int] = {}
        self.inflows: list[tuple[int, float, int | None]] = []
        self.evac: dict[int, str | None] = {}         # zona -> id de la acción que la evacua
        self.evac_all: str | None = None
        self.show_stopped = False
        self.stopped_stages: set[int] = set()
        self.no_answer: dict[str, int] = {}
        self.rejects: dict[str, int] = {}
        self.offline_until: dict[str, int] = {}
        self.comms_down: dict[str, int] = {}
        self.transport_factor = 1.0
        self.transport_until: int | None = None
        self.externals: list[dict[str, Any]] = []
        self.dry_since: dict[int, int] = {}
        self.sensor_last: dict[int, int] = {}
        self.crush_open: dict[int, str] = {}
        self.peak = [0.0] * L.n
        self.peak_t = [0] * L.n
        self.peak_occ = [0] * L.n
        self.over5 = [0] * L.n
        self.over_cap = [0] * L.n
        self.seq = 0
        self.is_twin = False
        self.transport_boost = 1.0
        self.dhist: list[list[float]] = []            # densidades de los últimos minutos (para la tendencia)
        self.trend_last: dict[int, int] = {}
        self.wind_level = 0
        self.wind_last = -10 ** 6
        self.flow_last: dict[int, int] = {}           # personas movidas en el último tick, clave origen*64+destino
        self.arrivals_last: dict[int, int] = {}
        self.exits_last: dict[int, int] = {}
        self._rep_cur: list[Report] = []
        self._rep_obs: list[Report] = []
        self._res_cur: list[Action] = []
        self._res_obs: list[Action] = []

        self._ph_i = max(0, bisect_right(L.starts, self.abs0) - 1)
        self._phase = L.timeline[self._ph_i]
        self._initial_crowd(init)
        for rid in init.get("resources_offline", []):
            if rid in self.resources:
                self.resources[rid].status = ResourceStatus.OFFLINE
        for z, st in init.get("zone_state", {}).items():
            if z in L.idx and st in P["state_inflow"]:
                self.state[L.idx[z]] = st
        for z, fl in init.get("flags", {}).items():
            if z in L.idx:
                self.flags[L.idx[z]].update(fl)

        self.events = sorted(case.get("events", []), key=lambda e: e.get("t", 0))
        self._ev_i = 0
        self._fire_events()
        self._sensors()
        self._rep_obs, self._rep_cur = self._rep_cur, []

    def _initial_crowd(self, init: dict[str, Any]) -> None:
        ph, L = self._phase, self.L
        frac = ph.arrived_before + ph.share * (self.abs0 - ph.start) / (ph.end - ph.start)
        arrived = int(ph.attendance * min(frac, 1.0))
        inside = arrived
        if ph.leaving:
            gone = 1.0 if ph.profile == "closed" else 0.9 * (self.abs0 - ph.start) / (ph.end - ph.start)
            inside = int(arrived * (1.0 - gone))
        w = ph.weights
        self.occ = [int(inside * w[i]) for i in range(L.n)]
        self.occ[L.general] += inside - sum(self.occ)
        self.exited = arrived - inside
        self.outside = self.population - arrived
        for z, n in init.get("occupancy", {}).items():
            if z in L.idx:
                i = L.idx[z]
                self.outside -= int(n) - self.occ[i]
                self.occ[i] = max(0, int(n))
        if self.outside < 0:  # el caso mete más gente de la que quedaba fuera
            self.population -= self.outside
            self.injected_people -= self.outside
            self.outside = 0

    # ------------------------------------------------------------------ lectura

    def clock(self) -> dict[str, Any]:
        a = self.abs0 + self.t
        return {"day": self._phase.day, "hhmm": f"{(a % _DAY) // 60:02d}:{a % 60:02d}",
                "show_phase": "stopped" if self.show_stopped else self._phase.name}

    def observe(self) -> Observation:
        L, t = self.L, self.t
        zones = {}
        for i, zid in enumerate(L.ids):
            fl = dict(self.flags[i])
            rr = self.reroutes.get(i)
            if rr:
                fl["reroute_to"] = L.ids[rr[0]]
            if i in self.evac or self.evac_all:
                fl["evacuating"] = True
            if self.broadcasts.get(i, 0) > t:
                fl["broadcast_until"] = self.broadcasts[i]
            fl["flow_out"] = out = {}
            if i in self.exits_last:
                out["outside"] = self.exits_last[i]
            if i in self.arrivals_last:
                fl["arrivals"] = self.arrivals_last[i]
            zones[zid] = Zone(zid, L.names[i], L.kinds[i], L.area[i], L.capacity[i], self.occ[i],
                              self.state[i], list(L.neighbors[i]), fl)
        for key, m in self.flow_last.items():
            zones[L.ids[key // 64]].flags["flow_out"][L.ids[key % 64]] = m
        resources = {r.id: Resource(r.id, r.kind, r.name, r.zone, r.status, r.task, r.contact, r.eta, r.shift_ends)
                     for r in self.resources.values()}
        weather = dict(self.weather)
        weather["wind_level"] = self.wind_level  # 0 normal · 1 preaviso · 2 riesgo en estructuras · 3 riesgo grave
        return Observation(t, zones, resources, list(self._rep_obs), list(self._res_obs), weather, self.clock())

    def done(self) -> bool:
        return self.t >= self.duration

    def density(self, zone: str) -> float:
        i = self.L.idx[zone]
        return self.occ[i] / self.L.area[i]

    def travel_time(self, from_zone: str, to_zone: str, resource_id: str | None = None) -> int | None:
        """Minutos estimados ahora mismo; None si no hay ruta (p. ej. ambulancia bloqueada)."""
        L = self.L
        if from_zone not in L.idx or to_zone not in L.idx:
            return None
        r = self.resources.get(resource_id) if resource_id else None
        route = self._route(L.idx[from_zone], L.idx[to_zone], bool(r and r.kind is ResourceKind.AMBULANCE))
        return None if route is None else math.ceil(route[1])

    def contact_state(self, resource_id: str) -> str:
        """ok | offline | no_answer | rejects. Lo consulta SimComms."""
        r = self.resources.get(resource_id)
        if r is None or r.status is ResourceStatus.OFFLINE:
            return "offline"
        if self.no_answer.get(resource_id, -1) > self.t:
            return "no_answer"
        if self.rejects.get(resource_id, -1) > self.t:
            return "rejects"
        return "ok"

    def channel_down(self, channel: Channel | str | None) -> bool:
        if self.comms_down.get("all", -1) > self.t:
            return True
        return channel is not None and self.comms_down.get(str(channel), -1) > self.t

    def answer_for(self, action: Action) -> tuple[str, dict[str, Any]]:
        """Respuesta a un ASK con el dato que faltaba, sacado de la verdad del caso."""
        inc, known = self._truth_target(action)
        if inc is None and action.zone in self.L.idx:  # pregunta por una zona: alguien mira y cuenta lo que hay
            inc, known = self._match(self.L.idx[action.zone], None), True
        if inc is not None and inc.status in _ACTIVE:
            zname = self.L.names[self.L.idx[inc.zone]] if inc.zone in self.L.idx else "zona sin confirmar"
            needs = ", ".join(f"{n} de {k}" for k, n in inc.needs.items()) or "nada por ahora"
            text = (f"Confirmado: {inc.type.replace('_', ' ')} en {zname}. Gravedad {inc.severity} sobre 10. "
                    f"Hace falta: {needs}.")
            data = {"exists": True, "zone": inc.zone, "type": inc.type, "family": inc.family.value,
                    "severity": inc.severity, "needs": dict(inc.needs), "deadline": inc.deadline}
            point = self._point_for(inc) if action.params.get("precise") else None
            if point:
                text += f" Estamos junto a {point}."
                data["point"] = point
            return text, data
        if known or inc is not None:
            return "He mirado y aquí no pasa nada. Falsa alarma o ya está resuelto.", {"exists": False}
        return "No tengo más datos de eso ahora mismo.", {"exists": None}

    # -- capa «ops»: localizar a alguien en una zona amplia -----------------------------------------
    _POINTS = ("la torre de sonido", "la torre de luces 2", "el puesto 7", "la barra 3", "el acceso 4", "el mástil 5")

    def _locate_range(self, inc: Incident | None) -> tuple[int, int] | None:
        """(mín, máx) minutos de búsqueda si el incidente es de una PERSONA en una zona amplia; None si no aplica."""
        spec = (self.ops.get("locate") or {}) if self.ops else {}
        if inc is None or not spec or inc.family not in (Family.MEDICAL, Family.AGGRESSION):
            return None
        rng = (spec.get("zones") or {}).get(inc.zone or "")
        return (int(rng[0]), int(rng[1])) if rng else None

    def _point_for(self, inc: Incident) -> str | None:
        """El punto concreto que sabe dar quien avisó (no siempre sabe: `locate.p_point`). Determinista por incidente."""
        if self._locate_range(inc) is None:
            return None
        h = random.Random(f"{self.seed}:point:{inc.id}")
        if h.random() >= float(self.ops["locate"].get("p_point", 0.8)):
            return None
        return h.choice(self._POINTS)

    def truth(self) -> dict[str, Any]:
        L = self.L
        incidents = {}
        for iid, inc in self.incidents.items():
            d = inc.to_dict()
            d.update(self.records[iid])
            incidents[iid] = d
        return {
            "case_id": self.case_id, "seed": self.seed, "t": self.t, "duration": self.duration, "twin": self.is_twin,
            "clock": self.clock(), "weather": dict(self.weather),
            "incidents": incidents,
            "peak_density": {L.ids[i]: {"density": round(self.peak[i], 3), "occupancy": self.peak_occ[i],
                                        "t": self.peak_t[i]} for i in range(L.n)},
            "minutes_over_5": {L.ids[i]: self.over5[i] for i in range(L.n)},
            "minutes_over_capacity": {L.ids[i]: self.over_cap[i] for i in range(L.n)},
            "occupancy": {L.ids[i]: self.occ[i] for i in range(L.n)},
            "zone_state": {L.ids[i]: self.state[i] for i in range(L.n)},
            "population": {"total": self.population, "outside": self.outside, "inside": sum(self.occ),
                           "exited": self.exited, "injected": self.injected_people, "backlog": self.backlog},
            "resources": {r.id: {"zone": r.zone, "status": r.status.value, "task": r.task}
                          for r in self.resources.values()},
            "reports": dict(self.report_truth),
            "wasted_dispatches": [dict(w) for w in self.wasted],
            "skipped_events": [dict(e) for e in self.skipped],
            "water": {"dry_minutes": {L.ids[i]: n for i, n in self.dry_minutes.items()},
                      "stockouts": [dict(x) for x in self.stockouts]},
            "actions": [dict(a) for a in self.action_log.values()],
            "injected": [dict(e) for e in self.injected],
        }

    def clone(self) -> "World":
        """Copia exacta, futuro incluido y mismo estado del RNG. Es la del adversario."""
        rng = random.Random()
        rng.setstate(self.rng.getstate())
        return self._copy(rng)

    def twin(self, seed: int | None = None) -> "World":
        """Gemelo para ENSAYAR una decisión: el estado de ahora, sin futuro.

        No lleva los eventos del caso que aún no han ocurrido, ni incidentes espontáneos (calor, viento, agua),
        ni avisos retenidos; su RNG es propio. Lo que ya está en marcha sigue: acciones vivas, desvíos, externos
        pedidos y las oleadas activas, que se suponen indefinidas al ritmo actual (no sabe cuándo acaban).
        """
        new = self._copy(random.Random((self.seed * 1000003 + self.t) ^ 0x7717 if seed is None else seed))
        new.is_twin = True
        new.spontaneous = False
        new._ev_i = len(new.events)
        new.held = []
        new.inflows = [(z, rate, None) for z, rate, _ in new.inflows]
        new.duration = 10 ** 9
        return new

    def _copy(self, rng: random.Random) -> "World":
        new = World.__new__(World)
        d = new.__dict__
        d.update(self.__dict__)  # lo estático (L, P, events) y lo que se reemplaza entero en cada tick se comparte
        new.rng = rng
        for k in ("occ", "state", "peak", "peak_t", "peak_occ", "over5", "over_cap", "reports", "held", "inflows",
                  "active", "_rep_cur", "_rep_obs"):
            d[k] = list(d[k])
        for k in ("carry", "weather", "report_truth", "reroutes", "broadcasts", "evac", "no_answer", "rejects",
                  "offline_until", "comms_down", "dry_since", "sensor_last", "crush_open", "trend_last", "dry_minutes"):
            d[k] = dict(d[k])
        new.stopped_stages = set(self.stopped_stages)
        new.stockouts = list(self.stockouts)
        new.flags = [dict(f) for f in self.flags]
        new.resources = {r.id: Resource(r.id, r.kind, r.name, r.zone, r.status, r.task, r.contact, r.eta, r.shift_ends)
                         for r in self.resources.values()}
        new.incidents = {}
        for iid, inc in self.incidents.items():
            c = copy.copy(inc)
            c.needs, c.reports, c.assigned, c.notes = dict(inc.needs), list(inc.reports), list(inc.assigned), list(inc.notes)
            new.incidents[iid] = c
        new.records = {k: dict(v) for k, v in self.records.items()}
        new.action_log = {k: dict(v) for k, v in self.action_log.items()}
        new.injected = list(self.injected)
        new.wasted = list(self.wasted)
        new.skipped = list(self.skipped)
        # las acciones vivas se copian para que el futuro simulado no toque las del agente
        amap: dict[int, Action] = {}
        for a in list(self.live.values()) + self._res_cur + self._res_obs:
            if id(a) not in amap:
                c = copy.copy(a)
                c.params = dict(a.params)
                amap[id(a)] = c
        new.live = {k: amap[id(a)] for k, a in self.live.items()}
        new._res_cur = [amap[id(a)] for a in self._res_cur]
        new._res_obs = [amap[id(a)] for a in self._res_obs]

        def task(v: dict[str, Any]) -> dict[str, Any]:
            c = dict(v)
            if "path" in c:
                c["path"] = list(c["path"])
            if c.get("action") is not None:
                c["action"] = amap.get(id(c["action"]), c["action"])
            if "job" in c:      # búsqueda en curso: el trayecto guardado dentro también se copia
                c["job"] = task(c["job"])
            return c
        new.travel = {k: task(v) for k, v in self.travel.items()}
        new.timed = {k: task(v) for k, v in self.timed.items()}
        new.externals = [task(v) for v in self.externals]
        return new

    # ------------------------------------------------------------------ avisos e incidentes

    def _next(self, prefix: str) -> str:
        self.seq += 1
        return f"{prefix}{self.seq}"

    def _add_report(self, r: dict[str, Any], truth: str | None) -> Report:
        rid = r.get("id") or self._next("r")
        if rid in self.report_truth:
            rid = self._next(f"{rid}-")
        try:
            ch = Channel(r.get("channel", "whatsapp"))
        except ValueError:
            ch = Channel.WHATSAPP
        rep = Report(rid, self.t, ch, r.get("text", ""), r.get("source", ""), r.get("lang", "es"),
                     r.get("zone_hint"), truth if truth else r.get("truth_incident"))
        self.report_truth[rid] = rep.truth_incident
        (self.held if self.channel_down(ch) else self._rep_cur).append(rep)
        self.reports.append(rep)
        return rep

    def _open_incident(self, d: dict[str, Any], reports: list[dict[str, Any]], origin: str) -> Incident:
        iid = d.get("id") or self._next("x")
        if iid in self.incidents:
            iid = self._next(f"{iid}-")
        try:
            fam = Family(d.get("family", "info"))
        except ValueError:
            fam = Family.INFO
        deadline = d.get("deadline")
        if deadline is not None and deadline <= self.t:  # el generador lo dio relativo a la apertura
            deadline = self.t + int(deadline)
        inc = Incident(iid, fam, d.get("type", "unknown"), d.get("zone"), int(d.get("severity", 5)), self.t,
                       deadline, dict(d.get("needs", {})), notes=list(d.get("notes", [])))
        sm = self.P["service_min"]
        base = d.get("service_min") or sm["type"].get(inc.type) or sm["family"].get(fam.value) or sm["default"]
        lo, hi = base if isinstance(base, list) else (base * 0.85, base * 1.15)
        self.incidents[iid] = inc
        self.records[iid] = {"origin": origin, "t_first_dispatch": None, "t_first_attention": None,
                             "t_effective_dispatch": None, "t_resolved": None, "t_failed": None, "progress": 0.0,
                             "service_min": round(self.rng.uniform(lo, hi), 2)}
        self.active.append(iid)
        for r in reports:
            inc.reports.append(self._add_report(r, iid).id)
        return inc

    def _truth_target(self, action: Action) -> tuple[Incident | None, bool]:
        """Incidente verdadero al que apunta una acción, y si la referencia era conocida (aviso real)."""
        inc = self.incidents.get(action.incident) if action.incident else None
        if inc is not None:
            return inc, True
        refs = action.params.get("reports") or ([action.params["report"]] if action.params.get("report") else [])
        known = False
        for rid in refs:
            if rid in self.report_truth:
                known = True
                inc = self.incidents.get(self.report_truth[rid] or "")
                if inc is not None:
                    return inc, True
        return None, known

    def _match(self, zone: int, kind: ResourceKind | None) -> Incident | None:
        """Incidente activo más grave de la zona al que todavía le falta un recurso de este tipo."""
        zid, best = self.L.ids[zone], None
        for iid in self.active:
            inc = self.incidents[iid]
            if inc.zone != zid or (kind is not None and not self._needs(inc, kind)):
                continue
            if best is None or (-inc.severity, inc.t_open) < (-best.severity, best.t_open):
                best = inc
        return best

    def _needs(self, inc: Incident, kind: ResourceKind) -> bool:
        for need, n in inc.needs.items():
            if _covers(kind, need):
                have = sum(1 for rid in inc.assigned if _covers(self.resources[rid].kind, need))
                if have < n:
                    return True
        return False

    # ------------------------------------------------------------------ efectos (casos, jurado, Caos)

    def inject(self, event: dict[str, Any]) -> None:
        self._event(event, "inject")

    def _event(self, ev: dict[str, Any], origin: str) -> None:
        kind = ev.get("kind")
        cond = ev.get("cond")
        if cond and "unless_resolved" in cond:
            # encadenamiento: el derivado solo nace si el origen sigue sin resolver (id desconocido = nace igual)
            src = self.incidents.get(cond["unless_resolved"])
            if src is not None and src.status in (IncidentStatus.RESOLVED, IncidentStatus.FALSE_ALARM):
                what = ev.get("incident", {}).get("id") or ev.get("effect", {}).get("kind") or kind
                self.skipped.append({"t": self.t, "origin": origin, "kind": kind, "what": what, "cond": dict(cond),
                                     "reason": f"{src.id} {src.status.value} en t={self.records[src.id]['t_resolved']}"})
                return
        if kind == "world" and "effect" in ev:
            self._effect(ev["effect"], origin)
        elif kind == "report_only":
            for r in ev.get("reports", []):
                self._add_report(r, None)
        else:
            self._effect(ev, origin)

    def _fire_events(self) -> None:
        ev = self.events
        while self._ev_i < len(ev) and ev[self._ev_i].get("t", 0) <= self.t:
            self._event(ev[self._ev_i], "case")
            self._ev_i += 1

    def _effect(self, e: dict[str, Any], origin: str) -> None:
        L, P, t = self.L, self.P, self.t
        log = {"t": t, "origin": origin, "effect": e}
        self.injected.append(log)
        kind = e.get("kind")
        n = e.get("n", e.get("ticks", e.get("duration")))
        rid = e.get("resource", e.get("id"))
        zi = L.idx.get(e.get("zone", e.get("id")))
        r = self.resources.get(rid) if isinstance(rid, str) else None
        if kind in ("resource_offline", "resource_online", "resource_no_answer", "resource_rejects") and r is None:
            log["error"] = "unknown_resource"
        elif kind in ("zone_state", "zone_inflow", "zone_flag") and zi is None:
            log["error"] = "unknown_zone"
        elif kind == "resource_offline":
            self._release(r, "resource_offline", ActionStatus.FAILED)
            r.status = ResourceStatus.OFFLINE
            if n:
                self.offline_until[r.id] = t + int(n)
        elif kind == "resource_online":
            self.offline_until.pop(r.id, None)
            if r.status is ResourceStatus.OFFLINE:
                r.status = ResourceStatus.AVAILABLE
        elif kind == "resource_no_answer":
            self.no_answer[r.id] = t + int(n or P["no_answer_default_min"])
        elif kind == "resource_rejects":
            self.rejects[r.id] = t + int(n or P["rejects_default_min"])
        elif kind == "zone_state":
            if e.get("state") in P["state_inflow"]:
                self.state[zi] = e["state"]
            else:
                log["error"] = "unknown_state"
        elif kind == "zone_inflow":
            rate = e.get("per_min", e.get("rate", e.get("people_per_min", e.get("value", 0))))
            self.inflows.append((zi, float(rate), t + int(n) if n else None))
        elif kind == "zone_flag":
            if "flag" in e:
                self.flags[zi][e["flag"]] = e.get("value")
            for k, v in e.items():  # también vale la forma {"zone": "food", "power": false}
                if k not in _EFFECT_META:
                    self.flags[zi][k] = v
        elif kind == "weather":
            self.weather.update({k: v for k, v in e.items() if k not in ("kind", "reason")})
        elif kind == "comms_down":
            self.comms_down[str(e.get("channel") or "all")] = t + int(n or 10)
        elif kind == "incident":
            body = e.get("incident") or {k: v for k, v in e.items() if k not in ("kind", "reports", "t")}
            log["effect"] = {"kind": "incident", "id": self._open_incident(body, e.get("reports", []), origin).id}
        elif kind == "transport_cut":
            self.transport_factor = float(e.get("factor", 0.0))
            self.transport_until = t + int(n) if n else None
        else:
            log["error"] = "unknown_effect"

    # ------------------------------------------------------------------ acciones

    def apply(self, action: Action) -> Action:
        """Ejecuta la acción sobre el mundo. Muta y devuelve el mismo objeto; nunca lanza."""
        if action.status in _TERMINAL or action.status is ActionStatus.AWAITING_APPROVAL or action.id in self.live:
            return action
        self.action_log[action.id] = {"id": action.id, "kind": str(action.kind), "t": self.t, "zone": action.zone,
                                      "resource": action.resource, "incident": action.incident,
                                      "autonomy": str(action.autonomy), "status": str(action.status)}
        try:
            handler = getattr(self, f"_do_{ActionKind(action.kind).value}")
            if action.kind in (ActionKind.DISPATCH, ActionKind.REQUEST_EXTERNAL) and action.channel is not None \
                    and self.channel_down(action.channel):
                self._finish(action, ActionStatus.FAILED, "comms_down")
            else:
                handler(action)
        except Exception as ex:  # una acción imposible nunca tumba la ejecución
            self._finish(action, ActionStatus.FAILED, f"internal: {ex!r}")
        return action

    def _finish(self, a: Action, status: ActionStatus, error: str | None = None) -> None:
        a.status = status
        if error:
            a.params["error"] = error
        if status is ActionStatus.EXECUTING:
            self.live[a.id] = a
        else:
            self.live.pop(a.id, None)
        log = self.action_log.get(a.id)
        if log is not None:
            log["status"] = status.value
            if status is not ActionStatus.EXECUTING:
                log["t_end"] = self.t
            if error:
                log["error"] = error
        if not any(x is a for x in self._res_cur):
            self._res_cur.append(a)

    def _zone_of(self, a: Action, key: str = "zone") -> int | None:
        z = a.zone if key == "zone" else None
        return self.L.idx.get(z or a.params.get(key) or "")

    def _do_dispatch(self, a: Action) -> None:
        r = self.resources.get(a.resource or "")
        if r is None:
            return self._finish(a, ActionStatus.FAILED, "unknown_resource")
        cs = self.contact_state(r.id)
        if cs != "ok":
            return self._finish(a, ActionStatus.REJECTED if cs == "rejects" else ActionStatus.FAILED,
                                {"rejects": "rejected", "offline": "resource_offline"}.get(cs, cs))
        if r.status is not ResourceStatus.AVAILABLE:
            return self._finish(a, ActionStatus.FAILED, "resource_busy")
        inc, _ = self._truth_target(a)
        if inc is not None and inc.status not in _ACTIVE:
            return self._finish(a, ActionStatus.FAILED, "incident_closed")
        dest = self.L.idx.get(inc.zone or "") if inc is not None else self._zone_of(a)
        if dest is None:
            return self._finish(a, ActionStatus.FAILED, "unknown_target")
        if inc is None:
            inc = self._match(dest, r.kind)
        elif not any(_covers(r.kind, need) for need in inc.needs):
            inc = None  # tipo de recurso que ese incidente no necesita: irá, no servirá y volverá
        self._go(r, dest, a, inc)

    def _go(self, r: Resource, dest: int, a: Action | None, inc: Incident | None, then: str = "attend",
            payload: Any = None) -> None:
        route = self._route(self.L.idx[r.zone], dest, r.kind is ResourceKind.AMBULANCE)
        if route is None:
            if a is not None:
                self._finish(a, ActionStatus.FAILED, "route_blocked")
            return
        path, eta = route
        r.status, r.eta = ResourceStatus.EN_ROUTE, math.ceil(eta)
        r.task = (a.incident if a is not None and a.incident else None) or (inc.id if a is None and inc else None)
        if inc is not None and then == "attend":
            if r.id not in inc.assigned:
                inc.assigned.append(r.id)
            if inc.status is IncidentStatus.OPEN:
                inc.status = IncidentStatus.ASSIGNED
            if self.records[inc.id]["t_first_dispatch"] is None:
                self.records[inc.id]["t_first_dispatch"] = self.t
        self.travel[r.id] = {"path": path, "prog": 0.0, "dest": dest, "action": a, "then": then,
                             "truth": inc.id if inc is not None else None, "payload": payload, "blocked": 0, "t0": self.t,
                             "point": a.params.get("point") if a is not None else None}
        if a is not None:
            a.params["eta"] = r.eta
            a.params["path"] = [self.L.ids[i] for i in path]
            self._finish(a, ActionStatus.EXECUTING)
        if not path:
            self._arrive(r)

    def _do_recall(self, a: Action) -> None:
        r = self.resources.get(a.resource or "")
        if r is None:
            return self._finish(a, ActionStatus.FAILED, "unknown_resource")
        if r.status is ResourceStatus.OFFLINE:
            return self._finish(a, ActionStatus.FAILED, "resource_offline")
        self._release(r, "recalled", ActionStatus.CANCELLED)
        self._finish(a, ActionStatus.DONE)

    def _do_set_zone(self, a: Action) -> None:
        zi, st = self._zone_of(a), a.params.get("state")
        if zi is None or st not in self.P["state_inflow"]:
            return self._finish(a, ActionStatus.FAILED, "unknown_zone" if zi is None else "unknown_state")
        self.state[zi] = st
        if st != "closed":
            self.evac.pop(zi, None)  # reabrir una zona evacuada da por terminada la evacuación
        self._finish(a, ActionStatus.DONE)

    def _do_reroute(self, a: Action) -> None:
        src = self._zone_of(a)
        if src is None:
            src = self._zone_of(a, "from")
        p = a.params
        if src is not None and (p.get("cancel") or p.get("fraction") == 0):
            self.reroutes.pop(src, None)
            return self._finish(a, ActionStatus.DONE)
        dst = self.L.idx.get(p.get("to") or p.get("target") or p.get("to_zone") or "")
        if src is None or dst is None or src == dst:
            return self._finish(a, ActionStatus.FAILED, "unknown_zone")
        frac = min(1.0, max(0.0, float(p.get("fraction", self.P["reroute_fraction"]))))
        self.reroutes[src] = (dst, frac, self.t + int(p["minutes"]) if p.get("minutes") else None)
        self._finish(a, ActionStatus.DONE)

    def _do_broadcast(self, a: Action) -> None:
        zi = self._zone_of(a)
        if zi is not None:
            self.broadcasts[zi] = self.t + int(a.params.get("minutes", self.P["broadcast_minutes"]))
        self._finish(a, ActionStatus.DONE)

    def _do_resupply(self, a: Action) -> None:
        zi = self._zone_of(a)
        if zi is None or "water_l" not in self.flags[zi]:
            return self._finish(a, ActionStatus.FAILED, "no_water_point")
        r = self.resources.get(a.resource or "log_1")
        if r is None or r.kind is not ResourceKind.LOGISTICS:
            return self._finish(a, ActionStatus.FAILED, "needs_logistics")
        if r.status is not ResourceStatus.AVAILABLE or self.contact_state(r.id) != "ok":
            return self._finish(a, ActionStatus.FAILED, "resource_busy")
        a.resource = r.id
        self._go(r, zi, a, self._match(zi, r.kind), then="resupply", payload=a.params.get("litres"))

    def _do_evacuate(self, a: Action) -> None:
        if a.zone in (None, "", "all") and not a.params.get("zone"):
            self.evac_all = a.id
        else:
            zi = self._zone_of(a)
            if zi is None:
                return self._finish(a, ActionStatus.FAILED, "unknown_zone")
            self.evac[zi] = a.id
        self._finish(a, ActionStatus.EXECUTING)

    def _do_stop_show(self, a: Action) -> None:
        resume = bool(a.params.get("resume", False))
        zi = self.L.idx.get(a.zone or "")
        if zi is None or zi not in self.L.stages:
            self.stopped_stages = set() if resume else set(self.L.stages)
        elif resume:
            self.stopped_stages.discard(zi)
        else:
            self.stopped_stages.add(zi)
        self.show_stopped = bool(self.L.stages) and self.L.stages <= self.stopped_stages
        self._finish(a, ActionStatus.DONE)

    def _do_request_external(self, a: Action) -> None:
        P = self.P
        kind = str(a.params.get("kind", a.params.get("service", "ambulance")))
        if kind not in P["external_eta_min"]:
            return self._finish(a, ActionStatus.FAILED, "unknown_external")
        eta = P["external_eta_min"][kind] + self.rng.randint(0, 3)
        if self.transport_factor < 1.0 and kind != "transport":
            eta += P["transport_cut_delay_min"]
        inc, _ = self._truth_target(a)
        self.externals.append({"at": self.t + eta, "kind": kind, "action": a, "truth": inc.id if inc else None,
                               "zone": self._zone_of(a)})
        a.params["eta"] = eta
        self._finish(a, ActionStatus.EXECUTING)

    def _noop(self, a: Action) -> None:  # no cambian el mundo físico; quedan en el registro
        self._finish(a, ActionStatus.DONE)

    def _do_notify(self, a: Action) -> None:
        """Sin efecto físico, salvo pasarle a un equipo el PUNTO concreto donde está la persona (capa «ops»)."""
        rid = a.resource or ""
        if a.params.get("point") and rid in self.resources:
            if rid in self.travel:
                self.travel[rid]["point"] = a.params["point"]
            job = self.timed.get(rid)
            if job is not None and job.get("then") == "found":   # ya estaba buscando: con el punto, lo encuentra ya
                job["until"] = min(job["until"], self.t + 1)
                job["job"]["point"] = a.params["point"]
        self._finish(a, ActionStatus.DONE)

    _do_ask = _do_merge = _do_dismiss = _noop

    def _release(self, r: Resource, reason: str, action_status: ActionStatus) -> None:
        """Suelta al recurso de lo que estuviera haciendo y lo deja AVAILABLE donde está."""
        for job in (self.travel.pop(r.id, None), self.timed.pop(r.id, None)):
            if job and job.get("action") is not None and job["action"].status is ActionStatus.EXECUTING:
                self._finish(job["action"], action_status, reason)
        for iid in self.active:
            inc = self.incidents[iid]
            if r.id in inc.assigned:
                inc.assigned.remove(r.id)
                self._restatus(inc)
        if r.status is not ResourceStatus.OFFLINE:
            r.status = ResourceStatus.AVAILABLE
        r.task, r.eta = None, 0

    def _restatus(self, inc: Incident) -> None:
        if inc.status not in _ACTIVE:
            return
        res = self.resources
        if any(res[x].status is ResourceStatus.BUSY and res[x].zone == inc.zone for x in inc.assigned):
            inc.status = IncidentStatus.IN_PROGRESS
        else:
            inc.status = IncidentStatus.ASSIGNED if inc.assigned else IncidentStatus.OPEN

    # ------------------------------------------------------------------ recursos

    def _slow(self, d: float) -> float:
        for limit, factor in self.P["slow"]:
            if d < limit:
                return factor
        return 4.0

    def _route(self, src: int, dst: int, ambulance: bool) -> tuple[list[int], float] | None:
        """Dijkstra; entrar en una zona densa cuesta más. La ambulancia no cruza zonas por encima de
        `amb_max_density`: solo puede entrar en una así si es el destino (último tramo a pie, con camilla)."""
        if src == dst:
            return [], 0.0
        L, occ, amb_max = self.L, self.occ, self.P["amb_max_density"]
        dist = {src: 0.0}
        prev: dict[int, int] = {}
        heap = [(0.0, src)]
        while heap:
            d, u = heapq.heappop(heap)
            if u == dst:
                path = [u]
                while path[-1] != src:
                    path.append(prev[path[-1]])
                return path[-2::-1], d
            if d > dist[u]:
                continue
            for v, m in L.adj[u]:
                dens = occ[v] / L.area[v]
                if ambulance and v != dst and (dens > amb_max or not L.vehicle[v]):
                    continue
                nd = d + m * self._slow(dens)
                if nd < dist.get(v, 1e18):
                    dist[v], prev[v] = nd, u
                    heapq.heappush(heap, (nd, v))
        return None

    def _step_resources(self) -> None:
        L, t = self.L, self.t
        for rid in [k for k, until in self.offline_until.items() if until <= t]:
            del self.offline_until[rid]
            if self.resources[rid].status is ResourceStatus.OFFLINE:
                self.resources[rid].status = ResourceStatus.AVAILABLE
        for rid in list(self.travel):
            r, job = self.resources[rid], self.travel[rid]
            path = job["path"]
            cur, nxt = L.idx[r.zone], path[0]
            amb = r.kind is ResourceKind.AMBULANCE
            if amb and nxt != job["dest"] and self.occ[nxt] / L.area[nxt] > self.P["amb_max_density"]:
                route = self._route(cur, job["dest"], True)
                if route is None:  # bloqueada: espera a que se despeje
                    job["blocked"] += 1
                    continue
                path = job["path"] = route[0]
                job["prog"], nxt = 0.0, path[0]
            job["prog"] += 1.0 / self._slow(self.occ[nxt] / L.area[nxt])
            if job["prog"] + 1e-9 >= L.minutes[(cur, nxt)]:
                r.zone, job["prog"] = L.ids[nxt], 0.0
                path.pop(0)
            if not path:
                self._arrive(r)
            else:
                rest, prv = -job["prog"] * self._slow(self.occ[path[0]] / L.area[path[0]]), L.idx[r.zone]
                for z in path:
                    rest += L.minutes[(prv, z)] * self._slow(self.occ[z] / L.area[z])
                    prv = z
                r.eta = max(1, math.ceil(rest))
        for rid, job in self.timed.items():
            if job["then"] == "found":
                self.resources[rid].eta = max(1, job["until"] - t)
        for rid in [k for k, job in self.timed.items() if job["until"] <= t]:
            job, r = self.timed.pop(rid), self.resources[rid]
            if job["then"] == "found":      # ha dado con la persona: ahora sí llega
                job["job"]["searched_real"] = t - job["since"]
                self.travel[rid] = job["job"]
                self._arrive(r)
                continue
            if job["then"] == "refill":
                fl = self.flags[job["dest"]]
                cap = fl.get("water_capacity_l", 8000)
                fl["water_l"] = min(cap, fl.get("water_l", 0) + float(job["payload"] or cap))
                for iid in list(self.active):  # rellenar cierra el incidente de agua de esa zona
                    inc = self.incidents[iid]
                    if inc.family is Family.SUPPLY and inc.zone == r.zone:
                        self._close(inc, IncidentStatus.RESOLVED)
            if job.get("action") is not None and job["action"].status is ActionStatus.EXECUTING:
                self._finish(job["action"], ActionStatus.DONE)
            if r.status is ResourceStatus.BUSY:
                r.status, r.task = ResourceStatus.AVAILABLE, None
        for r in self.resources.values():
            if r.shift_ends is not None and t >= r.shift_ends and r.status is ResourceStatus.AVAILABLE:
                r.status = ResourceStatus.OFFLINE
        for ext in [x for x in self.externals if x["at"] <= t]:
            self.externals.remove(ext)
            if ext["kind"] == "transport":  # lanzaderas de refuerzo: más caudal de salida y suplen parte del corte
                self.transport_boost = self.P["transport_boost"]
                self.transport_factor = max(self.transport_factor, self.P["transport_relief_factor"])
                ext["action"].params["outcome"] = "transport_reinforced"
                self._finish(ext["action"], ActionStatus.DONE)
                continue
            kind = ResourceKind(self.P["external_kind"][ext["kind"]])
            rid = self._next(f"ext_{ext['kind']}_")
            r = self.resources[rid] = Resource(rid, kind, f"Externo: {ext['kind']}", L.ids[L.external_entry],
                                               contact="112")
            a = ext["action"]
            a.params["resource"] = rid
            self._finish(a, ActionStatus.DONE)
            inc = self.incidents.get(ext["truth"] or "")
            dest = L.idx.get(inc.zone or "") if inc is not None and inc.status in _ACTIVE else ext["zone"]
            if dest is not None:
                self._go(r, dest, None, inc if inc is not None and inc.status in _ACTIVE else self._match(dest, kind))

    def _resupply_minutes(self, zi: int) -> int:
        """Minutos de descarga y llenado. Con la capa «ops», un rango POR PUNTO (p. ej. el norte obliga a rodear);
        RNG propio por reposición para no alterar el del mundo."""
        rng = ((self.ops.get("resupply_min") or {}) if self.ops else {}).get(self.L.ids[zi])
        if not rng:
            return int(self.P["resupply_min"])
        return random.Random(f"{self.seed}:resupply:{self.L.ids[zi]}:{self.t}").randint(int(rng[0]), int(rng[1]))

    def _arrive(self, r: Resource) -> None:
        job = self.travel.pop(r.id)
        a, t = job["action"], self.t
        r.eta = 0
        if job["then"] == "resupply":
            r.status = ResourceStatus.BUSY
            minutes = self._resupply_minutes(job["dest"])
            self.timed[r.id] = {"until": t + minutes, "then": "refill", "dest": job["dest"],
                                "action": a, "payload": job["payload"]}
            return
        inc = self.incidents.get(job["truth"] or "")
        if "searched" not in job:
            # capa «ops»: en una zona amplia, sin un punto concreto, el equipo tarda en dar con la persona
            rng = self._locate_range(inc if inc is not None and inc.status in _ACTIVE else None)
            job["searched"] = 0
            if rng is not None and not job.get("point"):
                n = random.Random(f"{self.seed}:search:{inc.id}:{r.id}").randint(*rng)
                if n > 0:
                    job["searched"] = n
                    r.status, r.eta = ResourceStatus.EN_ROUTE, n
                    self.timed[r.id] = {"until": t + n, "then": "found", "dest": job["dest"], "action": a, "job": job,
                                        "since": t}
                    return
        if inc is not None and inc.status in _ACTIVE and self._locate_range(inc) is not None:
            spent = job.get("searched_real", job["searched"])
            self.records[inc.id].setdefault("search_min", spent)
            if a is not None:
                a.params["search_min"] = spent          # lo cuenta el equipo al llegar: es lo que OBSERVA el agente
                if job.get("point"):
                    a.params["point"] = job["point"]
        if inc is None or inc.status not in _ACTIVE or not (r.id in inc.assigned or self._needs(inc, r.kind)):
            explicit = a is not None and a.incident in self.incidents
            inc = None if explicit else self._match(job["dest"], r.kind)
        if inc is not None and not any(_covers(r.kind, need) for need in inc.needs):
            inc.assigned = [x for x in inc.assigned if x != r.id]
            self._restatus(inc)
            inc = None
        r.status = ResourceStatus.BUSY
        if inc is None:  # falsa alarma, duplicado o recurso que no hacía falta: mira, no encuentra nada y vuelve
            self.wasted.append({"t": t, "resource": r.id, "zone": r.zone, "action": a.id if a else None})
            self.timed[r.id] = {"until": t + self.P["check_min"], "then": "free", "dest": job["dest"], "action": None}
            if a is not None:
                a.params["outcome"] = "nothing_found"
                self._finish(a, ActionStatus.DONE)
            return
        if r.id not in inc.assigned:
            inc.assigned.append(r.id)
        inc.status = IncidentStatus.IN_PROGRESS
        rec = self.records[inc.id]
        if rec["t_first_dispatch"] is None:
            rec["t_first_dispatch"] = t
        if rec["t_first_attention"] is None:
            rec["t_first_attention"] = t
            rec["t_effective_dispatch"] = job.get("t0")   # cuándo salió el despacho que de verdad ACABÓ llegando
        if a is not None:
            a.params["outcome"] = "on_scene"
            self._finish(a, ActionStatus.DONE)

    def _close(self, inc: Incident, status: IncidentStatus) -> None:
        inc.status = status
        self.records[inc.id]["t_resolved" if status is IncidentStatus.RESOLVED else "t_failed"] = self.t
        self.active.remove(inc.id)
        for rid in list(inc.assigned):
            r = self.resources[rid]
            job = self.travel.pop(rid, None)
            if job is None and self.timed.get(rid, {}).get("then") == "found":
                job = self.timed.pop(rid)
            if job and job.get("action") is not None and job["action"].status is ActionStatus.EXECUTING:
                self._finish(job["action"], ActionStatus.CANCELLED, "incident_" + status.value)
            if r.status is not ResourceStatus.OFFLINE:
                r.status = ResourceStatus.AVAILABLE
            r.task, r.eta = None, 0

    def _step_incidents(self) -> None:
        """Avanza el servicio de lo que está atendido y falla lo que pasó su plazo sin atención."""
        L, res, t = self.L, self.resources, self.t
        for iid in list(self.active):
            inc = self.incidents[iid]
            if inc.status is IncidentStatus.IN_PROGRESS:
                on = [res[x].kind for x in inc.assigned if res[x].status is ResourceStatus.BUSY and res[x].zone == inc.zone]
                total = sum(inc.needs.values()) or 1
                got = sum(min(n, sum(1 for k in on if _covers(k, need))) for need, n in inc.needs.items())
                rec = self.records[iid]
                rec["progress"] = round(rec["progress"] + got / total, 3)
                if rec["progress"] >= rec["service_min"]:
                    zi = L.idx.get(inc.zone or "")
                    # una aglomeración no se da por resuelta mientras la zona siga saturada
                    if inc.family is not Family.CROWD or zi is None or self.occ[zi] <= L.capacity[zi]:
                        if inc.family is Family.SUPPLY and zi is not None and "water_l" in self.flags[zi]:
                            self.flags[zi]["water_l"] = self.flags[zi].get("water_capacity_l", 8000)
                        self._close(inc, IncidentStatus.RESOLVED)
            elif inc.deadline is not None and t >= inc.deadline and inc.needs:
                self._close(inc, IncidentStatus.FAILED)

    # ------------------------------------------------------------------ multitud

    def _weights(self, leaving: bool) -> list[float]:
        L, P, fl = self.L, self.P, self.flags
        w = list(L.evac_weights if self.evac_all else self._phase.weights)
        g = L.general
        for i in L.powered:
            if fl[i].get("power") is False:  # sin luz en restauración la gente se va a pista y foso
                lost = w[i] * (1 - P["power_off_food_factor"])
                w[i] -= lost; w[g] += 0.6 * lost; w[L.front] += 0.4 * lost
        for i in L.struct:
            if fl[i].get("structure_ok") is False:
                lost = w[i] * (1 - P["structure_risk_factor"])
                w[i] -= lost; w[g] += lost
        temp = self.weather.get("temp_c", 25)
        hot = 1 + max(0, temp - P["heat_threshold_c"]) * 0.1
        dry = [i for i in L.water if fl[i].get("water_l", 1) <= 0]
        for i in L.water:
            w[i] *= hot
        if dry and len(dry) < len(L.water):  # la cola se pasa al punto que aún tiene agua
            moved = 0.0
            for i in dry:
                lost = w[i] * (1 - P["dry_water_factor"])
                w[i] -= lost; moved += lost
            for i in L.water:
                if i not in dry:
                    w[i] += moved / (len(L.water) - len(dry))
        for i in self.stopped_stages:
            lost = w[i] * (1 - P["stop_show_factor"])
            w[i] -= lost; w[g] += lost
        if leaving and self.transport_factor < 1.0 and L.transport >= 0:
            w[L.transport] *= max(self.transport_factor, P["transport_cut_weight"])
        for i in self.broadcasts:
            w[i] *= 0.85
        for i in self.evac:
            w[i] = 0.0
        return w

    def _step_crowd(self) -> None:
        L, P, occ, t = self.L, self.P, self.occ, self.t
        n, area = L.n, L.area
        evac, reroutes = self.evac, self.reroutes
        leaving = self._phase.leaving or self.evac_all is not None
        for k in [k for k, until in self.broadcasts.items() if until <= t]:
            del self.broadcasts[k]
        for k in [k for k, v in reroutes.items() if v[2] is not None and v[2] <= t]:
            del reroutes[k]
        if self.inflows:
            self.inflows = [f for f in self.inflows if f[2] is None or f[2] > t]
        if self.transport_until is not None and self.transport_until <= t:
            self.transport_factor, self.transport_until = 1.0, None

        w = self._weights(leaving)
        k = sum(occ) / (sum(w) or 1.0)
        p = [occ[i] - w[i] * k for i in range(n)]
        for zi, _, _ in self.inflows:  # mientras dura una oleada hacia una zona, de ahí no se va nadie por gusto
            if not L.is_gate[zi] and p[zi] > 0 and zi not in self.stopped_stages:
                p[zi] = 0.0
        hard_d, state_fac, bfac = P["hard_density"], P["state_inflow"], P["broadcast_factor"]
        hardfac, infac = [0.0] * n, [0.0] * n  # entrada forzada (llegan igual) y voluntaria (se frena si está lleno)
        for i in range(n):
            d = occ[i] / area[i]
            if i in evac or d >= hard_d:
                continue
            h = state_fac[self.state[i]]
            if d > hard_d - 1.0:  # ya casi no cabe nadie
                h *= hard_d - d
            if i in self.broadcasts:
                h *= bfac
            hardfac[i] = h
            cd = L.comfort[i]
            infac[i] = h if d <= cd else h * max(0.0, 1.0 - (d - cd) / 1.5)

        flows: list[tuple[int, int, float]] = []

        def push(s: int, d: int, f0: float) -> None:
            rr = reroutes.get(d)
            if rr is not None and rr[0] != s:  # REROUTE: parte de lo que iba a `d` acaba en rr[0]
                mv = f0 * rr[1]
                f0 -= mv
                if mv * hardfac[rr[0]] > 0:
                    flows.append((s, rr[0], mv * hardfac[rr[0]]))
            if f0 * infac[d] > 0:
                flows.append((s, d, f0 * infac[d]))

        boost = P["evac_boost"]
        rush = P["egress_rush"] if leaving else 1.0
        for a, b, cap, c, leafs in L.edges:
            if leafs == 0:
                diff = (p[a] - p[b]) * rush
            elif leafs == 3:
                diff = min(p[a], -p[b]) if p[a] > 0 else -min(p[b], -p[a])
            else:
                diff = p[a] if leafs == 1 else -p[b]
            if diff < 0:
                a, b, diff = b, a, -diff
            if diff < 1:
                continue
            f = c * diff
            if a in evac:
                f *= boost
            elif leaving and f < 5:
                f = min(diff * 0.5, 5.0)
            push(a, b, cap if f > cap else f)

        busy_sec = {r.zone for r in self.resources.values()
                    if r.status is ResourceStatus.BUSY and r.kind is ResourceKind.SECURITY}
        gate_fac = {}
        for g in L.gates:
            gf = float(self.flags[g].get("flow_factor", 1.0))
            gate_fac[g] = gf * P["security_gate_bonus"] if L.ids[g] in busy_sec else gf
            if p[g] > 0:  # la puerta es una cola: descarga hacia dentro lo que dan los tornos
                inner = [i for i in L.gate_inner[g] if infac[i] > 0] or L.gate_inner[g]
                out = min(L.entry[g] * gate_fac[g], p[g]) / len(inner)
                for i in inner:
                    push(g, i, out)
            rr = reroutes.get(g)
            if rr is not None and L.is_gate[rr[0]] and occ[g] > 0.5 * L.capacity[g]:
                flows.append((g, rr[0], occ[g] * rr[1] * P["reroute_queue_frac"] * hardfac[rr[0]]))
        if leaving or evac:
            for inner, g, cap, c in L.gate_edges:
                diff = max(p[inner], -p[g]) if inner in evac else -p[g]
                if diff >= 1 and (leaving or inner in evac):
                    f = c * diff * (boost if inner in evac else 1.0)
                    push(inner, g, min(cap, max(f, min(diff * 0.5, 5.0))))

        for zi, rate, _ in self.inflows:  # oleada hacia una zona interior: sale de sus vecinas
            if not L.is_gate[zi]:
                nb = L.crowd_nb[zi]
                tot = sum(occ[j] for j in nb)
                if zi in self.stopped_stages:  # sin música nadie empuja hacia ese escenario
                    rate *= P["stop_show_factor"]
                if tot > 0:
                    for j in nb:
                        flows.append((j, zi, rate * hardfac[zi] * occ[j] / tot))

        carry = self.carry
        moved: dict[int, int] = {}
        for s, d, f in flows:
            key = s * 64 + d
            f += carry.get(key, 0.0)
            m = int(f)
            carry[key] = f - m
            if m > occ[s]:
                m = occ[s]
            if m:
                occ[s] -= m
                occ[d] += m
                moved[key] = moved.get(key, 0) + m
        self.flow_last = moved
        self.exits_last = gone = {}

        self._arrivals(hardfac)
        if leaving or evac:
            for i in L.exits:
                if leaving or i in evac:
                    rate = L.exit_rate[i] * (self.transport_factor * self.transport_boost if i == L.transport
                                             else gate_fac.get(i, 1.0))
                    f = rate + carry.get(-i - 1, 0.0)
                    m = min(int(f), occ[i])
                    carry[-i - 1] = f - int(f)
                    occ[i] -= m
                    self.exited += m
                    if m:
                        gone[i] = m

    def _arrivals(self, hardfac: list[float]) -> None:
        """Llegadas de fuera a las puertas: programa + rezagados + `zone_inflow`, con desvíos y estados."""
        L, ph, carry = self.L, self._phase, self.carry
        want = ph.arrive + carry.get(-100, 0.0)
        base = int(want)
        carry[-100] = want - base
        release = 0
        if self.backlog > 0:
            release = min(self.backlog, 20 + int(self.backlog * self.P["backlog_release"]))
            self.backlog -= release
        total = min(base + release, self.outside)
        attempt = {g: int(total * L.gate_share[g]) for g in L.gates}
        attempt[L.main_gate] += total - sum(attempt.values())
        extra = 0
        for zi, rate, _ in self.inflows:
            if L.is_gate[zi]:
                f = rate + carry.get(-200 - zi, 0.0)
                carry[-200 - zi] = f - int(f)
                attempt[zi] += int(f)
                extra += int(f)
        if total + extra > self.outside:  # la oleada inyectada no cabe en «los de fuera»: crece la población
            grow = total + extra - self.outside
            self.population += grow
            self.injected_people += grow
            self.outside += grow
        self.arrivals_last = came = {}
        if not total and not extra:
            return
        for g in list(attempt):
            rr = self.reroutes.get(g)
            if rr is not None and attempt[g]:
                mv = int(attempt[g] * rr[1])
                attempt[g] -= mv
                attempt[rr[0]] = attempt.get(rr[0], 0) + mv
        for z, a in attempt.items():
            adm = int(a * hardfac[z])
            if adm:
                came[z] = adm
            self.occ[z] += adm
            self.outside -= adm
            self.backlog += a - adm

    # ------------------------------------------------------------------ efectos en cadena y sensores

    _WIND_TEXT = ("", "preaviso: bajar lonas y pantallas y revisar anclajes",
                  "riesgo en estructuras: despejar el entorno de torres, carpas y pantallas",
                  "riesgo grave: fuera de certificado, parar el espectáculo es decisión del Director del Plan")

    def _wind(self) -> None:
        """Estación meteorológica: avisa al subir de escalón y repite mientras haya riesgo."""
        wind, t = self.weather.get("wind_kmh", 0), self.t
        level = sum(1 for s in self.P["wind_steps_kmh"] if wind >= s)
        if level > self.wind_level or (level >= 2 and t - self.wind_last >= self.P["wind_repeat_min"]):
            self.wind_last = t
            self._add_report({"channel": "sensor", "source": "estación meteorológica",
                              "text": f"Viento de {wind:.0f} km/h, escalón {level} de 3. {self._WIND_TEXT[level].capitalize()}."},
                             None)
        self.wind_level = level

    def _step_chains(self) -> None:
        L, P, t, fl = self.L, self.P, self.t, self.flags
        if self.weather.get("wind_kmh", 0) >= P["wind_steps_kmh"][0] or self.wind_level:
            self._wind()
        inside = sum(self.occ)
        temp = self.weather.get("temp_c", 25)
        if L.water and inside:
            use = inside * P["water_l_per_person_min"] * (1 + max(0, temp - P["water_heat_from_c"]) * P["water_heat_slope"])
            for i in L.water:
                left = fl[i].get("water_l", 0)
                if left > 0:
                    left = fl[i]["water_l"] = max(0.0, round(left - use / len(L.water), 1))
                if left <= 0:
                    self.dry_minutes[i] = self.dry_minutes.get(i, 0) + 1
                if left > 0:
                    self.dry_since.pop(i, None)
                elif i not in self.dry_since:
                    self.dry_since[i] = t
                    self.stockouts.append({"t": t, "zone": L.ids[i]})
                    rep = {"channel": "sensor", "source": f"depósito {L.ids[i]}", "zone_hint": L.ids[i],
                           "text": f"Depósito de {L.names[i]} agotado: 0 litros."}
                    if self.spontaneous:
                        self._open_incident({"family": "supply", "type": "water_out", "zone": L.ids[i],
                                             "severity": P["water_incident"]["severity"],
                                             "deadline": t + P["water_incident"]["deadline_min"],
                                             "needs": P["water_incident"]["needs"]}, [rep], "auto")
                    else:
                        self._add_report(rep, None)
        if not self.spontaneous or not inside:
            return
        dry = any(t - since >= P["dry_delay_min"] for since in self.dry_since.values())
        over = temp - P["heat_threshold_c"] + (P["dry_extra_c"] if dry else 0)
        if over > 0:
            rate = P["heat_rate"] * over ** 1.5 * inside / 10000 * (P["dry_multiplier"] if dry else 1.0)
            if self.rng.random() < rate:
                self._heat_incident("fainting" if dry else "heat_exhaustion")
        steps = P["wind_steps_kmh"]
        wind = self.weather.get("wind_kmh", 0)
        if wind >= steps[1]:  # escalón 2: riesgo en estructuras; escalón 3: riesgo grave
            prob = P["wind_rate"] * (wind - steps[1] + 1) * (1.5 if self.weather.get("rain") else 1.0)
            if wind >= steps[2]:
                prob *= P["wind_severe_factor"]
            for i in L.struct:
                if fl[i].get("structure_ok") and self.rng.random() < prob:
                    fl[i]["structure_ok"] = False
                    spec = P["structure_incident"]
                    self._open_incident(
                        {"family": "infra", "type": "structure_risk", "zone": L.ids[i], "severity": spec["severity"],
                         "deadline": t + spec["deadline_min"], "needs": spec["needs"]},
                        [{"channel": "radio", "source": "jefe de escenario", "zone_hint": L.ids[i],
                          "text": f"El viento está moviendo la estructura en {L.names[i]}, hay que revisarla ya."}], "auto")

    def _heat_incident(self, kind: str) -> None:
        L, occ = self.L, self.occ
        wts = [0.0 if i in L.no_spont else occ[i] * (1.0 if self.flags[i].get("shade") else 1.5) for i in range(L.n)]
        x, zi = self.rng.random() * sum(wts), 0
        for zi, wt in enumerate(wts):
            x -= wt
            if x < 0:
                break
        spec = self.P["heat_incident"]
        texts = ["Hay una persona mareada y muy roja por el calor, casi no responde",
                 "Una chica se ha desmayado aquí, necesitamos ayuda",
                 "Un chico se ha caído redondo, creo que es un golpe de calor"]
        self._open_incident(
            {"family": "medical", "type": kind, "zone": L.ids[zi], "severity": spec["severity"],
             "deadline": self.t + spec["deadline_min"], "needs": spec["needs"]},
            [{"channel": "whatsapp", "source": "asistente", "zone_hint": L.ids[zi],
              "text": f"{self.rng.choice(texts)} ({L.names[zi]})"}], "auto")

    def _sensors(self) -> None:
        """Contadores de aforo: aviso por umbral (o capacidad), aviso por tendencia y alerta crítica."""
        L, P, occ, t = self.L, self.P, self.occ, self.t
        crush_d, repeat, win = P["crush_density"], P["sensor_repeat_min"], P["sensor_trend_window_min"]
        hist = self.dhist
        old = hist[win - 1] if len(hist) >= win else None
        cur = [occ[i] / L.area[i] for i in range(L.n)]
        for i, d in enumerate(cur):
            if d > self.peak[i]:
                self.peak[i], self.peak_t[i], self.peak_occ[i] = d, t, occ[i]
            slope = (d - old[i]) / win if old is not None else 0.0
            over = d > L.sensor_d[i] or occ[i] > L.capacity[i]
            if not over:
                # tendencia: aún por debajo del umbral, pero a este ritmo llega a densidad crítica dentro del horizonte
                if slope >= P["sensor_trend_per_min"] and d >= P["sensor_trend_min_density"] \
                        and d + slope * P["sensor_trend_horizon_min"] >= crush_d \
                        and t - self.trend_last.get(i, -10 ** 6) >= repeat:
                    self.trend_last[i] = t
                    crowd = self._match(i, None)
                    self._add_report(
                        {"channel": "sensor", "source": f"contador {L.ids[i]}", "zone_hint": L.ids[i],
                         "text": f"Tendencia en {L.names[i]}: {d:.1f}/m² y subiendo {slope:.2f}/m² por minuto; "
                                 f"a este ritmo, {crush_d}/m² en {math.ceil((crush_d - d) / slope)} min."},
                        crowd.id if crowd is not None and crowd.family is Family.CROWD else None)
                continue
            if d > 5.0:
                self.over5[i] += 1
            if occ[i] > L.capacity[i]:
                self.over_cap[i] += 1
            truth = self.crush_open.get(i)
            if truth is not None and self.incidents[truth].status not in _ACTIVE:
                failed = self.records[truth]["t_failed"]
                if failed is None or t - failed >= P["crush_reopen_min"]:
                    del self.crush_open[i]
                    truth = None
            if d > crush_d and i in L.crush and i not in self.crush_open:
                spec = P["crush_incident"]
                truth = self.crush_open[i] = self._open_incident(
                    {"family": "crowd", "type": "crush_risk", "zone": L.ids[i], "severity": spec["severity"],
                     "deadline": t + spec["deadline_min"], "needs": spec["needs"]},
                    [{"channel": "sensor", "source": f"contador {L.ids[i]}", "zone_hint": L.ids[i],
                      "text": f"ALERTA densidad crítica en {L.names[i]}: {occ[i]} personas, {d:.1f}/m²."}], "auto").id
                self.sensor_last[i] = t
            elif t - self.sensor_last.get(i, -10 ** 6) >= repeat:
                self.sensor_last[i] = t
                if truth is None:
                    crowd = self._match(i, None)
                    truth = crowd.id if crowd is not None and crowd.family is Family.CROWD else None
                trend = ""
                if slope >= 0.05 and d < crush_d:
                    trend = f" Subiendo {slope:.2f}/m² por minuto: {crush_d}/m² en {math.ceil((crush_d - d) / slope)} min."
                self._add_report({"channel": "sensor", "source": f"contador {L.ids[i]}", "zone_hint": L.ids[i],
                                  "text": f"Contador de aforo {L.names[i]}: {occ[i]} personas ({d:.1f}/m²), "
                                          f"capacidad {L.capacity[i]}.{trend}"}, truth)
        self.dhist = ([cur] + hist)[:win]

    # ------------------------------------------------------------------ tick

    def step(self) -> None:
        self._step_crowd()
        self.t += 1
        L = self.L
        ph = self._phase
        while self.abs0 + self.t >= ph.end:
            self._ph_i += 1
            ph = self._phase = L.timeline[self._ph_i]
            if ph.new_day:  # a las 06:00 los que salieron anoche vuelven a ser «los de fuera» y se rellena el agua
                self.outside += self.exited
                self.exited = 0
                self.backlog = 0
                for i in L.water:
                    self.flags[i]["water_l"] = self.flags[i].get("water_capacity_l", 8000)
        self._step_resources()
        self._step_chains()
        self._step_incidents()
        self._sensors()
        if self.evac or self.evac_all:
            self._check_evac()
        self._fire_events()
        if self.held:
            ready = [r for r in self.held if not self.channel_down(r.channel)]
            if ready:
                self.held = [r for r in self.held if r not in ready]
                self._rep_cur.extend(ready)
        self._rep_obs, self._rep_cur = self._rep_cur, []
        self._res_obs, self._res_cur = self._res_cur, []

    def _check_evac(self) -> None:
        for zi, aid in list(self.evac.items()):
            a = self.live.get(aid or "")
            if a is not None and self.occ[zi] <= 0.02 * self.L.capacity[zi]:
                self._finish(a, ActionStatus.DONE)
        if self.evac_all and self.evac_all in self.live and sum(self.occ) <= 0.01 * self.population:
            self._finish(self.live[self.evac_all], ActionStatus.DONE)
