"""Contrafactual pareado: dato simulado, determinista, sin tocar mundo ni acción."""
import copy
import unittest
from motor.contracts import Action, ActionKind, ActionStatus
from motor.world import World
from motor.server.recibo import calculate, observe


def gate_world():
    return World.from_case({"id": "receipt", "seed": 7, "start_hhmm": "21:30", "duration_min": 40,
                            "initial": {"occupancy": {"gate_b": 1500}}, "events": []}, 7)


class ReceiptTests(unittest.TestCase):
    def test_deterministic_isolated_and_no_effect(self):
        w = gate_world()
        a = Action("X", ActionKind.NOTIFY, 0, zone="gate_b", status=ActionStatus.EXECUTING)
        before, act = copy.deepcopy(w.truth()), copy.deepcopy(a)
        r = calculate(w, a, minutes=15)
        self.assertEqual(r, calculate(w, a, minutes=15))
        self.assertEqual(r["verdict"], "sin_cambio")
        self.assertIn("No cambió nada medible", r["text"])
        self.assertEqual(w.truth(), before)
        self.assertEqual(a, act)
        self.assertEqual(r["N"], 1)

    def test_veto_can_be_right_and_can_be_wrong(self):
        w = gate_world()
        w.inject({"kind": "zone_inflow", "zone": "gate_b", "per_min": 260, "n": 15})
        a = Action("R", ActionKind.REROUTE, 0, zone="gate_b", params={"to": "gate_a", "fraction": .6},
                   status=ActionStatus.EXECUTING)
        yes, no = calculate(w, a), calculate(w, a, accepted=False)
        self.assertNotEqual(yes["verdict"], "sin_cambio")
        self.assertEqual(yes["benefit"], -no["benefit"])
        self.assertEqual(no["counter_label"], "Si se hubiera aprobado")
        # Desviar desde una puerta vacía hacia la ya saturada es perjudicial.
        w2 = gate_world()
        w2.inject({"kind": "zone_inflow", "zone": "gate_a", "per_min": 260, "n": 15})
        bad = Action("BAD", ActionKind.REROUTE, 0, zone="gate_a", params={"to": "gate_b", "fraction": 1},
                     status=ActionStatus.EXECUTING)
        veto = calculate(w2, bad, accepted=False)
        self.assertGreater(veto["benefit"], 0)
        self.assertIn(veto["verdict"], ("mejor", "mixto"))  # puede mejorar el balance y trasladar densidad

    def test_observed_comparison_and_horizon_cap(self):
        w = gate_world()
        a = Action("X", ActionKind.NOTIFY, 0, zone="gate_b", status=ActionStatus.EXECUTING)
        live = w.clone()
        live.apply(copy.deepcopy(a))
        frames = []
        for _ in range(4):
            live.step()
            frames.append(observe(live))
        r = calculate(w, a, minutes=100, observed=frames)
        self.assertEqual(r["minutes"], 4)
        self.assertTrue(r["censored"])
        self.assertEqual(r["factual_source"], "observado_en_simulador")
        self.assertLessEqual(calculate(w, a, minutes=100)["minutes"], 15)

    def test_later_actions_are_replayed_but_not_mutated(self):
        w = gate_world()
        a = Action("X", ActionKind.NOTIFY, 0, zone="gate_b", status=ActionStatus.EXECUTING)
        later = [{"t": 2, "action": Action("R", ActionKind.REROUTE, 2, zone="gate_b",
                  params={"to": "gate_c", "fraction": .5}, status=ActionStatus.EXECUTING)}]
        old = copy.deepcopy(later)
        self.assertEqual(calculate(w, a, later=later)["verdict"], "sin_cambio")
        self.assertEqual(later, old)


class ReceiptRuntimeTests(unittest.TestCase):
    def test_worker_receipt_matches_actual_and_caps(self):
        from motor.server.evidence_runtime import ReceiptService
        service = ReceiptService()
        self.addCleanup(service.close)
        w = gate_world()
        for i in range(12):
            a = Action(f"R{i}", ActionKind.REROUTE, 0, zone="gate_b", params={"to": "gate_c", "fraction": .1},
                       status=ActionStatus.EXECUTING)
            service.capture(w, a)
            w.apply(a)
        for _ in range(15):
            w.step()
            service.observe(w)
        service.wait()
        result = service.view()
        self.assertEqual(result["N"], 10)
        self.assertEqual(result["pending"], 0)
        self.assertGreaterEqual(result["skipped"], 2)
        self.assertTrue(all(r["factual_source"] == "observado_en_simulador" for r in result["items"]))

    def test_veto_recorded_and_reserved_receipt_hidden(self):
        from motor.server.evidence_runtime import ReceiptService
        service = ReceiptService()
        self.addCleanup(service.close)
        w = gate_world()
        a = Action("V", ActionKind.REROUTE, 0, incident="private", zone="gate_b", params={"to": "gate_a", "fraction": .6})
        service.capture(w, a, accepted=False, human=True)
        for _ in range(15):
            w.step()
            service.observe(w)
        service.wait()
        self.assertFalse(service.view()["items"][0]["accepted"])
        self.assertEqual(service.view({"private"})["items"], [])

    def test_external_effect_only_replayed_once(self):
        from motor.server.evidence_runtime import ReceiptService
        service = ReceiptService()
        self.addCleanup(service.close)
        w = gate_world()
        a = Action("B", ActionKind.BROADCAST, 0, zone="gate_b")
        service.capture(w, a, accepted=False, human=True)
        w.inject({"kind": "zone_inflow", "zone": "gate_c", "per_min": 80, "n": 4})
        for _ in range(15):
            w.step()
            service.observe(w)
        service.wait()
        row = service.view()["items"][0]
        self.assertEqual(row["minutes"], 15)
        self.assertEqual(len(service.pending["B"]["later"]), 1)

    def test_human_priority_is_independent_of_worker_completion(self):
        from motor.server.evidence_runtime import ReceiptService
        services = [ReceiptService(), ReceiptService()]
        for s in services:
            self.addCleanup(s.close)
            w = gate_world()
            for i in range(10):
                s.capture(w, Action(f'a{i}', ActionKind.REROUTE, 0, zone='gate_b', params={'to':'gate_a','fraction':.1}))
            for _ in range(15):
                w.step(); s.observe(w)
            if s is services[0]:
                s.wait()
            s.capture(w, Action('H', ActionKind.STOP_SHOW, w.t), accepted=False, human=True)
            for _ in range(15):
                w.step(); s.observe(w)
            s.wait()
        self.assertEqual(services[0].view()['items'], services[1].view()['items'])
