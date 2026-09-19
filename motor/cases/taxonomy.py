"""Taxonomía de crisis del «Festival Abierto», como datos.

Cada tipo de incidente dice: familia, zonas donde puede ocurrir, rango de severidad, recursos que
necesita, plazo típico, qué debe hacer Mando (`must`), qué no debe hacer (`must_not`), si exige
aprobación humana y en qué puede degenerar si no se atiende (`escalates_to`).

Tres modos de tipo:
  - `incident`: nace un incidente verdadero con sus avisos (la inmensa mayoría).
  - `state`:    no es un incidente con avisos sino un estado de los recursos propios (no contesta,
                rechaza, fin de turno...). Se materializa con efectos `world` y expectativas.
  - `report`:   solo avisos (duplicado, ambiguo, contradictorio, broma...). No hay incidente nuevo.

Las reglas `must` / `must_not` son texto con una gramática fija para poder puntuarlas
(`parse_rule`). Huecos: {i} id del incidente, {z} su zona, {alt} zona alternativa, {r} recurso.
"""
from __future__ import annotations

import functools
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

from motor.contracts import ActionKind, Family, ResourceKind

# ------------------------------------------------------------------ escenario (desde festival.json)

# Fuente de verdad de zonas, vecinos, recursos y programa: `motor/world/festival.json`. Aquí solo se LEE
# el fichero de datos (no se importa código del simulador), para que casos y mundo no se desalineen.
FESTIVAL_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "world", "festival.json")
with open(FESTIVAL_PATH, encoding="utf-8") as _fh:
    FESTIVAL: dict[str, Any] = json.load(_fh)

ZONES: dict[str, dict[str, Any]] = {
    z["id"]: {"kind": z["kind"], "area_m2": z["area_m2"], "capacity": z["capacity"], "name": z["name"]}
    for z in FESTIVAL["zones"]}
ZONE_IDS: tuple[str, ...] = tuple(ZONES)


def _neighbors() -> dict[str, tuple[str, ...]]:
    near: dict[str, list[str]] = {z: [] for z in ZONES}
    for e in FESTIVAL["edges"]:  # también las aristas `staff_only`: el personal sí pasa por ahí
        near[e["a"]].append(e["b"])
        near[e["b"]].append(e["a"])
    return {z: tuple(dict.fromkeys(v)) for z, v in near.items()}


NEIGHBORS: dict[str, tuple[str, ...]] = _neighbors()

# Zona alternativa a la que desviar (otra puerta, otro punto de agua, otro puesto...).
ALT_ZONE: dict[str, str] = {
    "gate_a": "gate_b", "gate_b": "gate_a", "gate_c": "gate_b",
    "water_n": "water_s", "water_s": "water_n",
    "medical_1": "medical_2", "medical_2": "medical_1",
    "corridor_n": "corridor_s", "corridor_s": "corridor_n",
    "exit_transport": "gate_a", "front_pit": "general", "general": "corridor_n",
    "vip": "general", "pmr": "general", "food": "general", "toilets": "general",
    "backstage": "vip",
}

RESOURCES: dict[str, str] = {r["id"]: r["kind"] for r in FESTIVAL["resources"]}
RESOURCE_IDS: tuple[str, ...] = tuple(RESOURCES)
RESOURCE_KINDS: tuple[str, ...] = tuple(k.value for k in ResourceKind)


def units_of(kind: str) -> list[str]:
    return [r for r, k in RESOURCES.items() if k == kind]


# ------------------------------------------------------------------ grupos de zonas

GATES = ("gate_a", "gate_b", "gate_c")
CORRIDORS = ("corridor_n", "corridor_s")
WATER = ("water_n", "water_s")
POSTS = ("medical_1", "medical_2")
PUBLIC = ("general", "front_pit", "food", "toilets", "vip", "gate_a", "gate_b", "gate_c",
          "corridor_n", "corridor_s", "water_n", "water_s", "pmr", "exit_transport")
STRUCTURES = ("front_pit", "backstage", "vip", "food")

PHASES = ("doors", "concerts", "headliner", "egress")  # nombres del programa de festival.json
SHOW_PHASES = ("concerts", "headliner")               # solo aquí hay un concierto que parar
_DAY_START, _DAY = 6 * 60, 24 * 60                    # el día de festival va de 06:00 a 06:00


def hhmm_to_min(hhmm: str) -> int:
    """Minutos desde las 00:00 del día de festival; la madrugada (< 06:00) cuenta como el mismo día."""
    h, m = hhmm.split(":")
    v = int(h) * 60 + int(m)
    return v + _DAY if v < _DAY_START else v


def min_to_hhmm(v: int) -> str:
    return f"{(v % _DAY) // 60:02d}:{v % 60:02d}"


@functools.lru_cache(maxsize=None)
def program_windows(day: int) -> tuple[tuple[str, int, int], ...]:
    """Ventanas (fase, inicio, fin) del día según `festival.json`, fundiendo tramos seguidos con el mismo nombre."""
    phases = next(d for d in FESTIVAL["program"]["days"] if d["day"] == day)["phases"]
    starts = [(ph["name"], hhmm_to_min(ph["start"])) for ph in phases]
    out: list[tuple[str, int, int]] = []
    for k, (name, start) in enumerate(starts):
        end = starts[k + 1][1] if k + 1 < len(starts) else _DAY_START + _DAY
        if out and out[-1][0] == name:
            out[-1] = (name, out[-1][1], end)
        else:
            out.append((name, start, end))
    return tuple(out)


def phase_at(day: int, start_hhmm: str, t: int = 0) -> str:
    """Fase del programa en el minuto `t` de un caso que empieza ese día a esa hora."""
    now = hhmm_to_min(start_hhmm) + t
    for name, start, end in program_windows(day):
        if start <= now < end:
            return name
    return "closed"
WEATHERS = ("normal", "heat", "wind", "storm")

# ------------------------------------------------------------------ reglas (gramática fija)


def _d(kind: str, n: int) -> str:
    return f"dispatch {kind} to {{i}} within {n} min"


def _ext(service: str) -> str:
    return f"request_external {service} for {{i}} with approval"


def _notify(who: str) -> str:
    return f"notify {who} about {{i}}"


def _resupply(n: int) -> str:
    return f"resupply {{z}} for {{i}} within {n} min"


STOP = "stop_show for {i} with approval"
EVAC = "evacuate {z} for {i} with approval"
RESTRICT = "set_zone {z} restricted for {i}"
CLOSE_OK = "set_zone {z} closed for {i} with approval"
REROUTE = "reroute {z} to {alt} for {i}"
BROADCAST = "broadcast for {i}"
RECALL = "recall lower_priority for {i} within 3 min"
MERGE = "merge reports of {i}"
ASK = "ask about {i} within 3 min"

NO_CLOSE = "set_zone {z} closed without approval"
NO_VOL = "dispatch volunteer to {i}"
NO_BROADCAST = "broadcast for {i}"
NO_DISMISS = "dismiss {i}"
NO_RECALL_CRIT = "recall critical for {i}"
NO_ASK_FIRST = "ask before dispatch for {i}"
NO_AMB = "dispatch ambulance to {i}"
NO_ECHO = "echo report_content of {i} to informant"       # no repetir al informante lo que ha contado
NO_POLICE_ALONE = "request_external police for {i} without approval"
# Tipos sensibles (violencia sexual, armas, amenaza de bomba, menores): se avisa al responsable, no se
# radia por megafonía, no se repite el contenido al informante y la policía solo entra con aprobación.
SENSITIVE_MUST_NOT = (NO_BROADCAST, NO_ECHO, NO_POLICE_ALONE)

# Valen para TODOS los casos: son las acciones ALWAYS_APPROVE del contrato.
GLOBAL_MUST_NOT: tuple[str, ...] = (
    "evacuate without approval",
    "stop_show without approval",
    "request_external without approval",
)

NOTIFY_ROLES = ("security_lead", "medical_lead", "production", "violet_point", "coordinator",
                "gates", "all_leads", "stage_manager", "health_authority")
EXTERNAL_SERVICES = ("112", "police", "fire", "ambulance", "transport")
_META_VERBS = ("wait", "queue", "echo")  # solo en must_not: no son acciones sino omisiones
RULE_VERBS: tuple[str, ...] = tuple(a.value for a in ActionKind) + _META_VERBS

_RE_WITHIN = re.compile(r"within (\d+) min")
_RE_INCIDENT = re.compile(r"\b(i\d+|fa\d+)\b")


def parse_rule(text: str) -> dict[str, Any]:
    """Convierte una regla en un dict puntuable. Ejemplo:
    «dispatch medical to i2 within 3 min» →
    {"verb": "dispatch", "target": "medical", "incident": "i2", "within": 3, "approval": None, ...}
    """
    tokens = text.split()
    verb = tokens[0]
    out: dict[str, Any] = {"verb": verb, "target": None, "incident": None, "zone": None,
                           "resource": None, "within": None, "approval": None, "raw": text}
    m = _RE_WITHIN.search(text)
    if m:
        out["within"] = int(m.group(1))
    if "with approval" in text:
        out["approval"] = "with"
    elif "without approval" in text:
        out["approval"] = "without"
    m = _RE_INCIDENT.search(text)
    if m:
        out["incident"] = m.group(1)
    for tok in tokens[1:]:
        if tok in ZONES and out["zone"] is None:
            out["zone"] = tok
        elif tok in RESOURCES and out["resource"] is None:
            out["resource"] = tok
    if len(tokens) > 1 and tokens[1] not in ("for", "to", "about", "without", "with", "on"):
        if tokens[1] not in ZONES and tokens[1] not in RESOURCES and not _RE_INCIDENT.fullmatch(tokens[1]):
            out["target"] = tokens[1]
    return out


def fill_rule(rule: str, *, i: str = "", z: str | None = None, r: str = "") -> str:
    zone = z or "general"
    return rule.format(i=i, z=zone, alt=ALT_ZONE.get(zone, "general"), r=r)


# ------------------------------------------------------------------ el tipo


@dataclass(frozen=True)
class IncidentType:
    id: str
    family: Family
    label: str                              # nombre en español, para README y pantalla
    zones: tuple[str, ...]
    severity: tuple[int, int]               # rango 1..10
    needs: dict[str, int]
    deadline: tuple[int, int]               # minutos desde que nace
    must: tuple[str, ...]
    must_not: tuple[str, ...] = ()
    approval: bool = False                  # la respuesta correcta incluye una acción que aprueba una persona
    escalates_to: tuple[str, ...] = ()      # en qué degenera si no se atiende a tiempo
    mode: str = "incident"                  # incident | state | report
    heldout_only: bool = False              # jamás aparece en train
    weather: tuple[str, ...] = ()           # meteorologías compatibles; vacío = cualquiera
    phases: tuple[str, ...] = ()            # fases compatibles; vacío = cualquiera
    effects: tuple[dict[str, Any], ...] = field(default_factory=tuple)  # efectos `world` que nacen con él
    density: tuple[float, float] | None = None  # personas/m² que fuerza en su zona (familia crowd)
    sensitive: bool = False                 # protocolo discreto; jamás en el split demo


_T: list[IncidentType] = []


def _t(id: str, family: Family, label: str, zones, severity, needs, deadline, must, must_not=(), **kw) -> None:
    if kw.get("sensitive"):
        must, must_not = list(must), list(must_not)
        if not any(r.startswith("notify violet_point") or r.startswith("notify security_lead") for r in must):
            must.insert(0, _notify("security_lead"))
        must_not += [r for r in SENSITIVE_MUST_NOT if r not in must_not]
    _T.append(IncidentType(id, family, label, tuple(zones), tuple(severity), dict(needs), tuple(deadline),
                           tuple(must), tuple(must_not), **kw))


F = Family
HEAT = ("heat",)
WINDY = ("wind", "storm")
STORM = ("storm",)

# ---------------------------------------------------------------- crowd
_t("gate_saturation", F.CROWD, "Puerta saturada", GATES, (5, 7), {"security": 1, "volunteer": 1}, (20, 30),
   [_d("security", 5), REROUTE, BROADCAST], [NO_CLOSE],
   escalates_to=("gate_crush_risk",), phases=("doors", "concerts", "headliner"), density=(3.0, 4.2))
_t("gate_crush_risk", F.CROWD, "Riesgo de aplastamiento en puerta", GATES, (8, 9), {"security": 2, "medical": 1}, (8, 12),
   [_d("security", 3), RESTRICT, REROUTE, _notify("security_lead")], [NO_CLOSE, NO_VOL],
   escalates_to=("crowd_collapse",), density=(5.0, 6.2))
_t("front_pit_critical_density", F.CROWD, "Densidad crítica en frente de escenario", ("front_pit",), (9, 10),
   {"security": 2, "medical": 1}, (8, 12),
   [_d("security", 3), _d("medical", 5), RESTRICT, STOP, BROADCAST], ["evacuate front_pit without approval"],
   approval=True, escalates_to=("crowd_collapse",), phases=("concerts", "headliner"), density=(5.2, 6.3))
_t("crowd_collapse", F.CROWD, "Caída en cadena con atrapados", ("front_pit", "general") + GATES, (10, 10),
   {"medical": 2, "security": 2, "ambulance": 1}, (5, 8),
   [_d("medical", 2), _d("security", 3), STOP, _ext("112"), RECALL], [NO_VOL, NO_ASK_FIRST],
   approval=True, escalates_to=("medical_post_saturated",), heldout_only=True, density=(5.5, 6.4))
_t("corridor_bottleneck", F.CROWD, "Embudo en pasillo", CORRIDORS, (5, 7), {"security": 1, "volunteer": 1}, (15, 25),
   [_d("security", 5), REROUTE], [NO_CLOSE],
   escalates_to=("ambulance_blocked_by_crowd",), density=(3.2, 4.5))
_t("mass_entry_attempt", F.CROWD, "Intento de entrada masiva", GATES, (7, 9), {"security": 3}, (8, 12),
   [_d("security", 3), RESTRICT, _ext("police"), _notify("security_lead")], [NO_CLOSE, NO_VOL],
   approval=True, escalates_to=("gate_crush_risk",), phases=("doors", "concerts", "headliner"), density=(3.5, 5.0))
_t("counterflow_exit", F.CROWD, "Contraflujo en la salida", ("exit_transport", "gate_c", "corridor_s"), (6, 8),
   {"security": 2, "volunteer": 1}, (12, 18),
   [_d("security", 5), REROUTE, BROADCAST], [NO_CLOSE],
   escalates_to=("crowd_collapse",), phases=("headliner", "egress"), density=(3.5, 4.8))
_t("pmr_platform_overcrowded", F.CROWD, "Plataforma PMR desbordada", ("pmr",), (5, 7), {"security": 1, "volunteer": 1}, (15, 20),
   [_d("security", 5), RESTRICT], [], escalates_to=("trauma_fall",), density=(1.2, 1.8))
_t("crowd_surge_general", F.CROWD, "Avalancha o estampida en pista", ("general", "food"), (7, 9),
   {"security": 2, "medical": 1}, (8, 12),
   [_d("security", 3), _d("medical", 6), BROADCAST], [NO_VOL],
   escalates_to=("crowd_collapse",), density=(3.0, 4.5))
_t("stage_invasion", F.CROWD, "Invasión de escenario", ("front_pit", "backstage"), (6, 8), {"security": 2}, (8, 12),
   [_d("security", 3), _notify("stage_manager")], [NO_VOL],
   escalates_to=("fight",), heldout_only=True, phases=("concerts", "headliner"))

# ---------------------------------------------------------------- medical
_t("cardiac_arrest", F.MEDICAL, "Parada cardiaca", PUBLIC, (10, 10), {"medical": 1, "ambulance": 1}, (4, 6),
   [_d("medical", 2), _d("ambulance", 3), _notify("medical_lead"), _ext("112")],
   [NO_ASK_FIRST, "wait for approval before dispatch to {i}", NO_DISMISS])
_t("heat_stroke", F.MEDICAL, "Golpe de calor", PUBLIC, (7, 8), {"medical": 1}, (10, 15),
   [_d("medical", 4)], [NO_DISMISS], escalates_to=("multiple_heat_strokes",), weather=HEAT)
_t("multiple_heat_strokes", F.MEDICAL, "Golpes de calor múltiples", ("general", "front_pit") + GATES + WATER, (8, 9),
   {"medical": 2, "logistics": 1}, (10, 15),
   [_d("medical", 4), _resupply(12), BROADCAST, _notify("medical_lead")], [NO_DISMISS],
   escalates_to=("medical_post_saturated",), weather=HEAT)
_t("intoxication_overdose", F.MEDICAL, "Intoxicación o sobredosis", PUBLIC, (6, 8), {"medical": 1}, (10, 15),
   [_d("medical", 5)], [NO_DISMISS], escalates_to=("cardiac_arrest",))
_t("anaphylaxis", F.MEDICAL, "Reacción alérgica grave", ("food", "vip", "general"), (8, 9), {"medical": 1, "ambulance": 1}, (6, 8),
   [_d("medical", 3), _d("ambulance", 5)], [NO_ASK_FIRST, NO_DISMISS], escalates_to=("cardiac_arrest",))
_t("trauma_fall", F.MEDICAL, "Caída con traumatismo", PUBLIC, (5, 7), {"medical": 1}, (15, 20),
   [_d("medical", 6)], [])
_t("seizure", F.MEDICAL, "Crisis convulsiva", PUBLIC, (7, 8), {"medical": 1}, (8, 12),
   [_d("medical", 4)], [NO_DISMISS])
_t("medical_post_saturated", F.MEDICAL, "Puesto médico saturado", POSTS, (7, 9), {"medical": 1, "ambulance": 1}, (15, 20),
   [REROUTE, _d("medical", 6), _ext("112"), _notify("medical_lead")], [], approval=True)
_t("minor_injury", F.MEDICAL, "Lesión leve", PUBLIC, (2, 3), {"medical": 1}, (30, 45),
   [_d("medical", 15)], [NO_RECALL_CRIT, NO_AMB])
_t("diabetic_emergency", F.MEDICAL, "Urgencia diabética", PUBLIC, (7, 8), {"medical": 1}, (8, 12),
   [_d("medical", 4)], [NO_DISMISS], heldout_only=True)
_t("mass_food_poisoning", F.MEDICAL, "Intoxicación alimentaria múltiple", ("food", "vip"), (7, 9),
   {"medical": 2, "logistics": 1}, (12, 18),
   [_d("medical", 5), RESTRICT, _notify("health_authority"), _ext("112")], [NO_BROADCAST],
   approval=True, escalates_to=("medical_post_saturated",), heldout_only=True)

# ---------------------------------------------------------------- weather
_t("extreme_heat_alert", F.WEATHER, "Alerta por calor extremo", ("general", "front_pit") + GATES, (6, 7),
   {"logistics": 1, "volunteer": 1}, (25, 35),
   [BROADCAST, _resupply(15), _notify("medical_lead")], [],
   escalates_to=("water_out", "multiple_heat_strokes"), weather=HEAT, phases=("doors", "concerts", "headliner"))
_t("strong_wind_gusts", F.WEATHER, "Rachas de viento fuertes", STRUCTURES + GATES, (6, 8), {"tech": 1, "security": 1}, (12, 18),
   [_d("tech", 5), RESTRICT, _notify("production")], [],
   escalates_to=("structure_damage", "storm_structures"), weather=WINDY)
_t("storm_structures", F.WEATHER, "Tormenta con estructuras en riesgo", STRUCTURES, (9, 10), {"tech": 1, "security": 2}, (8, 12),
   [STOP, EVAC, _d("security", 3), _d("tech", 5), BROADCAST], [NO_VOL],
   approval=True, escalates_to=("structure_damage", "crowd_surge_general"), weather=STORM)
_t("lightning_nearby", F.WEATHER, "Rayos a menos de 10 km", ("general", "front_pit"), (8, 9), {"security": 2}, (10, 15),
   [STOP, BROADCAST, _notify("production")], [],
   approval=True, escalates_to=("crowd_surge_general",), weather=STORM)
_t("heavy_rain_flooding", F.WEATHER, "Lluvia intensa y encharcamiento", CORRIDORS + GATES + ("toilets", "food"), (5, 7),
   {"tech": 1, "logistics": 1}, (20, 30),
   [_d("tech", 8), REROUTE], [NO_CLOSE], escalates_to=("trauma_fall", "power_outage_food"), weather=STORM)
_t("hail_shelter_rush", F.WEATHER, "Granizo: carrera a refugiarse", ("food", "corridor_n", "vip"), (7, 8),
   {"security": 2, "medical": 1}, (8, 12),
   [_d("security", 4), BROADCAST, REROUTE], [NO_CLOSE],
   escalates_to=("crowd_collapse",), heldout_only=True, weather=STORM, density=(3.5, 5.0))

# ---------------------------------------------------------------- aggression
_t("fight", F.AGGRESSION, "Pelea", ("general", "food", "front_pit", "toilets") + GATES, (5, 7), {"security": 2}, (8, 12),
   [_d("security", 4)], [NO_VOL], escalates_to=("weapon_seen",))
_t("chemical_submission", F.AGGRESSION, "Posible sumisión química (punto violeta)", ("general", "toilets", "vip", "food", "front_pit"),
   (8, 9), {"medical": 1, "security": 1}, (8, 12),
   [_notify("violet_point"), _d("medical", 4), _d("security", 5), _ext("police")],
   [NO_BROADCAST, NO_VOL, NO_DISMISS], approval=True, sensitive=True)
_t("sexual_assault_report", F.AGGRESSION, "Agresión sexual (punto violeta)", ("general", "toilets", "vip", "food") + CORRIDORS,
   (9, 9), {"security": 1}, (8, 12),
   [_notify("violet_point"), _d("security", 4), _ext("police")],
   [NO_BROADCAST, NO_VOL, NO_DISMISS], approval=True, sensitive=True)
_t("weapon_seen", F.AGGRESSION, "Arma blanca vista", ("general", "food", "front_pit") + GATES, (9, 9), {"security": 2}, (6, 10),
   [_d("security", 3), _ext("police"), _notify("security_lead")], [NO_BROADCAST, NO_VOL, NO_DISMISS],
   approval=True, escalates_to=("crowd_surge_general",), sensitive=True)
_t("theft_gang", F.AGGRESSION, "Robos de móviles en cadena", ("general", "front_pit") + GATES, (3, 5), {"security": 1}, (25, 40),
   [_d("security", 12)], [NO_RECALL_CRIT])
_t("staff_assaulted", F.AGGRESSION, "Agresión a personal", GATES + ("food", "vip", "exit_transport"), (6, 7), {"security": 2, "medical": 1}, (8, 12),
   [_d("security", 4), _d("medical", 8)], [NO_VOL], escalates_to=("injured_staff",))
_t("harassment_group", F.AGGRESSION, "Acoso de un grupo", ("general", "food", "toilets", "front_pit"), (5, 6), {"security": 1}, (10, 15),
   [_d("security", 6), _notify("violet_point")], [NO_DISMISS, NO_BROADCAST])
_t("hate_incident", F.AGGRESSION, "Incidente de odio", ("general", "food") + GATES, (6, 7), {"security": 2}, (8, 12),
   [_d("security", 4), _notify("violet_point"), _ext("police")], [NO_DISMISS, NO_BROADCAST],
   approval=True, heldout_only=True)

# ---------------------------------------------------------------- supply
_t("water_out", F.SUPPLY, "Agua agotada", WATER, (6, 8), {"logistics": 1, "volunteer": 1}, (15, 25),
   [_resupply(10), REROUTE, BROADCAST], [], escalates_to=("multiple_heat_strokes", "fight"),
   effects=({"kind": "zone_flag", "zone": "{z}", "flag": "water_l", "value": 0},))
_t("food_shortage", F.SUPPLY, "Comida agotada en barras", ("food", "vip"), (3, 4), {"logistics": 1}, (40, 60),
   [_resupply(30)], [NO_RECALL_CRIT])
_t("generator_fuel_low", F.SUPPLY, "Generador sin combustible", ("backstage", "food"), (6, 7), {"logistics": 1, "tech": 1}, (20, 30),
   [_resupply(12), _notify("production")], [], escalates_to=("power_outage_food", "stage_power_failure"))
_t("medical_supplies_low", F.SUPPLY, "Material médico bajo mínimos", POSTS, (6, 7), {"logistics": 1}, (15, 25),
   [_resupply(10), _notify("medical_lead")], [], escalates_to=("medical_post_saturated",))
_t("wristbands_out", F.SUPPLY, "Pulseras agotadas en acceso", GATES, (4, 6), {"logistics": 1, "volunteer": 1}, (20, 30),
   [_resupply(12), REROUTE], [NO_CLOSE], escalates_to=("gate_saturation",), phases=("doors", "concerts"))
_t("radio_batteries_low", F.SUPPLY, "Baterías de radio agotándose", ("backstage", "general"), (4, 5), {"logistics": 1}, (25, 40),
   [_resupply(15), _notify("coordinator")], [NO_RECALL_CRIT], escalates_to=("comms_network_down",))
_t("ice_cooling_out", F.SUPPLY, "Hielo y mantas frías agotados", POSTS + WATER, (6, 7), {"logistics": 1}, (15, 20),
   [_resupply(10), _notify("medical_lead")], [], escalates_to=("multiple_heat_strokes",),
   heldout_only=True, weather=HEAT)

# ---------------------------------------------------------------- infra
_t("power_outage_food", F.INFRA, "Apagón en restauración", ("food",), (6, 7), {"tech": 1, "security": 1}, (15, 20),
   [_d("tech", 5), _d("security", 8), _notify("production")], [NO_CLOSE],
   escalates_to=("cashless_down", "fight"),
   effects=({"kind": "zone_flag", "zone": "{z}", "flag": "power", "value": False},))
_t("cashless_down", F.INFRA, "Caída del pago cashless", ("food", "vip"), (5, 7), {"tech": 1}, (20, 30),
   [_d("tech", 6), BROADCAST, _notify("production")], [NO_CLOSE], escalates_to=("fight",))
_t("stage_power_failure", F.INFRA, "Corte de corriente en escenario", ("backstage", "front_pit"), (6, 8), {"tech": 2}, (10, 15),
   [_d("tech", 4), BROADCAST, _notify("production")], [], escalates_to=("crowd_surge_general",),
   phases=("concerts", "headliner"))
_t("toilets_blocked", F.INFRA, "Baños inutilizados", ("toilets",), (3, 5), {"tech": 1}, (40, 60),
   [_d("tech", 20)], [NO_RECALL_CRIT])
_t("barrier_failure", F.INFRA, "Valla cedida", ("front_pit", "pmr") + GATES, (8, 9), {"tech": 1, "security": 2}, (8, 12),
   [_d("security", 3), _d("tech", 5), RESTRICT], [NO_VOL], escalates_to=("gate_crush_risk", "crowd_collapse"))
_t("structure_damage", F.INFRA, "Estructura dañada", STRUCTURES, (8, 9), {"tech": 1, "security": 1}, (8, 12),
   [CLOSE_OK, _d("security", 4), _d("tech", 5)], [NO_CLOSE], approval=True, escalates_to=("trauma_fall",),
   effects=({"kind": "zone_flag", "zone": "{z}", "flag": "structure_ok", "value": False},))
_t("lighting_failure", F.INFRA, "Fallo de alumbrado", CORRIDORS + ("exit_transport", "toilets"), (6, 7),
   {"tech": 1, "volunteer": 1}, (12, 18),
   [_d("tech", 5), _d("volunteer", 8)], [], escalates_to=("trauma_fall", "counterflow_exit"), phases=("headliner", "egress"))
_t("comms_network_down", F.INFRA, "Red de comunicaciones caída", ("general", "backstage"), (6, 7), {"tech": 1}, (15, 20),
   [_d("tech", 6), _notify("all_leads")], [],
   effects=({"kind": "comms_down", "channel": "whatsapp", "n": 10},))
_t("turnstile_failure", F.INFRA, "Tornos averiados", GATES, (4, 6), {"tech": 1, "volunteer": 1}, (20, 30),
   [_d("tech", 8), REROUTE], [NO_CLOSE], escalates_to=("gate_saturation",), phases=("doors", "concerts"))
_t("gas_leak_food", F.INFRA, "Fuga de gas en cocinas", ("food",), (9, 9), {"security": 2, "tech": 1}, (6, 10),
   [_d("security", 3), RESTRICT, EVAC, _ext("fire")], [NO_VOL, NO_DISMISS],
   approval=True, escalates_to=("small_fire",), heldout_only=True)
_t("small_fire", F.INFRA, "Conato de incendio", ("food", "backstage", "toilets"), (8, 9), {"security": 2, "tech": 1}, (6, 10),
   [_d("security", 3), RESTRICT, _ext("fire")], [NO_VOL, NO_DISMISS],
   approval=True, escalates_to=("crowd_surge_general",))

# ---------------------------------------------------------------- resource
_t("ambulance_blocked_by_crowd", F.RESOURCE, "Ambulancia bloqueada por la multitud", ("corridor_s", "general", "gate_b"), (8, 9),
   {"security": 2}, (6, 10),
   [_d("security", 3), RESTRICT, _ext("ambulance")], [NO_VOL], approval=True,
   effects=({"kind": "resource_offline", "resource": "amb_1", "reason": "bloqueada por la multitud"},), density=(3.5, 4.8))
_t("injured_staff", F.RESOURCE, "Personal propio lesionado", PUBLIC, (6, 7), {"medical": 1}, (10, 15),
   [_d("medical", 5), _notify("coordinator")], [],
   effects=({"kind": "resource_offline", "resource": "{sec}", "reason": "lesionado"},))
_t("vehicle_breakdown", F.RESOURCE, "Ambulancia interna averiada", ("corridor_s", "backstage"), (6, 7), {"tech": 1}, (15, 20),
   [_d("tech", 6), _ext("ambulance"), _notify("medical_lead")], [], approval=True,
   effects=({"kind": "resource_offline", "resource": "amb_1", "reason": "avería"},))
_t("medical_team_overwhelmed", F.RESOURCE, "Equipo médico pide refuerzo", PUBLIC, (7, 8), {"medical": 1}, (8, 12),
   [_d("medical", 4), _notify("medical_lead")], [NO_DISMISS], heldout_only=True)
# Estados de los recursos (modo state): {r} es el recurso afectado, {i} el incidente principal.
_t("resource_offline_start", F.RESOURCE, "Un recurso fuera de servicio desde el inicio", (), (4, 4), {}, (0, 0),
   [], ["dispatch {r} while offline"], mode="state")
_t("shift_end_no_relief", F.RESOURCE, "Fin de turno sin relevo", (), (5, 5), {}, (0, 0),
   ["notify coordinator about {r}"], ["dispatch {r} after shift_end"], mode="state")
_t("team_no_answer", F.RESOURCE, "Equipo que no contesta", (), (6, 6), {}, (0, 0),
   ["dispatch alternative to {i} within 4 min after no_answer from {r}", "notify coordinator about {r}"],
   ["wait on {r} beyond 3 min"], mode="state")
_t("team_rejects", F.RESOURCE, "Equipo que rechaza la orden", (), (6, 6), {}, (0, 0),
   ["dispatch alternative to {i} within 3 min after reject from {r}"], ["dispatch {r} again to {i}"], mode="state")
_t("all_busy_higher_priority", F.RESOURCE, "Todo ocupado cuando entra algo más grave", (), (8, 8), {}, (0, 0),
   [RECALL], ["queue {i} behind lower_priority"], mode="state")

# ---------------------------------------------------------------- info
_t("lost_child", F.INFO, "Menor perdido", PUBLIC, (7, 8), {"security": 1, "volunteer": 1}, (15, 20),
   [_notify("security_lead"), _d("security", 4), _notify("gates")], [NO_BROADCAST, NO_DISMISS], sensitive=True)
_t("lost_vulnerable_adult", F.INFO, "Adulto vulnerable desorientado", PUBLIC, (6, 7), {"volunteer": 1, "security": 1}, (20, 30),
   [_d("volunteer", 6), _notify("gates")], [NO_BROADCAST])
_t("rumor_panic", F.INFO, "Bulo que provoca carreras", ("general", "front_pit", "food"), (6, 8), {"security": 2}, (8, 12),
   [BROADCAST, _d("security", 4), _notify("security_lead")], [],
   escalates_to=("crowd_surge_general", "counterflow_exit"))
_t("fake_staff_instructions", F.INFO, "Falso personal dando órdenes de evacuar", ("general", "food") + GATES, (7, 8),
   {"security": 2}, (8, 12),
   [_d("security", 4), BROADCAST, _notify("security_lead")], [], escalates_to=("counterflow_exit",), heldout_only=True)
# Calidad de la información (modo report): {i} es el incidente afectado, {fa} la falsa alarma.
_t("ambiguous_report", F.INFO, "Aviso ambiguo", (), (0, 0), {}, (0, 0), [ASK], ["dispatch to {i} before location known"], mode="report")
_t("duplicate_reports", F.INFO, "Avisos duplicados con detalles distintos", (), (0, 0), {}, (0, 0),
   [MERGE], ["dispatch twice to {i}"], mode="report")
_t("contradictory_reports", F.INFO, "Avisos contradictorios", (), (0, 0), {}, (0, 0),
   ["ask about {i} within 3 min"], [NO_DISMISS], mode="report")
_t("false_alarm_prank", F.INFO, "Broma o falsa alarma", (), (0, 0), {}, (0, 0),
   ["dismiss {i}"], ["dispatch ambulance to {i}", "request_external for {i}"], mode="report")
_t("buried_key_fact", F.INFO, "Dato clave enterrado en el mensaje", (), (0, 0), {}, (0, 0),
   [], ["dismiss {i}"], mode="report")
_t("sensor_glitch", F.INFO, "Lectura de sensor espuria", (), (0, 0), {}, (0, 0),
   ["ask about {i} within 3 min", "dismiss {i}"], ["stop_show for {i}", "dispatch ambulance to {i}"],
   mode="report", heldout_only=True)

# ---------------------------------------------------------------- external
_t("transport_cut_exit", F.EXTERNAL, "Corte de transporte a la salida", ("exit_transport",), (7, 8),
   {"security": 2, "volunteer": 2}, (15, 25),
   [BROADCAST, _ext("transport"), _d("security", 5), REROUTE], [NO_CLOSE],
   approval=True, escalates_to=("counterflow_exit",), phases=("headliner", "egress"),
   effects=({"kind": "transport_cut", "mode": "metro", "n": 40},), density=(2.5, 3.8))
_t("suspicious_object", F.EXTERNAL, "Objeto sospechoso", GATES + ("food", "general", "toilets", "exit_transport"), (9, 9),
   {"security": 2}, (6, 10),
   [_ext("police"), RESTRICT, _d("security", 3), _notify("security_lead")],
   [NO_BROADCAST, NO_VOL, NO_DISMISS, "evacuate {z} without approval"],
   approval=True, escalates_to=("rumor_panic",))
_t("bomb_threat_call", F.EXTERNAL, "Amenaza de bomba por teléfono", ("general", "front_pit") + GATES, (9, 10), {"security": 2}, (6, 10),
   [_ext("police"), _notify("security_lead"), _notify("production")],
   [NO_BROADCAST, NO_DISMISS, "evacuate {z} without approval"],
   approval=True, escalates_to=("rumor_panic",), heldout_only=True, sensitive=True)
_t("artist_delay_cancel", F.EXTERNAL, "Retraso o cancelación del cabeza de cartel", ("front_pit",), (5, 7), {"security": 2}, (12, 18),
   [BROADCAST, _d("security", 6), _notify("production")], [],
   escalates_to=("fight", "crowd_surge_general"), phases=("concerts", "headliner"))
_t("drone_intrusion", F.EXTERNAL, "Dron no autorizado sobre el público", ("front_pit", "general", "backstage"), (5, 6),
   {"security": 1}, (15, 20),
   [_notify("security_lead"), _ext("police")], [NO_BROADCAST], approval=True)
_t("nearby_wildfire_smoke", F.EXTERNAL, "Humo de incendio cercano", ("general",) + GATES, (8, 8), {"security": 1, "medical": 1}, (12, 18),
   [_ext("fire"), BROADCAST, _notify("medical_lead")], [],
   approval=True, heldout_only=True, weather=("heat", "wind"))
_t("road_access_blocked", F.EXTERNAL, "Acceso rodado cortado (ambulancias externas)", ("gate_b", "exit_transport"), (6, 7),
   {"security": 1}, (15, 25),
   [_ext("police"), _notify("medical_lead")], [], approval=True)

TAXONOMY: dict[str, IncidentType] = {t.id: t for t in _T}
SENSITIVE_TYPES: frozenset[str] = frozenset(t.id for t in _T if t.sensitive)
# Fuera del split demo (decisión D4 del consejo): lo sensible y, además, atrapados.
DEMO_EXCLUDED_TYPES: frozenset[str] = SENSITIVE_TYPES | {"crowd_collapse"}
DEMO_FORBIDDEN_WORDS = re.compile(
    r"\b(bomba|bomb|explosivo|navaja|cuchillo|knife|pistola|gun|shooter|tiroteo|arma|weapon|violaci[oó]n|rape|"
    r"agresi[oó]n sexual|sexual|sumisi[oó]n|spiked|atrapad[oa]s?|aplastad[oa]s?|muert[oa]s?|dead)\b", re.IGNORECASE)
assert len(TAXONOMY) == len(_T), "id de tipo repetido"

# ------------------------------------------------------------------ vistas de la taxonomía

INCIDENT_TYPES: tuple[str, ...] = tuple(t.id for t in _T if t.mode == "incident")
STATE_TYPES: tuple[str, ...] = tuple(t.id for t in _T if t.mode == "state")
REPORT_TYPES: tuple[str, ...] = tuple(t.id for t in _T if t.mode == "report")

# Dimensión «calidad de la información» → tipo de la familia info que la representa.
INFO_QUALITIES = ("clean", "ambiguous", "duplicated", "contradictory", "false_alarms", "buried")
INFO_QUALITY_TYPE = {
    "ambiguous": "ambiguous_report", "duplicated": "duplicate_reports",
    "contradictory": "contradictory_reports", "false_alarms": "false_alarm_prank",
    "buried": "buried_key_fact",
}
# Dimensión «estado de los recursos» → tipo de la familia resource que lo representa.
RESOURCE_STATES = ("full", "one_offline", "shift_end", "no_answer", "rejects", "all_busy")
RESOURCE_STATE_TYPE = {
    "one_offline": "resource_offline_start", "shift_end": "shift_end_no_relief",
    "no_answer": "team_no_answer", "rejects": "team_rejects", "all_busy": "all_busy_higher_priority",
}

# Perturbaciones `world` a mitad de caso: las que rompen los supuestos del plan.
PERTURBATIONS = ("none", "resource_offline", "resource_online", "resource_no_answer", "resource_rejects",
                 "zone_closed", "zone_inflow", "zone_flag", "weather_shift", "comms_down",
                 "transport_cut", "second_wave")
WORLD_EFFECTS = ("resource_offline", "resource_online", "resource_no_answer", "resource_rejects", "zone_state",
                 "zone_inflow", "zone_flag", "weather", "comms_down", "incident", "transport_cut")

# Encadenamientos entre tipos compartidos que SOLO aparecen en heldout. Los que tocan un tipo
# `heldout_only` lo son automáticamente.
HELDOUT_ONLY_CHAINS: frozenset[tuple[str, str]] = frozenset({
    ("intoxication_overdose", "cardiac_arrest"),
    ("anaphylaxis", "cardiac_arrest"),
    ("power_outage_food", "fight"),
    ("suspicious_object", "rumor_panic"),
    ("corridor_bottleneck", "ambulance_blocked_by_crowd"),
    ("lighting_failure", "counterflow_exit"),
})

# Parejas de familias que en train NUNCA coinciden en un mismo caso (sí en heldout y en demo).
TRAIN_EXCLUDED_FAMILY_PAIRS: frozenset[frozenset[str]] = frozenset({
    frozenset({"weather", "aggression"}),
    frozenset({"weather", "external"}),
    frozenset({"supply", "external"}),
})


def all_chains() -> list[tuple[str, str]]:
    return [(t.id, b) for t in _T for b in t.escalates_to]


def is_heldout_chain(a: str, b: str) -> bool:
    return (a, b) in HELDOUT_ONLY_CHAINS or TAXONOMY[a].heldout_only or TAXONOMY[b].heldout_only


def _heldout_perturbations(index: int) -> frozenset[str]:
    """Para un tipo compartido, tres perturbaciones (rotando por su índice) quedan reservadas a heldout."""
    p = PERTURBATIONS[1:]
    return frozenset({p[index % len(p)], p[(index + 4) % len(p)], p[(index + 7) % len(p)]})


def allowed_perturbations(type_id: str, split: str) -> frozenset[str]:
    """Perturbaciones con las que el tipo puede aparecer en cada partición. La combinación
    (familia × tipo × perturbación) pertenece a train o a heldout, nunca a las dos."""
    t = TAXONOMY[type_id]
    if split == "demo":
        return frozenset(PERTURBATIONS)
    if t.heldout_only:
        return frozenset(PERTURBATIONS) if split == "heldout" else frozenset()
    held = _heldout_perturbations(INCIDENT_TYPES.index(type_id))
    return held if split == "heldout" else frozenset(PERTURBATIONS) - held


def split_types(split: str) -> list[str]:
    """Tipos de incidente (modo incident) que pueden aparecer en la partición."""
    return [t for t in INCIDENT_TYPES if allowed_perturbations(t, split)]


def combo_universe(split: str) -> set[tuple[str, str, str]]:
    return {(TAXONOMY[t].family.value, t, p) for t in INCIDENT_TYPES for p in allowed_perturbations(t, split)}


def _self_check() -> None:
    for t in _T:
        for z in t.zones:
            assert z in ZONES, (t.id, z)
        for k in t.needs:
            assert k in RESOURCE_KINDS, (t.id, k)
        for b in t.escalates_to:
            assert b in TAXONOMY and TAXONOMY[b].mode == "incident", (t.id, b)
        for w in t.weather:
            assert w in WEATHERS, (t.id, w)
        for p in t.phases:
            assert p in PHASES, (t.id, p)
        for rule in t.must + t.must_not:
            assert rule.split()[0] in RULE_VERBS, (t.id, rule)
        if t.mode == "incident":
            assert t.zones and t.needs and 1 <= t.severity[0] <= t.severity[1] <= 10, t.id
            assert 0 < t.deadline[0] <= t.deadline[1], t.id
    for a, b in HELDOUT_ONLY_CHAINS:
        assert b in TAXONOMY[a].escalates_to, (a, b)


_self_check()
