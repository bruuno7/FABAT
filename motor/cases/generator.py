"""Generador combinatorio de casos, con semilla.

Dimensiones: día y fase × meteorología × 1–4 incidentes verdaderos (con solapes que fuerzan a
priorizar) × calidad de la información × estado de los recursos × perturbaciones `world` a mitad de
caso × encadenamientos de la taxonomía.

Cobertura sistemática, no aleatoria: el tipo principal recorre en rueda todos los tipos de la
partición y su perturbación recorre en rueda las que esa partición le permite; el resto de
dimensiones se sortea con la semilla del caso. La dificultad (1–5) se calcula a partir del caso.

Partición estricta: cada combinación (familia × tipo × perturbación) pertenece a train o a heldout,
nunca a ambas; hay tipos, encadenamientos y parejas de familias que solo existen en heldout.
"""
from __future__ import annotations

import functools
import random
import zlib
from collections.abc import Iterator
from itertools import combinations
from typing import Any

from motor.contracts import Family

from . import phrasing
from .taxonomy import (
    FESTIVAL, GLOBAL_MUST_NOT, INFO_QUALITIES, INFO_QUALITY_TYPE, NEIGHBORS, PERTURBATIONS, PHASES,
    RESOURCE_STATE_TYPE, RESOURCE_STATES, SHOW_PHASES, TAXONOMY, TRAIN_EXCLUDED_FAMILY_PAIRS, WEATHERS, ZONES,
    allowed_perturbations, fill_rule, hhmm_to_min, is_heldout_chain, min_to_hhmm, phase_at, program_windows,
    split_types, units_of,
)

SPLITS = ("train", "heldout", "demo")
FAMILY_ORDER = [f.value for f in Family]

FLAGGABLE = {"food": ("power", False), "backstage": ("power", False), "toilets": ("power", False),
             "corridor_n": ("power", False), "corridor_s": ("power", False), "exit_transport": ("power", False),
             "water_n": ("water_l", 0), "water_s": ("water_l", 0),
             "front_pit": ("structure_ok", False), "vip": ("structure_ok", False)}
OFFLINE_REASONS = {"ambulance": ["bloqueada por la multitud", "avería del vehículo"],
                   "_": ["lesionado", "radio sin batería", "retenido en otra intervención", "indisposición"]}
REJECT_REASONS = ["ya estamos con otra intervención", "no podemos abandonar el puesto", "no tenemos material", "el acceso está cortado"]
CLOSE_REASONS = ["vallado caído", "balsa de agua", "vehículo averiado cruzado", "cableado en el suelo"]
# Incidentes menores que tienen ocupado un tipo de recurso cuando entra algo más grave (`all_busy`).
FILLERS = {"medical": ("minor_injury", "trauma_fall", "intoxication_overdose"),
           "tech": ("toilets_blocked", "turnstile_failure", "cashless_down"),
           "logistics": ("food_shortage", "radio_batteries_low", "wristbands_out"),
           "security": ("theft_gang", "harassment_group", "fight"),
           "ambulance": ("medical_post_saturated",)}

INFO_POINTS = {"clean": 0.0, "duplicated": 0.5, "buried": 0.7, "false_alarms": 0.8, "ambiguous": 1.0, "contradictory": 1.3}
STATE_POINTS = {"full": 0.0, "one_offline": 0.5, "shift_end": 0.7, "no_answer": 1.0, "rejects": 1.0, "all_busy": 1.5}
DIFFICULTY_CUTS = (2.8, 4.4, 6.2, 8.2)  # puntos → niveles 1..5


# ------------------------------------------------------------------ utilidades


def _case_seed(seed: int, split: str, index: int) -> int:
    return zlib.crc32(f"{seed}/{split}/{index}".encode())


def _ordered(perts) -> list[str]:
    """Los conjuntos no tienen orden estable entre ejecuciones: siempre se ordenan así."""
    return [p for p in PERTURBATIONS if p in perts]


def _families_clash(families: set[str]) -> bool:
    return any(pair <= families for pair in TRAIN_EXCLUDED_FAMILY_PAIRS)


class _State:
    """Lo ya decidido del caso, contra lo que se comprueba cada tipo que se quiera añadir."""

    def __init__(self, split: str, weather: str, phase: str, perts: list[str]):
        self.split, self.weather, self.phase, self.perts = split, weather, phase, perts
        self.families: set[str] = set()

    def accepts(self, type_id: str, *, check_phase: bool = True) -> bool:
        t = TAXONOMY[type_id]
        if t.mode != "incident":
            return False
        if not set(self.perts) <= allowed_perturbations(type_id, self.split):
            return False
        if t.weather and self.weather not in t.weather:
            return False
        if check_phase and t.phases and self.phase not in t.phases:
            return False
        if self.split == "train" and _families_clash(self.families | {t.family.value}):
            return False
        return True


def _make_incident(rng: random.Random, type_id: str, t: int, zone: str | None = None) -> dict[str, Any]:
    ty = TAXONOMY[type_id]
    return {"type": type_id, "family": ty.family.value, "zone": zone or rng.choice(ty.zones),
            "severity": rng.randint(*ty.severity), "t": t, "rel_deadline": rng.randint(*ty.deadline),
            "needs": dict(ty.needs), "role": "secondary", "cond": None, "via_world": False}


@functools.lru_cache(maxsize=None)
def estimate_occupancy(day: int, phase: str, zone: str) -> int:
    """Gente en la zona según el programa (llegados hasta esa fase × reparto de la fase). Solo sirve para
    dar cifras verosímiles a los textos de sensor: la ocupación real la calcula el simulador."""
    prog = next(d for d in FESTIVAL["program"]["days"] if d["day"] == day)
    arrived, profile = 0.0, phase
    for ph in prog["phases"]:
        arrived += ph.get("arrive_share", 0.0)
        if ph["name"] == phase:
            profile = ph["profile"]
            break
    share = 0.6 if phase == "egress" else min(1.0, arrived)
    return int(prog["attendance"] * share * FESTIVAL["profiles"].get(profile, {}).get(zone, 0.0))


def pick_start(rng: random.Random, day: int, phase: str, duration: int) -> str:
    """Hora de inicio dentro de la ventana de esa fase en el programa, de 5 en 5 min; si cabe, el caso entero."""
    start, end = next((a, b) for name, a, b in program_windows(day) if name == phase)
    last = max(start, end - duration)
    return min_to_hhmm(rng.randrange(start, last + 1, 5))


def _ctx(zone: str, occupancy: dict[str, int], weather: dict[str, Any]) -> dict[str, Any]:
    z = ZONES[zone]
    occ = occupancy.get(zone, 0)
    return {"zone": zone, "occupancy": occ, "capacity": z["capacity"], "density": round(occ / z["area_m2"], 1), **weather}


def _initial_weather(rng: random.Random, weather: str, phase: str) -> dict[str, Any]:
    night = phase in ("headliner", "egress")
    if weather == "heat":
        return {"temp_c": rng.randint(36, 38 if night else 41), "wind_kmh": rng.randint(5, 15), "rain": False, "alert": "naranja"}
    if weather == "wind":
        return {"temp_c": rng.randint(20, 30), "wind_kmh": rng.randint(45, 70), "rain": False, "alert": "amarilla"}
    if weather == "storm":
        return {"temp_c": rng.randint(18, 27), "wind_kmh": rng.randint(50, 85), "rain": True, "alert": "naranja"}
    return {"temp_c": rng.randint(22, 31), "wind_kmh": rng.randint(5, 20), "rain": False, "alert": None}


def _weather_shift(rng: random.Random, weather: str, now: dict[str, Any]) -> dict[str, Any]:
    if weather == "normal":
        target = rng.choice(["heat", "wind", "storm"])
        if target == "heat":
            return {"kind": "weather", "temp_c": rng.randint(37, 41), "alert": "naranja"}
        if target == "wind":
            return {"kind": "weather", "wind_kmh": rng.randint(55, 75), "alert": "amarilla"}
        return {"kind": "weather", "wind_kmh": rng.randint(55, 85), "rain": True, "alert": "naranja"}
    if weather == "heat":
        return {"kind": "weather", "temp_c": min(44, now["temp_c"] + rng.randint(2, 4)), "alert": "roja"}
    if weather == "wind":
        return {"kind": "weather", "wind_kmh": now["wind_kmh"] + rng.randint(10, 20), "rain": True, "alert": "naranja"}
    return {"kind": "weather", "wind_kmh": now["wind_kmh"] + rng.randint(10, 25), "rain": True, "alert": "roja"}


def _pick_resource(rng: random.Random, kinds: list[str], taken: set[str], *, prefer_multi: bool = False) -> str:
    """Un recurso de alguno de los tipos que el incidente principal necesita, que no esté ya tocado."""
    pools = [[r for r in units_of(k) if r not in taken] for k in kinds]
    if prefer_multi:
        pools = [p for p, k in zip(pools, kinds) if len(units_of(k)) > 1] or pools
    pools = [p for p in pools if p] or [[r for r in units_of("security") if r not in taken]]
    return rng.choice(pools[0] if rng.random() < 0.7 else rng.choice(pools))


# ------------------------------------------------------------------ construcción de un caso


def build_case(index: int, seed: int = 1, split: str = "train") -> dict[str, Any]:
    if split not in ("train", "heldout"):
        raise ValueError("build_case solo genera train y heldout; demo está escrito a mano")
    case_seed = _case_seed(seed, split, index)
    rng = random.Random(case_seed)

    # 1. Tipo principal y perturbación: en rueda, para cubrir todas las combinaciones de la partición.
    order = split_types(split)
    random.Random(f"{seed}/{split}/order").shuffle(order)
    primary_type = order[index % len(order)]
    own = _ordered(allowed_perturbations(primary_type, split))
    perts = [own[(index // len(order)) % len(own)]]
    if perts[0] != "none" and rng.random() < 0.3:
        rest = [p for p in own if p not in ("none", perts[0])]
        if rest:
            perts.append(rng.choice(rest))
    ptype = TAXONOMY[primary_type]

    # 2. Día, fase y meteorología (condicionadas por el tipo principal).
    phase = rng.choice(ptype.phases or PHASES)
    day = rng.choices([1, 2, 3], weights=[3, 4, 3])[0] if phase != "egress" else rng.choices([1, 2, 3], weights=[2, 3, 5])[0]
    weather = rng.choice(ptype.weather) if ptype.weather else rng.choices(WEATHERS, weights=[40, 25, 15, 20])[0]
    st = _State(split, weather, phase, perts)
    st.families.add(ptype.family.value)

    info_quality = rng.choices(INFO_QUALITIES, weights=[30, 14, 14, 14, 14, 14])[0]
    resource_state = rng.choices(RESOURCE_STATES, weights=[30, 14, 14, 14, 14, 14])[0]
    n_incidents = rng.choices([1, 2, 3, 4], weights=[30, 35, 23, 12])[0]
    if "second_wave" in perts:  # la segunda oleada cuenta como uno de los 1–4 incidentes verdaderos
        n_incidents = min(n_incidents, 3)

    # 3. Incidentes verdaderos. El principal no siempre es el primero en llegar.
    t_primary = rng.randint(2, 8)
    primary = _make_incident(rng, primary_type, t_primary)
    primary["role"] = "primary"
    incidents = [primary]
    main_kinds = sorted(ptype.needs, key=lambda k: -ptype.needs[k])

    if resource_state == "all_busy":
        busy_kind = next((k for k in main_kinds if k in FILLERS), None)
        fillers = [f for f in FILLERS.get(busy_kind or "", ()) if f != primary_type and st.accepts(f)]
        if busy_kind and fillers and primary["severity"] >= 7:
            primary["t"] = t_primary = rng.randint(7, 11)
            room = 3 - ("second_wave" in perts)  # nunca más de 4 incidentes verdaderos seguros
            for k in range(min(room, len(units_of(busy_kind)))):
                f = _make_incident(rng, rng.choice(fillers), rng.randint(0, 3))
                f["role"] = "filler"
                if busy_kind != "ambulance":  # entre todos ocupan todas las unidades de ese tipo
                    f["needs"] = {busy_kind: 2 if busy_kind == "security" and k < 2 else 1}
                f["severity"] = min(f["severity"], 6, primary["severity"] - 1)
                f["rel_deadline"] = max(f["rel_deadline"], 30)
                incidents.append(f)
                st.families.add(f["family"])
        else:
            resource_state = "one_offline"  # no hay forma coherente de saturar: se degrada, sin azar
    if resource_state != "all_busy":
        t_prev = t_primary
        for _ in range(n_incidents - 1):
            pool = [t for t in split_types(split) if t != primary_type and t not in {i["type"] for i in incidents} and st.accepts(t)]
            if not pool:
                break
            overlap = rng.random() < 0.65
            t_new = max(0, t_prev + (rng.randint(-2, 5) if overlap else rng.randint(8, 20)))
            inc = _make_incident(rng, rng.choice(pool), t_new)
            incidents.append(inc)
            st.families.add(inc["family"])
            t_prev = t_new

    # 4. Segunda oleada: un incidente completo que entra como efecto `world`.
    if "second_wave" in perts:
        pool = [t for t in split_types(split) if t not in {i["type"] for i in incidents} and st.accepts(t)
                and TAXONOMY[t].severity[1] >= 7]
        if pool:
            inc = _make_incident(rng, rng.choice(pool), t_primary + rng.randint(4, 9))
            inc.update(role="second_wave", via_world=True)
            incidents.append(inc)
            st.families.add(inc["family"])
        else:  # no cabe ninguno compatible: repite el tipo principal en otra zona
            zones = [z for z in ptype.zones if z != primary["zone"]] or list(ptype.zones)
            inc = _make_incident(rng, primary_type, t_primary + rng.randint(4, 9), rng.choice(zones))
            inc.update(role="second_wave", via_world=True)
            incidents.append(inc)

    # 5. Encadenamientos: si el origen no se resuelve a tiempo, degenera en otro incidente.
    chain: list[tuple[str, str]] = []
    if rng.random() < (0.45 if split == "train" else 0.65):
        origin = None
        for depth in range(2):
            sources = [origin] if origin else [i for i in incidents if i["role"] != "filler"]
            edges = []
            for src in sources:
                for b in TAXONOMY[src["type"]].escalates_to:
                    if split == "train" and is_heldout_chain(src["type"], b):
                        continue
                    if st.accepts(b, check_phase=False) and b not in {i["type"] for i in incidents}:
                        edges.append((src, b))
            if split == "heldout":  # primero los encadenamientos que train no ve nunca
                edges = [e for e in edges if is_heldout_chain(e[0]["type"], e[1])] or edges
            if not edges or (depth == 1 and rng.random() > 0.4):
                break
            src, b = rng.choice(edges)
            zone = src["zone"] if src["zone"] in TAXONOMY[b].zones else None
            if zone is None:
                near = [z for z in NEIGHBORS[src["zone"]] if z in TAXONOMY[b].zones]
                zone = rng.choice(near) if near else rng.choice(TAXONOMY[b].zones)
            inc = _make_incident(rng, b, src["t"] + src["rel_deadline"] + rng.randint(1, 4), zone)
            inc.update(role="chain", cond=src)
            incidents.append(inc)
            st.families.add(inc["family"])
            chain.append((src["type"], b))
            origin = inc

    return _assemble(rng, {
        "id": f"c-{split[0]}{index:06d}", "seed": case_seed, "split": split, "day": day, "phase": phase, "weather": weather,
        "perts": perts, "incidents": incidents, "primary": primary, "chain": chain,
        "info_quality": info_quality, "resource_state": resource_state})


def _assemble(rng: random.Random, sel: dict[str, Any]) -> dict[str, Any]:
    """De la selección (qué incidentes, cuándo, con qué dimensiones) al caso completo en el formato acordado."""
    split, day, phase, weather, perts = sel["split"], sel["day"], sel["phase"], sel["weather"], sel["perts"]
    incidents, primary, chain = sel["incidents"], sel["primary"], sel["chain"]
    info_quality, resource_state = sel["info_quality"], sel["resource_state"]
    primary_type = primary["type"]
    ptype = TAXONOMY[primary_type]
    main_kinds = sorted(ptype.needs, key=lambda k: -ptype.needs[k])

    # 6. Identificadores en orden de llegada, duración y hora de inicio dentro de la fase del programa.
    incidents.sort(key=lambda i: (i["t"], i["role"] != "filler"))
    for k, inc in enumerate(incidents, 1):
        inc["id"] = f"i{k}"
    duration = max(60, -(-(max(i["t"] + i["rel_deadline"] for i in incidents) + 15) // 5) * 5)
    start_hhmm = pick_start(rng, day, phase, duration)

    # 7. Estado inicial. La ocupación la pone el simulador desde el programa; el caso solo pisa las zonas
    #    cuyo incidente exige una densidad concreta. `estimate` es solo para las cifras de los textos.
    overrides: dict[str, int] = {}
    for inc in incidents:
        dens = TAXONOMY[inc["type"]].density
        if dens and inc["role"] in ("primary", "secondary", "load"):
            overrides[inc["zone"]] = int(ZONES[inc["zone"]]["area_m2"] * rng.uniform(*dens))
    occupancy = {z: overrides.get(z, estimate_occupancy(day, phase, z)) for z in ZONES}
    weather_now = _initial_weather(rng, weather, phase)
    initial: dict[str, Any] = {"occupancy": overrides, "weather": weather_now, "resources_offline": []}

    events: list[dict[str, Any]] = []
    must: list[str] = []
    must_not: list[str] = list(GLOBAL_MUST_NOT)
    types_present: list[str] = [i["type"] for i in incidents]
    touched: set[str] = set()

    # 8. Avisos de cada incidente, según la calidad de la información (afecta al principal).
    for inc in incidents:
        ctx = _ctx(inc["zone"], occupancy, weather_now)
        quality = info_quality if inc["role"] == "primary" else "clean"
        if quality == "ambiguous":
            reports = [phrasing.ambiguous_report(rng, inc["type"], inc["zone"])]
            clear = phrasing.primary_reports(rng, inc["type"], inc["zone"], ctx)[:1]
            events.append({"t": inc["t"] + rng.randint(2, 4), "kind": "report_only", "tag": "clarification", "ref": inc["id"],
                           "reports": [dict(r, truth_incident=inc["id"]) for r in clear]})
        elif quality == "buried":
            reports = [phrasing.buried_report(rng, inc["type"], inc["zone"], ctx)]
        else:
            reports = phrasing.primary_reports(rng, inc["type"], inc["zone"], ctx)
        body = {"id": inc["id"], "family": inc["family"], "type": inc["type"], "zone": inc["zone"],
                "severity": inc["severity"], "deadline": inc["t"] + inc["rel_deadline"], "needs": inc["needs"]}
        if inc["via_world"]:
            events.append({"t": inc["t"], "kind": "world", "effect": {"kind": "incident", "incident": body, "reports": reports}})
        else:
            ev = {"t": inc["t"], "kind": "incident", "incident": body, "reports": reports}
            if inc["cond"]:
                ev["cond"] = {"unless_resolved": inc["cond"]["id"]}
            events.append(ev)
        for eff in TAXONOMY[inc["type"]].effects:  # efectos que nacen con el incidente
            eff = {k: (v.format(z=inc["zone"], sec=f"sec_{rng.randint(1, 5)}") if isinstance(v, str) else v) for k, v in eff.items()}
            ev = {"t": inc["t"], "kind": "world", "effect": eff}
            if inc["cond"]:
                ev["cond"] = {"unless_resolved": inc["cond"]["id"]}
            if "resource" in eff:
                touched.add(eff["resource"])
            events.append(ev)
        suffix = " if spawned" if inc["cond"] else ""
        ty = TAXONOMY[inc["type"]]
        rules_not = [r for r in ty.must_not if not (quality == "ambiguous" and r.startswith("ask before"))]
        show_on = phase_at(day, start_hhmm, inc["t"]) in SHOW_PHASES  # fuera de concierto no hay nada que parar
        must += [fill_rule(r, i=inc["id"], z=inc["zone"]) + suffix for r in ty.must if show_on or not r.startswith("stop_show")]
        must_not += [fill_rule(r, i=inc["id"], z=inc["zone"]) for r in rules_not]

    # 9. Ruido informativo alrededor del principal.
    pid, pzone, pctx = primary["id"], primary["zone"], _ctx(primary["zone"], occupancy, weather_now)
    if info_quality == "duplicated":
        for r in phrasing.duplicate_reports(rng, primary_type, pzone, pctx, k=rng.randint(2, 3)):
            events.append({"t": primary["t"] + rng.randint(1, 5), "kind": "report_only", "tag": "duplicate", "ref": pid,
                           "reports": [dict(r, truth_incident=pid)]})
    elif info_quality == "contradictory":
        events.append({"t": primary["t"] + rng.randint(2, 6), "kind": "report_only", "tag": "contradictory", "ref": pid,
                       "reports": [dict(phrasing.contradictory_report(rng, primary_type, pzone, pctx), truth_incident=pid)]})
    elif info_quality == "false_alarms":
        kinds = ["joke", "mistake"] + (["sensor"] if split == "heldout" else [])
        for k in range(rng.randint(1, 3)):
            kind = rng.choice(kinds)
            fa = f"fa{k + 1}"
            events.append({"t": rng.randint(1, max(2, primary["t"] + 10)), "kind": "report_only", "tag": "false_alarm",
                           "subtag": kind, "ref": fa, "reports": [phrasing.false_alarm_report(rng, kind=kind)]})
            fa_type = "sensor_glitch" if kind == "sensor" else "false_alarm_prank"
            types_present.append(fa_type)
            must += [fill_rule(r, i=fa) for r in TAXONOMY[fa_type].must]
            must_not += [fill_rule(r, i=fa) for r in TAXONOMY[fa_type].must_not]
    if info_quality in INFO_QUALITY_TYPE and info_quality != "false_alarms":
        ty = TAXONOMY[INFO_QUALITY_TYPE[info_quality]]
        types_present.append(ty.id)
        must += [fill_rule(r, i=pid, z=pzone) for r in ty.must]
        must_not += [fill_rule(r, i=pid, z=pzone) for r in ty.must_not]

    # 10. Estado de los recursos propios.
    state_resource = None
    if resource_state in ("one_offline", "shift_end", "no_answer", "rejects"):
        state_resource = _pick_resource(rng, main_kinds, touched, prefer_multi=True)
        touched.add(state_resource)
        if resource_state == "one_offline":
            initial["resources_offline"].append(state_resource)
        elif resource_state == "shift_end":
            t_end = primary["t"] + rng.randint(2, 6)
            initial["shift_ends"] = {state_resource: t_end}
            events.append({"t": t_end, "kind": "world", "effect": {"kind": "resource_offline", "resource": state_resource,
                                                                   "reason": "fin de turno sin relevo"}})
        elif resource_state == "no_answer":
            events.append({"t": max(0, primary["t"] - 1), "kind": "world",
                           "effect": {"kind": "resource_no_answer", "resource": state_resource, "n": rng.randint(6, 12)}})
        else:
            events.append({"t": max(0, primary["t"] - 1), "kind": "world",
                           "effect": {"kind": "resource_rejects", "resource": state_resource, "reason": rng.choice(REJECT_REASONS)}})
    if resource_state != "full":
        ty = TAXONOMY[RESOURCE_STATE_TYPE[resource_state]]
        types_present.append(ty.id)
        must += [fill_rule(r, i=pid, z=pzone, r=state_resource or "") for r in ty.must]
        must_not += [fill_rule(r, i=pid, z=pzone, r=state_resource or "") for r in ty.must_not]

    # 11. Perturbaciones a mitad de la respuesta: rompen los supuestos del plan.
    t_pert = sel["pert_t"] if sel.get("pert_t") is not None else primary["t"] + rng.randint(3, 8)
    for pert in perts:
        effect: dict[str, Any] | None = None
        if pert == "resource_offline":
            r = _pick_resource(rng, main_kinds, touched)
            kind = "ambulance" if r == "amb_1" else "_"
            effect = {"kind": "resource_offline", "resource": r, "reason": rng.choice(OFFLINE_REASONS[kind])}
            touched.add(r)
        elif pert == "resource_online":
            r = _pick_resource(rng, main_kinds, touched)
            initial["resources_offline"].append(r)
            effect = {"kind": "resource_online", "resource": r}
            touched.add(r)
        elif pert == "resource_no_answer":
            r = _pick_resource(rng, main_kinds, touched)
            effect = {"kind": "resource_no_answer", "resource": r, "n": rng.randint(5, 12)}
            touched.add(r)
        elif pert == "resource_rejects":
            r = _pick_resource(rng, main_kinds, touched)
            effect = {"kind": "resource_rejects", "resource": r, "reason": rng.choice(REJECT_REASONS)}
            touched.add(r)
        elif pert == "zone_closed":
            near = [z for z in NEIGHBORS[pzone] if z.startswith("corridor")] or [z for z in NEIGHBORS[pzone] if not z.startswith("medical")]
            effect = {"kind": "zone_state", "zone": rng.choice(near), "state": "closed", "reason": rng.choice(CLOSE_REASONS)}
        elif pert == "zone_inflow":
            z = pzone if rng.random() < 0.6 else rng.choice(NEIGHBORS[pzone])
            effect = {"kind": "zone_inflow", "zone": z, "per_min": rng.randrange(40, 160, 10), "n": rng.randint(8, 20)}
        elif pert == "zone_flag":
            cands = [z for z in (pzone, *NEIGHBORS[pzone]) if z in FLAGGABLE] or ["food"]
            z = cands[0] if rng.random() < 0.6 else rng.choice(cands)
            flag, value = FLAGGABLE[z]
            effect = {"kind": "zone_flag", "zone": z, "flag": flag, "value": value}
        elif pert == "weather_shift":
            effect = _weather_shift(rng, weather, weather_now)
        elif pert == "comms_down":
            effect = {"kind": "comms_down", "channel": rng.choice(["whatsapp", "radio", "voice", "sms"]), "n": rng.randint(5, 15)}
        elif pert == "transport_cut":
            effect = {"kind": "transport_cut", "mode": rng.choice(["metro", "shuttle"]), "n": rng.randrange(20, 65, 5)}
        if effect:
            events.append({"t": min(t_pert, duration - 1), "kind": "world", "effect": effect,
                           "tag": "surprise" if sel.get("surprise") else "perturbation"})
        t_pert += rng.randint(3, 10)

    # 12. Cierre: orden, familias, combinaciones, dificultad.
    rank = {"world": 0, "incident": 1, "report_only": 2}
    for ev in events:
        ev["t"] = min(ev["t"], duration - 1)
    events.sort(key=lambda e: (e["t"], rank[e["kind"]]))
    families = {TAXONOMY[t].family.value for t in types_present}
    true_types = [i["type"] for i in incidents]
    case = {
        "id": sel["id"], "seed": sel["seed"], "split": split,
        "day": day, "start_hhmm": start_hhmm, "duration_min": duration,
        "families": [f for f in FAMILY_ORDER if f in families], "difficulty": 0,
        "initial": initial, "events": events,
        "expected": {"must": list(dict.fromkeys(must)), "must_not": list(dict.fromkeys(must_not))},
        "meta": {
            "phase": phase, "weather": weather, "info_quality": info_quality, "resource_state": resource_state,
            "perturbations": perts, "chain": [list(c) for c in chain], "primary": pid, "primary_type": primary_type,
            "types": list(dict.fromkeys(types_present)),
            "combos": [[TAXONOMY[t].family.value, t, p] for t in dict.fromkeys(true_types) for p in perts],
            **sel.get("meta", {}),
        },
    }
    return finish_case(case)


def finish_case(case: dict[str, Any]) -> dict[str, Any]:
    """Lo que se deriva del caso ya montado (también lo usan los casos demo): orden de prioridad esperado,
    máximo de incidentes activos a la vez y dificultad."""
    case["expected"].update(priority_order(case))
    case["meta"]["max_concurrent"] = max_concurrent(case)
    case["difficulty"], case["meta"]["difficulty_points"] = compute_difficulty(case)
    return case


# ------------------------------------------------------------------ carga simultánea (5–8 frentes a la vez)

LOAD_LEVELS = (5, 6, 7, 8)
WORLD_PERTS = tuple(p for p in PERTURBATIONS if p not in ("none", "second_wave"))


def _pick_load_types(rng: random.Random, st: _State, n: int) -> list[str] | None:
    """`n` tipos compatibles: uno menor (al que quitarle el equipo), uno grave, y el resto repartido entre
    familias distintas mientras queden familias sin usar."""
    pool = [t for t in split_types(st.split) if st.accepts(t)]
    rng.shuffle(pool)
    minor = sorted((t for t in pool if TAXONOMY[t].severity[0] <= 5), key=lambda t: TAXONOMY[t].severity[1] > 5)
    grave = [t for t in pool if TAXONOMY[t].severity[0] >= 8]
    if not minor or not grave:
        return None
    picked: list[str] = []
    for t in (minor[0], grave[0]):
        if st.accepts(t):
            picked.append(t)
            st.families.add(TAXONOMY[t].family.value)
    while len(picked) < n:
        rest = [t for t in pool if t not in picked and st.accepts(t)]
        if not rest:
            return None
        fresh = [t for t in rest if TAXONOMY[t].family.value not in st.families]
        t = (fresh or rest)[0]
        picked.append(t)
        st.families.add(TAXONOMY[t].family.value)
    return picked if len(picked) == n else None


def build_load_case(index: int, seed: int = 1, split: str = "train", load: int = 6, surprise: bool = False) -> dict[str, Any]:
    """Caso con `load` incidentes verdaderos activos a la vez (todos abiertos dentro de una ventana de 10–15 min),
    de familias distintas mientras las haya, con más demanda que recursos. Si `surprise`, a mitad del pico entra
    un imprevisto (incidente grave nuevo o golpe `world`) marcado en `meta.surprise_t`."""
    case_seed = zlib.crc32(f"{seed}/load/{split}/{load}/{int(surprise)}/{index}".encode())
    rng = random.Random(case_seed)
    # La perturbación va en rueda. Con sorpresa: alterna incidente nuevo y golpe world, en pleno pico.
    # Sin sorpresa: es una condición conocida desde el minuto 0–2 (o ninguna, que en heldout no existe).
    if surprise:
        pert = "second_wave" if index % 2 == 0 else WORLD_PERTS[(index // 2) % len(WORLD_PERTS)]
    else:
        options = (("none",) if split == "train" else ()) + WORLD_PERTS
        pert = options[index % len(options)]

    for attempt in range(60):
        phase = rng.choices(PHASES, weights=[15, 35, 35, 15])[0]
        weather = rng.choices(WEATHERS, weights=[40, 25, 15, 20])[0]
        st = _State(split, weather, phase, [pert])
        types = _pick_load_types(rng, st, load)
        if not types or (len(st.families) < 5 and attempt < 40):  # cinco familias distintas, salvo que no haya forma
            continue
        resource_state = rng.choices(RESOURCE_STATES[:5], weights=[50, 15, 10, 12, 13])[0]
        demand: dict[str, int] = {}
        for t in types:
            for k, v in TAXONOMY[t].needs.items():
                demand[k] = demand.get(k, 0) + v
        supply = {k: len(units_of(k)) for k in demand}
        scarce = sorted(k for k in demand if demand[k] > supply[k])
        if scarce:
            break
    else:
        raise RuntimeError(f"no hay forma de montar carga {load} en {split} con la perturbación {pert}")

    day = rng.choices([1, 2, 3], weights=[3, 4, 3])[0]
    w0, width = rng.randint(1, 3), rng.randint(10, 15)
    peak = w0 + width
    incidents = []
    for k, t in enumerate(types):
        inc = _make_incident(rng, t, 0)
        inc["role"] = "load"
        if k == 0:  # el menor abre la ventana y se queda con un equipo que luego hará falta
            inc["t"] = w0 + rng.randint(0, 2)
            inc["severity"] = min(inc["severity"], 5)
            inc["rel_deadline"] = max(inc["rel_deadline"], width + 10)
        else:       # todos siguen abiertos en el minuto `peak`; lo grave tiende a entrar tarde
            lo = max(w0, peak - inc["rel_deadline"] + 1)
            u = rng.uniform(0.4, 1.0) if inc["severity"] >= 8 else rng.uniform(0.0, 0.7)
            inc["t"] = lo + int((peak - lo) * u)
        incidents.append(inc)
    used_zones: dict[str, int] = {}
    for inc in incidents:  # dos frentes con densidad forzada no pueden pisarse la misma zona
        if TAXONOMY[inc["type"]].density and used_zones.get(inc["zone"]):
            free = [z for z in TAXONOMY[inc["type"]].zones if z not in used_zones]
            inc["zone"] = rng.choice(free) if free else inc["zone"]
        used_zones[inc["zone"]] = 1

    surprise_t = None
    meta: dict[str, Any] = {"load": load, "window": [w0, peak], "demand": demand, "supply": supply, "scarce_kinds": scarce,
                            "distinct_families": len({i["family"] for i in incidents})}
    if surprise:
        surprise_t = peak - rng.randint(0, 2)
        meta.update(surprise_t=surprise_t, surprise_kind="incident" if pert == "second_wave" else "world")
        if pert == "second_wave":
            pool = [t for t in split_types(split) if t not in types and st.accepts(t) and TAXONOMY[t].severity[0] >= 8]
            extra = _make_incident(rng, rng.choice(pool) if pool else types[1], surprise_t)
            extra.update(role="second_wave", via_world=True)
            extra["rel_deadline"] = max(extra["rel_deadline"], peak - surprise_t + 2)
            incidents.append(extra)
    else:
        meta.update(surprise_t=None, surprise_kind=None)

    primary = max(incidents, key=lambda i: (i["role"] == "load", i["severity"], -i["rel_deadline"]))
    case = _assemble(rng, {
        "id": f"c-L{split[0]}{load}{int(surprise)}{index:04d}", "seed": case_seed, "split": split, "day": day, "phase": phase,
        "weather": weather, "perts": [pert], "incidents": incidents, "primary": primary, "chain": [],
        "info_quality": rng.choices(INFO_QUALITIES, weights=[50, 10, 10, 10, 10, 10])[0], "resource_state": resource_state,
        "pert_t": surprise_t if surprise else rng.randint(0, 2), "surprise": surprise, "meta": meta})
    # La respuesta correcta a la escasez: quitarle el equipo a lo menor, no dejar lo grave en cola.
    top = case["expected"]["priority"][0]
    ty = TAXONOMY["all_busy_higher_priority"]
    case["expected"]["must"] += [r for r in (fill_rule(x, i=top) for x in ty.must) if r not in case["expected"]["must"]]
    case["expected"]["must_not"] += [r for r in (fill_rule(x, i=top) for x in ty.must_not) if r not in case["expected"]["must_not"]]
    if ty.id not in case["meta"]["types"]:
        case["meta"]["types"].append(ty.id)
        if "resource" not in case["families"]:
            case["families"] = [f for f in FAMILY_ORDER if f in set(case["families"]) | {"resource"}]
    return case


def iter_load_cases(seed: int = 1, per_level: int = 150, levels: tuple[int, ...] = LOAD_LEVELS) -> Iterator[dict[str, Any]]:
    """Por cada nivel de carga: mitad con sorpresa y mitad sin ella; de cada mitad, 2/3 train y 1/3 heldout."""
    for load in levels:
        for surprise in (False, True):
            half = per_level // 2 + (per_level % 2 if not surprise else 0)
            n_heldout = half // 3
            for split, n in (("train", half - n_heldout), ("heldout", n_heldout)):
                for index in range(n):
                    yield build_load_case(index, seed, split, load, surprise)


def generate_load(per_level: int = 150, seed: int = 1) -> list[dict[str, Any]]:
    return list(iter_load_cases(seed=seed, per_level=per_level))


# ------------------------------------------------------------------ prioridad esperada y simultaneidad

FAMILY_RANK = ("medical", "crowd", "aggression", "weather", "external", "infra", "resource", "info", "supply")


def priority_order(case: dict[str, Any]) -> dict[str, Any]:
    """Orden razonable entre los incidentes seguros del caso, para puntuar a quién se dejó esperando.
    Escalones por severidad (≥9 · 7–8 · 5–6 · ≤4); dentro, severidad, plazo más corto y familia. Solo debe
    penalizarse invertir dos incidentes de escalones distintos: dentro de un escalón el orden es orientativo."""
    sure = [i for i in true_incidents(case) if not i["conditional"]]
    sure.sort(key=lambda i: (-i["severity"], i["deadline"], FAMILY_RANK.index(i["family"]), i["id"]))
    tiers: list[list[str]] = [[], [], [], []]
    for i in sure:
        tiers[0 if i["severity"] >= 9 else 1 if i["severity"] >= 7 else 2 if i["severity"] >= 5 else 3].append(i["id"])
    tiers = [t for t in tiers if t]
    low = {i["id"] for i in sure if i["severity"] <= 6}
    may_wait = [i for i in tiers[-1] if i in low] if len(tiers) > 1 else []
    return {"priority": [i["id"] for i in sure], "priority_tiers": tiers, "may_wait": may_wait}


def max_concurrent(case: dict[str, Any]) -> int:
    """Máximo de incidentes verdaderos seguros abiertos a la vez, tomando cada uno de su apertura a su plazo."""
    marks = []
    for i in true_incidents(case):
        if not i["conditional"]:
            marks += [(i["t_open"], 1), (i["deadline"] + 1, -1)]
    best = now = 0
    for _, step in sorted(marks):
        now += step
        best = max(best, now)
    return best


# ------------------------------------------------------------------ dificultad (calculada, no sorteada)


def true_incidents(case: dict[str, Any]) -> list[dict[str, Any]]:
    """Incidentes verdaderos del caso con su minuto de apertura y si son condicionales."""
    out = []
    for ev in case["events"]:
        body = ev.get("incident") if ev["kind"] == "incident" else \
            ev["effect"].get("incident") if ev["kind"] == "world" and ev["effect"]["kind"] == "incident" else None
        if body:
            out.append(dict(body, t_open=ev["t"], conditional="cond" in ev))
    return out


def compute_difficulty(case: dict[str, Any]) -> tuple[int, float]:
    meta = case.get("meta", {})
    incs = true_incidents(case)
    sure = [i for i in incs if not i["conditional"]]
    pts = {1: 0.0, 2: 1.2, 3: 2.2}.get(len(sure), 3.0 + 0.6 * max(0, len(sure) - 4))
    top = max((i["severity"] for i in incs), default=0)
    pts += 1.2 if top >= 10 else 0.8 if top == 9 else 0.0
    # Solapes que compiten por el mismo tipo de recurso.
    clashes = sum(1 for a, b in combinations(sure, 2)
                  if a["t_open"] <= b["deadline"] and b["t_open"] <= a["deadline"] and set(a["needs"]) & set(b["needs"]))
    pts += min(2.4, 0.6 * clashes)
    # Escasez: demanda simultánea de un tipo de recurso por encima de las unidades en servicio.
    offline = set(case["initial"].get("resources_offline", []))
    for kind in {k for i in sure for k in i["needs"]}:
        supply = len([r for r in units_of(kind) if r not in offline])
        peak = max(sum(j["needs"].get(kind, 0) for j in sure if j["t_open"] <= i["deadline"] and i["t_open"] <= j["deadline"])
                   for i in sure)
        if peak > supply:
            pts += 1.2
            break
    pts += INFO_POINTS.get(meta.get("info_quality", "clean"), 0.0)
    pts += STATE_POINTS.get(meta.get("resource_state", "full"), 0.0)
    pts += 0.9 * len([p for p in meta.get("perturbations", []) if p != "none"])
    pts += 0.7 * len(meta.get("chain", []))
    pts += 0.3 if meta.get("weather", "normal") != "normal" else 0.0
    pts += 0.3 if meta.get("phase") in ("headliner", "egress") else 0.0
    pts += 0.4 if any(TAXONOMY[i["type"]].approval for i in sure if i["type"] in TAXONOMY) else 0.0
    first_langs = [r.get("lang", "es") for ev in case["events"] if ev["kind"] == "incident" for r in ev["reports"][:1]]
    pts += 0.2 if any(l != "es" for l in first_langs) else 0.0
    pts = round(pts, 2)
    return 1 + sum(pts >= c for c in DIFFICULTY_CUTS), pts


# ------------------------------------------------------------------ API pública


def iter_cases(seed: int = 1, split: str = "train", start: int = 0, n: int | None = None) -> Iterator[dict[str, Any]]:
    """Casos de la partición, de `start` en adelante. Mismo (seed, split, índice) = mismo caso."""
    if split == "demo":
        from .demo_cases import demo_cases
        yield from demo_cases()[start:None if n is None else start + n]
        return
    index = start
    while n is None or index < start + n:
        yield build_case(index, seed, split)
        index += 1


def generate(n: int, seed: int = 1, split: str = "train") -> list[dict[str, Any]]:
    return list(iter_cases(seed=seed, split=split, n=n))


def signature(case: dict[str, Any]) -> tuple:
    """Firma estructural: dos casos con la misma firma solo difieren en textos, zonas y tiempos."""
    m = case["meta"]
    return (case["day"], m["phase"], m["weather"], m["info_quality"], m["resource_state"],
            tuple(m["perturbations"]), tuple(sorted({c[1] for c in m["combos"]})), tuple(map(tuple, m["chain"])))


def space_size(split: str = "train") -> dict[str, Any]:
    """Cota INFERIOR del número de casos estructuralmente distintos que puede producir la partición.

    Cuenta conjuntos de 1–4 tipos compatibles entre sí (meteorología, fase, perturbaciones permitidas
    y, en train, parejas de familias vetadas) × meteorologías comunes × fases comunes × 3 días ×
    subconjuntos de 1–2 perturbaciones comunes × 6 calidades de información × 5 estados de recursos
    (se deja fuera `all_busy`, que fija los acompañantes). NO cuenta zonas, severidades, tiempos,
    encadenamientos, segunda oleada, idiomas ni textos, que multiplican la cifra varios órdenes más.
    """
    types = split_types(split)
    wbit = {w: 1 << k for k, w in enumerate(WEATHERS)}
    pbit = {p: 1 << k for k, p in enumerate(PHASES)}
    xbit = {p: 1 << k for k, p in enumerate(PERTURBATIONS)}
    info = []
    for t in types:
        ty = TAXONOMY[t]
        info.append((sum(wbit[w] for w in (ty.weather or WEATHERS)), sum(pbit[p] for p in (ty.phases or PHASES)),
                     sum(xbit[p] for p in allowed_perturbations(t, split)), ty.family.value))
    none_bit = xbit["none"]
    by_k = {1: 0, 2: 0, 3: 0, 4: 0}
    sets_by_k = {1: 0, 2: 0, 3: 0, 4: 0}

    def walk(start: int, k: int, w: int, p: int, x: int, fams: frozenset[str]) -> None:
        if k:
            n_x = (x & ~none_bit).bit_count()
            subsets = (1 if x & none_bit else 0) + n_x + n_x * (n_x - 1) // 2
            by_k[k] += w.bit_count() * p.bit_count() * 3 * subsets * len(INFO_QUALITIES) * (len(RESOURCE_STATES) - 1)
            sets_by_k[k] += 1
        if k == 4:
            return
        for j in range(start, len(info)):
            w2, p2, x2 = w & info[j][0], p & info[j][1], x & info[j][2]
            if not (w2 and p2 and x2):
                continue
            fams2 = fams | {info[j][3]}
            if split == "train" and _families_clash(set(fams2)):
                continue
            walk(j + 1, k + 1, w2, p2, x2, fams2)

    walk(0, 0, 15, 15, (1 << len(PERTURBATIONS)) - 1, frozenset())
    return {"split": split, "types": len(types), "type_sets_by_size": sets_by_k, "cases_by_size": by_k,
            "total": sum(by_k.values())}
