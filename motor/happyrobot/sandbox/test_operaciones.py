import copy
import unittest

from motor.happyrobot.sandbox.fa_operaciones import OperationError, apply_event


class OperacionesTest(unittest.TestCase):
    def setUp(self):
        self.docs = {
            "actor/worker-1": {"roles": ["medico"], "preferred_channel": "telegram"},
            "actor/worker-2": {"roles": ["medico"], "preferred_channel": "phone"},
            "actor/reporter-1": {"roles": [], "preferred_channel": "telegram"},
            "incident/incident-1": {"status": "open", "reporter_id": "reporter-1", "assignment_ids": ["assignment-1"], "location": "barra 3"},
            "assignment/assignment-1": {"status": "offered", "incident_id": "incident-1", "actor_id": "worker-1", "task_id": "medical-task", "role": "medico"},
            "reservation/actor:worker-1": None,
            "reservation/task:medical-task": None,
            "question/question-1": None,
        }
        self.versions = {key: 1 if value is not None else 0 for key, value in self.docs.items()}

    def event(self, kind, actor="worker-1", **payload):
        return {
            "schema_version": 2, "event_id": "event-1", "event_type": kind,
            "actor_id": actor, "incident_id": "incident-1", "assignment_id": "assignment-1",
            "conversation_id": "conversation-1", "correlation_id": "trace-1", "channel": "telegram",
            "occurred_at": "2026-09-19T14:00:00Z", "received_at": "2026-09-19T14:00:01Z",
            "payload": payload,
        }

    def apply(self, event):
        snapshot = {key: {"version": self.versions[key], "value": value} for key, value in self.docs.items()}
        result = apply_event(event, snapshot)
        for write in result["writes"]:
            self.docs[write["entity"]] = write["value"]
            self.versions[write["entity"]] += 1
        return result

    def test_accept_is_same_operation_for_telegram_and_phone(self):
        event = self.event("assignment.accepted")
        snapshot = {key: {"version": self.versions[key], "value": value} for key, value in self.docs.items()}
        self.assertEqual(apply_event(event, snapshot), apply_event(dict(event, channel="phone"), snapshot))
        result = self.apply(event)
        self.assertEqual(self.docs["assignment/assignment-1"]["status"], "accepted")
        self.assertEqual(self.docs["reservation/actor:worker-1"]["assignment_id"], "assignment-1")
        self.assertEqual(result["messages"][0]["recipient_id"], "reporter-1")
        self.assertNotIn("va hacia", result["messages"][0]["text"])

    def test_foreign_actor_and_unclaimed_role_cannot_accept(self):
        with self.assertRaisesRegex(OperationError, "assignment_for_other_actor"):
            self.apply(self.event("assignment.accepted", actor="worker-2"))
        self.docs["actor/worker-1"]["roles"] = []
        with self.assertRaisesRegex(OperationError, "role_not_authorized"):
            self.apply(self.event("assignment.accepted"))

    def test_busy_worker_and_taken_task_cannot_accept(self):
        self.docs["reservation/actor:worker-1"] = {"assignment_id": "different"}
        with self.assertRaisesRegex(OperationError, "actor_busy"):
            self.apply(self.event("assignment.accepted"))
        self.docs["reservation/actor:worker-1"] = None
        self.docs["reservation/task:medical-task"] = {"assignment_id": "different"}
        with self.assertRaisesRegex(OperationError, "task_covered"):
            self.apply(self.event("assignment.accepted"))

    def test_explicit_eta_does_not_implicitly_accept(self):
        with self.assertRaisesRegex(OperationError, "assignment_not_accepted"):
            self.apply(self.event("assignment.eta_updated", eta_min=5))
        self.apply(self.event("assignment.accepted"))
        for bad in (True, -1, 241, "cinco"):
            with self.assertRaises(OperationError):
                self.apply(self.event("assignment.eta_updated", eta_min=bad))
        self.apply(self.event("assignment.eta_updated", eta_min=5))
        self.assertEqual(self.docs["assignment/assignment-1"]["eta_min"], 5)

    def test_completed_task_closes_only_without_other_open_assignments(self):
        self.apply(self.event("assignment.accepted"))
        for kind in ("assignment.arrived", "assignment.located", "assignment.completed"):
            self.apply(self.event(kind))
        self.assertEqual(self.docs["incident/incident-1"]["status"], "closed")
        self.assertEqual(self.docs["reservation/actor:worker-1"], {})
        with self.assertRaisesRegex(OperationError, "incident_closed"):
            self.apply(self.event("assignment.accepted"))

    def test_other_team_keeps_incident_open(self):
        self.docs["incident/incident-1"]["assignment_ids"].append("assignment-2")
        self.docs["assignment/assignment-2"] = {"status": "accepted", "actor_id": "worker-2", "incident_id": "incident-1"}
        self.versions["assignment/assignment-2"] = 1
        self.apply(self.event("assignment.accepted"))
        self.apply(self.event("assignment.arrived"))
        self.apply(self.event("assignment.located"))
        self.apply(self.event("assignment.completed"))
        self.assertEqual(self.docs["incident/incident-1"]["status"], "open")

    def test_worker_question_and_reporter_answer_are_bound_to_incident(self):
        self.apply(self.event("assignment.accepted"))
        question = dict(self.event("question.created", text="¿Cuántos heridos hay?"), question_id="question-1")
        result = self.apply(question)
        self.assertEqual(self.docs["question/question-1"]["recipient_id"], "reporter-1")
        self.assertEqual(result["messages"][0]["question_id"], "question-1")
        answer = dict(self.event("question.answered", actor="reporter-1", text="Solo uno"), question_id="question-1")
        result = self.apply(answer)
        self.assertEqual(result["messages"][0]["recipient_id"], "worker-1")
        self.assertEqual(self.docs["question/question-1"]["status"], "answered")
        self.assertEqual(self.apply(answer)["messages"], [])

    def test_question_cannot_be_answered_by_another_worker(self):
        self.apply(self.event("assignment.accepted"))
        self.apply(dict(self.event("question.created", text="¿Sigue ardiendo?"), question_id="question-1"))
        with self.assertRaisesRegex(OperationError, "question_for_other_actor"):
            self.apply(dict(self.event("question.answered", actor="worker-2", text="No"), question_id="question-1"))

    def test_second_question_does_not_overwrite_first(self):
        self.docs["question/question-2"] = None
        self.versions["question/question-2"] = 0
        self.apply(self.event("assignment.accepted"))
        self.apply(dict(self.event("question.created", text="¿Cuántos heridos?"), question_id="question-1"))
        self.apply(dict(self.event("question.created", text="¿Sigue ardiendo?"), question_id="question-2"))
        self.assertEqual(self.docs["question/question-1"]["text"], "¿Cuántos heridos?")
        self.assertEqual(self.docs["question/question-2"]["status"], "pending")

    def test_unknown_snapshot_requires_read_and_does_not_mutate_input(self):
        event = self.event("assignment.accepted")
        snapshot = {key: {"version": self.versions[key], "value": value} for key, value in self.docs.items()}
        before = copy.deepcopy(snapshot)
        apply_event(event, snapshot)
        self.assertEqual(snapshot, before)
        del snapshot["reservation/task:medical-task"]
        with self.assertRaisesRegex(OperationError, "snapshot_missing"):
            apply_event(event, snapshot)

    def test_call_end_never_closes_incident(self):
        result = self.apply(dict(self.event("call.ended"), call_id="call-1"))
        self.assertEqual(result["writes"], [])
        self.assertEqual(result["messages"], [])
        self.assertEqual(self.docs["incident/incident-1"]["status"], "open")

    def test_decline_keeps_question_about_availability_and_blocks_late_accept(self):
        self.docs["question/availability:assignment-1"] = None
        self.versions["question/availability:assignment-1"] = 0
        result = self.apply(self.event("assignment.declined", reason="Atendiendo otro aviso"))
        self.assertEqual(self.docs["question/availability:assignment-1"]["kind"], "availability")
        self.assertEqual(result["messages"][0]["recipient_id"], "worker-1")
        with self.assertRaisesRegex(OperationError, "invalid_transition"):
            self.apply(self.event("assignment.accepted"))

    def test_unimplemented_events_fail_instead_of_creating_incidents(self):
        with self.assertRaisesRegex(OperationError, "unsupported_operation"):
            self.apply(self.event("message.received", text="Hola"))


if __name__ == "__main__":
    unittest.main()
