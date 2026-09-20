"""Pruebas de la lista fija con desvíos, usando el mundo y las comunicaciones reales."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

import motor.baseline as baseline
from motor.contracts import ALWAYS_APPROVE, ActionKind, ActionStatus, Autonomy
from motor.world import SimComms, World


_CASE = Path(__file__).resolve().parent.parent / "world" / "demo_case.json"


class BaselineRerouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.case = json.loads(_CASE.read_text(encoding="utf-8"))
        self.assertTrue(hasattr(baseline, "BaselineReroute"), "falta exportar BaselineReroute")

    def _start(self, agent_type=None):
        world = World.from_case(self.case, self.case["seed"])
        comms = SimComms(world, self.case["seed"])
        agent = (agent_type or baseline.BaselineReroute)(comms=comms)
        return world, agent

    def _run(self, agent_type=None, decision=None):
        world, agent = self._start(agent_type)
        approved = set()
        emitted = []
        while not world.done():
            for action in agent.tick(world.observe()):
                emitted.append(action.to_dict())
                if action.status == ActionStatus.AWAITING_APPROVAL:
                    self.assertEqual(action.autonomy, Autonomy.APPROVE)
                    if decision is not None:
                        agent.approve(action.id, decision)
                        if decision:
                            approved.add(action.id)
                    continue
                if action.kind in ALWAYS_APPROVE:
                    self.assertIn(action.id, approved, "ejecución sin aprobación humana")
                world.apply(action)
            world.step()
        return world.truth(), agent.snapshot(), emitted, world.observe()

    def test_demo_with_destination_inflow_overloads_gate_a_and_is_never_removed(self):
        # Simulación N=1, semilla 7: la demo sin tráfico propio del destino alcanza 4.77/m²,
        # no >5. Este fixture añade llegadas explícitas a A; no cambia el mundo ni el umbral.
        self.case["events"].append({"t": 2, "kind": "world", "effect": {
            "kind": "zone_inflow", "zone": "gate_a", "per_min": 20, "n": 45,
            "reason": "fixture sintético: tráfico propio del destino"}})
        truth, snapshot, emitted, obs = self._run()
        reroutes = [a for a in emitted if a["kind"] == ActionKind.REROUTE]
        self.assertTrue(any(a["zone"] == "gate_b" and a["params"] ==
                            {"to": "gate_a", "fraction": 0.6} for a in reroutes))
        self.assertTrue(all(a["params"]["fraction"] == 0.6 and "cancel" not in a["params"]
                            and "minutes" not in a["params"] for a in reroutes))
        self.assertEqual(obs.zones["gate_b"].flags["reroute_to"], "gate_a")
        self.assertGreater(truth["peak_density"]["gate_a"]["density"], 5)
        self.assertGreater(truth["minutes_over_5"]["gate_a"], 0)
        plain_truth, _, _, _ = self._run(baseline.Baseline)
        self.assertLess(plain_truth["peak_density"]["gate_a"]["density"], 5)
        self.assertEqual(snapshot["plans"], [])
        self.assertEqual(snapshot["agent"], "baseline_reroute")

    def test_demo_is_deterministic(self):
        first = self._run()
        second = self._run()
        self.assertEqual(first[:3], second[:3])

    def test_demo_always_approve_waits_for_human(self):
        for decision in (None, False, True):
            with self.subTest(decision=decision):
                truth, _, emitted, _ = self._run(decision=decision)
                requests = [a for a in emitted if a["kind"] in ALWAYS_APPROVE]
                self.assertTrue(requests, "la demo debe ejercitar una aprobación")
                executed = [a for a in truth["actions"] if a["kind"] in ALWAYS_APPROVE]
                self.assertEqual(bool(executed), decision is True)

    def test_manual_destinations_ignore_destination_occupancy(self):
        for source, destination in (("gate_b", "gate_a"), ("gate_a", "gate_b"), ("gate_c", "gate_b")):
            for occupancy in (0, 8000):
                with self.subTest(source=source, occupancy=occupancy):
                    self.case["initial"]["occupancy"] = {"gate_b": 1300, destination: occupancy}
                    world, agent = self._start()
                    world.inject({"kind": "report_only", "reports": [
                        {"channel": "radio", "zone_hint": source, "text": "Puerta saturada, no avanza la cola"}
                    ]})
                    world.step()
                    reroutes = [a for a in agent.tick(world.observe()) if a.kind == ActionKind.REROUTE]
                    self.assertEqual([(a.zone, a.params) for a in reroutes],
                                     [(source, {"to": destination, "fraction": 0.6})])

    def test_dispatches_keep_arrival_order_and_do_not_merge(self):
        world, agent = self._start()
        world.inject({"kind": "report_only", "reports": [
            {"channel": "radio", "text": "Cola atascada en la puerta B"},
            {"channel": "radio", "text": "Cola atascada en la puerta B"},
            {"channel": "radio", "text": "Arma en el foso"},
        ]})
        world.step()
        obs = world.observe()
        expected = baseline.Baseline().tick(obs)
        actual = agent.tick(obs)
        dispatches = lambda actions: [(a.zone, a.resource, a.params) for a in actions
                                     if a.kind == ActionKind.DISPATCH]
        self.assertEqual(dispatches(actual), dispatches(expected))
        self.assertEqual(len(dispatches(actual)), 3)
        self.assertFalse(any(a.kind == ActionKind.MERGE for a in actual))
        self.assertEqual(len([a for a in actual if a.kind == ActionKind.REROUTE]), 1)
        self.assertEqual(agent.snapshot()["plans"], [])

    def test_unrelated_reports_do_not_reroute(self):
        world, agent = self._start()
        world.inject({"kind": "report_only", "reports": [
            {"channel": "radio", "zone_hint": "gate_b", "text": "Una persona mareada"},
            {"channel": "radio", "zone_hint": "food", "text": "Cola atascada"},
            {"channel": "radio", "text": "Puerta saturada, no sé cuál"},
        ]})
        world.step()
        obs = world.observe()
        self.assertEqual(len(obs.new_reports), 3)
        self.assertFalse(any(a.kind == ActionKind.REROUTE for a in agent.tick(obs)))


if __name__ == "__main__":
    unittest.main()
