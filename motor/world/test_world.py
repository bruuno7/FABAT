"""python3 -m unittest motor.world.test_world -v   (desde la raíz del proyecto)"""
from __future__ import annotations

import json
import time
import unittest
from pathlib import Path

from motor.contracts import (
    Action, ActionKind, ActionStatus, Autonomy, Channel, IncidentStatus, ResourceStatus,
)
from motor.world import SimComms, World, load_festival
from motor.world.demo import run

DEMO = json.loads((Path(__file__).parent / "demo_case.json").read_text(encoding="utf-8"))


def case(**kw) -> dict:
    base = {"id": "t", "seed": 1, "day": 2, "start_hhmm": "18:30", "duration_min": 60, "events": []}
    base.update(kw)
    return base


def conserved(w: World) -> bool:
    return w.outside >= 0 and w.exited >= 0 and w.outside + sum(w.occ) + w.exited == w.population


def dispatch(w: World, aid: str, res: str, **kw) -> Action:
    return w.apply(Action(aid, ActionKind.DISPATCH, w.t, resource=res, **kw))


class TestFestival(unittest.TestCase):
    def test_layout(self):
        fest = load_festival()
        ids = {z["id"] for z in fest["zones"]}
        self.assertEqual(len(ids), 17)
        self.assertAlmostEqual(sum(z["area_m2"] for z in fest["zones"]), 30000, delta=500)
        seen, todo = set(), ["gate_a"]  # grafo conexo
        while todo:
            z = todo.pop()
            if z not in seen:
                seen.add(z)
                todo += [e["b"] if e["a"] == z else e["a"] for e in fest["edges"] if z in (e["a"], e["b"])]
        self.assertEqual(seen, ids)
        self.assertEqual(len(fest["resources"]), 15)
        for day in fest["program"]["days"]:
            self.assertAlmostEqual(sum(p.get("arrive_share", 0) for p in day["phases"]), 1.0, places=6)


class TestDeterminism(unittest.TestCase):
    def test_same_seed_same_truth(self):
        hot = dict(DEMO, initial={"occupancy": {"gate_b": 1300}, "weather": {"temp_c": 39, "wind_kmh": 85}})
        a, b = run(hot, 11, reroute_at=6, verbose=False), run(hot, 11, reroute_at=6, verbose=False)
        self.assertEqual(json.dumps(a, sort_keys=True, default=str), json.dumps(b, sort_keys=True, default=str))
        self.assertTrue(any(i["origin"] == "auto" for i in a["incidents"].values()), "el caso caliente debe usar el RNG")
        c = run(hot, 12, reroute_at=6, verbose=False)
        self.assertNotEqual(json.dumps(a, sort_keys=True, default=str), json.dumps(c, sort_keys=True, default=str))

    def test_clone_is_exact_and_independent(self):
        w = World.from_case(dict(DEMO, initial={"weather": {"temp_c": 39}}), 5)
        for _ in range(10):
            w.step()
        a = dispatch(w, "d1", "sec_4", incident="i1")
        self.assertEqual(a.status, ActionStatus.EXECUTING)
        before = json.dumps(w.truth(), sort_keys=True, default=str)
        ghost = w.clone()
        ghost.inject({"kind": "zone_inflow", "zone": "gate_a", "per_min": 500})
        ghost.inject({"kind": "resource_offline", "resource": "sec_4"})
        for _ in range(30):
            ghost.step()
        self.assertEqual(before, json.dumps(w.truth(), sort_keys=True, default=str))
        self.assertEqual(a.status, ActionStatus.EXECUTING, "el clon no puede tocar las acciones del agente")
        self.assertEqual(w.resources["sec_4"].status, ResourceStatus.EN_ROUTE)
        twin = w.clone()
        for _ in range(40):
            w.step()
            twin.step()
        self.assertEqual(json.dumps(w.truth(), sort_keys=True, default=str),
                         json.dumps(twin.truth(), sort_keys=True, default=str))
        self.assertEqual(w.rng.getstate(), twin.rng.getstate())


class TestCrowd(unittest.TestCase):
    def _gate_a_peak(self, reroute: bool) -> tuple[float, dict]:
        w = World.from_case(DEMO, 7)
        while not w.done():
            if reroute and w.t == 6:
                a = w.apply(Action("rr", ActionKind.REROUTE, w.t, zone="gate_b", params={"to": "gate_a", "fraction": 0.7}))
                self.assertEqual(a.status, ActionStatus.DONE)
            w.step()
            self.assertTrue(conserved(w))
        return w.truth()["peak_density"]["gate_a"]["density"], w.truth()

    def test_reroute_saturates_the_other_gate(self):
        calm, _ = self._gate_a_peak(False)
        hit, truth = self._gate_a_peak(True)
        self.assertLess(calm, 1.0)
        self.assertGreater(hit, 6.5)
        auto = [i for i in truth["incidents"].values() if i["origin"] == "auto" and i["zone"] == "gate_a"]
        self.assertTrue(auto and auto[0]["family"] == "crowd" and auto[0]["severity"] >= 8)

    def test_closed_and_restricted_gate(self):
        def entered(state: str) -> int:
            w = World.from_case(case(), 1)
            w.apply(Action("s", ActionKind.SET_ZONE, 0, zone="gate_b", params={"state": state}))
            for _ in range(20):
                w.step()
            self.assertTrue(conserved(w))
            return w.population - w.outside
        self.assertGreater(entered("open"), entered("restricted"))
        self.assertGreater(entered("restricted"), entered("closed"))

    def test_sensor_report_and_power_chain(self):
        w = World.from_case(case(initial={"occupancy": {"gate_c": 2200}}), 1)
        reps = w.observe().new_reports
        self.assertTrue(any(r.channel == Channel.SENSOR and r.zone_hint == "gate_c" for r in reps))
        base = World.from_case(case(), 1)
        dark = World.from_case(case(), 1)
        dark.inject({"kind": "zone_flag", "zone": "food", "power": False})
        for _ in range(30):
            base.step()
            dark.step()
        self.assertLess(dark.occ[dark.L.idx["food"]], base.occ[base.L.idx["food"]])
        self.assertGreater(dark.occ[dark.L.idx["front_pit"]], base.occ[base.L.idx["front_pit"]])

    def test_three_days_without_incidents(self):
        w = World.from_case(case(day=1, start_hhmm="12:00", duration_min=3 * 1440), 3)
        peak_inside = 0
        while not w.done():
            w.observe()
            w.step()
            self.assertGreaterEqual(min(w.occ), 0)
            self.assertTrue(conserved(w), f"se pierde gente en t={w.t}")
            peak_inside = max(peak_inside, sum(w.occ))
        truth = w.truth()
        self.assertGreater(peak_inside, 38000)
        self.assertLess(sum(w.occ), 50)
        self.assertEqual(truth["incidents"], {}, "un festival normal no debe generar incidentes solo")
        self.assertLess(truth["peak_density"]["front_pit"]["density"], 5.0)


class TestResources(unittest.TestCase):
    def test_dispatch_resolves_and_frees(self):
        w = World.from_case(DEMO, 7)
        while w.t < 41:
            w.step()
        a = dispatch(w, "d1", "med_1", zone="front_pit")  # sin id de verdad: casa por zona y tipo
        self.assertEqual(a.status, ActionStatus.EXECUTING)
        self.assertEqual(a.params["path"], ["front_pit"])
        while not w.done():
            w.step()
        inc = w.truth()["incidents"]["i2"]
        self.assertEqual(inc["status"], "resolved")
        self.assertLessEqual(inc["t_first_attention"], 48)
        self.assertEqual(a.status, ActionStatus.DONE)
        self.assertEqual(w.resources["med_1"].status, ResourceStatus.AVAILABLE)
        self.assertEqual(w.resources["med_1"].zone, "front_pit")

    def test_unattended_incident_fails(self):
        w = World.from_case(DEMO, 7)
        while not w.done():
            w.step()
        inc = w.truth()["incidents"]
        self.assertEqual(inc["i2"]["status"], IncidentStatus.FAILED.value)
        self.assertEqual(inc["i2"]["t_failed"], 48)
        self.assertEqual(inc["i1"]["status"], IncidentStatus.FAILED.value)

    def test_wasted_dispatch_and_recall(self):
        w = World.from_case(case(), 1)
        a = dispatch(w, "d1", "med_3", zone="food")
        for _ in range(8):
            w.step()
        self.assertEqual(a.params.get("outcome"), "nothing_found")
        self.assertEqual(len(w.truth()["wasted_dispatches"]), 1)
        self.assertEqual(w.resources["med_3"].status, ResourceStatus.AVAILABLE)
        b = dispatch(w, "d2", "sec_5", zone="front_pit")
        w.step()
        w.apply(Action("rc", ActionKind.RECALL, w.t, resource="sec_5"))
        self.assertEqual(b.status, ActionStatus.CANCELLED)
        self.assertEqual(w.resources["sec_5"].status, ResourceStatus.AVAILABLE)

    def test_ambulance_does_not_cross_dense_zone(self):
        w = World.from_case(case(), 1)
        clear = dispatch(w, "d0", "amb_1", zone="gate_c")
        self.assertEqual(clear.params["path"], ["corridor_s", "gate_c"])
        crowded = {"corridor_s": 3600, "general": 26000}  # 2 /m²: por encima de lo que cruza un vehículo (1,5)
        w = World.from_case(case(initial={"occupancy": crowded}), 1)
        detour = dispatch(w, "d1", "amb_1", zone="gate_c")  # segunda ruta sanitaria: vial de servicio sur
        self.assertEqual(detour.status, ActionStatus.EXECUTING)
        self.assertEqual(detour.params["path"], ["backstage", "gate_c"])
        w2 = World.from_case(case(initial={"occupancy": crowded}), 1)
        blocked = dispatch(w2, "d2", "amb_1", zone="water_s")  # a water_s solo se llega cruzando público
        self.assertEqual(blocked.status, ActionStatus.FAILED)
        self.assertEqual(blocked.params["error"], "route_blocked")
        on_foot = dispatch(w2, "d3", "med_1", zone="water_s")
        self.assertEqual(on_foot.status, ActionStatus.EXECUTING)
        self.assertEqual(on_foot.params["path"], ["corridor_s", "water_s"])
        # el destino sí puede estar lleno: el último tramo se hace a pie con la camilla
        w4 = World.from_case(case(initial={"occupancy": {"front_pit": 10000}}), 1)
        pit = dispatch(w4, "d5", "amb_1", zone="front_pit")
        self.assertEqual((pit.status, pit.params["path"][-1]), (ActionStatus.EXECUTING, "front_pit"))
        # bloqueo a mitad de camino: espera en vez de atravesar, y sigue cuando se despeja
        w3 = World.from_case(case(), 1)
        a = dispatch(w3, "d4", "amb_1", zone="water_s")
        for _ in range(10):
            w3.occ[w3.L.idx["corridor_s"]], w3.occ[w3.L.idx["general"]] = 3600, 26000
            w3.step()
        self.assertEqual(w3.resources["amb_1"].zone, "medical_1")
        self.assertEqual(a.status, ActionStatus.EXECUTING)
        w3.occ[w3.L.idx["corridor_s"]] = 500
        for _ in range(4):
            w3.step()
        self.assertEqual((w3.resources["amb_1"].zone, a.status), ("water_s", ActionStatus.DONE))

    def test_second_medical_route_reaches_the_north(self):
        w = World.from_case(case(initial={"occupancy": {"corridor_s": 3600, "general": 26000}}), 1)
        a = dispatch(w, "d1", "amb_1", zone="toilets")
        self.assertEqual(a.params["path"], ["backstage", "medical_2", "corridor_n", "toilets"])
        fest = load_festival()
        roads = [e for e in fest["edges"] if e.get("service_road")]
        self.assertEqual(len(roads), 2)
        self.assertLessEqual(fest["params"]["amb_max_density"], 2.0)

    def test_cardiac_arrest_keeps_the_team_busy(self):
        ev = {"t": 1, "kind": "incident", "reports": [],
              "incident": {"id": "i1", "family": "medical", "type": "cardiac_arrest", "zone": "general",
                           "severity": 10, "deadline": 6, "needs": {"medical": 1}}}
        w = World.from_case(case(duration_min=90, events=[ev]), 1)
        w.step()
        dispatch(w, "d1", "med_3", incident="i1")
        while not w.done():
            w.step()
        inc = w.truth()["incidents"]["i1"]
        self.assertEqual((inc["status"], inc["t_first_attention"]), ("resolved", 1))  # llegar a tiempo es lo que cuenta
        self.assertTrue(30 <= inc["service_min"] <= 60)
        self.assertGreaterEqual(inc["t_resolved"] - inc["t_first_attention"], 30)


class TestActionsAndEffects(unittest.TestCase):
    def test_impossible_actions_never_raise(self):
        w = World.from_case(case(), 1)
        bad = [Action("b1", ActionKind.DISPATCH, 0, resource="nope", zone="food"),
               Action("b2", ActionKind.DISPATCH, 0, resource="sec_1"),
               Action("b3", ActionKind.SET_ZONE, 0, zone="gate_a", params={"state": "ajar"}),
               Action("b4", ActionKind.REROUTE, 0, zone="gate_a", params={"to": "mars"}),
               Action("b5", ActionKind.RESUPPLY, 0, zone="food"),
               Action("b6", ActionKind.REQUEST_EXTERNAL, 0, params={"kind": "army"}),
               Action("b7", ActionKind.EVACUATE, 0, zone="atlantis")]
        for a in bad:
            self.assertIs(w.apply(a), a)
            self.assertEqual(a.status, ActionStatus.FAILED, a.id)
            self.assertIn("error", a.params)
        waiting = Action("b8", ActionKind.EVACUATE, 0, zone="vip", status=ActionStatus.AWAITING_APPROVAL)
        self.assertEqual(w.apply(waiting).status, ActionStatus.AWAITING_APPROVAL)
        for kind in (ActionKind.MERGE, ActionKind.DISMISS, ActionKind.ASK, ActionKind.NOTIFY, ActionKind.BROADCAST):
            self.assertEqual(w.apply(Action(f"n-{kind}", kind, 0)).status, ActionStatus.DONE)

    def test_every_action_kind_has_an_effect(self):
        w = World.from_case(case(start_hhmm="22:30", initial={"flags": {"water_n": {"water_l": 0}}}), 1)
        w.step()
        self.assertTrue(any(i["type"] == "water_out" for i in w.truth()["incidents"].values()))
        rs = w.apply(Action("rs", ActionKind.RESUPPLY, w.t, zone="water_n"))
        ev = w.apply(Action("ev", ActionKind.EVACUATE, w.t, zone="vip", autonomy=Autonomy.APPROVE))
        ex = w.apply(Action("ex", ActionKind.REQUEST_EXTERNAL, w.t, zone="front_pit", params={"kind": "ambulance"}))
        pit0 = w.occ[w.L.idx["front_pit"]]
        self.assertEqual(w.observe().clock["show_phase"], "headliner")
        self.assertEqual(w.apply(Action("ss", ActionKind.STOP_SHOW, w.t)).status, ActionStatus.DONE)
        for _ in range(30):
            w.step()
            self.assertTrue(conserved(w))
        self.assertEqual(w.observe().clock["show_phase"], "stopped")
        self.assertEqual(rs.status, ActionStatus.DONE)
        self.assertEqual(w.flags[w.L.idx["water_n"]]["water_l"] > 7000, True)
        self.assertEqual(ev.status, ActionStatus.DONE)
        self.assertLess(w.occ[w.L.idx["vip"]], 50)
        self.assertEqual(ex.status, ActionStatus.DONE)
        self.assertIn(ex.params["resource"], w.resources)
        self.assertLess(w.occ[w.L.idx["front_pit"]], pit0 * 0.7)
        changed = {a.id for a in w.observe().action_results}
        self.assertTrue(changed <= {"rs", "ev", "ex", "ss"})

    def test_inject_accepts_every_world_effect(self):
        w = World.from_case(case(), 1)
        effects = [
            {"kind": "resource_offline", "resource": "amb_1", "reason": "bloqueada"},
            {"kind": "resource_online", "resource": "amb_1"},
            {"kind": "resource_no_answer", "resource": "sec_1", "n": 5},
            {"kind": "resource_rejects", "resource": "sec_2", "n": 5},
            {"kind": "zone_state", "zone": "gate_c", "state": "closed"},
            {"kind": "zone_inflow", "zone": "front_pit", "per_min": 300, "n": 10},
            {"kind": "zone_flag", "zone": "food", "flag": "power", "value": False},
            {"kind": "weather", "temp_c": 40, "wind_kmh": 70, "rain": True, "alert": "naranja"},
            {"kind": "comms_down", "channel": "voice", "n": 4},
            {"kind": "incident", "incident": {"id": "j1", "family": "aggression", "type": "fight", "zone": "food",
                                              "severity": 6, "deadline": 15, "needs": {"security": 1}},
             "reports": [{"channel": "whatsapp", "text": "pelea en las barras"}]},
            {"kind": "transport_cut", "n": 20},
            {"kind": "meteorite"},
        ]
        for e in effects:
            w.inject(e)
        w.inject({"kind": "world", "effect": {"kind": "zone_state", "zone": "gate_c", "state": "restricted"}})
        truth = w.truth()
        errors = [e for e in truth["injected"] if "error" in e]
        self.assertEqual([e["effect"]["kind"] for e in errors], ["meteorite"])
        self.assertEqual(truth["zone_state"]["gate_c"], "restricted")
        self.assertIn("j1", truth["incidents"])
        self.assertEqual(w.weather["temp_c"], 40)
        self.assertEqual(dispatch(w, "x1", "sec_1", zone="food").params["error"], "no_answer")
        self.assertEqual(dispatch(w, "x2", "sec_2", zone="food").status, ActionStatus.REJECTED)
        self.assertEqual(dispatch(w, "x3", "sec_3", zone="food", channel=Channel.VOICE).params["error"], "comms_down")
        self.assertEqual(dispatch(w, "x4", "sec_3", zone="food", channel=Channel.RADIO).status, ActionStatus.EXECUTING)
        for _ in range(30):
            w.step()
            self.assertTrue(conserved(w))


class TestTwin(unittest.TestCase):
    def test_twin_has_no_future_and_does_not_touch_the_real_world(self):
        hot = dict(DEMO, initial={"occupancy": {"gate_b": 1300}, "weather": {"temp_c": 41}})
        w = World.from_case(hot, 7)
        for _ in range(6):
            w.step()
        live = dispatch(w, "d1", "sec_4", incident="i1")
        before = json.dumps(w.truth(), sort_keys=True, default=str)
        rng_before = w.rng.getstate()
        tw = w.twin()
        self.assertTrue(tw.truth()["twin"])
        self.assertNotEqual(tw.rng.getstate(), rng_before)
        self.assertEqual((tw.t, tw.occ, tw.clock()), (w.t, w.occ, w.clock()))
        self.assertEqual(tw.resources["sec_4"].status, ResourceStatus.EN_ROUTE)  # lo que ya está en marcha sigue
        tw.apply(Action("rr", ActionKind.REROUTE, tw.t, zone="gate_b", params={"to": "gate_a"}))
        tw.apply(Action("cl", ActionKind.SET_ZONE, tw.t, zone="gate_c", params={"state": "closed"}))
        texts = []
        for _ in range(60):
            texts += [r.text for r in tw.observe().new_reports]
            tw.step()
        truth = tw.truth()
        self.assertEqual(set(truth["incidents"]) - {"i1"}, {i for i, v in truth["incidents"].items()
                                                           if v["type"] == "crush_risk"})
        self.assertNotIn("i2", truth["incidents"])  # el futuro del caso (t=40) no existe en el gemelo
        self.assertFalse(any("collapsed" in x or "humo" in x for x in texts))
        self.assertFalse(tw.done())
        self.assertEqual(before, json.dumps(w.truth(), sort_keys=True, default=str))
        self.assertEqual(w.rng.getstate(), rng_before)
        self.assertEqual((live.status, w.state[w.L.idx["gate_c"]], w.reroutes), (ActionStatus.EXECUTING, "open", {}))
        self.assertEqual(w.twin().rng.getstate(), w.twin().rng.getstate())
        self.assertNotEqual(w.twin(1).rng.getstate(), w.twin(2).rng.getstate())

    def test_twin_predicts_the_saturation_of_gate_a(self):
        w = World.from_case(DEMO, 7)
        for _ in range(6):
            w.step()
        reroute = lambda t: Action("rr", ActionKind.REROUTE, t, zone="gate_b", params={"to": "gate_a", "fraction": 0.7})
        tw = w.twin()
        tw.apply(reroute(tw.t))
        w.apply(reroute(w.t))
        ga = w.L.idx["gate_a"]
        predicted, real = {}, {}
        for world, out in ((tw, predicted), (w, real)):
            for _ in range(35):
                world.step()
                out[world.t] = world.occ[ga] / world.L.area[ga]
        hit = lambda series, d: next(t for t, v in series.items() if v >= d)
        self.assertLessEqual(abs(hit(predicted, 4.0) - hit(real, 4.0)), 1)   # minuto en que gate_a pasa de 4 /m²
        self.assertLessEqual(abs(hit(predicted, 6.5) - hit(real, 6.5)), 1)
        self.assertLess(max(abs(predicted[t] - real[t]) for t in real), 0.15)
        calm = World.from_case(DEMO, 7).twin()  # la otra rama del ensayo: sin desvío, gate_a ni se entera
        for _ in range(41):
            calm.step()
        self.assertLess(calm.density("gate_a"), 1.0)

    def test_twin_is_as_cheap_as_clone(self):
        w = World.from_case(DEMO, 7)
        for _ in range(30):
            w.step()
        def cost(fn) -> float:
            t0 = time.perf_counter()
            for _ in range(300):
                fn()
            return time.perf_counter() - t0
        cost(w.twin)
        self.assertLess(cost(w.twin), 3 * cost(w.clone) + 0.01)


class TestRealism(unittest.TestCase):
    def test_density_warning_at_4_and_by_trend(self):
        w = World.from_case(DEMO, 7)
        first: dict[str, int] = {}
        while w.t < 30:
            for r in w.observe().new_reports:
                if r.zone_hint == "gate_b" and r.channel == Channel.SENSOR:
                    key = "trend" if r.text.startswith("Tendencia") else "critical" if "ALERTA" in r.text else "level"
                    first.setdefault(key, w.t)
                    self.assertEqual(r.truth_incident is not None, w.t >= 3)
            w.step()
        self.assertLess(first["trend"], first["level"])        # la tendencia avisa antes que el umbral
        self.assertLess(first["level"], first["critical"])
        self.assertLess(w.truth()["peak_density"]["gate_b"]["density"], 9)
        at_level = World.from_case(DEMO, 7)
        while at_level.t < first["level"]:
            at_level.step()
        self.assertLess(at_level.density("gate_b"), 4.0)      # puertas y pasillos avisan a 3,5; zonas estáticas a 4
        calm = World.from_case(case(start_hhmm="22:15", duration_min=60), 1)  # cabeza de cartel normal: sin ruido
        n = 0
        while not calm.done():
            n += len(calm.observe().new_reports)
            calm.step()
        self.assertEqual(n, 0)

    def test_wind_steps(self):
        def run_wind(kmh: int, seeds=range(12)) -> tuple[int, float, list[str]]:
            broken, texts, level = 0, [], 0
            for seed in seeds:
                w = World.from_case(case(duration_min=90, initial={"weather": {"wind_kmh": kmh}}), seed)
                while not w.done():
                    obs = w.observe()
                    texts += [r.text for r in obs.new_reports if r.source == "estación meteorológica"]
                    level = obs.weather["wind_level"]
                    w.step()
                broken += sum(1 for i in w.truth()["incidents"].values() if i["type"] == "structure_risk")
            return level, broken / len(seeds), texts
        l0, b0, t0 = run_wind(30)
        l1, b1, t1 = run_wind(44)
        l2, b2, t2 = run_wind(55)
        l3, b3, t3 = run_wind(68)
        self.assertEqual((l0, l1, l2, l3), (0, 1, 2, 3))
        self.assertEqual((b0, b1, t0), (0, 0, []))
        self.assertEqual(len(t1), 12)                  # preaviso: una vez por ejecución, sin daños
        self.assertTrue(all("escalón 1" in x for x in t1))
        self.assertGreater(len(t2), len(t1))           # con riesgo se repite
        self.assertLess(b2, b3)                        # riesgo < riesgo grave (N=12 semillas)
        self.assertGreater(b3, 1.0)

    def test_flow_out_matches_what_moved(self):
        w = World.from_case(DEMO, 7)
        for _ in range(8):
            w.step()
        before = list(w.occ)
        entered_before = w.population - w.outside
        w.step()
        obs = w.observe()
        delta = {z: 0 for z in obs.zones}
        for z, zone in obs.zones.items():
            self.assertIsInstance(zone.flags["flow_out"], dict)
            for dst, m in zone.flags["flow_out"].items():
                self.assertGreater(m, 0)
                delta[z] -= m
                if dst != "outside":
                    self.assertIn(dst, obs.zones)
                    delta[dst] += m
            delta[z] += zone.flags.get("arrivals", 0)
        self.assertEqual([w.occ[i] - before[i] for i in range(w.L.n)], [delta[z] for z in w.L.ids])
        self.assertEqual(sum(z.flags.get("arrivals", 0) for z in obs.zones.values()),
                         w.population - w.outside - entered_before)
        self.assertGreater(obs.zones["gate_b"].flags["flow_out"]["corridor_n"], 0)

    def test_transport_reinforcement_relieves_the_exit(self):
        def left_inside(reinforce: bool) -> tuple[int, Action]:
            cut = {"t": 1, "kind": "world", "effect": {"kind": "transport_cut"}}
            w = World.from_case(case(start_hhmm="23:40", duration_min=80, events=[cut]), 1)
            a = Action("tr", ActionKind.REQUEST_EXTERNAL, 2, params={"kind": "transport"}, autonomy=Autonomy.APPROVE)
            while not w.done():
                if reinforce and w.t == 2:
                    self.assertEqual(w.apply(a).status, ActionStatus.EXECUTING)
                w.step()
                self.assertTrue(conserved(w))
            return sum(w.occ), a
        stuck, _ = left_inside(False)
        relieved, a = left_inside(True)
        self.assertEqual((a.status, a.params["outcome"]), (ActionStatus.DONE, "transport_reinforced"))
        self.assertNotIn("resource", a.params)
        self.assertLess(relieved, stuck * 0.6)


class TestConditionalEvents(unittest.TestCase):
    CASE = {"id": "cond", "seed": 1, "day": 2, "start_hhmm": "19:00", "duration_min": 40,
            "initial": {"spontaneous": False}, "events": [
                {"t": 1, "kind": "incident", "incident": {"id": "i1", "family": "medical", "type": "fainting",
                                                          "zone": "general", "severity": 6, "deadline": 30,
                                                          "needs": {"medical": 1}}, "reports": []},
                {"t": 20, "kind": "incident", "cond": {"unless_resolved": "i1"},
                 "incident": {"id": "i2", "family": "medical", "type": "cardiac_arrest", "zone": "general",
                              "severity": 9, "deadline": 28, "needs": {"medical": 1}},
                 "reports": [{"channel": "radio", "text": "ha dejado de respirar"}]},
                {"t": 20, "kind": "world", "cond": {"unless_resolved": "i1"},
                 "effect": {"kind": "zone_flag", "zone": "food", "power": False}},
                {"t": 21, "kind": "world", "cond": {"unless_resolved": "no-existe"},
                 "effect": {"kind": "zone_state", "zone": "gate_c", "state": "restricted"}}]}

    def _run(self, attend: bool) -> tuple[dict, World]:
        w = World.from_case(self.CASE, 1)
        while not w.done():
            if attend and w.t == 1:
                self.assertEqual(dispatch(w, "d1", "med_3", incident="i1").status, ActionStatus.DONE)  # ya está en general
            w.step()
        return w.truth(), w

    def test_resolved_origin_skips_the_chained_event(self):
        truth, w = self._run(attend=True)
        self.assertEqual(truth["incidents"]["i1"]["status"], "resolved")
        self.assertLess(truth["incidents"]["i1"]["t_resolved"], 20)
        self.assertNotIn("i2", truth["incidents"])
        self.assertTrue(w.flags[w.L.idx["food"]]["power"])
        self.assertEqual([(e["t"], e["what"], e["cond"]) for e in truth["skipped_events"]],
                         [(20, "i2", {"unless_resolved": "i1"}), (20, "zone_flag", {"unless_resolved": "i1"})])
        self.assertTrue(all("i1 resolved" in e["reason"] for e in truth["skipped_events"]))
        self.assertFalse(any("ha dejado de respirar" in r.text for r in w.reports))
        self.assertEqual(truth["zone_state"]["gate_c"], "restricted", "un id desconocido no bloquea el evento")
        self.assertEqual(w.clone().truth()["skipped_events"], truth["skipped_events"])

    def test_unattended_origin_spawns_the_chained_event(self):
        truth, w = self._run(attend=False)
        self.assertEqual(truth["incidents"]["i2"]["t_open"], 20)
        self.assertFalse(w.flags[w.L.idx["food"]]["power"])
        self.assertEqual(truth["skipped_events"], [])


class TestComms(unittest.TestCase):
    def test_answers(self):
        w = World.from_case(DEMO, 7)
        comms = SimComms(w, 7, p_reject=0.0, p_no_answer=0.0)
        while w.t < 10:
            w.step()
        w.inject({"kind": "resource_no_answer", "resource": "med_2", "n": 5})
        w.inject({"kind": "resource_rejects", "resource": "med_3", "n": 5})
        obs = w.observe()
        comms.send(Action("c1", ActionKind.DISPATCH, w.t, resource="med_1", zone="front_pit"), obs.resources["med_1"])
        comms.send(Action("c2", ActionKind.DISPATCH, w.t, resource="med_2", zone="front_pit"), obs.resources["med_2"])
        comms.send(Action("c3", ActionKind.DISPATCH, w.t, resource="med_3", zone="front_pit"), obs.resources["med_3"])
        comms.send(Action("c4", ActionKind.ASK, w.t, zone="gate_b"), None)
        got: dict[str, dict] = {}
        while w.t < 60:
            w.step()
            if w.t == 55:  # el aviso de humo es falso: no tiene incidente verdadero detrás
                smoke = [r for r in w.observe().new_reports if r.channel == Channel.SMS][0]
                self.assertIsNone(smoke.truth_incident)
                comms.send(Action("c5", ActionKind.ASK, w.t, params={"report": smoke.id}), None)
            for r in comms.poll(w.t):
                self.assertGreaterEqual(set(r), {"action_id", "result", "text", "t"})
                self.assertLessEqual(r["t"], w.t)
                got[r["action_id"]] = r
        self.assertEqual(comms.poll(w.t + 10), [])
        self.assertEqual([got[k]["result"] for k in ("c1", "c2", "c3", "c4", "c5")],
                         ["accept", "no_answer", "reject", "answer", "answer"])
        self.assertTrue(got["c4"]["data"]["exists"])
        self.assertEqual(got["c4"]["data"]["zone"], "gate_b")
        self.assertFalse(got["c5"]["data"]["exists"])

    def test_comms_seeded(self):
        def results(seed: int) -> list[str]:
            w = World.from_case(case(), 1)
            c = SimComms(w, seed, p_reject=0.3, p_no_answer=0.3)
            for i in range(40):
                c.send(Action(f"a{i}", ActionKind.DISPATCH, 0, resource="sec_1", zone="food"), w.resources["sec_1"])
            return [r["result"] for r in c.poll(10)]
        self.assertEqual(results(4), results(4))
        self.assertEqual(set(results(4)), {"accept", "reject", "no_answer"})


class TestOpsLayer(unittest.TestCase):
    """Capa de «operación real» (`initial.ops`): opcional; sin ella el mundo es el de siempre."""

    PERSON = {"t": 1, "kind": "incident", "incident": {"id": "i1", "family": "medical", "type": "fainting", "zone": "general",
                                                       "severity": 6, "deadline": 40, "needs": {"medical": 1}},
              "reports": [{"channel": "whatsapp", "source": "asistente", "text": "Una chica se ha desmayado", "zone_hint": "general"}]}

    def _resupply_done_at(self, ops: dict | None) -> int:
        init = {"spontaneous": False, "flags": {"water_n": {"water_l": 50}}}
        if ops:
            init["ops"] = ops
        w = World.from_case(case(initial=init))
        a = w.apply(Action("r1", ActionKind.RESUPPLY, w.t, zone="water_n", resource="log_1"))
        eta = a.params["eta"]
        while a.status is ActionStatus.EXECUTING and w.t < 59:
            w.step()
        self.assertIs(a.status, ActionStatus.DONE)
        self.assertGreater(w.observe().zones["water_n"].flags["water_l"], 7900)     # lleno (menos lo bebido ese minuto)
        return w.t - eta

    def test_resupply_minutes_are_per_point_and_off_by_default(self) -> None:
        plain = self._resupply_done_at(None)
        slow = self._resupply_done_at({"resupply_min": {"water_n": [25, 25]}})
        other = self._resupply_done_at({"resupply_min": {"water_s": [25, 25]}})
        self.assertEqual(slow - plain, 25 - load_festival()["params"]["resupply_min"])
        self.assertEqual(other, plain)      # el rango de OTRO punto no afecta a este

    def test_water_level_is_observable_and_stockouts_are_counted(self) -> None:
        w = World.from_case(case(initial={"spontaneous": False, "weather": {"temp_c": 38},
                                          "flags": {"water_n": {"water_l": 120}}}, duration_min=30))
        levels = []
        while not w.done():
            levels.append(w.observe().zones["water_n"].flags["water_l"])
            w.step()
        self.assertTrue(all(a >= b for a, b in zip(levels, levels[1:])))     # se ve bajar minuto a minuto
        self.assertEqual(levels[-1], 0)
        water = w.truth()["water"]
        self.assertEqual([x["zone"] for x in water["stockouts"]], ["water_n"])
        self.assertGreater(water["dry_minutes"]["water_n"], 0)
        self.assertNotIn("water_s", water["dry_minutes"])

    def test_search_in_wide_zone_costs_minutes_without_a_point(self) -> None:
        ops = {"locate": {"zones": {"general": [6, 6]}, "p_point": 1.0}}
        arrivals = {}
        for name, extra, o in (("plain", {}, None), ("search", {}, ops), ("point", {"point": "la torre de sonido"}, ops)):
            w = World.from_case(case(initial={"spontaneous": False, **({"ops": o} if o else {})}, events=[self.PERSON]))
            w.step()
            a = dispatch(w, "d1", "med_1", zone="general", params=dict(extra))
            while a.status is ActionStatus.EXECUTING:
                w.step()
            arrivals[name] = (w.t, a.params.get("search_min"), w.truth()["incidents"]["i1"].get("search_min"))
        self.assertEqual(arrivals["search"][0] - arrivals["plain"][0], 6)
        self.assertEqual(arrivals["search"][1:], (6, 6))          # lo cuenta el equipo (observable) y queda en la verdad
        self.assertEqual(arrivals["point"][0], arrivals["plain"][0])
        self.assertEqual(arrivals["point"][1], 0)
        self.assertIsNone(arrivals["plain"][1])                   # sin capa de operación no existe el concepto

    def test_point_by_notify_cuts_the_search_and_ask_gives_the_point(self) -> None:
        ops = {"locate": {"zones": {"general": [9, 9]}, "p_point": 1.0}}
        w = World.from_case(case(initial={"spontaneous": False, "ops": ops}, events=[self.PERSON]))
        comms = SimComms(w, 1)
        w.step()
        ask = Action("q1", ActionKind.ASK, w.t, zone="general", channel=Channel.WHATSAPP,
                     params={"purpose": "point", "precise": True, "reports": [w.reports[0].id]})
        comms.send(ask)
        plain = Action("q2", ActionKind.ASK, w.t, zone="general", channel=Channel.WHATSAPP, params={"reports": [w.reports[0].id]})
        comms.send(plain)
        replies = {r["action_id"]: r for r in comms.poll(w.t + 5)}
        self.assertTrue(replies["q1"]["data"]["point"])
        self.assertNotIn("point", replies["q2"]["data"])          # solo si se PIDE un punto concreto
        a = dispatch(w, "d1", "med_1", zone="general")
        while w.resources["med_1"].zone != "general":
            w.step()
        w.step()
        t_search = w.t
        self.assertIs(a.status, ActionStatus.EXECUTING)           # está buscando
        w.apply(Action("n1", ActionKind.NOTIFY, w.t, resource="med_1", params={"point": replies["q1"]["data"]["point"]}))
        while a.status is ActionStatus.EXECUTING:
            w.step()
        self.assertLessEqual(w.t - t_search, 2)
        self.assertLess(a.params["search_min"], 9)

    def test_contact_profile_per_resource(self) -> None:
        ops = {"contact": {"med_1": {"p_no_answer": 1.0, "p_reject": 0.0}, "med_2": {"p_no_answer": 0.0, "p_reject": 0.0}}}
        w = World.from_case(case(initial={"spontaneous": False, "ops": ops}, events=[self.PERSON]))
        comms = SimComms(w, 5)
        w.step()
        for rid in ("med_1", "med_2"):
            comms.send(Action(f"d-{rid}", ActionKind.DISPATCH, w.t, resource=rid, zone="general", channel=Channel.VOICE),
                       w.resources[rid])
        got = {r["action_id"]: r["result"] for r in comms.poll(w.t + 5)}
        self.assertEqual(got, {"d-med_1": "no_answer", "d-med_2": "accept"})

    def test_twin_does_not_leak_search_state(self) -> None:
        ops = {"locate": {"zones": {"general": [8, 8]}, "p_point": 1.0}}
        w = World.from_case(case(initial={"spontaneous": False, "ops": ops}, events=[self.PERSON]))
        w.step()
        a = dispatch(w, "d1", "med_3", zone="general")
        w.step(); w.step()
        tw = w.twin()
        for _ in range(12):
            tw.step()
        self.assertIs(a.status, ActionStatus.EXECUTING)           # el futuro ensayado no toca la acción real
        while a.status is ActionStatus.EXECUTING:
            w.step()
        self.assertEqual(a.params["search_min"], 8)


class TestPerformance(unittest.TestCase):
    def test_90_minutes_well_under_50_ms(self):
        run(DEMO, 7, reroute_at=6, verbose=False)
        t0 = time.perf_counter()
        for _ in range(20):
            run(DEMO, 7, reroute_at=6, verbose=False)
        ms = (time.perf_counter() - t0) / 20 * 1000
        self.assertLess(ms, 25, f"{ms:.1f} ms por caso de 90 min")


if __name__ == "__main__":
    unittest.main()
