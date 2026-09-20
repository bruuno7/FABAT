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
        self.sequence = 0

    def seed(self, entity, value=None):
        self.docs[entity] = value
        self.versions[entity] = 1 if value is not None else 0

    def event(self, kind, actor="worker-1", **payload):
        self.sequence += 1
        return {
            "schema_version": 2, "event_id": "event-" + str(self.sequence), "event_type": kind,
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
        self.seed("reservation/actor:worker-1", {"assignment_id": "different"})
        with self.assertRaisesRegex(OperationError, "actor_busy"):
            self.apply(self.event("assignment.accepted"))
        self.seed("reservation/actor:worker-1")
        self.seed("reservation/task:medical-task", {"assignment_id": "different"})
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

    def test_required_task_without_an_offer_prevents_automatic_closure(self):
        self.docs["incident/incident-1"]["tasks"] = {"medical-task": {"role": "medico"}, "fire-task": {"role": "bomberos"}}
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

    def test_report_persists_incident_and_conversation_without_promising_dispatch(self):
        self.seed("incident/new-incident")
        self.seed("conversation/conversation-1")
        event = dict(self.event("incident.reported", actor="reporter-1", text="Humo en un móvil", location="barra 3"), incident_id="new-incident")
        result = self.apply(event)
        self.assertEqual(self.docs["incident/new-incident"]["reporter_id"], "reporter-1")
        self.assertEqual(self.docs["conversation/conversation-1"]["incident_ids"], ["new-incident"])
        self.assertEqual(self.docs["incident/new-incident"]["assignment_ids"], [])
        self.assertNotIn("avisando", result["messages"][0]["text"])
        with self.assertRaisesRegex(OperationError, "incident_exists"):
            self.apply(event)

    def test_context_keeps_two_incidents_without_expiring_incident_state(self):
        self.seed("incident/new-incident")
        self.seed("conversation/conversation-1", {"actor_id": "reporter-1", "incident_ids": ["incident-1"]})
        self.apply(dict(self.event("incident.reported", actor="reporter-1", text="Hay otro incidente"), incident_id="new-incident"))
        self.assertEqual(self.docs["conversation/conversation-1"]["incident_ids"], ["incident-1", "new-incident"])
        self.assertEqual(self.docs["incident/incident-1"]["status"], "open")

    def test_offer_requires_coordinator_permission_and_matching_capacity(self):
        self.seed("actor/coordinator", {"permissions": ["coordinate"]})
        self.seed("assignment/new-assignment")
        event = dict(self.event("assignment.offered", recipient_id="worker-2", role="medico", task_id="medical-task"), assignment_id="new-assignment")
        with self.assertRaisesRegex(OperationError, "coordinator_required"):
            self.apply(event)
        event["actor_id"] = "coordinator"
        event["payload"]["role"] = "bomberos"
        with self.assertRaisesRegex(OperationError, "capacity_mismatch"):
            self.apply(event)
        event["payload"]["role"] = "medico"
        self.seed("reservation/actor:worker-2")
        result = self.apply(event)
        self.assertEqual(self.docs["assignment/new-assignment"]["status"], "offered")
        self.assertEqual(result["messages"][0]["purpose"], "offer")
        self.assertEqual(result["messages"][0]["assignment_id"], "new-assignment")
        self.assertEqual(self.docs["reservation/actor:worker-2"]["assignment_id"], "new-assignment")

    def test_offer_cannot_change_capacity_for_existing_task(self):
        self.seed("actor/coordinator", {"permissions": ["coordinate"]})
        self.seed("assignment/new-assignment")
        self.docs["incident/incident-1"]["tasks"] = {"medical-task": {"role": "bomberos"}}
        with self.assertRaisesRegex(OperationError, "task_capacity_mismatch"):
            self.apply(dict(self.event("assignment.offered", actor="coordinator", recipient_id="worker-2", role="medico", task_id="medical-task"), assignment_id="new-assignment"))

    def test_role_claim_requires_an_unexpired_actor_bound_grant(self):
        self.docs["actor/worker-1"]["roles"] = []
        self.seed("approval/grant-1", {"kind": "role_claim", "actor_id": "worker-2", "role": "medico", "expires_at": "2026-09-19T15:00:00Z", "status": "approved"})
        self.seed("reservation/role:medico")
        event = self.event("actor.role_claimed", role="medico", grant_id="grant-1")
        with self.assertRaisesRegex(OperationError, "invalid_role_grant"):
            self.apply(event)
        self.docs["approval/grant-1"]["actor_id"] = "worker-1"
        self.docs["approval/grant-1"]["expires_at"] = "2026-09-19T13:00:00Z"
        with self.assertRaisesRegex(OperationError, "invalid_role_grant"):
            self.apply(event)
        self.docs["approval/grant-1"]["expires_at"] = "2026-09-19T15:00:00Z"
        self.apply(event)
        self.assertEqual(self.docs["actor/worker-1"]["roles"], ["medico"])
        self.assertEqual(self.docs["reservation/role:medico"]["actor_id"], "worker-1")
        self.assertEqual(self.docs["approval/grant-1"]["status"], "consumed")

    def test_taken_role_and_release_while_assigned_are_rejected(self):
        self.seed("approval/grant-1", {"kind": "role_claim", "actor_id": "worker-1", "role": "medico", "expires_at": "2026-09-19T15:00:00Z", "status": "approved"})
        self.seed("reservation/role:medico", {"actor_id": "worker-2"})
        with self.assertRaisesRegex(OperationError, "role_taken"):
            self.apply(self.event("actor.role_claimed", role="medico", grant_id="grant-1"))
        self.apply(self.event("assignment.accepted"))
        with self.assertRaisesRegex(OperationError, "actor_busy"):
            self.apply(self.event("actor.role_released"))

    def test_unknown_availability_keeps_question_open_and_never_means_now(self):
        self.seed("question/availability:assignment-1")
        self.apply(self.event("assignment.declined", reason="Estoy ocupado"))
        event = dict(self.event("question.answered", text="No sé cuándo podré", available_in_min=None), question_id="availability:assignment-1")
        self.apply(event)
        self.assertEqual(self.docs["actor/worker-1"]["availability"], "unknown")
        self.assertEqual(self.docs["question/availability:assignment-1"]["status"], "pending")
        event = dict(self.event("question.answered", text="En quince minutos", available_in_min=15), question_id="availability:assignment-1")
        self.apply(event)
        self.assertEqual(self.docs["actor/worker-1"]["available_after"], "2026-09-19T14:15:01Z")
        self.assertEqual(self.docs["question/availability:assignment-1"]["status"], "answered")

    def test_unavailable_actor_cannot_accept_even_without_active_reservation(self):
        self.docs["actor/worker-1"].update(availability="unknown", available_after=None)
        with self.assertRaisesRegex(OperationError, "actor_unavailable"):
            self.apply(self.event("assignment.accepted"))
        self.docs["actor/worker-1"].update(availability="unavailable", available_after="2026-09-19T14:05:00Z")
        with self.assertRaisesRegex(OperationError, "actor_unavailable"):
            self.apply(self.event("assignment.accepted"))
        self.docs["actor/worker-1"]["available_after"] = "2026-09-19T13:59:00Z"
        self.apply(self.event("assignment.accepted"))

    def test_reporter_location_update_preserves_incident_and_question_reference(self):
        self.apply(self.event("assignment.accepted"))
        result = self.apply(self.event("incident.updated", actor="reporter-1", text="Estamos en la barra 4, no en la 3", location="barra 4"))
        self.assertEqual(self.docs["incident/incident-1"]["location"], "barra 4")
        self.assertEqual(result["messages"][0]["recipient_id"], "worker-1")
        with self.assertRaisesRegex(OperationError, "incident_for_other_actor"):
            self.apply(self.event("incident.updated", actor="worker-2", text="Esto no es mi incidente"))

    def test_closure_request_asks_reporter_before_closing(self):
        self.seed("actor/coordinator", {"permissions": ["coordinate"]})
        self.apply(self.event("assignment.accepted"))
        event = dict(self.event("incident.close_requested", actor="coordinator"), question_id="question-1")
        self.apply(event)
        self.assertEqual(self.docs["incident/incident-1"]["status"], "open")
        self.assertEqual(self.docs["question/question-1"]["kind"], "closure")
        result = self.apply(dict(self.event("question.answered", actor="reporter-1", text="Sí, está resuelto", confirmed=True), question_id="question-1"))
        self.assertEqual(self.docs["incident/incident-1"]["status"], "closed")
        self.assertEqual(self.docs["assignment/assignment-1"]["status"], "cancelled")
        self.assertEqual(self.docs["reservation/actor:worker-1"], {})
        self.assertIn("worker-1", [m["recipient_id"] for m in result["messages"]])

    def test_rejected_closure_keeps_incident_open(self):
        self.apply(dict(self.event("incident.close_requested", actor="reporter-1"), question_id="question-1"))
        self.apply(dict(self.event("question.answered", actor="reporter-1", text="No, todavía necesitamos ayuda", confirmed=False), question_id="question-1"))
        self.assertEqual(self.docs["incident/incident-1"]["status"], "open")
        self.assertEqual(self.docs["question/question-1"]["status"], "answered")

    def test_snapshot_version_zero_is_required_for_missing_entities(self):
        snapshot = {key: {"version": self.versions[key], "value": value} for key, value in self.docs.items()}
        snapshot["actor/worker-1"]["value"] = None
        with self.assertRaisesRegex(OperationError, "invalid_snapshot"):
            apply_event(self.event("assignment.accepted"), snapshot)

    def test_unimplemented_events_fail_instead_of_creating_incidents(self):
        with self.assertRaisesRegex(OperationError, "unsupported_operation"):
            self.apply(self.event("message.received", text="Hola"))


if __name__ == "__main__":
    unittest.main()
