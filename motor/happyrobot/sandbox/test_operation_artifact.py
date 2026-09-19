import json
from pathlib import Path
import unittest

from motor.happyrobot.sandbox import build_nodes
from motor.happyrobot.sandbox.fa_operaciones import run_input
from motor.happyrobot.sandbox import test_operaciones


class OperationArtifactTest(unittest.TestCase):
    def test_exports_exact_source_without_regex_rewriting(self):
        trigger = "11111111-1111-4111-8111-111111111111"
        config = json.loads(build_nodes.updates("fa_operaciones", TRIGGER_PID=trigger))["configuration"]
        source = (Path(__file__).parent / "fa_operaciones.py").read_text()
        self.assertEqual(config["code"], source + "\noutput = run_input(input_data)\n")
        fixture = test_operaciones.OperacionesTest()
        fixture.setUp()
        event = fixture.event("assignment.accepted")
        snapshot = {key: {"version": fixture.versions[key], "value": value} for key, value in fixture.docs.items()}
        data = {"event_json": json.dumps(event), "snapshot_json": json.dumps(snapshot)}
        ns = {"input_data": data}
        exec(config["code"], ns)
        self.assertEqual(ns["output"], run_input(data))
        self.assertEqual(ns["output"]["status"], "ready")

    def test_placeholders_cannot_be_uploaded(self):
        for trigger in (None, "TRIGGER_PID", "trigger", ""):
            with self.assertRaises(ValueError):
                build_nodes.updates("fa_operaciones", TRIGGER_PID=trigger)

    def test_missing_snapshot_requests_data_instead_of_defaulting_to_empty(self):
        fixture = test_operaciones.OperacionesTest()
        fixture.setUp()
        result = run_input({"event_json": fixture.event("assignment.accepted"), "snapshot_json": {}})
        self.assertEqual(result["status"], "needs_snapshot")
        self.assertEqual(json.loads(result["required_entities_json"]), ["actor/worker-1"])
        self.assertEqual(result["commit_json"], "")

    def test_invalid_json_cannot_produce_a_commit(self):
        for value in (None, [], "{", "null"):
            result = run_input({"event_json": value, "snapshot_json": "{}"})
            self.assertEqual(result["status"], "rejected")
            self.assertEqual(result["commit_json"], "")


if __name__ == "__main__":
    unittest.main()
