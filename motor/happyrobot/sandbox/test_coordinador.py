import copy
import json
import unittest

from motor.happyrobot.sandbox.fa_coordinador import coordinate, coordinator_input, derived_id, public_context


class CoordinatorTest(unittest.TestCase):
    def setUp(self):
        self.event = {"schema_version": 2, "event_id": "input-1", "event_type": "message.received", "actor_id": "public",
            "channel": "telegram", "conversation_id": "conversation-1", "correlation_id": "trace-1",
            "occurred_at": "2026-09-19T20:00:00Z", "received_at": "2026-09-19T20:00:01Z", "payload": {"text": "Necesitamos ayuda en la barra"}}
        self.docs = {
            "actor/public": {"roles": [], "preferred_channel": "telegram", "channels": {"telegram": {"chat_id": "private-contact"}}},
            "actor/worker": {"roles": ["medico"], "preferred_channel": "telegram"},
            "actor/service-coordinator": {"roles": [], "permissions": ["coordinate"]},
            "reservation/role:medico": {"actor_id": "worker"},
            "conversation/conversation-1": {"actor_id": "public", "incident_ids": []},
        }
        self.snapshot = {key: {"version": 1, "value": value} for key, value in self.docs.items()}

    def plan(self, proposal):
        for _ in range(32):
            result = coordinator_input({"event_json": self.event, "snapshot_json": self.snapshot, "proposal_json": proposal})
            if result["status"] != "needs_snapshot":
                return result
            for key in json.loads(result["required_entities_json"]):
                self.snapshot[key] = {"version": 0, "value": None}
        self.fail("unbounded snapshot discovery")

    def seed_incident(self, iid="incident-1", actor="public"):
        self.snapshot["incident/" + iid] = {"version": 1, "value": {"reporter_id": actor, "status": "open", "assignment_ids": [], "tasks": {}}}
        self.snapshot["conversation/conversation-1"]["value"]["incident_ids"].append(iid)

    def test_new_incident_and_offer_share_one_atomic_parent_commit(self):
        result = self.plan({"intent": "report", "location": "barra", "offers": [{"recipient_id": "worker", "role": "medico"}]})
        self.assertEqual(result["status"], "ready", result)
        commit = json.loads(result["commit_json"])
        writes = {item["entity"]: item["value"] for item in commit["writes"]}
        iid = derived_id(self.event["event_id"], "incident")
        aid = derived_id(self.event["event_id"], "assignment")
        self.assertEqual(commit["event_id"], self.event["event_id"])
        self.assertEqual(writes["incident/" + iid]["assignment_ids"], [aid])
        self.assertEqual(writes["assignment/" + aid]["actor_id"], "worker")
        self.assertEqual(commit["expected"]["incident/" + iid], 0)
        self.assertEqual(len(commit["messages"]), 2)
        self.assertEqual(self.snapshot["incident/" + iid], {"version": 0, "value": None})

    def test_chat_never_becomes_a_new_incident(self):
        result = self.plan({"intent": "chat", "reply": "Hola, ¿qué necesitas?"})
        commit = json.loads(result["commit_json"])
        self.assertFalse(any(item["entity"].startswith("incident/") for item in commit["writes"]))
        self.assertEqual(commit["messages"][0]["purpose"], "conversation")
        self.assertNotIn("incident_id", commit["messages"][0])

    def test_model_cannot_choose_a_worker_or_capability_outside_the_roster(self):
        for offer in ({"recipient_id": "unknown", "role": "medico"}, {"recipient_id": "worker", "role": "bomberos"}):
            result = self.plan({"intent": "report", "offers": [offer]})
            self.assertEqual(result["status"], "rejected")
            self.assertEqual(result["commit_json"], "")

    def test_failed_second_operation_cannot_leave_a_partial_incident(self):
        self.snapshot["actor/worker"]["value"].update(availability="unknown")
        before = copy.deepcopy(self.snapshot)
        result = self.plan({"intent": "report", "offers": [{"recipient_id": "worker", "role": "medico"}]})
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["error"], "actor_unavailable")
        for key, value in before.items():
            self.assertEqual(self.snapshot[key], value)

    def test_ambiguous_incident_requests_clarification_without_modifying_either(self):
        self.seed_incident("first")
        self.seed_incident("second")
        result = self.plan({"intent": "update"})
        commit = json.loads(result["commit_json"])
        self.assertFalse(any(item["entity"].startswith("incident/") for item in commit["writes"]))
        self.assertEqual(commit["messages"][0]["purpose"], "conversation")

    def test_explicit_other_incident_cannot_be_modified_by_model_output(self):
        self.seed_incident("own")
        result = self.plan({"intent": "update", "incident_id": "someone-else"})
        self.assertEqual(result["status"], "ready")
        commit = json.loads(result["commit_json"])
        self.assertEqual(commit["messages"][0]["purpose"], "conversation")
        self.assertFalse(any(item["entity"].startswith("incident/") for item in commit["writes"]))

    def test_location_answer_updates_the_existing_incident(self):
        self.seed_incident()
        result = self.plan({"intent": "update", "location": "barra 4"})
        writes = json.loads(result["commit_json"])["writes"]
        incidents = [item for item in writes if item["entity"].startswith("incident/")]
        self.assertEqual(len(incidents), 1)
        self.assertEqual(incidents[0]["entity"], "incident/incident-1")
        self.assertEqual(incidents[0]["value"]["location"], "barra 4")

    def test_closure_request_does_not_close_based_on_model_inference(self):
        self.seed_incident()
        result = self.plan({"intent": "request_close", "confirmed": True})
        self.assertEqual(result["status"], "ready", result)
        writes = json.loads(result["commit_json"])["writes"]
        self.assertTrue(any(item["entity"].startswith("question/") and item["value"]["kind"] == "closure" for item in writes))
        self.assertFalse(any(item["entity"].startswith("incident/") and item["value"]["status"] == "closed" for item in writes))

    def test_coordinator_offer_does_not_replace_an_unfilled_medical_requirement(self):
        self.snapshot["actor/organizer"] = {"version": 1, "value": {"roles": ["organizador"], "preferred_channel": "telegram"}}
        self.snapshot["reservation/role:organizador"] = {"version": 1, "value": {"actor_id": "organizer"}}
        result = self.plan({"intent": "report", "required_roles": ["medico"], "offers": [{"recipient_id": "organizer", "role": "organizador"}]})
        self.assertEqual(result["status"], "ready", result)
        incident = next(item["value"] for item in json.loads(result["commit_json"])["writes"] if item["entity"].startswith("incident/"))
        self.assertEqual({item["role"] for item in incident["tasks"].values()}, {"medico", "organizador"})

    def test_model_cannot_choose_among_several_questions_without_an_explicit_anchor(self):
        self.seed_incident()
        for qid in ("first-question", "second-question"):
            self.snapshot["question/" + qid] = {"version": 1, "value": {"recipient_id": "public", "requester_id": "worker",
                "incident_id": "incident-1", "kind": "information", "status": "pending", "text": "¿Dónde estás?"}}
        result = self.plan({"intent": "answer", "question_id": "first-question"})
        commit = json.loads(result["commit_json"])
        self.assertEqual(commit["messages"][0]["purpose"], "conversation")
        self.assertFalse(any(item["entity"].startswith("question/") for item in commit["writes"]))
        self.event["question_id"] = "second-question"
        result = self.plan({"intent": "answer", "question_id": "first-question"})
        answered = [item for item in json.loads(result["commit_json"])["writes"] if item["entity"].startswith("question/")]
        self.assertEqual(answered[0]["entity"], "question/second-question")

    def test_public_context_omits_contacts_and_permissions(self):
        self.plan({"intent": "chat", "reply": "Hola"})
        context = public_context(self.event, self.snapshot)
        serialized = json.dumps(context)
        self.assertNotIn("private-contact", serialized)
        self.assertNotIn("channels", serialized)
        self.assertNotIn("permissions", serialized)

    def test_rejected_or_malformed_intents_never_produce_commits(self):
        for proposal in (None, [], {"intent": "approve"}, {"intent": "evacuate"}):
            result = coordinator_input({"event_json": self.event, "snapshot_json": self.snapshot, "proposal_json": proposal})
            self.assertEqual(result["status"], "rejected")
            self.assertEqual(result["commit_json"], "")


if __name__ == "__main__":
    unittest.main()
