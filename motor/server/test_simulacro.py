"""Pruebas del ensayo aislado y de sus denominadores."""
import copy
import threading
import unittest
from motor.server.simulacro import clone_pair, trial, summarize, SimulacroService
from motor.server.app import Session, load_case


class SimulacroTests(unittest.TestCase):
    def setUp(self):
        self.session = Session(load_case("demo-1"), threaded=False, playbook="seed", local_params=False)
        self.addCleanup(self.session.close)
        for _ in range(7):
            self.session.tick()

    def test_no_live_comms_or_state_mutation_and_determinism(self):
        s = self.session
        before = copy.deepcopy(s.agent.snapshot()), copy.deepcopy(s.world.truth())
        w, a = clone_pair(s.world, s.agent)
        effect = {"kind": "resource_offline", "resource": "med_1", "n": 12}
        one, two = trial(w, a, effect), trial(w, a, effect)
        self.assertEqual(one, two)
        self.assertEqual((s.agent.snapshot(), s.world.truth()), before)
        self.assertEqual(type(a.comms).__name__, "SimComms")
        self.assertTrue(w.is_twin)
        self.assertEqual(s.comms.stats["real_sent"], 0)

    def test_denominator_errors_and_recovery_censoring(self):
        rows = [{"index": 0, "label": "Cerrar pasillo", "effect": {"kind": "zone_state", "zone": "corridor_s"},
                 "broken": True, "recovery_min": 3, "plans": ["Plan nuevo"], "error": None},
                {"index": 1, "label": "Cerrar pasillo", "effect": {"kind": "zone_state", "zone": "corridor_s"},
                 "broken": True, "recovery_min": None, "plans": [], "error": None},
                {"index": 2, "label": "Otro", "effect": {}, "error": "RuntimeError", "broken": None}]
        result = summarize(rows)
        self.assertEqual(result["N"], 3)
        self.assertEqual(result["errors"], 1)
        weak = result["weaknesses"][0]
        self.assertEqual((weak["failures"], weak["N"], weak["exposed_N"]), (2, 3, 2))
        self.assertEqual((weak["recovery_median_min"], weak["recovery_N"], weak["censored_N"]), (3, 1, 1))

    def test_job_validation_cancellation_and_time_limit(self):
        service = SimulacroService()
        self.addCleanup(service.close)
        with self.assertRaises(ValueError):
            service.start(self.session, n=201, seed=1)
        service.start(self.session, n=50, seed=8, wall_limit=.01)
        service.join(4)
        self.assertEqual(service.status()["status"], "limited")
        self.assertLess(service.status()["N"], 50)
        service.start(self.session, n=500, seed=8)
        service.cancel()
        service.join(4)
        self.assertEqual(service.status()["status"], "cancelled")
        self.assertLess(service.status()["N"], 500)

    def test_prefix_is_deterministic(self):
        service = SimulacroService()
        self.addCleanup(service.close)
        service.start(self.session, n=50, seed=88)
        service.join(60)
        first = service.status()
        service.start(self.session, n=50, seed=88)
        service.join(60)
        second = service.status()
        self.assertEqual(first["rows"], second["rows"])
        self.assertEqual(first["N"], 50)

    def test_lock_and_replay_are_permanent_without_touching_live_session(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from motor.server import regression_live
        from motor.server.simulacro import run_locked
        service = SimulacroService()
        self.addCleanup(service.close)
        service.start(self.session, n=50, seed=1)
        service.join(60)
        rows = service.status()["rows"]
        failing = next(r for r in rows if r.get("broken"))
        before = copy.deepcopy(self.session.world.truth())
        with tempfile.TemporaryDirectory() as folder, patch.object(regression_live, "DIR", Path(folder)):
            locked = service.lock_test(failing["index"], "test")
            saved = regression_live.load(locked["n"])
            self.assertEqual(saved["simulacro"]["effect"], failing["effect"])
            replay = run_locked(saved)
            self.assertFalse(replay["result"]["passed"])
            self.assertEqual(regression_live.load(locked["n"])["last_run"], replay["result"])
        self.assertEqual(before, self.session.world.truth())


class EvidenceHTTPTests(unittest.TestCase):
    def setUp(self):
        import os
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from motor.server.app import create_app
        self.env = patch.dict(os.environ, {"TELEGRAM_MODE": "off", "MANDO_PUBLIC_URL": "https://example.invalid",
                                          "MANDO_OPERATOR_TOKEN": "test-only", "MANDO_OPERATORS": ""})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.app = create_app("demo-1", threaded=False, playbook="seed", local_params=False)
        self.client = TestClient(self.app)
        self.addCleanup(self.app.state.session.close)
        self.addCleanup(self.app.state.chat.stop)
        self.addCleanup(self.client.close)
        self.headers = {"X-Mando-Operator": "test-only"}

    def test_operator_required_for_start_cancel_and_lock(self):
        for path in ("/api/simulacro/start", "/api/simulacro/cancel", "/api/regression/lock"):
            response = self.client.post(path, json={"n": 50, "simulacro_index": 0})
            self.assertIn(response.status_code, (401, 403))
        self.assertEqual(self.client.post('/api/simulacro/start', json={"n": 51}, headers=self.headers).status_code, 422)
        self.assertEqual(self.client.post('/api/simulacro/start', json=[], headers=self.headers).status_code, 422)
        self.assertEqual(self.client.post('/api/regression/lock', json={"simulacro_index": -1}, headers=self.headers).status_code, 422)

    def test_read_routes_and_reports(self):
        self.assertEqual(self.client.get('/simulacro').status_code, 200)
        self.assertEqual(self.client.get('/api/simulacro/status').json()['status'], 'idle')
        evidence = self.client.get('/api/evidence').json()
        self.assertIn('recibos', evidence)
        self.assertIn('coordinacion', evidence)
        self.assertEqual(self.client.get('/api/evidence?call_minutes=nan').status_code, 422)
        report = self.client.get('/api/informe').json()
        self.assertIn('recibos', report)
        self.assertIn('coordinacion', report)

    def test_session_receipts_capture_approvals_and_finish_without_live_mutation(self):
        s = self.app.state.session
        while not s.world.done():
            s.tick()
            for a in s.state()['approvals']:
                s.approve(a['id'], False, 'veto de prueba')
        s.receipts.wait()
        result = self.client.get('/api/evidence').json()
        self.assertGreater(result['recibos']['N'], 0)
        self.assertLessEqual(result['recibos']['N'], 10)
        self.assertTrue(any(r['accepted'] is False for r in result['recibos']['items']))
        self.assertEqual(result['coordinacion']['outbound'], len(s.comms.calls))
