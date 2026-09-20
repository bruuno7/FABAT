import json
from pathlib import Path
import unittest

from motor.happyrobot import workflow_artifacts as artifacts
from motor.happyrobot.sandbox import build_nodes
from motor.happyrobot.sandbox import fa_comunicaciones as comms


TRIGGER = "11111111-1111-4111-8111-111111111111"


def results(*statuses):
    return json.dumps([{"id": "m%d" % index, "status": status} for index, status in enumerate(statuses)])


class CommunicationsStepTest(unittest.TestCase):
    def test_recovery_tick_is_bounded_and_defaults_without_asking_for_everything(self):
        self.assertEqual(json.loads(comms.recover_input({})["body_json"]), {"limit": comms.DEFAULT_TICK})
        self.assertEqual(comms.recover_input({})["path"], "/outbox/recover")
        self.assertEqual(json.loads(comms.recover_input({"limit": "16"})["body_json"]), {"limit": 16})
        self.assertEqual(json.loads(comms.recover_input({"limit": 3})["body_json"]), {"limit": 3})

    def test_an_unbounded_tick_is_refused_instead_of_clamped_silently(self):
        for limit in (0, 17, -1, 1.5, "8.5", "abc", "", True, [8], {"limit": 8}):
            with self.subTest(limit=limit):
                output = comms.recover_input({"limit": limit})
                if limit == "":
                    self.assertEqual(output["status"], "ready")
                    self.assertEqual(output["limit"], comms.DEFAULT_TICK)
                else:
                    self.assertEqual(output["status"], "rejected")
                    self.assertEqual(output["path"], "")
                    self.assertEqual(output["body_json"], "{}")

    def test_inbox_recovery_bounds_and_refuses_duplicates(self):
        self.assertEqual(json.loads(comms.inbox_input({})["ids_json"]), [])
        self.assertEqual(json.loads(comms.inbox_input({"items_json": '["e1","e2"]'})["ids_json"]), ["e1", "e2"])
        for value in ('["e1","e1"]', '["e1", 2]', '["../etc"]', '["e1"]' * 0 + json.dumps(["e%d" % i for i in range(17)]), "{}", "{", None):
            with self.subTest(value=value):
                if value is None:
                    self.assertEqual(comms.inbox_input({})["status"], "ready")
                    continue
                self.assertEqual(comms.inbox_input({"items_json": value})["status"], "rejected")

    def test_an_ambiguous_delivery_is_never_counted_as_delivered(self):
        summary = json.loads(comms.summary_input({"results_json": results("succeeded", "unknown", "simulated")})["summary_json"])
        self.assertEqual(summary["delivered"], 1)
        self.assertEqual(summary["simulated"], 1)
        self.assertEqual(summary["ambiguous"], 1)
        self.assertEqual(summary["processed"], 3)
        self.assertTrue(summary["needs_attention"])

    def test_summary_separates_every_outcome_and_stays_quiet_when_all_is_well(self):
        summary = json.loads(comms.summary_input({"results_json": results(
            "succeeded", "succeeded", "simulated", "deferred", "pending", "failed", "unknown", "sending", "missing", "unavailable")})["summary_json"])
        self.assertEqual(summary["processed"], 10)
        self.assertEqual(summary["delivered"], 2)
        self.assertEqual(summary["simulated"], 1)
        self.assertEqual(summary["rescheduled"], 2)
        self.assertEqual(summary["stalled"], 1)
        self.assertEqual(summary["ambiguous"], 1)
        self.assertEqual(summary["in_flight"], 3)
        self.assertEqual(summary["unrecognized"], 0)
        self.assertTrue(summary["needs_attention"])
        calm = json.loads(comms.summary_input({"results_json": results("succeeded", "simulated")})["summary_json"])
        self.assertFalse(calm["needs_attention"])

    def test_an_unknown_status_is_flagged_rather_than_silently_dropped(self):
        payload = json.loads(results("SUCCESS", "", "delivered"))
        payload.append({"id": "m3"})
        summary = json.loads(comms.summary_input({"results_json": json.dumps(payload)})["summary_json"])
        self.assertEqual(summary["processed"], 0)
        self.assertEqual(summary["unrecognized"], 4)
        self.assertTrue(summary["needs_attention"])

    def test_a_corrupt_result_set_produces_no_summary(self):
        for value in ("{}", "{", json.dumps(["succeeded"]),
                      json.dumps([{"id": "m", "status": "succeeded"}] * 17), None):
            with self.subTest(value=value):
                output = comms.summary_input({"results_json": value})
                self.assertEqual(output["status"], "rejected")
                self.assertTrue(output["needs_attention"])


class CommunicationsArtifactTest(unittest.TestCase):
    def exported(self, name):
        return json.loads(build_nodes.updates(name, TRIGGER_PID=TRIGGER))["configuration"]

    def execute(self, name, input_data):
        ns = {"input_data": input_data}
        exec(self.exported(name)["code"], ns)
        return ns["output"]

    def test_exports_exact_core_and_communications_source_without_rewriting(self):
        root = Path(__file__).parent
        core = (root / "fa_operaciones.py").read_text() + "\n" + (root / "fa_comunicaciones.py").read_text()
        for name, entry, keys in (
            ("fa_comunicaciones_recover", "recover_input", ("limit",)),
            ("fa_comunicaciones_inbox", "inbox_input", ("items_json",)),
            ("fa_comunicaciones_resumen", "summary_input", ("results_json",)),
        ):
            with self.subTest(name):
                config = self.exported(name)
                self.assertEqual(config["code"], core + "\noutput = %s(input_data)\n" % entry)
                self.assertEqual([item["key"] for item in config["input_data"]], list(keys))

    def test_communications_artifacts_refuse_placeholder_triggers(self):
        for name in build_nodes.COMMS:
            for trigger in (None, "TRIGGER_PID", "trigger", ""):
                with self.subTest(name=name, trigger=trigger):
                    with self.assertRaises(ValueError):
                        build_nodes.updates(name, TRIGGER_PID=trigger)

    def test_exported_recovery_step_matches_the_bridge_contract(self):
        output = self.execute("fa_comunicaciones_recover", {"limit": "8"})
        self.assertEqual(output, {"status": "ready", "path": "/outbox/recover", "limit": 8,
                                  "body_json": json.dumps({"limit": 8})})
        self.assertEqual(self.execute("fa_comunicaciones_recover", {"limit": "99"})["status"], "rejected")

    def test_exported_summary_runs_without_imports_or_network(self):
        output = self.execute("fa_comunicaciones_resumen", {"results_json": results("succeeded", "unknown")})
        self.assertEqual(output["status"], "ready")
        self.assertTrue(output["needs_attention"])


class CommunicationsGraphTest(unittest.TestCase):
    def names(self):
        return {name: {"persistent_id": "00000000-0000-4000-8000-0000000000%02d" % index}
                for index, name in enumerate(artifacts.COMMUNICATION_NAMES)}

    def test_graph_is_sequential_and_uses_only_known_events(self):
        nodes = artifacts.communication_nodes(TRIGGER)
        self.assertEqual([node["name"] for node in nodes], list(artifacts.COMMUNICATION_NAMES))
        self.assertEqual(nodes[0]["parent_node_id"], TRIGGER)
        self.assertEqual([node.get("parent_node_index") for node in nodes[1:]], [0, 1, 2, 3])
        known = set(artifacts.EVENTS.values()) | {artifacts.CRON_TRIGGER, artifacts.LOOP_EVENT}
        for node in nodes:
            if "event_id" in node:
                self.assertIn(node["event_id"], known)

    def test_the_tick_calls_the_bounded_recovery_route_not_a_per_item_loop(self):
        nodes = {node["name"]: node for node in artifacts.communication_nodes(TRIGGER)}
        recovery = nodes[artifacts.COMMUNICATION_NAMES[1]]["configuration"]
        self.assertIn("/outbox/recover", json.dumps(recovery["url"]))
        self.assertIn("HR_STATE_DELIVERY_SECRET", json.dumps(recovery["headers"]))
        self.assertEqual(json.loads(recovery["body"]["raw"]), {"limit": artifacts.CRON_MAX})
        self.assertFalse(any(node["type"] == "loop" for node in nodes.values()))

    def test_bindings_reference_persistent_ids_only_and_leak_no_values(self):
        nodes = self.names()
        updates = artifacts.communication_bindings(nodes, TRIGGER)
        # "Leer inbox pendiente" ya se configura al construir el grafo; el resto sí se enlaza.
        self.assertEqual(set(updates), {artifacts.COMMUNICATION_NAMES[index] for index in (1, 2, 4)})
        rendered = json.dumps(updates)
        self.assertIn(artifacts.RECOVER_RESULTS_FIELD, rendered)
        self.assertIn(artifacts.INBOX_ITEMS_FIELD, rendered)
        for index in (0, 1, 3):  # nodos origen de path/body, de results y de items
            self.assertIn(nodes[artifacts.COMMUNICATION_NAMES[index]]["persistent_id"], rendered)
        self.assertNotIn("super-secret-value", rendered)
        self.assertNotIn("private-token", rendered)

    def test_the_cron_trigger_configuration_matches_the_platform_schema(self):
        config = artifacts.cron_config("*/5 * * * *", "Europe/Madrid")
        self.assertEqual(config, {"cron": {"expression": "*/5 * * * *", "timezone": "Europe/Madrid"}})
        self.assertEqual(artifacts.CRON_TRIGGER, "0192fff4-4da6-7712-a139-53c87250339f")
        for expression in ("* * * *", "every 5 minutes", "", None, "* * * * * *"):
            with self.assertRaises(ValueError):
                artifacts.cron_config(expression)
        for timezone in ("Madrid", "", None, 3):
            with self.assertRaises(ValueError):
                artifacts.cron_config("*/5 * * * *", timezone)

    def test_only_bounded_tick_sizes_are_accepted(self):
        for limit in (1, 8, 16):
            self.assertEqual(len(artifacts.communication_nodes(TRIGGER, limit)), len(artifacts.COMMUNICATION_NAMES))
        for limit in (0, 17, -1, 1.5, "8", None, True):
            with self.assertRaises(ValueError):
                artifacts.communication_nodes(TRIGGER, limit)


if __name__ == "__main__":
    unittest.main()
