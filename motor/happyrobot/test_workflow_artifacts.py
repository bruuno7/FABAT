import json
import unittest
from uuid import UUID

from motor.happyrobot import workflow_artifacts as artifacts
from motor.happyrobot.sandbox import test_operaciones


class WorkflowArtifactTest(unittest.TestCase):
    trigger = "11111111-1111-4111-8111-111111111111"

    def test_retry_graph_is_sequential_bounded_and_uses_verified_event_types(self):
        nodes = artifacts.body_nodes(self.trigger)
        self.assertEqual(nodes[0]["iterate_for"], 3)
        self.assertFalse(nodes[0]["execute_in_parallel"])
        self.assertEqual(nodes[1]["configuration"]["webhookSchemaVersion"], 2)
        self.assertNotIn("rawBody", nodes[1]["configuration"])
        self.assertNotIn("data", nodes[1]["configuration"])
        self.assertIn(self.trigger, nodes[1]["configuration"]["body"]["raw"])
        for node in nodes:
            if "event_id" in node:
                self.assertIn(node["event_id"], artifacts.EVENTS.values())

    def test_reference_builder_rejects_node_names_instead_of_creating_broken_variables(self):
        for value in ("trigger", "0", "node", "TRIGGER_PID"):
            with self.assertRaises(ValueError):
                artifacts.ref(value, "event_id")
        self.assertIn(self.trigger, artifacts.raw_ref(self.trigger, "event_id"))

    def test_exported_snapshot_contains_exact_core_source_and_executes_without_imports(self):
        from pathlib import Path
        root = Path(__file__).parent / "sandbox"
        config = artifacts.python_config("fa_snapshot", self.trigger)
        self.assertTrue(config["code"].startswith((root / "fa_operaciones.py").read_text() + "\n" + (root / "fa_consumidor.py").read_text()))
        fixture = test_operaciones.OperacionesTest()
        fixture.setUp()
        event = fixture.event("assignment.accepted")
        snapshot = {key: {"version": fixture.versions[key], "value": value} for key, value in fixture.docs.items()}
        ns = {"__package__": "remote_sandbox", "input_data": {"event_id": event["event_id"], "state_status": "pending", "status_code": 200,
              "event_json": json.dumps(event), "snapshot_json": json.dumps(snapshot)}}
        exec(config["code"], ns)
        self.assertEqual(ns["output"]["path"], "/commit")
        self.assertEqual(json.loads(ns["output"]["body_json"])["event_id"], event["event_id"])

    def test_bindings_only_reference_persistent_node_ids(self):
        names = ("Leer contexto", "Calcular transición", "Confirmar transición", "Leer estado final", "Cerrar intento", "Registrar resultado", "Leer cierre del intento", "Resultado operación")
        nodes = {name: {"persistent_id": str(UUID(int=index + 1))} for index, name in enumerate(names)}
        updates = artifacts.bindings(nodes, self.trigger)
        self.assertEqual(set(updates), set(names) - {"Leer contexto", "Leer estado final", "Leer cierre del intento"})
        body = updates["Confirmar transición"]["configuration"]["body"]["raw"]
        self.assertEqual(body, artifacts.raw_ref(nodes["Calcular transición"]["persistent_id"], "body_json"))
        self.assertNotIn("secret-value", json.dumps(updates))


if __name__ == "__main__":
    unittest.main()
