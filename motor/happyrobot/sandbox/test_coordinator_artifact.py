import copy
import json
from pathlib import Path
import unittest
from uuid import UUID

from motor.happyrobot import workflow_artifacts as artifacts
from motor.happyrobot.sandbox import build_nodes
from motor.happyrobot.sandbox import test_coordinador


TRIGGER = "11111111-1111-4111-8111-111111111111"
LLM = "22222222-2222-4222-8222-222222222222"


def variables(value, found=None):
    """Todas las referencias {{grupo.variable}} de un payload, ya convertidas en nodos por plate()."""
    found = [] if found is None else found
    if isinstance(value, dict):
        if value.get("type") == "variable":
            found.append((value.get("group_id"), value.get("variable_id")))
        for item in value.values():
            variables(item, found)
    elif isinstance(value, list):
        for item in value:
            variables(item, found)
    return found


class CoordinatorArtifactTest(unittest.TestCase):
    def setUp(self):
        self.fixture = test_coordinador.CoordinatorTest()
        self.fixture.setUp()
        self.event = self.fixture.event
        self.snapshot = self.fixture.snapshot

    def context_snapshot(self):
        """Lo que devuelve /coordinator/context: actor, conversación y las cinco reservas de rol (las
        ausentes con version 0), más la reserva de cada persona con rol, como al descubrir `actor/*`."""
        snapshot = copy.deepcopy(self.snapshot)
        for role in ("medico", "bomberos", "policia", "staff_entradas", "organizador"):
            seat = snapshot.setdefault("reservation/role:" + role, {"version": 0, "value": None})
            if seat["value"] and seat["value"].get("actor_id"):
                snapshot.setdefault("reservation/actor:" + seat["value"]["actor_id"], {"version": 0, "value": None})
        return snapshot

    def discover(self, proposal, snapshot):
        """Simula la carga de entidades: el paso de entidades pide lo que falta y el router lo devuelve
        como version 0 hasta que la instantánea está completa."""
        for _ in range(32):
            output = self.execute("fa_coordinador_entidades", {"event_json": json.dumps(self.event),
                "proposal_json": json.dumps(proposal), "event_id": self.event["event_id"]})
            if output["status"] != "ready":
                return snapshot, output
            missing = [entity for entity in json.loads(json.loads(output["body_json"])["extra_entities_json"])
                       if entity not in snapshot]
            if not missing:
                return snapshot, output
            for entity in missing:
                snapshot[entity] = {"version": 0, "value": None}
        self.fail("unbounded snapshot discovery")

    def exported(self, name):
        return json.loads(build_nodes.updates(name, TRIGGER_PID=TRIGGER))["configuration"]

    def execute(self, name, input_data):
        ns = {"input_data": input_data}
        exec(self.exported(name)["code"], ns)
        return ns["output"]

    def test_exports_exact_core_and_coordinator_source_without_rewriting(self):
        root = Path(__file__).parent
        core = (root / "fa_operaciones.py").read_text() + "\n" + (root / "fa_coordinador.py").read_text()
        for name, entry, keys in (
            ("fa_coordinador_contexto", "context_input", ("event_json", "snapshot_json", "state_status", "status_code")),
            ("fa_coordinador_entidades", "request_input", ("event_json", "proposal_json", "event_id")),
            ("fa_coordinador", "coordinator_rpc_input",
             ("event_id", "state_status", "status_code", "event_json", "snapshot_json", "proposal_json")),
        ):
            with self.subTest(name):
                config = self.exported(name)
                self.assertEqual(config["code"], core + "\noutput = %s(input_data)\n" % entry)
                self.assertEqual([item["key"] for item in config["input_data"]], list(keys))
                self.assertEqual(config["execution_profile"], "standard")

    def test_coordinator_artifacts_refuse_placeholder_triggers(self):
        for name in build_nodes.COORDINATOR:
            for trigger in (None, "TRIGGER_PID", "trigger", ""):
                with self.subTest(name=name, trigger=trigger):
                    with self.assertRaises(ValueError):
                        build_nodes.updates(name, TRIGGER_PID=trigger)

    def test_context_step_hides_contacts_permissions_and_channels(self):
        output = self.execute("fa_coordinador_contexto", {"event_json": json.dumps(self.event),
            "snapshot_json": json.dumps(self.context_snapshot()), "state_status": "pending", "status_code": 200})
        self.assertEqual(output["status"], "ready")
        context = json.loads(output["context_json"])
        self.assertEqual(context["actor_id"], "public")
        serialized = json.dumps(context)
        self.assertNotIn("private-contact", serialized)
        self.assertNotIn("channels", serialized)
        self.assertNotIn("permissions", serialized)

    def test_context_step_never_returns_a_context_after_a_failed_read(self):
        for status, code in (("pending", 503), ("applied", 200), ("missing", 404)):
            output = self.execute("fa_coordinador_contexto", {"event_json": json.dumps(self.event),
                "snapshot_json": json.dumps(self.snapshot), "state_status": status, "status_code": code})
            self.assertEqual(output["context_json"], "{}")
            self.assertNotEqual(output["status"], "ready")

    def test_entities_step_asks_only_for_what_the_snapshot_lacks(self):
        output = self.execute("fa_coordinador_entidades", {"event_json": json.dumps(self.event),
            "proposal_json": json.dumps({"intent": "report"}), "event_id": self.event["event_id"]})
        self.assertEqual(output["status"], "ready")
        body = json.loads(output["body_json"])
        self.assertEqual(body["id"], self.event["event_id"])
        self.assertTrue(any(entity.startswith("incident/") for entity in json.loads(body["extra_entities_json"])))

    def test_invalid_proposal_cannot_request_arbitrary_entities(self):
        output = self.execute("fa_coordinador_entidades", {"event_json": json.dumps(self.event),
            "proposal_json": json.dumps({"intent": "report", "offers": [{"role": "alien"}]}),
            "event_id": self.event["event_id"]})
        self.assertEqual(output["status"], "rejected")
        self.assertEqual(json.loads(output["body_json"])["extra_entities_json"], "[]")

    def test_exported_coordinator_commits_the_parent_transition_once(self):
        proposal = {"intent": "chat", "reply": "Hola, ¿qué necesitas?"}
        snapshot, request = self.discover(proposal, self.context_snapshot())
        self.assertEqual(request["status"], "ready")
        output = self.execute("fa_coordinador", {"event_id": self.event["event_id"], "state_status": "pending",
            "status_code": 200, "event_json": json.dumps(self.event), "snapshot_json": json.dumps(snapshot),
            "proposal_json": json.dumps(proposal)})
        self.assertEqual(output["status"], "ready")
        self.assertEqual(output["path"], "/commit")
        commit = json.loads(output["body_json"])
        self.assertEqual(commit["event_id"], self.event["event_id"])
        self.assertEqual([message["purpose"] for message in commit["messages"]], ["conversation"])

    def test_exported_coordinator_settles_an_invalid_proposal_without_committing(self):
        output = self.execute("fa_coordinador", {"event_id": self.event["event_id"], "state_status": "pending",
            "status_code": 200, "event_json": json.dumps(self.event), "snapshot_json": json.dumps(self.snapshot),
            "proposal_json": json.dumps({"intent": "approve"})})
        self.assertEqual(output["path"], "/inbox/settle")
        self.assertEqual(json.loads(output["body_json"]), {"id": self.event["event_id"], "status": "deferred",
                                                           "reason": "invalid_intent"})

    def test_exported_coordinator_ignores_a_replayed_or_mismatched_event(self):
        for state, code, event in (("applied", 200, self.event), ("pending", 200, {"event_id": "other-event"}),
                                   ("pending", 503, self.event)):
            output = self.execute("fa_coordinador", {"event_id": self.event["event_id"], "state_status": state,
                "status_code": code, "event_json": json.dumps(event), "snapshot_json": json.dumps(self.snapshot),
                "proposal_json": json.dumps({"intent": "chat", "reply": "Hola"})})
            self.assertEqual(output["status"], "unavailable")
            self.assertEqual(output["path"], "/inbox/status")


class CoordinatorGraphTest(unittest.TestCase):
    def nodes(self):
        return artifacts.coordinator_nodes(TRIGGER, LLM)

    def test_graph_is_sequential_and_inserts_the_existing_llm_node(self):
        nodes = self.nodes()
        self.assertEqual([node["name"] for node in nodes], list(artifacts.COORDINATOR_NAMES))
        self.assertEqual(nodes[0]["parent_node_id"], TRIGGER)
        self.assertEqual(nodes[1]["parent_node_index"], 0)
        self.assertEqual(nodes[2]["parent_node_id"], str(UUID(LLM)))
        self.assertEqual([node.get("parent_node_index") for node in nodes[3:]], [2, 3, 4, 5, 6])
        for node in nodes:
            if "event_id" in node:
                self.assertIn(node["event_id"], artifacts.EVENTS.values())

    def test_graph_reads_the_coordinator_context_and_never_the_operations_one(self):
        nodes = self.nodes()
        reads = [node["configuration"]["url"] for node in nodes if node["name"].startswith("Leer contexto")]
        self.assertEqual(len(reads), 2)
        self.assertTrue(all("/hr/state/coordinator/context" in json.dumps(url) for url in reads))
        self.assertFalse(any("/operations/context" in json.dumps(node) for node in nodes))

    def test_bindings_reference_only_persistent_ids_and_hide_secrets(self):
        nodes = {name: {"persistent_id": str(UUID(int=index + 1))} for index, name in enumerate(artifacts.COORDINATOR_NAMES)}
        updates = artifacts.coordinator_bindings(nodes, TRIGGER, LLM)
        static = {"Leer contexto", "Leer estado final"}
        self.assertEqual(set(updates), set(artifacts.COORDINATOR_NAMES) - static)
        compose = nodes["Componer transición"]["persistent_id"]
        self.assertEqual(updates["Confirmar transición"]["configuration"]["body"]["raw"],
                         artifacts.raw_ref(compose, "body_json"))
        self.assertIn(compose, json.dumps(updates))
        fields = {field for group, field in variables(updates) if group == str(UUID(LLM))}
        self.assertEqual(fields, {"proposal_json"})
        serialized = json.dumps(updates)
        self.assertNotIn("secret-value", serialized)
        self.assertNotIn("ACTUAL_SECRET", serialized)

    def test_llm_proposal_field_is_declared_not_invented(self):
        nodes = {name: {"persistent_id": str(UUID(int=index + 1))} for index, name in enumerate(artifacts.COORDINATOR_NAMES)}
        updates = artifacts.coordinator_bindings(nodes, TRIGGER, LLM, proposal_field="structured_output")
        fields = {field for group, field in variables(updates) if group == str(UUID(LLM))}
        self.assertEqual(fields, {"structured_output"})

    def test_graph_builders_reject_placeholder_identifiers(self):
        for value in ("trigger", "0", "LLM_PID", ""):
            with self.assertRaises(ValueError):
                artifacts.coordinator_nodes(TRIGGER, value)


if __name__ == "__main__":
    unittest.main()
