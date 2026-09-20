"""Tests de Mando con un mundo falso mínimo (no depende de motor/world salvo el test de integración).

    python3 -m unittest motor.mando.test_mando -v
"""
from __future__ import annotations

import copy
import json
import re
import time
import unittest
from pathlib import Path
from typing import Any

from motor.contracts import (ALWAYS_APPROVE, Action, ActionKind, ActionStatus, Autonomy, Channel, IncidentStatus,
                             Observation, Report, Resource, ResourceKind, ResourceStatus, Zone)
from motor.mando import HeuristicParser, LLMParser, Mando, Playbook, report
from motor.mando import autonomy, priority

NO_FESTIVAL = "/no/existe/festival.json"   # fuerza tiempos por saltos: los tests no dependen de motor/world


# ---------------------------------------------------------------------------- mundo falso

def _zones() -> dict[str, Zone]:
    z = [
        Zone("gate_a", "Puerta A", "gate", 600, 1200, 100, neighbors=["corridor_n"]),
        Zone("gate_b", "Puerta B", "gate", 600, 1200, 300, neighbors=["corridor_n"]),
        Zone("gate_c", "Puerta C", "gate", 600, 1200, 200, neighbors=["corridor_n"]),
        Zone("corridor_n", "Pasillo norte", "corridor", 1500, 2500, 500,
             neighbors=["gate_a", "gate_b", "gate_c", "general", "food", "medical_1", "water_n"]),
        Zone("general", "Pista general", "general", 13000, 27000, 9000,
             neighbors=["corridor_n", "front_pit", "food", "toilets", "pmr"]),
        Zone("front_pit", "Frente de escenario", "stage_front", 2500, 10000, 5000, neighbors=["general"]),
        Zone("food", "Restauración", "food", 3000, 4500, 1500, neighbors=["general", "corridor_n", "toilets"]),
        Zone("toilets", "Baños", "toilets", 800, 800, 200, neighbors=["general", "food"]),
        Zone("pmr", "Plataforma PMR", "pmr", 200, 150, 40, neighbors=["general"]),
        Zone("medical_1", "Puesto médico 1", "medical", 150, 30, 5, neighbors=["corridor_n"]),
        Zone("water_n", "Punto de agua norte", "water", 300, 400, 100, neighbors=["corridor_n"],
             flags={"water_l": 900}),
    ]
    return {x.id: x for x in z}


def real_zones() -> dict[str, Zone]:
    """Zonas con los nombres del recinto de verdad (`motor/world/festival.json`) si está; si no, las del mundo falso."""
    try:
        data = json.loads((Path(__file__).parent.parent / "world" / "festival.json").read_text(encoding="utf-8"))
    except OSError:
        return _zones()
    near: dict[str, list[str]] = {}
    for e in data.get("edges", []):
        near.setdefault(e["a"], []).append(e["b"])
        near.setdefault(e["b"], []).append(e["a"])
    return {z["id"]: Zone(z["id"], z["name"], z["kind"], z["area_m2"], z["capacity"], 0, "open", near.get(z["id"], []),
                          dict(z.get("flags", {}))) for z in data["zones"]}


def _resources(kinds: dict[str, tuple[ResourceKind, str]]) -> dict[str, Resource]:
    return {rid: Resource(rid, kind, rid.replace("_", " ").title(), zone, contact="+34 600 000 000")
            for rid, (kind, zone) in kinds.items()}


FULL_TEAM = {
    "sec_1": (ResourceKind.SECURITY, "gate_a"), "sec_2": (ResourceKind.SECURITY, "gate_b"),
    "sec_3": (ResourceKind.SECURITY, "front_pit"), "med_1": (ResourceKind.MEDICAL, "medical_1"),
    "med_2": (ResourceKind.MEDICAL, "general"), "amb_1": (ResourceKind.AMBULANCE, "medical_1"),
    "tech_1": (ResourceKind.TECH, "food"), "log_1": (ResourceKind.LOGISTICS, "corridor_n"),
    "vol_1": (ResourceKind.VOLUNTEER, "water_n"),
}


class FakeWorld:
    """Lo justo de `WorldAPI` para ejercitar a Mando: muta las acciones en el sitio, como el simulador real."""

    def __init__(self, team: dict | None = None, service_min: int = 30) -> None:
        self.t = 0
        self.zones = _zones()
        self.resources = _resources(team or FULL_TEAM)
        self.weather: dict[str, Any] = {"temp_c": 28, "wind_kmh": 10}
        self.rejects: set[str] = set()
        self.voice_down = False
        self.service_min = service_min
        self._reports: list[Report] = []
        self._results: list[Action] = []
        self._jobs: dict[str, dict] = {}
        self._n = 0
        # flujo mínimo para poder ENSAYAR: solo se mueve si `dynamic` (los tests antiguos usan ocupaciones fijas)
        self.dynamic = False
        self.inflow: dict[str, int] = {}                      # llegadas por minuto a una zona
        self.reroutes: dict[str, tuple[str, float]] = {}      # origen -> (destino, fracción)
        self.discharge = 60                                   # personas/min que una puerta mete en el recinto
        self.show_stopped = False

    def twin(self) -> "FakeWorld":
        """Doble de `World.twin()`: copia del estado de ahora, sin avisos pendientes ni futuro."""
        tw = copy.deepcopy(self)
        tw._reports, tw._results = [], []
        return tw

    def report(self, text: str, channel: Channel = Channel.WHATSAPP, source: str = "asistente",
               zone_hint: str | None = None) -> Report:
        self._n += 1
        r = Report(f"r{self._n}", self.t, channel, text, source, zone_hint=zone_hint)
        self._reports.append(r)
        return r

    def observe(self) -> Observation:
        obs = Observation(self.t, self.zones, self.resources, self._reports, self._results, self.weather,
                          {"day": 2, "hhmm": "21:30", "show_phase": "concerts"})
        self._reports, self._results = [], []
        return obs

    def apply(self, a: Action) -> Action:
        if a.status in (ActionStatus.AWAITING_APPROVAL, ActionStatus.DONE, ActionStatus.CANCELLED):
            return a
        r = self.resources.get(a.resource or "")
        if a.kind in (ActionKind.DISPATCH, ActionKind.RESUPPLY):
            if a.channel == Channel.VOICE and self.voice_down:
                a.status, a.params["error"] = ActionStatus.FAILED, "comms_down"
            elif r is None or r.status == ResourceStatus.OFFLINE:
                a.status, a.params["error"] = ActionStatus.FAILED, "resource_offline"
            elif r.id in self.rejects:
                a.status, a.params["error"] = ActionStatus.REJECTED, "rejected"
            elif r.status != ResourceStatus.AVAILABLE:
                a.status, a.params["error"] = ActionStatus.FAILED, "resource_busy"
            else:
                r.status, r.task, r.eta = ResourceStatus.EN_ROUTE, a.incident, 2
                self._jobs[r.id] = {"action": a, "arrive": self.t + 2}
                a.status = ActionStatus.EXECUTING
        elif a.kind == ActionKind.RECALL and r is not None:
            job = self._jobs.pop(r.id, None)
            if job and job["action"].status == ActionStatus.EXECUTING:
                job["action"].status, job["action"].params["error"] = ActionStatus.CANCELLED, "recalled"
                self._results.append(job["action"])
            r.status, r.task, r.eta = ResourceStatus.AVAILABLE, None, 0
            a.status = ActionStatus.DONE
        elif a.kind == ActionKind.SET_ZONE and a.zone in self.zones:
            self.zones[a.zone].state = a.params["state"]
            a.status = ActionStatus.DONE
        elif a.kind == ActionKind.REROUTE and a.zone in self.zones:
            if a.params.get("cancel"):
                self.reroutes.pop(a.zone, None)
            else:
                self.reroutes[a.zone] = (a.params["to"], float(a.params.get("fraction", 0.6)))
            a.status = ActionStatus.DONE
        elif a.kind == ActionKind.STOP_SHOW:
            self.show_stopped = True
            a.status = ActionStatus.DONE
        else:
            a.status = ActionStatus.DONE
        self._results.append(a)
        return a

    def step(self) -> None:
        self.t += 1
        if self.dynamic:
            for zid, n in self.inflow.items():
                z = self.zones[zid]
                n = int(n * {"open": 1.0, "restricted": 0.4, "closed": 0.0}[z.state] * (0.4 if self.show_stopped else 1.0))
                dst, frac = self.reroutes.get(zid, (None, 0.0))
                moved = int(n * frac) if dst else 0
                z.occupancy += n - moved
                if dst:
                    self.zones[dst].occupancy += moved
            for z in self.zones.values():
                if z.kind == "gate":
                    z.occupancy = max(0, z.occupancy - self.discharge)
        for rid, job in list(self._jobs.items()):
            r, a = self.resources[rid], job["action"]
            if r.status == ResourceStatus.EN_ROUTE and self.t >= job["arrive"]:
                r.status, r.zone, r.eta = ResourceStatus.BUSY, a.zone or r.zone, 0
                a.status, a.params["outcome"] = ActionStatus.DONE, "on_scene"
                self._results.append(a)
            elif r.status == ResourceStatus.BUSY and self.t >= job["arrive"] + self.service_min:
                r.status, r.task = ResourceStatus.AVAILABLE, None
                del self._jobs[rid]


class FakeComms:
    """`CommsAPI` con guion: qué contesta cada recurso y qué se responde a cada pregunta."""

    def __init__(self) -> None:
        self.sent: list[Action] = []
        self.script: dict[str, str] = {}      # recurso -> accept | reject | no_answer
        self.answers: list[str] = []          # respuestas a los ASK, en orden
        self._pending: list[dict] = []

    def send(self, action: Action, resource: Resource | None) -> None:
        self.sent.append(action)
        if action.kind == ActionKind.ASK:
            if self.answers:
                self._pending.append({"action_id": action.id, "result": "answer", "text": self.answers.pop(0)})
        elif resource is not None:
            self._pending.append({"action_id": action.id, "result": self.script.get(resource.id, "accept"),
                                  "text": ""})

    def poll(self, t: int) -> list[dict]:
        out, self._pending = self._pending, []
        return out


def run(world: FakeWorld, mando: Mando, ticks: int = 1) -> list[Action]:
    """El ciclo de INTERFACES.md. Devuelve todas las acciones emitidas en esos ticks."""
    out = []
    for _ in range(ticks):
        for a in mando.tick(world.observe()):
            out.append(a)
            if a.status != ActionStatus.AWAITING_APPROVAL:
                world.apply(a)
        world.step()
    return out


def new(team: dict | None = None, **kw: Any) -> tuple[FakeWorld, Mando]:
    return FakeWorld(team), Mando(festival=NO_FESTIVAL, **kw)


def kinds(actions: list[Action], kind: ActionKind) -> list[Action]:
    return [a for a in actions if a.kind == kind]


def log_text(mando: Mando, kind: str | None = None) -> str:
    return "\n".join(e.text for e in mando.log if kind is None or e.kind == kind)


# ---------------------------------------------------------------------------- tests pedidos (a)–(j)

class TestTriage(unittest.TestCase):
    def test_a_ten_reports_one_dispatch(self):
        w, m = new()
        texts = ["Un chico se ha desmayado en la barra", "hay alguien desmayado en la zona de comida!!",
                 "se ha desmayado una persona junto a los food trucks", "DESMAYO EN LA BARRA 😱😱",
                 "someone fainted at the food court", "chico desmallado en la barra, venid",
                 "en restauración hay un desmayado", "un tio se ha desvanecido en la barra",
                 "desmayo zona de comida", "sigue el chico desmayado en la barra"]
        # Los avisos posteriores identifican explícitamente a la víctima; similitud y zona no son identidad.
        texts = [texts[0]] + [text + ". Es la misma persona del incidente M-001." for text in texts[1:]]
        actions = []
        for i in range(5):
            w.report(texts[2 * i])
            w.report(texts[2 * i + 1])
            actions += run(w, m)
        actions += run(w, m, 3)
        self.assertEqual(len(kinds(actions, ActionKind.DISPATCH)), 1, "diez avisos del mismo incidente, un equipo")
        self.assertEqual(len(m.incidents), 1)
        self.assertEqual(m.counters["merges"], 9)
        self.assertEqual(len(kinds(actions, ActionKind.MERGE)), 9)
        inc = next(iter(m.incidents.values()))
        self.assertEqual(inc.zone, "food")
        self.assertEqual(len(inc.reports), 10)
        self.assertGreater(inc.confidence, 0.9, "cada aviso independiente sube la confianza")

    def test_b_missing_zone_asks_first(self):
        comms = FakeComms()
        comms.answers = ["Estamos en la barra, al lado de los food trucks"]
        w, m = new(comms=comms)
        w.report("hay un chico herido sangrando mucho, venid rapido por favor")
        first = run(w, m)
        self.assertEqual([a.kind for a in first], [ActionKind.ASK], "sin zona, lo primero es preguntar")
        self.assertIn("zona", first[0].why)
        later = run(w, m, 2)
        dispatches = kinds(later, ActionKind.DISPATCH)
        self.assertEqual(len(dispatches), 1, "con la zona ya conocida, se despacha")
        self.assertEqual(dispatches[0].zone, "food")
        plans = list(m.plans.values())
        self.assertEqual(plans[1].supersedes, plans[0].id)

    def test_c_possible_cardiac_arrest_dispatches_at_once(self):
        w, m = new()
        w.report("creo que no respira!! un señor en el foso", Channel.WHATSAPP)
        actions = run(w, m)
        inc = next(iter(m.incidents.values()))
        self.assertLess(inc.confidence, 0.5, "el caso es de confianza baja")
        d = kinds(actions, ActionKind.DISPATCH)
        self.assertTrue(d, "riesgo vital: se despacha en el mismo tick")
        self.assertTrue(all(a.autonomy == Autonomy.AUTO and a.status != ActionStatus.AWAITING_APPROVAL for a in d))
        self.assertEqual(w.resources[d[0].resource].kind, ResourceKind.MEDICAL)
        self.assertFalse([a for a in d if w.resources[a.resource].kind == ResourceKind.AMBULANCE],
                         "la ambulancia espera a la confirmación")
        self.assertTrue(kinds(actions, ActionKind.ASK), "y se confirma mientras el equipo va de camino")
        self.assertGreaterEqual(inc.priority, 9.0)

    def test_h_three_heat_strokes_trigger_water(self):
        w, m = new()
        actions = []
        for text in ["golpe de calor en la pista, chica muy mareada", "otro golpe de calor, ahora en el foso",
                     "señor mayor con golpe de calor en la barra"]:
            w.report(text, Channel.RADIO, source=f"sanitario {len(actions)}")
            actions += run(w, m, 2)
        self.assertEqual(m.counters["patterns"], 1)
        resupply = kinds(actions, ActionKind.RESUPPLY)
        self.assertEqual(len(resupply), 1, "tres golpes de calor → reabastecer agua")
        self.assertEqual(resupply[0].zone, "water_n")
        self.assertTrue(kinds(actions, ActionKind.BROADCAST))
        self.assertTrue([a for a in kinds(actions, ActionKind.NOTIFY) if a.params.get("to") == "medical_lead"])
        self.assertIn("PATRÓN", log_text(m, "incident"))

    def test_contradiction_asks_and_false_alarm_dismisses(self):
        comms = FakeComms()
        comms.answers = ["Falsa alarma, aquí no pasa nada"]
        w, m = new(comms=comms)
        w.report("hay una pelea en los baños", Channel.WHATSAPP)
        w.report("en los baños no hay ninguna pelea, todo tranquilo", Channel.SMS)
        actions = run(w, m, 3)
        self.assertTrue(kinds(actions, ActionKind.ASK))
        self.assertTrue(kinds(actions, ActionKind.DISMISS))
        self.assertEqual(m.counters["false_alarms"], 1)


class TestAutonomy(unittest.TestCase):
    def test_d_evacuate_and_stop_show_always_wait(self):
        for kind in ALWAYS_APPROVE | {ActionKind.SET_ZONE}:
            a = autonomy.gate(Action("x", kind, 0, params={"state": "closed"}, why="porque sí"))
            self.assertEqual((a.autonomy, a.status), (Autonomy.APPROVE, ActionStatus.AWAITING_APPROVAL), kind)
        self.assertEqual(autonomy.gate(Action("y", ActionKind.SET_ZONE, 0, params={"state": "restricted"})).autonomy,
                         Autonomy.AUTO)

        w, m = new()
        w.zones["front_pit"].occupancy = 16500     # 6,6/m²
        w.report("nos están aplastando contra la valla en las primeras filas!!", Channel.RADIO, "jefe seguridad 3")
        w.report("mochila abandonada sospechosa en la puerta C", Channel.VOICE, "jefe seguridad 1")
        actions = run(w, m, 2)
        stop, evac = kinds(actions, ActionKind.STOP_SHOW), kinds(actions, ActionKind.EVACUATE)
        self.assertTrue(stop and evac)
        for a in actions:
            if a.kind in ALWAYS_APPROVE:
                self.assertEqual(a.status, ActionStatus.AWAITING_APPROVAL, a.kind)
        self.assertTrue(evac[0].params.get("prepared"), "ante una amenaza la evacuación se prepara, no se ejecuta")
        self.assertFalse([a for a in kinds(actions, ActionKind.BROADCAST) if a.zone == "gate_c"], "sin megafonía en una amenaza")
        self.assertTrue([a for a in kinds(actions, ActionKind.NOTIFY) if a.params.get("escalate")])

        m.approve(stop[0].id, True, "adelante")
        nxt = run(w, m)
        self.assertIn(stop[0].id, [a.id for a in nxt], "lo aprobado sale en el siguiente tick")
        self.assertEqual(stop[0].status, ActionStatus.DONE)

        m.approve(evac[0].id, False, "la policía dice que es de un técnico")
        run(w, m)
        self.assertEqual(evac[0].status, ActionStatus.REJECTED)
        self.assertEqual(len(m.lesson_candidates), 1)
        self.assertEqual(m.lesson_candidates[0]["source"], "veto del operador")
        self.assertIn("vetó", log_text(m, "plan"), "tras el veto hay plan nuevo con la alternativa")


class TestPlans(unittest.TestCase):
    def _saturate_gate_b(self, **kw):
        w, m = new(**kw)
        w.zones["gate_b"].occupancy = 1150
        w.report("La puerta B está atascada, no avanza y sigue llegando gente", Channel.VOICE, "jefe seguridad 2",
                 zone_hint="gate_b")
        return w, m, run(w, m)

    def test_e_broken_assumption_replans_without_gate_a(self):
        w, m, actions = self._saturate_gate_b()
        reroute = kinds(actions, ActionKind.REROUTE)
        self.assertEqual([(a.zone, a.params["to"]) for a in reroute], [("gate_b", "gate_a")])
        first = next(iter(m.plans.values()))
        watched = [s for s in first.assumptions if s.check.get("zone") == "gate_a"]
        self.assertTrue(watched, "el supuesto sobre gate_a queda escrito aunque la proyección diga que cabe")
        run(w, m, 2)
        self.assertIsNone(first.invalidated_by)

        w.zones["gate_a"].occupancy = 1100           # la proyección falló
        actions = run(w, m)
        self.assertEqual(first.invalidated_by, watched[0].id)
        self.assertFalse(watched[0].holds)
        self.assertEqual(watched[0].broken_at, w.t - 1)
        second = [p for p in m.plans.values() if p.supersedes == first.id]
        self.assertEqual(len(second), 1)
        self.assertIn("Puerta A", second[0].why, "el porqué del plan nuevo nombra el supuesto roto")
        steps = [m.actions[s] for s in second[0].steps]
        self.assertFalse([a for a in steps if "gate_a" in (a.zone, a.params.get("to"))], "el plan nuevo no usa gate_a")
        self.assertEqual([a.params["to"] for a in steps if a.kind == ActionKind.REROUTE], ["gate_c"])
        self.assertFalse([s for s in second[0].assumptions if s.check.get("zone") == "gate_a"])
        text = log_text(m)
        self.assertIn("SUPUESTO ROTO", text)
        self.assertIn("SUSTITUYE", text)
        self.assertIn("nuestro propio desvío", text)
        snap = m.snapshot()
        self.assertEqual(snap["counters"]["replans"], 1)
        self.assertEqual([p["live"] for p in snap["plans"]], [False, True])

    def test_f_recall_from_lowest_priority(self):
        team = {"med_1": (ResourceKind.MEDICAL, "medical_1"), "med_2": (ResourceKind.MEDICAL, "general"),
                "sec_1": (ResourceKind.SECURITY, "gate_a")}
        w, m = new(team)
        w.report("esguince de tobillo en la barra, nada grave", Channel.RADIO, "voluntarios 2")
        w.report("una chica con un corte en la mano en los baños, sangra bastante", Channel.RADIO, "jefe seguridad 4")
        run(w, m, 3)
        self.assertEqual({r.status for r in w.resources.values() if r.kind == ResourceKind.MEDICAL},
                         {ResourceStatus.BUSY})
        minor = min(m.incidents.values(), key=lambda i: i.priority)
        w.report("varón en parada cardiaca en la plataforma PMR, no respira, iniciamos RCP", Channel.RADIO, "jefe seguridad 3")
        actions = run(w, m)
        recall = kinds(actions, ActionKind.RECALL)
        self.assertEqual(len(recall), 1)
        self.assertEqual(recall[0].params["from_incident"], minor.id, "se le quita al de MENOR prioridad")
        dispatch = kinds(actions, ActionKind.DISPATCH)
        self.assertEqual([a.resource for a in dispatch], [recall[0].resource])
        self.assertEqual(dispatch[0].zone, "pmr")
        self.assertEqual(dispatch[0].status, ActionStatus.EXECUTING, "y no espera aprobación")
        self.assertIn("prioridad", recall[0].why)
        self.assertEqual(minor.status, IncidentStatus.OPEN)
        self.assertEqual(m.counters["recalls"], 1)
        run(w, m, 4)
        self.assertEqual(m.counters["recalls"], 1, "no oscila: el margen y el enfriamiento lo impiden")

    def test_g_reject_goes_to_next_resource(self):
        w, m = new()
        w.rejects.add("med_2")
        w.report("chico inconsciente en la pista, no reacciona", Channel.RADIO, "jefe seguridad 4")
        actions = run(w, m, 3)
        d = kinds(actions, ActionKind.DISPATCH)
        self.assertEqual([a.resource for a in d], ["med_2", "med_1"], "rechaza el más cercano → va el siguiente")
        self.assertEqual(d[0].status, ActionStatus.REJECTED)
        self.assertIn("rechaza", log_text(m, "outcome"))
        self.assertTrue([a for a in kinds(actions, ActionKind.NOTIFY) if a.params.get("to") == "coordinator"])
        run(w, m, 5)
        self.assertEqual(len([a for a in m.actions.values() if a.kind == ActionKind.DISPATCH and a.resource == "med_2"]), 1,
                         "al que rechazó no se le vuelve a mandar al mismo incidente")

    def test_g2_no_answer_by_phone_and_voice_down(self):
        comms = FakeComms()
        comms.script["med_2"] = "no_answer"
        w, m = new(comms=comms)
        w.report("chico inconsciente en la pista, no reacciona", Channel.RADIO, "jefe seguridad 4")
        actions = run(w, m, 3)
        self.assertEqual([a.resource for a in kinds(actions, ActionKind.DISPATCH)], ["med_2", "med_1"])
        self.assertEqual([a.resource for a in kinds(actions, ActionKind.RECALL)], ["med_2"])

        w, m = new()
        w.voice_down = True
        w.report("carterista robando móviles en la puerta A", Channel.RADIO, "jefe seguridad 1")
        d = kinds(run(w, m, 3), ActionKind.DISPATCH)
        self.assertEqual([(a.resource, a.channel) for a in d[:2]], [("sec_1", Channel.VOICE), ("sec_1", Channel.SMS)])
        self.assertEqual(d[1].params["message"], d[0].params["message"], "voz caída → el MISMO mensaje por SMS")

    def test_i_lesson_changes_a_decision(self):
        book = Playbook([{"id": "L-900", "text": "la puerta A se satura sola a esta hora",
                          "when": {"type": "gate_saturation", "zone": "gate_b"},
                          "then": {"forbid_action": {"kind": "reroute", "to": "gate_a"}, "priority_boost": 1.0},
                          "source": "run c-000123", "evidence_n": 12}])
        _, plain, base = self._saturate_gate_b()
        _, m, actions = self._saturate_gate_b(playbook=book)
        self.assertEqual([a.params["to"] for a in kinds(base, ActionKind.REROUTE)], ["gate_a"])
        self.assertEqual([a.params["to"] for a in kinds(actions, ActionKind.REROUTE)], ["gate_c"])
        lessons = log_text(m, "lesson")
        self.assertIn("Lección L-900 aplicada", lessons)
        self.assertIn("no se desvía hacia Puerta A", lessons)
        boosted, normal = next(iter(m.incidents.values())), next(iter(plain.incidents.values()))
        self.assertAlmostEqual(boosted.priority, min(10.0, normal.priority + 1.0), places=1)
        self.assertEqual(m.snapshot()["lessons"]["applied"], {"L-900": 2})

    def test_j_deterministic(self):
        def scenario() -> str:
            comms = FakeComms()
            comms.answers = ["en la barra", "no pasa nada"]
            w, m = new(comms=comms)
            w.rejects.add("sec_2")
            w.zones["gate_b"].occupancy = 1150
            w.report("La puerta B está atascada", Channel.VOICE, "jefe seguridad 2", zone_hint="gate_b")
            w.report("hay un herido, venid", Channel.SMS)
            run(w, m, 3)
            w.zones["gate_a"].occupancy = 1100
            w.report("creo que hay humo en los baños", Channel.SMS)
            w.report("no respira!! en el foso", Channel.WHATSAPP)
            run(w, m, 6)
            return json.dumps(m.snapshot(), sort_keys=True, ensure_ascii=False)
        first = scenario()
        self.assertEqual(first, scenario())
        self.assertGreater(len(first), 2000)


# ---------------------------------------------------------------------------- piezas sueltas

class TestParser(unittest.TestCase):
    def setUp(self):
        self.p, self.z = HeuristicParser(), _zones()

    def parse(self, text, channel=Channel.WHATSAPP, **kw):
        return self.p.parse(Report("r", 0, channel, text, **kw), self.z)

    def test_negation(self):
        self.assertEqual(self.parse("NO RESPIRA!!! ayuda")["type"], "cardiac_arrest")
        ok = self.parse("ya respira y está consciente, en la barra")
        self.assertTrue(ok["vitals_ok"])
        self.assertNotEqual(ok["type"], "cardiac_arrest")
        clear = self.parse("no hay fuego en la barra, falsa alarma")
        self.assertTrue(clear["all_clear"])
        self.assertIn("fire", clear["negated"])

    def test_zone_aliases(self):
        for text, zone in [("pelea en la puerta B", "gate_b"), ("fight at gate b", "gate_b"),
                           ("agobio en el foso", "front_pit"), ("desmayo en primeras filas", "front_pit"),
                           ("robo en la barra", "food"), ("herido en la zona de comida", "food"),
                           ("bagarre à la porte C", "gate_c"), ("pelea en los aseos", "toilets")]:
            self.assertEqual(self.parse(text)["zone"], zone, text)
        self.assertIsNone(self.parse("a la entrada a la pista hay una pelea")["zone"] == "gate_a" or None)
        self.assertIn("zone", self.parse("hay una pelea, venid")["missing"])

    def test_typos_emojis_quantities_languages(self):
        self.assertEqual(self.parse("chica incosciente 😱😱 en la BARRAAAA")["type"], "unconscious_person")
        self.assertEqual(self.parse("tres personas con golpe de calor en la pista")["count"], 3)
        self.assertEqual(self.parse("there is a fight near the food trucks")["type"], "fight")
        self.assertEqual(self.parse("il ne respire pas, devant la scène")["type"], "cardiac_arrest")
        self.assertEqual(self.parse("er ist bewusstlos am gate a")["zone"], "gate_a")

    def test_sensor_readings(self):
        s = self.parse("Contador de aforo Puerta B: 1300 personas (2.2/m²), capacidad 1200.", Channel.SENSOR,
                       source="contador gate_b", zone_hint="gate_b")
        self.assertEqual((s["type"], s["zone"]), ("gate_saturation", "gate_b"))
        self.assertGreater(s["confidence"], 0.9)
        self.assertEqual(s["needs"], {}, "una lectura de aforo pide gestión de flujo, no un equipo")
        self.assertEqual(self.parse("aforo front_pit: densidad 6,8 p/m²", Channel.SENSOR)["type"], "crush_risk")
        self.assertTrue(self.parse("contador gate_a: 300/1200", Channel.SENSOR)["informational"])
        self.assertEqual(self.parse("estación meteo: viento 74 km/h", Channel.SENSOR)["type"], "high_wind")

    def test_llm_parser_is_pluggable(self):
        with self.assertRaises(NotImplementedError):
            LLMParser().parse(Report("r", 0, Channel.SMS, "hola"), self.z)
        fake = lambda prompt: '{"type": "fight", "family": "aggression", "zone": "food", "severity": 6, "confidence": 0.8}'
        out = LLMParser(client=fake).parse(Report("r", 0, Channel.SMS, "se pegan en la barra"), self.z)
        self.assertEqual((out["type"], out["zone"], out["needs"]), ("fight", "food", {"security": 2}))
        from motor.mando import CascadeParser
        calls = []
        llm = LLMParser(client=lambda prompt: calls.append(1) or '{"type": "algo_nuevo", "family": "infra", "zone": null, "severity": 6}')
        cascade = CascadeParser(self.p, llm)
        self.assertEqual(cascade.parse(Report("r", 0, Channel.SMS, "pelea en la barra"), self.z)["type"], "fight")
        self.assertFalse(calls, "lo que las reglas reconocen no pasa por el modelo")
        odd = cascade.parse(Report("r", 0, Channel.SMS, "en la barra hay una cosa rarísima con una máquina"), self.z)
        self.assertEqual((odd["type"], str(odd["family"]), odd["zone"], len(calls)), ("algo_nuevo", "infra", "food", 1))
        self.assertTrue(CascadeParser(self.p).parse(Report("r", 0, Channel.SMS, "una cosa rarísima"), self.z)["generic"])
        broken = LLMParser(client=lambda p: "no es json", fallback=self.p)
        self.assertEqual(broken.parse(Report("r", 0, Channel.SMS, "pelea en la barra"), self.z)["type"], "fight")


HELDOUT_ONLY = {  # lista que dio el coordinador; si `motor.cases` está, se contrasta con su taxonomía
    "crowd_collapse", "stage_invasion", "diabetic_emergency", "mass_food_poisoning", "hail_shelter_rush", "hate_incident",
    "ice_cooling_out", "gas_leak_food", "medical_team_overwhelmed", "fake_staff_instructions", "sensor_glitch",
    "bomb_threat_call", "nearby_wildfire_smoke"}


class TestColloquialReports(unittest.TestCase):
    """Frases propias; síntomas y contexto, sin reproducir el corpus sintético."""

    def setUp(self):
        self.parser, self.zones = HeuristicParser(), real_zones()

    def parse(self, text):
        return self.parser.parse(Report("r", 0, Channel.WHATSAPP, text), self.zones)

    def test_medical_slang_and_symptoms(self):
        for text in ("Mi colega va drogado y está fatal junto a la barra grande",
                     "Una señora diabética tiembla en la primera fila",
                     "My brother has a fever by the main entrance"):
            with self.subTest(text=text):
                self.assertEqual(self.parse(text)["family"], "medical")
        p = self.parse("Tengo el brazo hinchao y no sé qué ocurre")
        self.assertEqual(p["type"], "unknown_medical")
        self.assertIsNone(p["zone"])
        self.assertIn("type", p["missing"])

    def test_person_falling_is_not_a_structure(self):
        p = self.parse("Mi hermana está deshidratada y se cae junto a los wc")
        self.assertEqual((p["family"], p["zone"]), ("medical", "toilets"))
        self.assertEqual(self.parse("Una señora se ha caído de la valla y está herida")["family"], "medical")

    def test_violence_vocabulary(self):
        for text in ("Roban carteras cerca de la entrada principal",
                     "Están dando una paliza detrás de la barra pequeña",
                     "Someone is groping my friend near the toilets",
                     "Han apuñalado a una señora en la primera fila"):
            with self.subTest(text=text):
                self.assertEqual(self.parse(text)["family"], "aggression")

    def test_crowd_slang_and_falling_people(self):
        for text in ("El acceso al foso está petado, menudo cuello de botella",
                     "Se cae gente junto a la barra y los de atrás siguen entrando"):
            with self.subTest(text=text):
                self.assertEqual(self.parse(text)["family"], "crowd")

    def test_object_description_can_separate_noun_and_warning(self):
        for text in ("Una maleta roja junto a la puerta C lleva horas sin dueño",
                     "A suitcase near the bar looks weird and nobody claims it"):
            with self.subTest(text=text):
                p = self.parse(text)
                self.assertEqual(p["family"], "external")
                self.assertTrue(p["threat"])
                self.assertTrue(p["reserved"])
        self.assertNotEqual(self.parse("La maleta roja es mía, estoy en la cola")["family"], "external")

    def test_electrical_and_fire_vocabulary(self):
        for text in ("Saltan chispas de un enchufe junto a la puerta B",
                     "Sparks over the bar, please send someone",
                     "Avisan de un conato junto a la fuente norte"):
            with self.subTest(text=text):
                p = self.parse(text)
                self.assertEqual(p["family"], "infra")
                self.assertFalse(p["all_clear"])
        self.assertTrue(self.parse("No hay chispas aquí, está comprobado")["all_clear"])

    def test_structure_damage_requires_an_object(self):
        for text in ("El soporte de la pantalla parece doblado",
                     "Hay riesgo de caída en una estructura junto a la entrada",
                     "La valla de la zona vip está caída",
                     "La rampa de acceso está suelta, revisadla",
                     "Se ha soltado parte del vallado junto a los aseos"):
            with self.subTest(text=text):
                self.assertEqual(self.parse(text)["family"], "infra")

    def test_plumbing_and_sound_failures(self):
        for text in ("Una tubería reventada vierte agua sobre el camino",
                     "El sonido peta constantemente junto a la pista",
                     "El sonido ha petado durante el ensayo",
                     "Los aseos están inundados, hay un atasco"):
            with self.subTest(text=text):
                self.assertEqual(self.parse(text)["family"], "infra")
        self.assertEqual(self.parse("Voy a los wc a buscar a mi colega")["family"], "info")
        self.assertEqual(self.parse("Los baños están atascados y nos están aplastando")["family"], "crowd")

    def test_shortage_vocabulary_and_context(self):
        for text in ("No nos queda comida en esta cola de la barra",
                     "En el botiquín norte ya no hay vendas",
                     "No hay jabón junto a los lavabos",
                     "El generador está sin combustible desde antes del concierto",
                     "Sold out of sandwiches at the food court"):
            with self.subTest(text=text):
                self.assertEqual(self.parse(text)["family"], "supply")

    def test_explicit_staff_shortage_not_medical_location(self):
        for text in ("No hay sanitarios en el puesto médico norte",
                     "No medics available at the main gate",
                     "We need more stewards near the north corridor",
                     "Sin voluntarios en la entrada principal, pedid refuerzos"):
            with self.subTest(text=text):
                self.assertEqual(self.parse(text)["family"], "resource")
        self.assertEqual(self.parse("Necesitamos sanitarios, una señora no respira")["family"], "medical")

    def test_wind_and_flood_vocabulary(self):
        for text in ("Las sombrillas de la barra salen volando",
                     "Flooding beside the wheelchair platform",
                     "Está granizando sobre la puerta A"):
            with self.subTest(text=text):
                self.assertEqual(self.parse(text)["family"], "weather")

    def test_explicit_locations_and_no_invented_zone(self):
        for text, zone in (("Ayuda en puerta b, el acceso está petado", "gate_b"),
                           ("Help at the south med tent", "medical_1"),
                           ("Auxilio junto a los bares", "food"),
                           ("Falta agua en el north refill", "water_n"),
                           ("Viento en puerta c, venid", "gate_c"),
                           ("Algo ocurre aquí, no sé dónde estoy", None)):
            with self.subTest(text=text):
                self.assertEqual(self.parse(text)["zone"], zone)


class TestNoHeldoutLeak(unittest.TestCase):
    """El código de Mando no puede conocer la partición que «nunca ha visto». Este test sí puede leer `motor.cases`."""

    def setUp(self):
        self.heldout = set(HELDOUT_ONLY)
        try:
            from motor.cases.taxonomy import TAXONOMY
            self.heldout |= {t for t, spec in TAXONOMY.items() if spec.heldout_only}
        except Exception:
            pass
        self.sources = {p.name: p.read_text(encoding="utf-8") for p in Path(__file__).parent.glob("*")
                        if p.suffix in (".py", ".json") and not p.name.startswith("test_")}

    def test_lexicon_has_no_heldout_only_types(self):
        from motor.mando import lexicon, planner
        leaked = self.heldout & (set(lexicon.TYPES) | set(planner.LABEL))
        self.assertFalse(leaked, f"tipos solo-heldout en el léxico: {sorted(leaked)}")

    def test_sources_never_mention_heldout_ids_nor_import_cases(self):
        for name, text in self.sources.items():
            self.assertNotRegex(text, r"(from|import)\s+motor\.cases|from\s+\.\.cases|motor/cases/(phrasing|taxonomy|data)",
                                f"{name} no puede leer ni importar motor/cases")
            hit = [t for t in self.heldout if re.search(rf"\b{t}\b", text)]
            self.assertFalse(hit, f"{name} menciona tipos solo-heldout: {hit}")

    def test_lexicon_does_not_copy_heldout_templates(self):
        """Ningún patrón literal de 4 o más palabras del léxico aparece tal cual en las plantillas solo-heldout.
        (Con 3 palabras salta «se ha caido», que es castellano corriente y ya estaba antes de ver ninguna plantilla.)"""
        try:
            from motor.cases.phrasing import CORE
        except Exception:
            self.skipTest("motor.cases.phrasing no disponible")
        from motor.mando import lexicon
        from motor.mando.parser import normalize
        templates = " | ".join(normalize(t) for type_, voices in CORE.items() if type_ in self.heldout
                               for phrases in voices.values() for t in phrases)
        literals = [p for s_ in lexicon.SPECS for p in s_.patterns
                    if len(p.split()) >= 4 and not re.search(r"[\\\[\](){}|?*+.^$]", p)]
        copied = [p for p in literals if p in templates]
        self.assertFalse(copied, f"patrones calcados de plantillas solo-heldout: {copied}")


class TestUnknownTypePolicy(unittest.TestCase):
    """Ante un aviso que el léxico no reconoce se generaliza por familia y señales; no se inventa protocolo."""

    def test_unrecognised_with_life_risk_dispatches_generic_medical_and_asks(self):
        w, m = new()
        w.report("a un chaval le ha pasado algo rarísimo en la pista, está muy grave, se muere", Channel.WHATSAPP)
        actions = run(w, m)
        inc = next(iter(m.incidents.values()))
        self.assertEqual(inc.type, "unknown_medical")
        d = kinds(actions, ActionKind.DISPATCH)
        self.assertEqual([w.resources[a.resource].kind for a in d], [ResourceKind.MEDICAL])
        self.assertTrue(kinds(actions, ActionKind.ASK))
        self.assertFalse([a for a in actions if a.kind in ALWAYS_APPROVE], "nada drástico sobre lo que no se entiende")
        self.assertIn("tipo no reconocido: actúo por familia y señales", log_text(m, "incident"))

    def test_unrecognised_threat_escalates_and_never_decides(self):
        w, m = new()
        w.report("han llamado diciendo que hay una bomba en la zona de comida", Channel.VOICE, "taquilla 1")
        actions = run(w, m)
        inc = next(iter(m.incidents.values()))
        self.assertEqual((inc.type, inc.zone), ("unknown_external", "food"))
        self.assertTrue([a for a in kinds(actions, ActionKind.NOTIFY) if a.params.get("escalate")])
        self.assertTrue(kinds(actions, ActionKind.ASK))
        self.assertFalse(kinds(actions, ActionKind.DISPATCH) + kinds(actions, ActionKind.BROADCAST)
                         + kinds(actions, ActionKind.EVACUATE), "ante una amenaza no reconocida Mando no decide nada")

    def test_unrecognised_rest_asks_then_acts_on_the_answer(self):
        comms = FakeComms()
        w, m = new(comms=comms)
        w.report("oye, en la barra pasa una cosa muy rara con una máquina, no sabría deciros", Channel.SMS)
        first = run(w, m)
        self.assertEqual([a.kind for a in first], [ActionKind.ASK])
        inc = next(iter(m.incidents.values()))
        self.assertTrue(inc.type.startswith("unknown_"))
        self.assertLess(inc.confidence, 0.5, "lo no reconocido baja la confianza")
        comms._pending.append({"action_id": first[0].id, "result": "answer", "text": "Confirmado.",
                               "data": {"exists": True, "zone": "food", "type": "tipo_que_mando_no_conoce",
                                        "family": "infra", "severity": 6, "needs": {"tech": 1}}})
        later = run(w, m, 2)
        self.assertEqual([w.resources[a.resource].kind for a in kinds(later, ActionKind.DISPATCH)], [ResourceKind.TECH])
        self.assertEqual(inc.type, "tipo_que_mando_no_conoce", "el nombre lo da quien está en el sitio, no el léxico")


class TestFreeTextBenchmark(unittest.TestCase):
    def test_hand_written_reports(self):
        """Avisos libres escritos a mano (`free_text_bench.py`). Se informa de la cifra tal cual; el suelo solo avisa de regresiones."""
        from motor.mando import free_text_bench as bench
        print()
        for name, rows in (("DEV", bench.DEV), ("HOLDOUT", bench.HOLDOUT)):
            r = bench.score(rows)
            print(f"    avisos libres {name}: N={r['n']} · familia {r['family']}/{r['n']} · zona {r['zone']}/{r['n']} · "
                  f"tipo {r['type']}/{r['type_n']}")
            for miss in r["misses"]:
                print("      ✗", " | ".join(miss))
            self.assertGreaterEqual(r["zone"] / r["n"], 0.8, name)


class TestRehearsalAndDecisionCard(unittest.TestCase):
    """Fase 2: ensayo previo en un gemelo, tarjeta de decisión, autonomía condicionada al ensayo."""

    def _gate_b_wave(self, inflow: int, gate_a: int = 100, gate_c: int = 200):
        w = FakeWorld()
        w.dynamic = True
        w.inflow["gate_b"] = inflow
        w.zones["gate_b"].occupancy, w.zones["gate_a"].occupancy, w.zones["gate_c"].occupancy = 1150, gate_a, gate_c
        m = Mando(festival=NO_FESTIVAL, twin=w.twin)
        w.report("La puerta B está atascada, no avanza y sigue llegando gente", Channel.VOICE, "jefe seguridad 2",
                 zone_hint="gate_b")
        return w, m, run(w, m)

    def test_rehearsal_picks_alternative_and_writes_numbers_into_assumptions(self):
        w, m, actions = self._gate_b_wave(inflow=900)
        lines = [e.text for e in m.log if e.data.get("rehearsal")]
        self.assertTrue(lines and lines[0].startswith("ENSAYO (12 min) para Puerta B:"), lines)
        self.assertIn("sin desvío", lines[0])
        self.assertIn("✗", lines[0])
        self.assertIn("✓", lines[0])
        self.assertGreaterEqual(lines[0].count("→"), 3, "se ensayan entre 2 y 4 alternativas")
        reroute = kinds(actions, ActionKind.REROUTE)[0]
        self.assertLess(reroute.params["dest_peak_density"], 4.0)
        self.assertEqual(reroute.autonomy, Autonomy.AUTO, "el ensayo deja el destino por debajo de 4/m²: se ejecuta solo")
        self.assertTrue(reroute.params["rehearsed"]["ok"])
        plan = next(iter(m.plans.values()))
        texts = [s.text for s in plan.assumptions if s.check["kind"] == "zone_occupancy_below"]
        self.assertRegex(texts[0], r"^ensayado: Puerta [AC] llega al \d+ % en \d+ min; supuesto: Puerta [AC] sigue por debajo del 85 %")
        self.assertLessEqual(m.rehearsal.used, 20)
        self.assertEqual(m.snapshot()["counters"]["rehearsals"], m.rehearsal.total)

    def test_reroute_needs_a_person_when_rehearsal_leaves_destination_over_4(self):
        for peak, expected in ((3.1, Autonomy.AUTO), (4.2, Autonomy.APPROVE), (None, Autonomy.APPROVE)):
            a = Action("r", ActionKind.REROUTE, 0, zone="gate_b", params={"to": "gate_a", "dest_peak_density": peak})
            self.assertEqual(autonomy.level(a, "gate"), expected, peak)
        self.assertEqual(autonomy.level(Action("c", ActionKind.REROUTE, 0, zone="gate_b", params={"cancel": True})), Autonomy.AUTO)
        w, m, actions = self._gate_b_wave(inflow=2500)      # una oleada que ninguna puerta aguanta
        reroute = kinds(actions, ActionKind.REROUTE)
        if reroute:   # solo se ejecuta solo si el ensayo deja el DESTINO por debajo de 4/m²; si no, lo decide una persona
            needs_person = reroute[0].params["dest_peak_density"] >= 4.0
            self.assertEqual(reroute[0].autonomy == Autonomy.APPROVE, needs_person)
            self.assertEqual("decision_card" in reroute[0].params, needs_person)
            self.assertIn("✗", log_text(m, "plan"), "el log dice que ninguna alternativa deja bien la puerta B")
        else:
            self.assertRegex(" ".join(p.why for p in m.plans.values()), "desviar no mejora|ningún destino con margen")

    def test_without_twin_falls_back_to_analytic_projection(self):
        w, m = new()
        w.zones["gate_b"].occupancy = 1150
        w.report("La puerta B está atascada", Channel.VOICE, "jefe seguridad 2", zone_hint="gate_b")
        reroute = kinds(run(w, m), ActionKind.REROUTE)[0]
        self.assertIsNone(reroute.params["rehearsed"])
        self.assertFalse([e for e in m.log if e.data.get("rehearsal")])
        self.assertTrue(next(iter(m.plans.values())).assumptions[-2].text.startswith("proyectado:")
                        or any(s.text.startswith("proyectado:") for s in next(iter(m.plans.values())).assumptions))

    def test_decision_card_two_branches_window_escalation_and_latency(self):
        w = FakeWorld()
        w.dynamic = True
        w.zones["front_pit"].occupancy = 14000        # 5,6/m²
        w.inflow["front_pit"] = 300
        m = Mando(festival=NO_FESTIVAL, twin=w.twin)
        w.report("nos están aplastando contra la valla en las primeras filas!!", Channel.RADIO, "jefe seguridad 3")
        stop = kinds(run(w, m), ActionKind.STOP_SHOW)[0]
        card = stop.params["decision_card"]
        self.assertEqual(card["addressee"], "Director del Plan de Actuación")
        self.assertIn("suplente", card["deputy"])
        self.assertTrue(card["rehearsed"])
        self.assertLess(card["if_approved"]["peak_density"], card["if_vetoed"]["peak_density"],
                        "las dos ramas están ensayadas y parar ayuda")
        self.assertTrue(2 <= card["window_min"] <= 15)
        self.assertEqual(card["escalate_at"], card["asked_at"] + max(2, (card["window_min"] + 1) // 2))
        self.assertIn("si apruebas:", log_text(m, "approval"))
        later = run(w, m, card["escalate_at"] - card["asked_at"] + 1)       # nadie contesta
        up = [a for a in kinds(later, ActionKind.NOTIFY) if a.params.get("about") == stop.id]
        self.assertEqual(len(up), 1, "se escala UNA vez al suplente")
        self.assertEqual(up[0].params["to"], card["deputy"])
        self.assertGreaterEqual(m.counters["escalations"], 1)
        m.approve(stop.id, True, "paramos")
        latency = m.snapshot()["counters"]["human_decision_latency"]
        self.assertEqual(latency, {stop.id: m.t - card["asked_at"]})
        self.assertGreaterEqual(latency[stop.id], 2)

    def test_prepared_evacuation_cannot_be_auto_approved(self):
        w, m = new()
        w.report("mochila abandonada sospechosa en la puerta C", Channel.VOICE, "jefe seguridad 1")
        evac = kinds(run(w, m), ActionKind.EVACUATE)[0]
        self.assertTrue(evac.params["prepared"])
        m.approve(evac.id, True)                       # el «sí» genérico de un aprobador automático
        self.assertEqual(evac.status, ActionStatus.AWAITING_APPROVAL)
        m.approve(evac.id, True, "vale")
        self.assertEqual(evac.status, ActionStatus.AWAITING_APPROVAL)
        self.assertIn("RECHAZADA", log_text(m, "approval"))
        m.approve(evac.id, True, "EVACUAR puerta C, orden de la policía")
        self.assertEqual(evac.status, ActionStatus.EXECUTING)

    def test_general_broadcast_needs_approval_but_gate_message_does_not(self):
        for zone, kind, expected in [("general", "general", Autonomy.APPROVE), ("front_pit", "stage_front", Autonomy.APPROVE),
                                     (None, None, Autonomy.APPROVE), ("gate_b", "gate", Autonomy.AUTO),
                                     ("water_n", "water", Autonomy.AUTO)]:
            a = autonomy.gate(Action("b", ActionKind.BROADCAST, 0, zone=zone, params={"message": "x"}, why="y"), kind)
            self.assertEqual(a.autonomy, expected, zone)


class TestReservedCases(unittest.TestCase):
    def test_sexual_assault_is_reserved_everywhere(self):
        comms = FakeComms()
        w, m = new(comms=comms)
        w.report("a mi amiga la han tocado sin su permiso, estamos en los baños", Channel.WHATSAPP)
        actions = run(w, m, 2)
        inc = next(iter(m.incidents.values()))
        self.assertEqual(inc.type, "sexual_assault")
        self.assertFalse(kinds(actions, ActionKind.BROADCAST), "nunca por megafonía")
        self.assertTrue([a for a in kinds(actions, ActionKind.NOTIFY) if a.params.get("to") == "violet_point"])
        police = kinds(actions, ActionKind.REQUEST_EXTERNAL)
        self.assertTrue(police and all(a.status == ActionStatus.AWAITING_APPROVAL for a in police), "policía solo con aprobación")
        self.assertIn("consentimiento", police[0].params["decision_card"]["addressee"])
        public = json.dumps(m.snapshot(), ensure_ascii=False)
        for secret in ("tocado", "sexual", "Baños", "toilets", "violet"):
            self.assertNotIn(secret, public, secret)
        shown = m.snapshot()["incidents"][0]
        self.assertEqual((shown["reserved"], shown["label"], shown["zone"], shown["type"]),
                         (True, "incidente reservado", None, "reserved"))
        self.assertIn("incidente reservado", [e["text"] for e in m.snapshot()["log"]])
        self.assertIn("toilets", json.dumps(m.snapshot(full=True)), "el centro de control sí lo ve")
        for a in comms.sent:
            self.assertNotIn("tocado", a.params.get("message", ""), "no se repite el contenido al informante")


class TestManyFronts(unittest.TestCase):
    TEAM = {"sec_1": (ResourceKind.SECURITY, "gate_a"), "sec_2": (ResourceKind.SECURITY, "gate_b"),
            "sec_3": (ResourceKind.SECURITY, "front_pit"), "sec_4": (ResourceKind.SECURITY, "general"),
            "med_1": (ResourceKind.MEDICAL, "medical_1")}

    def _six_fronts(self):
        w, m = new(self.TEAM)
        w.zones["gate_b"].occupancy = 1150
        w.report("La puerta B está atascada, no avanza", Channel.VOICE, "jefe seguridad 2", zone_hint="gate_b")
        w.report("se ha perdido una niña de 5 años, su madre está en la pista", Channel.RADIO, "voluntarios 1")
        w.report("hay un dron volando sobre la pista", Channel.RADIO, "jefe seguridad 4")
        w.report("me han robado el móvil en la barra", Channel.WHATSAPP)
        w.report("el artista se retrasa 40 minutos, la gente del foso está nerviosa", Channel.OPERATOR, "producción")
        w.report("chico inconsciente en los baños, no reacciona", Channel.RADIO, "jefe seguridad 1")
        return w, m, run(w, m)

    def test_six_fronts_five_resources_lowest_priority_waits_and_is_explained(self):
        w, m, actions = self._six_fronts()
        self.assertEqual(len(m.live), 6)
        fronts = {f["incident"]: f for f in m.snapshot(full=True)["fronts"]}
        self.assertEqual(len(fronts), 6)
        vital = [f for f in fronts.values() if f["life_threat"]]
        self.assertTrue(vital and all(f["team"] and not f["waiting"] for f in vital), "nadie con riesgo vital espera")
        waiting = [f for f in fronts.values() if f["waiting"]]
        self.assertEqual(len(waiting), 1)
        served_security = [f for f in fronts.values() if f["team"] and not f["life_threat"]]
        self.assertTrue(all(waiting[0]["priority"] <= f["priority"] for f in served_security),
                        "espera el de menor prioridad")
        self.assertRegex(waiting[0]["why_waiting"], r"espera seguridad: prioridad \d+,\d, sin riesgo vital; le llega .+ en ~\d+ min, cuando acabe M-\d+")
        self.assertEqual(len(kinds(actions, ActionKind.DISPATCH)), 5, "los cinco recursos salen, ninguno dos veces")
        self.assertEqual(len({a.resource for a in kinds(actions, ActionKind.DISPATCH)}), 5)

    def test_seventh_grave_incident_recalls_lowest_and_keeps_other_plans(self):
        w, m, _ = self._six_fronts()
        run(w, m, 3)
        before = {i.id: (m.meta[i.id].plan, list(i.assigned)) for i in m.live}
        holders = {rid: m.incidents[iid] for rid, (iid, kind) in m.assign.items() if kind == "security"}
        lowest = min(holders.values(), key=lambda i: i.priority)
        w.report("paquete sospechoso abandonado junto a la puerta A, nadie lo reclama", Channel.RADIO, "jefe seguridad 5")
        actions = run(w, m, 2)
        recall = kinds(actions, ActionKind.RECALL)
        self.assertEqual(len(recall), 1)
        self.assertEqual(recall[0].params["from_incident"], lowest.id, "se le quita al menos prioritario")
        self.assertEqual([a.resource for a in kinds(actions, ActionKind.DISPATCH)], [recall[0].resource])
        for iid, (plan, team) in before.items():
            if iid != lowest.id and plan is not None:    # a los demás no se les quita nada ni se les tira el plan por culpa del imprevisto
                self.assertEqual(m.incidents[iid].assigned, team, iid)
                self.assertFalse(str(m.plans[plan].invalidated_by or "").startswith("recall:"), iid)
                self.assertIn(m.meta[iid].plan, m.live_plans)
        self.assertIn(lowest.id, {f["incident"] for f in m.snapshot(full=True)["fronts"] if f["waiting"]})

    def test_tick_under_5_ms_with_8_fronts_and_rehearsal(self):
        w = FakeWorld()
        w.dynamic = True
        w.inflow["gate_b"] = 200
        m = Mando(festival=NO_FESTIVAL, twin=w.twin)
        for i, z in enumerate(["gate_a", "gate_c", "general", "front_pit", "food", "toilets", "pmr"]):
            w.report(f"pelea en {w.zones[z].name}", Channel.RADIO, f"jefe {i}", zone_hint=z)
        w.zones["gate_b"].occupancy = 1150
        w.report("La puerta B está atascada, no avanza", Channel.VOICE, "jefe seguridad 2", zone_hint="gate_b")
        times = []
        for _ in range(12):
            obs = w.observe()
            t0 = time.perf_counter()
            acts = m.tick(obs)
            times.append((time.perf_counter() - t0) * 1000)
            for a in acts:
                if a.status != ActionStatus.AWAITING_APPROVAL:
                    w.apply(a)
            w.step()
        self.assertEqual(len(m.incidents), 8)
        self.assertGreater(m.rehearsal.total, 0)
        print(f"\n    8 frentes con ensayo (gemelo de prueba): tick máx {max(times):.2f} ms, medio {sum(times) / len(times):.2f} ms, "
              f"{m.rehearsal.total} ensayos")
        self.assertLess(max(times), 5.0)


class TestPriorityAndReport(unittest.TestCase):
    def test_priority_is_bounded_and_explained(self):
        w, m = new()
        w.zones["gate_b"].occupancy = 3480          # 5,8/m²
        w.report("Puerta B atascada, no avanza", Channel.VOICE, "jefe seguridad 2", zone_hint="gate_b")
        run(w, m)
        inc = next(iter(m.incidents.values()))
        self.assertTrue(0 <= inc.priority <= 10)
        line = m.snapshot()["incidents"][0]["explain"]
        self.assertRegex(line, r"^prioridad \d+,\d = gravedad \d+ × plazo \d+ min .* × densidad 5,8/m²")
        lo, _ = priority.compute(inc, None, 0)
        self.assertLess(lo, inc.priority, "sin densidad la prioridad es menor")

    def test_report_says_what_went_wrong(self):
        w, m = new()
        w.rejects.add("med_2")
        w.zones["gate_b"].occupancy = 1150
        w.report("La puerta B está atascada", Channel.VOICE, "jefe seguridad 2", zone_hint="gate_b")
        w.report("chico inconsciente en la pista", Channel.RADIO, "jefe seguridad 4")
        run(w, m, 3)
        w.zones["gate_a"].occupancy = 1100
        run(w, m, 2)
        text, data = report(m)
        self.assertIn("Supuestos rotos (2)", text)
        self.assertIn("Qué hice mal", text)
        self.assertEqual({x["kind"] for x in data["mistakes"]}, {"dispatch_failed", "self_inflicted"})
        self.assertTrue(data["would_change"])
        json.dumps(data, ensure_ascii=False)

    def test_tick_is_fast_with_20_incidents(self):
        w, m = new(watch_zones=True)
        zones = ["gate_a", "gate_b", "gate_c", "general", "front_pit", "food", "toilets", "pmr", "corridor_n", "water_n"]
        for i, z in enumerate(zones):
            w.report(f"pelea en {w.zones[z].name}", Channel.RADIO, f"jefe {i}", zone_hint=z)
            w.report(f"persona con un esguince en {w.zones[z].name}", Channel.RADIO, f"sanitario {i}", zone_hint=z)
        run(w, m, 2)
        self.assertEqual(len(m.live), 20)
        obs = w.observe()
        t0 = time.perf_counter()
        for k in range(300):
            obs.t = w.t + k % 3     # sin avisos nuevos: el coste de mantener 20 incidentes vivos
            m.tick(obs)
        per_tick_ms = (time.perf_counter() - t0) / 300 * 1000
        print(f"\n    tick con {len(m.live)} incidentes vivos: {per_tick_ms:.3f} ms")
        self.assertLess(per_tick_ms, 1.0)


# ---------------------------------------------------------------------------- integración con el simulador real

try:
    from motor.world import SimComms, World
except Exception:  # el simulador lo escribe otro agente: si no está, el test se salta
    World = None


@unittest.skipIf(World is None, "motor.world no disponible")
# ---------------------------------------------------------------------------- memoria operativa y parámetros aprobados

def _hot_water_case(seed: int, litres: int = 260, duration: int = 90) -> dict[str, Any]:
    """Tarde de calor, depósito norte casi vacío y una reposición que tarda de verdad 25 min (Mando no lo sabe)."""
    return {"id": f"agua-{seed}", "seed": seed, "day": 2, "start_hhmm": "21:00", "duration_min": duration,
            "initial": {"spontaneous": False, "weather": {"temp_c": 39}, "flags": {"water_n": {"water_l": litres}},
                        "ops": {"resupply_min": {"water_n": [25, 25]}}},
            "events": []}


def _wind_alert_case(seed: int, arrives: bool) -> dict[str, Any]:
    """Preaviso de viento en t=3. Si `arrives`, sube a 75 km/h en t=12; si no, se desactiva."""
    end = {"kind": "weather", "wind_kmh": 75, "alert": "roja"} if arrives else {"kind": "weather", "wind_kmh": 10, "alert": None}
    return {"id": f"viento-{seed}-{arrives}", "seed": seed, "day": 2, "start_hhmm": "19:00", "duration_min": 45,
            "initial": {"spontaneous": False},
            "events": [{"t": 3, "kind": "world", "effect": {"kind": "weather", "wind_kmh": 45, "alert": "amarilla"}},
                       {"t": 12, "kind": "world", "effect": end}]}


def _play(case: dict[str, Any], params: Any = None, memory: Any = None, forbid_truth: bool = False):
    """Ciclo de INTERFACES.md con el simulador real. Devuelve (mundo, mando, acciones por minuto)."""
    from motor.world import SimComms, World
    world = World.from_case(case)
    mando = Mando(comms=SimComms(world, case["seed"]), params=params, memory=memory)
    if forbid_truth:
        def boom() -> dict:
            raise AssertionError("la memoria o Mando han leído world.truth()")
        world.truth = boom       # type: ignore[method-assign]
    trace = []
    while not world.done():
        obs = world.observe()
        for r in obs.new_reports:
            r.truth_incident = None          # lo que un agente honrado no debe leer, aquí ni existe
        for a in mando.tick(obs):
            trace.append((world.t, str(a.kind), a.zone, a.resource, str(a.status)))
            if a.status != ActionStatus.AWAITING_APPROVAL:
                world.apply(a)
        world.step()
    if memory is not None:
        memory.end_run()
    return world, mando, trace


class TestOperationalMemoryAndParams(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            import motor.world  # noqa: F401
        except Exception as ex:      # noqa: BLE001
            raise unittest.SkipTest(f"sin simulador: {ex!r}")
        from motor.mando.memory import OperationalMemory
        from motor.mando.tuning import Params, propose
        cls.Memory, cls.Params, cls.propose = OperationalMemory, Params, staticmethod(propose)

    def _day1(self, n: int):
        parts = []
        for seed in range(1, n + 1):
            mem = self.Memory()
            _play(_hot_water_case(seed), params=self.Params.initial(), memory=mem, forbid_truth=True)
            parts.append(mem.to_dict())
        return self.Memory.merge(parts)

    def test_memory_module_cannot_see_the_truth(self) -> None:
        import ast
        src = (Path(__file__).parent / "memory.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        mods = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | \
               {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        self.assertEqual(mods, {"__future__", "json", "re", "pathlib", "typing", "contracts"})     # ni simulador ni casos
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        for forbidden in ("truth", "truth_incident", "expected", "must", "must_not"):
            self.assertNotIn(forbidden, attrs)

    def test_memory_is_built_from_observations_only(self) -> None:
        mem = self.Memory()
        _play(_hot_water_case(7), params=self.Params.initial(), memory=mem, forbid_truth=True)    # truth() revienta si se toca
        d = mem.to_dict()
        self.assertEqual(d["runs"], 1)
        self.assertGreater(d["consumption"]["water_n"]["n_ticks"], 10)
        self.assertEqual(d["resupply"]["water_n"]["n"], 1)
        self.assertGreaterEqual(d["resupply"]["water_n"]["minutes"][0], 25)      # pedido → DONE, tal y como se vio
        self.assertEqual(d["contacts"]["log_1"]["channels"]["voice"]["sent"], 1)
        self.assertEqual(json.loads(json.dumps(d)), d)                           # serializable tal cual

    def test_day1_proposes_resupply_lead_with_its_n(self) -> None:
        memory = self._day1(6)
        props = self.propose(memory, names={"water_n": "Agua Norte"})
        c = next(x for x in props.changes if x.param == "resupply_lead_min" and x.key == "water_n")
        self.assertEqual((c.n, c.old, c.limited), (6, 10, False))
        self.assertGreaterEqual(c.new, 25)
        self.assertIn("N=6", c.text)
        self.assertIn("Agua Norte", c.text)
        self.assertEqual(memory.n_by_parameter()["resupply_lead_min"], {"water_n": 6})
        # con poca evidencia lo dice y el cambio es conservador
        few = next(x for x in self.propose(self._day1(2)).changes if x.param == "resupply_lead_min")
        self.assertTrue(few.limited)
        self.assertIn("EVIDENCIA LIMITADA", few.text)
        self.assertLess(few.new, c.new)
        # determinista: misma memoria, mismas propuestas
        self.assertEqual(self.propose(memory).to_dict(), self.propose(memory).to_dict())

    def test_memory_roundtrip_json(self) -> None:
        import tempfile
        memory = self._day1(2)
        with tempfile.TemporaryDirectory() as tmp:
            path = memory.save(Path(tmp) / "memory.day1.json", source={"n_cases": 2})
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["n_by_parameter"]["resupply_lead_min"], {"water_n": 2})
            again = self.Memory.load(path)
        self.assertEqual(again.data["resupply"], memory.data["resupply"])

    def test_unapproved_change_does_not_affect_mando(self) -> None:
        import tempfile
        props = self.propose(self._day1(6))
        self.assertTrue(props.changes)
        self.assertEqual(props.approved_params().to_dict()["values"], {})        # propuesto ≠ aprobado
        props.reject(props.changes[0].id, note="no me fío")
        self.assertEqual(props.approved_params().to_dict()["values"], {})
        with tempfile.TemporaryDirectory() as tmp:
            path = props.write_approved(Path(tmp) / "params.approved.json")
            loaded = self.Params.load(path)
        self.assertEqual(loaded.to_dict()["values"], {})
        case = _hot_water_case(11)
        _, _, base = _play(case, params=self.Params.initial())
        _, mando, same = _play(case, params=loaded)
        self.assertEqual(base, same)
        self.assertEqual(mando.snapshot()["counters"]["params_applied"], 0)
        self.assertNotIn("Parámetro aprendido", log_text(mando))

    def test_approved_param_changes_a_decision_and_is_logged(self) -> None:
        props = self.propose(self._day1(6))
        change = next(x for x in props.changes if x.param == "resupply_lead_min")
        props.approve(change.id, by="Ana")
        approved = props.approved_params()
        case = _hot_water_case(11, litres=1100)     # día 2: ~50 min de agua; la reposición real tarda ~29
        w0, _, before = _play(case, params=self.Params.initial())
        w1, mando, after = _play(case, params=approved)
        t0 = next(t for t, kind, *_ in before if kind == "resupply")
        t1 = next(t for t, kind, *_ in after if kind == "resupply")
        self.assertLess(t1, t0)                                                  # se pide ANTES
        text = log_text(mando, "param")
        self.assertIn("resupply_lead_min[water_n]", text)
        self.assertIn("N=6", text)
        self.assertGreaterEqual(mando.snapshot()["params"]["applied"]["resupply_lead_min[water_n]"], 1)
        self.assertEqual(len(w0.truth()["water"]["stockouts"]), 1)               # con el valor de ficha el depósito se acaba
        self.assertEqual(len(w1.truth()["water"]["stockouts"]), 0)               # con el aprobado, no

    def test_params_none_is_the_old_mando(self) -> None:
        _, mando, trace = _play(_hot_water_case(11), params=None)
        self.assertFalse(any(kind == "resupply" and t < 10 for t, kind, *_ in trace))   # no anticipa: reacciona al aviso
        self.assertFalse(mando.snapshot()["params"]["active"])

    def test_failed_weather_alert_never_relaxes_safety(self) -> None:
        from motor.mando import planner, tuning
        parts = []
        for seed in range(1, 9):                                                  # día 1: ocho avisos y la tormenta no llega
            mem = self.Memory()
            _play(_wind_alert_case(seed, arrives=False), params=self.Params.initial(), memory=mem, forbid_truth=True)
            parts.append(mem.to_dict())
        memory = self.Memory.merge(parts)
        eps = memory.data["weather"]["episodes"]
        self.assertEqual([e["outcome"] for e in eps], ["no_llego"] * 8)
        props = self.propose(memory)
        for c in props.changes:
            self.assertIn(c.param, tuning.TUNABLE)
            self.assertNotIn(c.param, tuning.SAFETY_LOCKED)
            props.approve(c.id)
        weather = [c for c in props.changes if c.param.startswith("weather")]
        self.assertTrue(weather)                                                  # aprende algo: seguimiento y cancelación…
        self.assertTrue(all("No cambia ningún criterio de seguridad" in c.text for c in weather))
        approved = props.approved_params()
        self.assertEqual(set(approved.to_dict()["values"]) - set(tuning.TUNABLE), set())
        for locked in tuning.SAFETY_LOCKED:                                       # …y un fichero manipulado no entra
            with self.assertRaises(ValueError):
                self.Params({locked: 999})
        self.assertEqual(planner.WIND_STOP, 70.0)
        # día 2: el mismo preaviso y esta vez SÍ llega. Lo grave se propone igual, al mismo minuto y con aprobación.
        case = _wind_alert_case(99, arrives=True)

        def grave(trace: list) -> list:
            return [(t, kind, status) for t, kind, _, _, status in trace if kind in ("stop_show", "evacuate", "set_zone")]
        _, _, before = _play(case, params=self.Params.initial())
        _, mando, after = _play(case, params=approved)
        self.assertTrue(any(kind == "stop_show" for _, kind, _ in grave(before)))
        self.assertEqual(grave(before), grave(after))
        self.assertTrue(all(status == "awaiting_approval" for _, kind, status in grave(after) if kind in ("stop_show", "evacuate")))
        # y el preaviso del día 2 se atiende igual que el del día 1: mismo incidente abierto en el mismo minuto
        first = [e.t for e in mando.log if e.kind == "incident" and e.text.startswith("Nuevo")][0]
        self.assertLessEqual(first, 4)

    def test_contact_order_changes_who_is_called_and_is_logged(self) -> None:
        case = {"id": "contacto", "seed": 4, "day": 2, "start_hhmm": "18:00", "duration_min": 20,
                "initial": {"spontaneous": False},
                "events": [{"t": 1, "kind": "incident",
                            "incident": {"id": "i1", "family": "medical", "type": "fainting", "zone": "general", "severity": 6,
                                         "deadline": 30, "needs": {"medical": 1}},
                            "reports": [{"channel": "radio", "source": "seguridad 4", "zone_hint": "general",
                                         "text": "Persona desmayada en la pista general, necesito sanitarios."}]}]}
        learned = self.Params({"contact_order": {"medical": {"order": ["med_1", "med_2", "med_3"], "fail_cost_min": 8.0,
                                                             "rate": {"med_1": 0.97, "med_2": 0.96, "med_3": 0.2},
                                                             "n": {"med_1": 40, "med_2": 35, "med_3": 30}}}},
                              {"contact_order[medical]": "N=105"})
        _, _, before = _play(case, params=self.Params.initial())
        _, mando, after = _play(case, params=learned)
        who0 = next(r for _, kind, _, r, _ in before if kind == "dispatch")
        who1 = next(r for _, kind, _, r, _ in after if kind == "dispatch")
        self.assertEqual(who0, "med_3")               # el más cercano
        self.assertNotEqual(who1, "med_3")            # …que casi nunca coge el teléfono
        self.assertIn("contact_order[medical] (N=105)", log_text(mando, "param"))

    def test_precise_location_asks_without_delaying_dispatch(self) -> None:
        case = {"id": "punto", "seed": 5, "day": 2, "start_hhmm": "18:00", "duration_min": 30,
                "initial": {"spontaneous": False, "ops": {"locate": {"zones": {"general": [8, 8]}, "p_point": 1.0}}},
                "events": [{"t": 1, "kind": "incident",
                            "incident": {"id": "i1", "family": "medical", "type": "fainting", "zone": "general", "severity": 6,
                                         "deadline": 30, "needs": {"medical": 1}},
                            "reports": [{"channel": "whatsapp", "source": "asistente", "zone_hint": "general",
                                         "text": "Una chica se ha desmayado en la pista general, ayuda"},
                                        {"channel": "whatsapp", "source": "asistente", "zone_hint": "general",
                                         "text": "La misma persona del incidente M-001 sigue desmayada en la pista general"}]}]}
        learned = self.Params({"require_precise_location": {"general": True}}, {"require_precise_location[general]": "N=23"})
        w0, _, before = _play(case, params=self.Params.initial())
        w1, mando, after = _play(case, params=learned)
        d0 = next(t for t, kind, *_ in before if kind == "dispatch")
        d1 = next(t for t, kind, *_ in after if kind == "dispatch")
        self.assertEqual(d0, d1)                                                  # preguntar NUNCA retrasa el despacho
        asks = [a for a in mando.actions.values() if a.kind == ActionKind.ASK and a.params.get("purpose") == "point"]
        self.assertEqual(len(asks), 1)
        self.assertIn("torre, puesto o acceso", asks[0].params["message"])
        self.assertIn("require_precise_location[general] (N=23)", log_text(mando, "param"))
        t0, t1 = (w.truth()["incidents"]["i1"]["t_first_attention"] for w in (w0, w1))
        self.assertLess(t1, t0)                                                   # el equipo da antes con la persona

    def test_longer_duplicate_window_never_applies_to_life_threat(self) -> None:
        world, mando = new()
        mando.triage.merge_window = 25
        world.report("Hay un chico inconsciente, no respira", zone_hint="general", source="asistente")
        run(world, mando, 1)
        for _ in range(18):
            run(world, mando, 1)
        world.report("Hay una persona inconsciente, no respira", zone_hint="general", source="asistente")
        run(world, mando, 1)
        vital = [i for i in mando.incidents.values() if i.zone == "general" and mando.meta[i.id].life_threat]
        self.assertEqual(len(vital), 2)       # a los 19 min puede ser OTRA persona: no se funde aunque la ventana sea de 25


class TestIntegrationRealWorld(unittest.TestCase):
    def test_demo_case_reroute_breaks_and_replans_without_gate_a(self):
        case = json.loads((Path(__file__).parent.parent / "world" / "demo_case.json").read_text(encoding="utf-8"))
        world = World.from_case(case)
        mando = Mando(comms=SimComms(world, case["seed"]), twin=getattr(world, "twin", None))
        punched, ticks = False, []
        while not world.done():
            obs = world.observe()
            t0 = time.perf_counter()
            actions = mando.tick(obs)
            ticks.append((time.perf_counter() - t0) * 1000)
            for a in actions:
                if a.status != ActionStatus.AWAITING_APPROVAL:
                    world.apply(a)
            if not punched and mando.reroutes.get("gate_b") == "gate_a":
                # golpe del jurado: llegan seis lanzaderas a la puerta A justo cuando Mando desvía hacia ella
                world.inject({"kind": "zone_inflow", "zone": "gate_a", "per_min": 260, "n": 20})
                punched = True
            world.step()

        reroutes = [a for a in mando.actions.values() if a.kind == ActionKind.REROUTE and a.params.get("to")]
        self.assertEqual((reroutes[0].zone, reroutes[0].params["to"]), ("gate_b", "gate_a"), "Mando desvía")
        broken = [e for e in mando.log if e.kind == "assumption_broken" and e.data["check"].get("zone") == "gate_a"]
        self.assertTrue(broken, "el supuesto sobre gate_a se rompe")
        old = mando.plans[broken[0].data["plan"]]
        new_plan = next(p for p in mando.plans.values() if p.supersedes == old.id)
        used = [mando.actions[s] for s in new_plan.steps if mando.actions[s].t >= broken[0].t]
        self.assertFalse([a for a in used if "gate_a" in (a.zone, a.params.get("to"))], "replanifica sin usar gate_a")
        self.assertFalse([s for s in new_plan.assumptions if s.check.get("zone") == "gate_a"])
        truth = world.truth()
        self.assertEqual({str(i["status"]) for i in truth["incidents"].values() if i["origin"] == "case"}, {"resolved"})
        approved = {e.ref for e in mando.log if e.kind == "approval" and e.data.get("ok")}
        unsafe = [a for a in truth["actions"] if a["kind"] in {str(k) for k in ALWAYS_APPROVE} and a["id"] not in approved]
        self.assertFalse(unsafe, "nada de ALWAYS_APPROVE se ejecuta sin aprobación")

        if getattr(world, "twin", None) is not None:
            self.assertTrue([e for e in mando.log if e.data.get("rehearsal")], "con gemelo, el desvío se ENSAYA antes de ejecutarse")
            self.assertTrue(reroutes[0].params["rehearsed"], "y el REROUTE lleva el resultado del ensayo")
        ticks.sort()
        print("\n    --- demo_case.json con World + SimComms + Mando (gemelo real) ---")
        print(f"    tick: medio {sum(ticks) / len(ticks):.3f} ms · p99 {ticks[int(len(ticks) * .99)]:.2f} ms · máx {ticks[-1]:.2f} ms · "
              f"{mando.rehearsal.total} ensayos")
        for e in mando.log:
            if e.kind in ("assumption_broken", "plan", "approval") or (e.kind == "action" and "REROUTE" in e.text):
                print(f"    t={e.t:>2} {e.text[:230]}")
        peak = {z: round(v["density"], 1) for z, v in truth["peak_density"].items() if z.startswith("gate")}
        print(f"    contadores: {mando.counters}")
        print(f"    densidad máxima en puertas: {peak} · despachos desperdiciados: {len(truth['wasted_dispatches'])}")


if __name__ == "__main__":
    unittest.main()
