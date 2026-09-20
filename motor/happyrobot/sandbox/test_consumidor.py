import copy
import json
import unittest
from unittest.mock import Mock

from motor.happyrobot.sandbox import test_operaciones
from motor.happyrobot.sandbox.fa_consumidor import consume, consumer_input, finish_input, recover, snapshot_input
from motor.happyrobot.sandbox.fa_operaciones import apply_event


class ConsumerTest(unittest.TestCase):
    def setUp(self):
        self.fixture = test_operaciones.OperacionesTest()
        self.fixture.setUp()
        self.event = self.fixture.event("assignment.accepted")
        self.snapshots = {key: {"version": self.fixture.versions[key], "value": value}
                          for key, value in self.fixture.docs.items()}
        self.calls = []
        self.conflicts = 0
        self.applied = False

    def api(self, path, body):
        self.calls.append((path, copy.deepcopy(body)))
        if path == "/inbox/event":
            return {"status": "applied" if self.applied else "pending", "event": self.event}
        if path == "/snapshot":
            return {key: copy.deepcopy(self.snapshots[key]) for key in body["entities"]}
        if path == "/commit":
            if self.conflicts:
                self.conflicts -= 1
                for key in self.snapshots:
                    if self.snapshots[key]["value"] is not None:
                        self.snapshots[key]["version"] += 1
                return {"status": "conflict"}
            self.assertEqual(body, apply_event(self.event, self.snapshots))
            self.applied = True
            return {"status": "applied"}
        if path == "/inbox/settle":
            return {"status": body["status"]}
        raise AssertionError(path)

    def test_loads_missing_entities_and_commits_the_exact_operation(self):
        before = copy.deepcopy(self.snapshots)
        result = consume(self.event["event_id"], self.api)
        self.assertEqual(result["status"], "applied")
        self.assertEqual(self.snapshots, before)
        self.assertEqual(len([call for call in self.calls if call[0] == "/commit"]), 1)
        self.assertEqual(len([call for call in self.calls if call[0] == "/inbox/settle"]), 0)

    def test_conflict_refreshes_all_versions_before_recomputing(self):
        self.conflicts = 1
        self.assertEqual(consume(self.event["event_id"], self.api)["status"], "applied")
        commits = [body for path, body in self.calls if path == "/commit"]
        self.assertEqual(len(commits), 2)
        self.assertEqual(commits[1]["expected"]["actor/worker-1"], commits[0]["expected"]["actor/worker-1"] + 1)

    def test_conflicts_are_bounded_and_deferred_for_recovery(self):
        self.conflicts = 100
        result = consume(self.event["event_id"], self.api)
        self.assertEqual(result["status"], "deferred")
        self.assertEqual(len([call for call in self.calls if call[0] == "/commit"]), 3)
        self.assertEqual(self.calls[-1], ("/inbox/settle", {"id": self.event["event_id"], "status": "deferred", "reason": "conflict"}))

    def test_replayed_event_is_not_evaluated_or_notified_again(self):
        self.applied = True
        self.assertEqual(consume(self.event["event_id"], self.api)["status"], "duplicate")
        self.assertEqual(len(self.calls), 1)

    def test_invalid_operation_is_quarantined_without_commit(self):
        self.event["event_type"] = "incident.closed"
        self.assertEqual(consume(self.event["event_id"], self.api)["status"], "rejected")
        self.assertEqual(self.calls[-1][1]["reason"], "unsupported_operation")
        self.assertFalse(any(path == "/commit" for path, _ in self.calls))

    def test_free_text_and_deadlines_stay_pending_for_the_happyrobot_coordinator(self):
        for kind in ("message.received", "deadline.elapsed", "review.requested"):
            self.calls.clear()
            self.event["event_type"] = kind
            self.assertEqual(consume(self.event["event_id"], self.api)["status"], "needs_coordination")
            self.assertEqual(len(self.calls), 1)

    def test_missing_snapshot_is_not_interpreted_as_nonexistent_entity(self):
        def incomplete(path, body):
            return {} if path == "/snapshot" else self.api(path, body)
        self.assertEqual(consume(self.event["event_id"], incomplete)["status"], "deferred")
        self.assertFalse(any(path == "/commit" for path, _ in self.calls))

    def test_transport_errors_do_not_leak_or_create_side_effects(self):
        api = Mock(side_effect=RuntimeError("private-token"))
        result = consume(self.event["event_id"], api)
        self.assertEqual(result["status"], "unavailable")
        self.assertNotIn("private-token", json.dumps(result))
        self.assertEqual(api.call_count, 1)

    def test_commit_timeout_is_reconciled_via_event_status(self):
        def timeout(path, body):
            result = self.api(path, body)
            if path == "/commit":
                raise TimeoutError("private-details")
            return result
        self.assertEqual(consume(self.event["event_id"], timeout)["status"], "unavailable")
        self.assertEqual(consume(self.event["event_id"], self.api)["status"], "duplicate")
        self.assertEqual(len([call for call in self.calls if call[0] == "/commit"]), 1)

    def test_recovery_is_bounded_and_continues_past_a_bad_event(self):
        calls = []
        def api(path, body):
            calls.append((path, body))
            if path == "/inbox/pending":
                return ["bad", "done"]
            if path == "/inbox/event":
                if body["id"] == "bad":
                    raise TimeoutError()
                return {"status": "applied", "event": {"event_id": "done"}}
            raise AssertionError(path)
        result = recover(api, limit=2)
        self.assertEqual(result["processed"], 2)
        self.assertEqual([item["status"] for item in result["results"]], ["unavailable", "duplicate"])
        self.assertEqual(calls[0], ("/inbox/pending", {"limit": 2}))

    def test_network_failure_status_zero_is_not_treated_as_http_success(self):
        first = consumer_input({"event_id": self.event["event_id"]})
        result = consumer_input({"event_id": self.event["event_id"], "state_json": first["state_json"],
                                 "response_json": {"status": "pending", "event": self.event}, "status_code": 0})
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["path"], "")

    def test_complete_snapshot_prepares_the_same_commit_without_extra_read_steps(self):
        output = snapshot_input({"event_id": self.event["event_id"], "state_status": "pending", "status_code": 200,
                                 "event_json": json.dumps(self.event), "snapshot_json": json.dumps(self.snapshots)})
        self.assertEqual(output["path"], "/commit")
        self.assertEqual(json.loads(output["body_json"]), apply_event(self.event, self.snapshots))

    def test_snapshot_entry_never_commits_after_a_failed_http_read_or_replay(self):
        for status, code in (("pending", 503), ("applied", 200), ("rejected", 200)):
            output = snapshot_input({"event_id": self.event["event_id"], "state_status": status, "status_code": code,
                                     "event_json": self.event, "snapshot_json": self.snapshots})
            self.assertEqual(output["path"], "/inbox/status")

    def test_native_loop_finish_defers_operations_but_keeps_coordination_events_pending(self):
        for kind in ("assignment.accepted", "message.received"):
            output = finish_input({"event_id": self.event["event_id"], "status_code": 200,
                "status_json": {"event_id": self.event["event_id"], "status": "pending", "event_type": kind}})
            self.assertEqual(output["path"], "/inbox/settle" if kind == "assignment.accepted" else "/inbox/status")
        output = finish_input({"event_id": self.event["event_id"], "status_code": 503, "status_json": {}})
        self.assertEqual(output["path"], "/inbox/status")

    def test_mismatched_event_id_cannot_be_processed(self):
        result = consume("other-event", self.api)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(len(self.calls), 1)


if __name__ == "__main__":
    unittest.main()
