"""Ensayo real del motor, sin sockets ni reloj real en el resultado."""
from __future__ import annotations

import contextlib
import importlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from motor.server.app import Session, load_case


class EnsayoTest(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec("motor.server.ensayo"), "falta el ensayo ejecutable")
        return importlib.import_module("motor.server.ensayo")

    def test_seven_observed_milestones_and_three_identical_runs(self):
        ensayo = self.module()
        outputs = []
        with patch("httpx.post", side_effect=AssertionError("red prohibida")), \
             patch("httpx.request", side_effect=AssertionError("red prohibida")), \
             patch("socket.create_connection", side_effect=AssertionError("red prohibida")):
            for _ in range(3):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    self.assertEqual(ensayo.main([]), 0)
                outputs.append(out.getvalue())
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[0], outputs[2])
        result = json.loads(outputs[0])
        self.assertEqual(result["case"], "c-d000001")
        self.assertEqual(result["N"], 1)
        self.assertEqual(result["missing"], [])
        self.assertEqual(len(result["milestones"]), 7)
        self.assertTrue(all(h["ok"] and h["evidence"] for h in result["milestones"].values()))
        self.assertEqual(result["informe"]["metrics"]["unsafe_actions"], 0)
        self.assertTrue(result["informe"]["approvals"])
        self.assertTrue(all(a["by"] == "operador-simulado" for a in result["informe"]["approvals"]))
        self.assertNotIn("real_s", outputs[0])
        self.assertNotIn("session_id", outputs[0])

    def test_key_moment_stops_before_scheduled_blow(self):
        ensayo = self.module()
        session = Session(load_case("demo-1"), threaded=False, playbook="seed", local_params=False)
        self.addCleanup(session.close)
        moment = ensayo.prepare_key_moment(session)
        self.assertEqual(session.world.t, 7)
        self.assertEqual(moment["scheduled_t"], 8)
        self.assertEqual(moment["effect"]["resource"], "amb_1")
        self.assertNotEqual(str(session.world.observe().resources["amb_1"].status), "offline")
        self.assertFalse(session.approvals)
        session.tick()
        self.assertEqual(str(session.world.observe().resources["amb_1"].status), "offline")

    def test_missing_milestones_return_failure(self):
        ensayo = self.module()
        case = load_case("demo-1")
        case.update(events=[], duration_min=1)
        with patch.object(ensayo, "load_case", return_value=case):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = ensayo.main(["--case", "sin-hitos"])
        self.assertEqual(code, 1)
        result = json.loads(out.getvalue())
        self.assertIn("supuesto_roto", result["missing"])
        self.assertFalse(result["ok"])

    def test_key_moment_rejects_real_comms_before_advancing(self):
        ensayo = self.module()
        session = Session(load_case("demo-1"), threaded=False, local_params=False)
        self.addCleanup(session.close)
        session.comms_mode = "happyrobot"
        with self.assertRaises(ValueError):
            ensayo.prepare_key_moment(session)
        self.assertEqual(session.world.t, 0)

    def test_key_moment_rejects_automatic_approvals(self):
        ensayo = self.module()
        session = Session(load_case("demo-1"), threaded=False, playbook="seed",
                          local_params=False, auto_approve_min=0)
        self.addCleanup(session.close)
        with self.assertRaises(ValueError):
            ensayo.prepare_key_moment(session)
        self.assertEqual(session.world.t, 0)

    def test_local_learning_files_do_not_change_rehearsal(self):
        ensayo = self.module()
        expected = ensayo.run_ensayo()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            params = root / "params.local.json"
            params.write_text('{"values":{"duplicate_window_min":900}}', encoding="utf-8")
            (root / "playbook.learned.json").write_text('{"lessons":[]}', encoding="utf-8")
            with patch("motor.server.app.memoria.LOCAL_APPROVED_PATH", params), \
                 patch("motor.server.app.HARNESS_OUT", root):
                self.assertEqual(ensayo.run_ensayo(), expected)


if __name__ == "__main__":
    unittest.main()
