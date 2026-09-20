"""Legacy safety regressions. Simulation only; no provider transports."""
import os
import threading
import time
import unittest
from unittest.mock import patch

from motor.contracts import ActionKind, ActionStatus, IncidentStatus, ResourceStatus
from motor.server import cerebro, cerebro_tools
from motor.server.app import create_app
from motor.server.rapido import Run


class SafetyDecisionTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {
            "MANDO_CEREBRO": "reglas", "MANDO_DB": "off", "MANDO_LEDGER_PATH": "",
            "TELEGRAM_MODE": "off", "HR_WORKFLOW_RAPIDO": "", "MANDO_TG_ROSTER": "off",
        })
        env.start()
        self.addCleanup(env.stop)
        self.app = create_app("demo-gates", threaded=False, comms_mode="sim")
        self.s = self.app.state.session
        self.addCleanup(self.app.state.chat.stop)
        self.addCleanup(self.s.close)

    def decide(self, **overrides):
        body = {"incident_id": "nuevo", "zona": "gate_b", "porque": "Comprobar una cola en la puerta B"}
        body.update(overrides)
        return cerebro_tools.decidir(self.s, body)

    def run_for(self, iid):
        run = Run(iid, "report-test", f"{self.s.session_id}:report-test",
                  deadline=time.monotonic() + 60)
        self.s.rapido.runs[iid] = run
        return run

    def test_human_gate_defers_dispatch_and_notification_until_approval(self):
        with patch.object(self.s.comms, "send") as send:
            out = self.decide(requiere_persona=True, recursos=["sec_2"],
                              avisar=[{"rol": "sec_2", "mensaje": "Comprobar cola"}])
            self.assertTrue(out["pendiente"])
            self.assertEqual(self.s.agent.assign, {})
            self.assertEqual(self.s.world.resources["sec_2"].status, ResourceStatus.AVAILABLE)
            send.assert_not_called()
            aid = next(a["action_id"] for a in out["aceptadas"] if a.get("tarjeta"))
            self.s.agent.approve(aid, True, "Adelante")
            self.assertEqual(self.s.agent.actions[aid].status, ActionStatus.DONE)
            self.assertEqual(self.s.agent.assign["sec_2"][0], out["incident_id"])
            self.assertEqual(send.call_count, 2)
            self.s.agent.approve(aid, True)
            self.assertEqual(send.call_count, 2)

    def test_approval_revalidates_resource_and_does_not_notify_on_conflict(self):
        out = self.decide(requiere_persona=True, recursos=["sec_2"],
                          avisar=[{"rol": "sec_2", "mensaje": "Comprobar cola"}])
        aid = out["aceptadas"][0]["action_id"]
        self.s.world.resources["sec_2"].status = ResourceStatus.OFFLINE
        with patch.object(self.s.comms, "send") as send:
            self.s.agent.approve(aid, True)
            send.assert_not_called()
        self.assertEqual(self.s.agent.actions[aid].status, ActionStatus.FAILED)
        self.assertEqual(self.s.agent.assign, {})

    def test_security_cannot_cover_medical_emergency(self):
        for resource in self.s.world.resources.values():
            if str(resource.kind) in ("medical", "ambulance"):
                resource.status = ResourceStatus.OFFLINE
        out = self.decide(zona="front_pit", porque="Persona no responde y no respira", recursos=["sec_2"])
        self.assertTrue(any(row.get("recurso") == "sec_2" for row in out["aceptadas"]))
        self.assertTrue(any(row.get("que") == "despacho vital" for row in out["bloqueadas"]))
        self.assertNotIn(out["incident_id"], self.s._cerebro_decided)

    def test_human_gate_does_not_block_independent_vital_medical_dispatch(self):
        out = self.decide(zona="front_pit", porque="Persona no responde y no respira",
                          requiere_persona=True, recursos=["sec_2"])
        self.assertNotIn("sec_2", self.s.agent.assign)
        self.assertTrue(any(row.get("origen") == "barandilla" and row.get("kind") == "dispatch"
                            for row in out["aceptadas"]))

    def test_invalid_later_action_has_no_earlier_effect(self):
        for malformed in ({"kind": "not-a-kind"}, {"kind": "set_zone", "zone": []},
                          {"kind": "reroute", "to": "gate_c", "fraction": "not-a-number"}):
            with self.subTest(action=malformed), patch.object(self.s.comms, "send") as send:
                with self.assertRaises(ValueError):
                    self.decide(acciones=[{"kind": "dispatch", "resource": "sec_2"}, malformed])
                send.assert_not_called()
                self.assertEqual(self.s.agent.assign, {})
                self.assertEqual(self.s.agent.actions, {})

    def test_invalid_destination_and_route_have_no_effects(self):
        with patch.object(self.s.comms, "send") as send:
            out = self.decide(recursos=[{"id": "sec_2", "zona": "unknown"}])
            self.assertFalse(out["ok"])
            with patch.object(self.s.world, "travel_time", return_value=None):
                out = self.decide(recursos=["sec_2"])
                self.assertFalse(out["ok"])
            send.assert_not_called()
        self.assertEqual(self.s.agent.assign, {})
        self.assertEqual(self.s.agent.actions, {})

    def test_invalid_notification_does_not_leave_earlier_dispatch(self):
        with patch.object(self.s.comms, "send") as send:
            out = self.decide(recursos=["sec_2"], avisar=[{"rol": "unknown", "mensaje": "Comprobar"}])
            self.assertFalse(out["ok"])
            send.assert_not_called()
        self.assertEqual(self.s.agent.assign, {})

    def test_clock_cannot_advance_during_reservation_and_application(self):
        entered, release, ticked = threading.Event(), threading.Event(), threading.Event()
        self.addCleanup(release.set)
        apply = self.s.world.apply

        def slow_apply(action):
            entered.set()
            self.assertTrue(release.wait(3))
            apply(action)

        def tick():
            self.s.tick()
            ticked.set()

        with patch.object(self.s.world, "apply", side_effect=slow_apply):
            decision = threading.Thread(target=lambda: self.decide(recursos=["sec_2"]))
            decision.start()
            self.assertTrue(entered.wait(3))
            clock = threading.Thread(target=tick)
            clock.start()
            self.assertFalse(ticked.wait(.05))
            release.set()
            decision.join(5)
            clock.join(5)
            self.assertTrue(ticked.is_set())
            self.assertFalse(decision.is_alive())

    def test_application_failure_rolls_back_prior_action_and_reservation(self):
        apply = self.s.world.apply

        def fail_second(action):
            if action.kind == ActionKind.NOTIFY:
                raise RuntimeError("injected world failure")
            apply(action)

        with patch.object(self.s.comms, "send") as send, patch.object(self.s.world, "apply", side_effect=fail_second):
            with self.assertRaisesRegex(ValueError, "falló la aplicación"):
                self.decide(recursos=["sec_2"], avisar=[{"rol": "sec_2", "mensaje": "Comprobar cola"}])
            send.assert_not_called()
        self.assertEqual(self.s.agent.assign, {})
        self.assertEqual(self.s.agent.actions, {})
        self.assertEqual(self.s.world.resources["sec_2"].status, ResourceStatus.AVAILABLE)
        self.assertEqual(self.s.receipts.captured, set())

    def test_failed_world_status_is_not_acknowledged_as_success(self):
        def reject(action):
            action.status = ActionStatus.FAILED
            action.params["error"] = "route_blocked"

        with patch.object(self.s.comms, "send") as send, patch.object(self.s.world, "apply", side_effect=reject):
            with self.assertRaisesRegex(ValueError, "route_blocked"):
                self.decide(recursos=["sec_2"])
            send.assert_not_called()
        self.assertEqual(self.s.agent.assign, {})

    def test_concurrent_decisions_reserve_one_owner(self):
        barrier = threading.Barrier(3)
        results = []

        def worker():
            barrier.wait()
            results.append(self.decide(recursos=["sec_2"]))

        with patch.object(self.s.comms, "send"):
            threads = [threading.Thread(target=worker) for _ in range(2)]
            for thread in threads:
                thread.start()
            barrier.wait()
            for thread in threads:
                thread.join(5)
                self.assertFalse(thread.is_alive())
        self.assertEqual(sum(result["ok"] for result in results), 1)
        owners = [inc for inc in self.s.agent.incidents.values() if "sec_2" in inc.assigned]
        self.assertEqual(len(owners), 1)

    def test_sends_happen_after_world_dispatch_commit(self):
        def send(action, resource):
            if action.kind == ActionKind.DISPATCH:
                self.assertNotEqual(self.s.world.resources[action.resource].status, ResourceStatus.AVAILABLE)
                self.assertEqual(self.s.agent.assign[action.resource][0], action.incident)

        with patch.object(self.s.comms, "send", side_effect=send):
            self.decide(recursos=["sec_2"])

    def test_explicit_merge_cannot_leave_two_active_owners(self):
        first = self.decide(recursos=["sec_2"])["incident_id"]
        second = self.decide(zona="gate_c")["incident_id"]
        with self.assertRaisesRegex(ValueError, "fusión"):
            self.decide(incident_id=second, fusionar_con=first)
        self.assertEqual(self.s.agent.assign["sec_2"][0], first)
        self.assertIn(second, self.s.agent.incidents)

    def test_rapid_replay_returns_saved_result_without_another_notification(self):
        iid = self.decide()["incident_id"]
        run = self.run_for(iid)
        body = dict(incident_id=iid, fase="rapida", agente="rapido", correlation_id=run.correlation_id,
                    recursos=["sec_2"], avisar=[{"rol": "sec_2", "mensaje": "Comprobar cola"}])
        with patch.object(self.s.comms, "send") as send:
            first = self.decide(**body)
            second = self.decide(**body)
            self.assertEqual(first["aceptadas"], second["aceptadas"])
            self.assertTrue(second["duplicate"])
            self.assertEqual(send.call_count, 2)
            with self.assertRaisesRegex(ValueError, "otra decisión"):
                self.decide(**dict(body, avisar=[]))

    def test_rapid_rejects_invalid_expired_resolved_and_superseded_runs(self):
        iid = self.decide()["incident_id"]
        run = self.run_for(iid)
        body = dict(incident_id=iid, fase="rapida", agente="rapido",
                    correlation_id=run.correlation_id, recursos=["sec_2"])
        with self.assertRaisesRegex(ValueError, "hace falta correlation"):
            self.decide(**dict(body, correlation_id=""))
        with self.assertRaises(ValueError):
            self.decide(**dict(body, correlation_id="malformed"))
        for status in ("timeout", "fallido", "superseded"):
            run.status = status
            with self.assertRaises(ValueError):
                self.decide(**body)
        run.status = "en_curso"
        run.deadline = time.monotonic() - 1
        with self.assertRaisesRegex(ValueError, "expirada"):
            self.decide(**body)
        run.status, run.deadline = "en_curso", time.monotonic() + 60
        self.s.agent.incidents[iid].status = IncidentStatus.RESOLVED
        with self.assertRaisesRegex(ValueError, "cerrado"):
            self.decide(**body)
        self.assertEqual(self.s.agent.assign, {})

    def test_review_failure_and_missing_review_remain_visible(self):
        iid = self.decide()["incident_id"]
        run = self.run_for(iid)
        body = dict(incident_id=iid, fase="rapida", correlation_id=run.correlation_id)
        self.decide(**body)
        run.review_deadline = time.monotonic() - 1
        self.assertEqual(self.s.rapido.view()["runs"][0]["revision_status"], "timeout")
        with self.assertRaisesRegex(ValueError, "revisión expirada"):
            self.decide(**dict(body, fase="revision", veredicto="confirma"))
        for status in ("failed", "timeout", "degraded"):
            out = self.decide(**dict(body, fase="revision", status=status, error="child failed"))
            self.assertFalse(out["ok"])
            row = self.s.rapido.view()["runs"][0]
            self.assertFalse(row["revision"])
            self.assertEqual(row["revision_error"], "child failed")
        self.assertEqual(self.s.agent.actions, {})

    def test_dirty_plan_can_replan_after_prior_decision(self):
        iid = self.decide()["incident_id"]
        cerebro.mark_decided(self.s, iid)
        self.s.agent.meta[iid].dirty = "el recurso quedó libre"
        self.s.agent.meta[iid].broken = None
        seen = []
        with patch.dict(os.environ, {"MANDO_CEREBRO": "agente", "MANDO_CEREBRO_TIMEOUT_S": "90"}):
            cerebro._plan_dirty_gated(self.s, lambda: seen.append(self.s.agent.meta[iid].dirty))
        self.assertEqual(seen, ["el recurso quedó libre"])


if __name__ == "__main__":
    unittest.main()
