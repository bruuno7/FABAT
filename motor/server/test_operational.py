"""Offline operational contract tests; all actors and addresses are synthetic."""
from __future__ import annotations

import copy
import json
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import cast
from unittest.mock import patch

from motor.server.operational import ACTIVE, OperationalError, OperationalStore
from motor.server.operational_types import Document, JSON, State


FESTIVAL: Document = {
    "zones": [
        {"id": "front_pit", "name": "Escenario 1", "kind": "stage"},
        {"id": "gate_a", "name": "Puerta A", "kind": "gate"},
    ],
}


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class OperationalTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "operations.sqlite"
        self.clock = Clock()
        self.store = self.open_store()
        self.sequence = 0

    def open_store(self) -> OperationalStore:
        store = OperationalStore(self.path, FESTIVAL, clock=self.clock)
        self.addCleanup(store.close)
        return store

    def command(self, kind: str, *, scope: str = "operator", principal: str = "operator",
                channel: str = "web", **fields: JSON) -> Document:
        self.sequence += 1
        return self.store.execute(
            {"command_id": f"cmd-{self.sequence}", "kind": kind, **fields},
            principal=principal, scope=scope, channel=channel,
        )

    def records(self, collection: str) -> list[Document]:
        return cast(list[Document], self.store.state()[collection])

    def assert_rejected_without_mutation(self, before: Document, count: int = 1) -> None:
        after = self.store.state()
        self.assertEqual(
            {k: v for k, v in before.items() if k not in {"revision", "events"}},
            {k: v for k, v in after.items() if k not in {"revision", "events"}},
        )
        previous = cast(list[Document], before["events"])
        events = cast(list[Document], after["events"])
        self.assertEqual(events[:len(previous)], previous)
        self.assertEqual([e["kind"] for e in events[len(previous):]], ["command.rejected"] * count)
        self.assertEqual(after["revision"], cast(int, before["revision"]) + count)

    def record(self, collection: str, identifier: str) -> Document:
        return next(item for item in self.records(collection) if item["id"] == identifier)

    def register(self, identifier: str = "medic", role: str = "medico", *,
                 channel: str = "telegram", availability: str = "available") -> str:
        self.sequence += 1
        self.store.execute({
            "command_id": f"cmd-{self.sequence}", "kind": "register_actor", "actor_id": identifier,
            "name": identifier, "roles": [role], "channel": channel,
            "address": f"synthetic-address-{identifier}", "availability": availability, "zone": "front_pit",
        })
        return identifier

    def identify(self, identifier: str) -> None:
        self.sequence += 1
        self.store.execute({
            "command_id": f"cmd-{self.sequence}", "kind": "identify", "channel": "telegram",
            "address": f"synthetic-address-{identifier}", "name": identifier,
        }, scope="telegram", channel="telegram", principal=identifier)

    def report(self, text: str = "Persona inconsciente no respira",
               zone: str | None = "front_pit", reporter: str = "operator") -> str:
        result = self.command(
            "report", text=text, zone=zone, principal=reporter,
            scope="operator" if reporter == "operator" else "telegram",
            channel="web" if reporter == "operator" else "telegram",
        )
        return cast(str, result["incident_id"])

    def transition(self, assignment: str, kind: str, **fields: JSON) -> Document:
        item = self.record("assignments", assignment)
        actor = self.record("actors", cast(str, item["actor_id"]))
        return self.command(kind, assignment_id=assignment, expected_version=item["version"],
                            scope=cast(str, actor["channel"]), channel=cast(str, actor["channel"]),
                            principal=cast(str, actor["id"]), **fields)

    def first_assignment(self) -> str:
        return cast(str, self.records("assignments")[0]["id"])

    def proposal(self, incident: str, *, scope: str = "operator",
                 actions: list[Document] | None = None, requires_person: bool = False) -> str:
        result = self.command("propose", incident_id=incident, scope=scope,
                              expected_version=self.record("incidents", incident)["version"],
                              actions=cast(JSON, actions or [{"kind": "stop_show"}]),
                              requiere_persona=requires_person, reason="Revisión de coordinación")
        return cast(str, result["approval_id"])

    def decide(self, identifier: str, approved: bool = True, *, scope: str = "operator") -> Document:
        approval = self.record("approvals", identifier)
        return self.command("decide", approval_id=identifier, approved=approved, scope=scope,
                            expected_version=approval["version"], content_hash=approval["content_hash"])

    def test_identification_cannot_grant_roles_or_impersonate(self) -> None:
        self.identify("reporter")
        self.assertEqual(self.record("actors", "reporter")["roles"], [])
        with self.assertRaises(OperationalError) as denied:
            self.store.execute({
                "command_id": "grant", "kind": "register_actor", "actor_id": "reporter",
                "name": "reporter", "roles": ["medico"], "channel": "telegram",
                "address": "synthetic-address-reporter", "availability": "available",
            }, principal="reporter", scope="telegram", channel="telegram")
        self.assertEqual(denied.exception.status, 403)
        with self.assertRaises(OperationalError):
            self.store.execute({
                "command_id": "spoof", "kind": "identify", "actor_id": "someone-else",
                "name": "name", "channel": "telegram", "address": "synthetic-other",
            }, principal="reporter", scope="telegram", channel="telegram")
        with self.assertRaises(OperationalError):
            self.store.execute({
                "command_id": "role-injection", "kind": "identify", "roles": ["medico"],
                "channel": "telegram", "address": "synthetic-other",
            }, principal="reporter", scope="telegram", channel="telegram")
        self.assertEqual(self.record("actors", "reporter")["roles"], [])

    def test_only_owner_can_mutate_task_report_and_availability(self) -> None:
        self.identify("alice")
        self.identify("bob")
        self.register()
        iid = self.report(reporter="alice")
        aid = self.first_assignment()
        before = self.store.state()
        operations: list[Document] = [
            {"kind": "accept", "assignment_id": aid, "expected_version": 1},
            {"kind": "update", "incident_id": iid,
             "expected_version": self.record("incidents", iid)["version"], "text": "Otro dato"},
            {"kind": "availability", "actor_id": "medic", "availability": "unavailable",
             "expected_version": self.record("actors", "medic")["version"]},
        ]
        for index, command in enumerate(operations):
            with self.assertRaises(OperationalError) as denied:
                self.store.execute({"command_id": f"forbidden-{index}", **command},
                                   principal="bob", scope="telegram", channel="telegram")
            self.assertEqual(denied.exception.status, 403)
        self.assert_rejected_without_mutation(before, 3)

    def test_wrong_transport_and_body_principal_are_rejected(self) -> None:
        self.identify("alice")
        for fields in ({"principal": "operator"}, {}):
            with self.assertRaises(OperationalError):
                self.store.execute({
                    "command_id": "spoof-channel", "kind": "report", "text": "Fuego", **fields,
                }, principal="alice", scope="telegram", channel="phone")
        self.assertEqual(self.records("incidents"), [])

    def test_medical_needs_cannot_be_satisfied_by_police(self) -> None:
        self.register("officer", "policia")
        iid = self.report()
        self.assertEqual(self.records("assignments"), [])
        incident = self.record("incidents", iid)
        self.assertIn("medico", cast(dict[str, JSON], incident["needs"]))
        self.assertIn("no_available_medico", cast(str, incident["why_waiting"]))
        for role in ("policia", "medico"):
            with self.assertRaises(OperationalError) as denied:
                self.command("offer", incident_id=iid, actor_id="officer", role=role,
                             expected_version=incident["version"])
            self.assertEqual(denied.exception.code, "capacity_mismatch")
        self.register()
        self.assertEqual(self.records("assignments")[0]["actor_id"], "medic")

    def test_explicit_offer_uses_selected_task_and_deadline(self) -> None:
        self.register()
        with patch.object(self.store, "_replan"):
            iid = self.report()
        incident = self.record("incidents", iid)
        with self.store._transaction() as (data, _):
            task_id = next(iter(data["incidents"][iid]["tasks"]))
        result = self.command("offer", incident_id=iid, actor_id="medic", role="medico",
                              task_id=task_id, ttl_seconds=45,
                              expected_version=incident["version"])
        assignment = self.record("assignments", cast(str, result["assignment_id"]))
        self.assertEqual(assignment["task_id"], task_id)
        self.assertEqual(assignment["expires_at"], self.clock.now + 45)
        with self.assertRaises(OperationalError):
            self.command("offer", incident_id=iid, actor_id="medic", role="medico",
                         task_id=task_id, expected_version=self.record("incidents", iid)["version"])

    def test_same_zone_victims_remain_distinct_and_missing_location_waits(self) -> None:
        self.identify("alice")
        self.identify("bob")
        one = self.report(reporter="alice")
        two = self.report(reporter="bob")
        three = self.report(zone=None, reporter="alice")
        self.assertEqual(len({one, two, three}), 3)
        self.assertIn("location_required", cast(str, self.record("incidents", three)["why_waiting"]))
        questions = [d for d in self.store.claim("test-worker") if d["purpose"] == "question"]
        self.assertEqual(len(questions), 1)
        self.assertEqual(questions[0]["recipient_id"], "alice")
        self.register()
        self.command("update", incident_id=three, text="Confirmo ubicación", zone="gate_a",
                     expected_version=self.record("incidents", three)["version"],
                     scope="telegram", channel="telegram", principal="alice")
        self.assertEqual(self.record("incidents", three)["zone"], "gate_a")
        self.assertNotIn("location_required", cast(str, self.record("incidents", three)["why_waiting"]))

    def test_dedup_and_collisions_survive_reopen(self) -> None:
        command: Document = {"command_id": "stable-report", "kind": "report",
                             "text": "Persona inconsciente", "zone": "front_pit"}
        first = self.store.execute(command)
        before = self.store.state()
        self.store.close()
        self.store = self.open_store()
        duplicate = self.store.execute(command)
        self.assertEqual(duplicate, {**first, "duplicate": True})
        self.assertEqual(before, self.store.state())
        with self.assertRaises(OperationalError) as collision:
            self.store.execute({**command, "text": "Otro aviso"})
        self.assertEqual((collision.exception.status, collision.exception.code), (409, "command_id_collision"))
        with self.assertRaises(OperationalError):
            self.store.execute(command, principal="other-operator")
        self.assertEqual(len(self.records("incidents")), 1)

    def test_invalid_command_result_is_durable_and_has_no_partial_effects(self) -> None:
        self.register()
        self.report()
        aid = self.first_assignment()
        command: Document = {"command_id": "too-soon", "kind": "complete",
                             "assignment_id": aid, "expected_version": 1}
        for _ in range(2):
            with self.assertRaises(OperationalError) as error:
                self.store.execute(command)
            self.assertEqual(error.exception.code, "invalid_transition")
            self.store.close()
            self.store = self.open_store()
        with self.assertRaises(OperationalError) as collision:
            self.store.execute({**command, "kind": "accept"})
        self.assertEqual(collision.exception.code, "command_id_collision")
        self.assertEqual(self.record("assignments", aid)["status"], "offered")

    def test_assignment_order_versions_eta_and_stale_callbacks(self) -> None:
        self.register(channel="phone")
        iid = self.report()
        aid = self.first_assignment()
        for kind in ("eta", "arrive", "locate", "complete"):
            with self.assertRaises(OperationalError):
                self.transition(aid, kind)
        self.transition(aid, "accept")
        invalid_etas: list[Document] = [
            {"eta_min": 5, "destination_zone_id": "front_pit", "destination_confirmed": False},
            {"eta_min": 5, "destination_zone_id": "gate_a", "destination_confirmed": True},
            {"eta_min": True, "destination_zone_id": "front_pit", "destination_confirmed": True},
            {"eta_min": 241, "destination_zone_id": "front_pit", "destination_confirmed": True},
        ]
        for fields in invalid_etas:
            with self.assertRaises(OperationalError):
                self.transition(aid, "eta", **fields)
        self.transition(aid, "eta", eta_min=5, destination_zone_id="front_pit", destination_confirmed=True)
        self.assertEqual(self.record("assignments", aid)["eta_min"], 5)
        with self.assertRaises(OperationalError) as stale:
            self.command("arrive", assignment_id=aid, expected_version=1)
        self.assertEqual(stale.exception.code, "stale_version")
        self.transition(aid, "arrive")
        self.transition(aid, "locate")
        self.transition(aid, "complete")
        self.assertEqual(self.record("incidents", iid)["status"], "closed")
        with self.assertRaises(OperationalError):
            self.transition(aid, "call_result", result="accept", metadata={})
        self.assertEqual(self.record("assignments", aid)["status"], "completed")

    def test_call_result_never_accepts_arrives_or_completes(self) -> None:
        self.register(channel="phone")
        self.report()
        aid = self.first_assignment()
        for result in ("accept", "reject", "no_answer", "unknown", "unclear", "timeout", "provider_failed"):
            self.transition(aid, "call_result", result=result, metadata={"details": "synthetic-private"})
            self.assertEqual(self.record("assignments", aid)["status"], "offered")
            self.assertIsNone(self.record("assignments", aid)["eta_min"])
        self.assertNotIn("synthetic-private", json.dumps(self.store.state()))

    def test_offer_deadline_rejects_accept_then_replans_and_is_idempotent(self) -> None:
        self.register("medic-a")
        self.register("medic-b")
        iid = self.report()
        aid = self.first_assignment()
        self.clock.now = cast(float, self.record("assignments", aid)["expires_at"])
        with self.assertRaises(OperationalError) as late:
            self.transition(aid, "accept")
        self.assertEqual(late.exception.code, "offer_expired")
        self.store.reconcile()
        self.assertEqual(self.record("assignments", aid)["status"], "expired")
        active = [a for a in self.records("assignments") if a["status"] == "offered"]
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["actor_id"], "medic-b")
        self.assertEqual(self.record("actors", "medic-a")["availability"], "unknown")
        before = self.store.state()
        self.store.reconcile()
        self.assertEqual(before, self.store.state())
        self.assertEqual(active[0]["incident_id"], iid)

    def test_accept_before_deadline_cannot_be_expired_later(self) -> None:
        self.register()
        self.report()
        aid = self.first_assignment()
        self.clock.now += 119
        self.transition(aid, "accept")
        self.clock.now += 1000
        self.store.reconcile()
        self.assertEqual(self.record("assignments", aid)["status"], "accepted")

    def test_decline_does_not_recycle_same_actor_even_after_availability(self) -> None:
        self.register()
        iid = self.report()
        self.transition(self.first_assignment(), "decline", reason="No puedo atender ahora")
        self.command("availability", actor_id="medic", availability="available",
                     expected_version=self.record("actors", "medic")["version"])
        self.assertEqual(len(self.records("assignments")), 1)
        self.assertIn("no_available_medico", cast(str, self.record("incidents", iid)["why_waiting"]))
        self.register("backup")
        self.assertEqual(self.records("assignments")[-1]["actor_id"], "backup")

    def test_only_lower_priority_offers_are_preempted(self) -> None:
        self.register()
        low = self.report("Persona con mareo leve")
        offered = self.first_assignment()
        high = self.report()
        self.assertGreater(cast(float, self.record("incidents", high)["priority"]),
                           cast(float, self.record("incidents", low)["priority"]))
        self.assertEqual(self.record("assignments", offered)["status"], "cancelled")
        active = next(a for a in self.records("assignments") if a["status"] == "offered")
        self.assertEqual(active["incident_id"], high)
        self.assertTrue(self.record("incidents", low)["why_waiting"])

    def test_arrived_team_is_not_preempted_by_life_threat(self) -> None:
        self.register()
        self.report("Persona con mareo leve")
        aid = self.first_assignment()
        self.transition(aid, "accept")
        self.transition(aid, "arrive")
        high = self.report()
        self.assertEqual(self.record("assignments", aid)["status"], "arrived")
        self.assertEqual(len(self.records("assignments")), 1)
        self.assertTrue(self.record("incidents", high)["why_waiting"])

    def test_two_connections_race_for_last_resource(self) -> None:
        self.register()
        other = self.open_store()
        barrier = threading.Barrier(2)

        def report(store: OperationalStore, identifier: str) -> Document:
            barrier.wait(timeout=5)
            return store.execute({"command_id": identifier, "kind": "report",
                                  "text": "Persona inconsciente", "zone": "front_pit"})

        with ThreadPoolExecutor(max_workers=2) as workers:
            one = workers.submit(report, self.store, "race-one")
            two = workers.submit(report, other, "race-two")
            self.assertTrue(one.result(timeout=10)["ok"])
            self.assertTrue(two.result(timeout=10)["ok"])
        active = [a for a in self.records("assignments") if a["status"] in ACTIVE]
        self.assertEqual(len(active), 1)
        self.assertEqual(len(self.records("incidents")), 2)
        self.assertEqual(sum(bool(i["why_waiting"]) for i in self.records("incidents")), 1)
        with sqlite3.connect(self.path) as connection:
            self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            state = cast(State, json.loads(connection.execute("SELECT body FROM operational_state").fetchone()[0]))
        self.assertEqual(set(state["reservations"].values()), {active[0]["id"]})
        self.assertEqual(len(state["reservations"]), 2)

    def test_two_connections_deduplicate_same_command(self) -> None:
        other = self.open_store()
        command: Document = {"command_id": "concurrent-id", "kind": "report", "text": "Fuego", "zone": "gate_a"}
        barrier = threading.Barrier(2)

        def execute(store: OperationalStore) -> Document:
            barrier.wait(timeout=5)
            return store.execute(command)

        with ThreadPoolExecutor(max_workers=2) as workers:
            futures = [workers.submit(execute, store) for store in (self.store, other)]
            results = [f.result(timeout=10) for f in futures]
        self.assertEqual(sorted(cast(bool, r["duplicate"]) for r in results), [False, True])
        self.assertEqual(len(self.records("incidents")), 1)

    def test_approval_requires_exact_hash_version_and_operator(self) -> None:
        self.register("coordinator", "organizador")
        iid = self.report()
        approval_id = self.proposal(iid, scope="proposal")
        approval = self.record("approvals", approval_id)
        self.assertEqual(self.records("deliveries"), [])
        with self.assertRaises(OperationalError) as denied:
            self.decide(approval_id, scope="proposal")
        self.assertEqual(denied.exception.status, 403)
        for digest in ("0" * 64, "á" * 64):
            with self.assertRaises(OperationalError):
                self.command("decide", approval_id=approval_id, expected_version=approval["version"],
                             approved=True, content_hash=digest)
        self.decide(approval_id)
        self.assertEqual(self.record("approvals", approval_id)["status"], "approved")
        self.assertEqual(len(self.records("deliveries")), 1)
        self.assertEqual(self.records("deliveries")[0]["purpose"], "stop_show")
        with self.assertRaises(OperationalError):
            self.decide(approval_id)

    def test_approval_stales_after_update_and_expires_after_restart(self) -> None:
        self.register("coordinator", "organizador")
        iid = self.report()
        first = self.proposal(iid)
        self.command("update", incident_id=iid, expected_version=self.record("incidents", iid)["version"],
                     text="Confirmación adicional")
        with self.assertRaises(OperationalError):
            self.decide(first)
        self.assertEqual(self.record("approvals", first)["status"], "stale")
        second = self.proposal(iid)
        self.store.close()
        self.clock.now += 301
        self.store = self.open_store()
        with self.assertRaises(OperationalError):
            self.decide(second)
        self.store.reconcile()
        self.assertEqual(self.record("approvals", second)["status"], "expired")
        self.assertFalse(any(d["purpose"] == "stop_show" for d in self.records("deliveries")))

    def test_approval_revalidates_coordinator_availability(self) -> None:
        self.register("coordinator", "organizador")
        iid = self.report()
        approval_id = self.proposal(iid, actions=[{"kind": "stop_show", "actor_id": "coordinator"}])
        self.command("availability", actor_id="coordinator", availability="unavailable",
                     expected_version=self.record("actors", "coordinator")["version"])
        with self.assertRaises(OperationalError):
            self.decide(approval_id)
        self.assertEqual(self.record("approvals", approval_id)["status"], "pending")
        self.assertEqual(self.records("deliveries"), [])

    def test_requiere_persona_blocks_even_simple_notification(self) -> None:
        self.register("coordinator", "organizador")
        iid = self.report()
        approval_id = self.proposal(iid, requires_person=True, actions=[
            {"kind": "notify", "actor_id": "coordinator", "text": "Revisar punto de encuentro"},
        ])
        self.assertEqual(self.records("deliveries"), [])
        self.decide(approval_id, False)
        self.assertEqual(self.record("approvals", approval_id)["status"], "rejected")
        self.assertEqual(self.records("deliveries"), [])

    def test_operator_notification_without_guard_applies_immediately(self) -> None:
        self.register("coordinator", "organizador")
        iid = self.report()
        result = self.command("propose", incident_id=iid,
                              expected_version=self.record("incidents", iid)["version"],
                              actions=[{"kind": "notify", "actor_id": "coordinator",
                                        "text": "Revisar punto de encuentro"}],
                              requiere_persona=False, reason="Aviso interno")
        self.assertNotIn("approval_id", result)
        self.assertEqual(len(self.records("approvals")), 0)
        delivery = next(d for d in self.records("deliveries") if d["purpose"] == "notify")
        self.assertEqual(delivery["incident_id"], iid)

    def test_invalid_second_action_rolls_back_notification(self) -> None:
        self.register("coordinator", "organizador")
        iid = self.report()
        before = self.store.state()
        with self.assertRaises(OperationalError):
            self.proposal(iid, actions=[
                {"kind": "notify", "actor_id": "coordinator", "text": "No debe enviarse"},
                {"kind": "offer", "actor_id": "coordinator", "role": "medico"},
            ])
        self.assert_rejected_without_mutation(before)

    def test_competing_actions_roll_back_reservations_and_outbox(self) -> None:
        self.register()
        with patch.object(self.store, "_replan"):
            iid = self.report()
        before = self.store.state()
        with self.assertRaises(OperationalError):
            self.proposal(iid, actions=[
                {"kind": "offer", "actor_id": "medic", "role": "medico"},
                {"kind": "offer", "actor_id": "medic", "role": "medico"},
            ])
        self.assert_rejected_without_mutation(before)
        self.store.reconcile()
        self.assertEqual(len(self.records("assignments")), 1)

    def test_completion_releases_only_own_task_and_cleans_sibling_offers(self) -> None:
        self.register("medic-a")
        self.register("medic-b")
        self.register("officer", "policia")
        iid = self.report("Persona inconsciente no respira y hay una pelea")
        medical = next(a for a in self.records("assignments") if a["role"] == "medico")
        aid = cast(str, medical["id"])
        for kind in ("accept", "arrive", "locate"):
            self.transition(aid, kind)
        with self.store._transaction() as (data, now):
            sibling = copy.deepcopy(data["assignments"][aid])
            sibling.update({"id": "sibling", "version": 1, "actor_id": "medic-b", "status": "offered"})
            data["assignments"]["sibling"] = sibling
            data["reservations"]["actor:medic-b"] = "sibling"
            self.store._say(data, now, "medic-b", "offer", "Oferta hermana", iid, sibling)
        self.transition(aid, "complete")
        self.assertEqual(self.record("assignments", "sibling")["status"], "cancelled")
        with self.store._transaction() as (data, _):
            self.assertNotIn("actor:medic-a", data["reservations"])
            self.assertNotIn("actor:medic-b", data["reservations"])
            self.assertIn("actor:officer", data["reservations"])
        self.assertNotEqual(self.record("incidents", iid)["status"], "closed")
        self.assertTrue(all(d["status"] == "cancelled" for d in self.records("deliveries")
                            if d.get("assignment_id") == "sibling"))

    def test_delivery_lease_is_exclusive_and_stale_settlement_fails(self) -> None:
        self.register()
        self.report()
        other = self.open_store()
        delivery = self.store.claim("worker-one", lease_seconds=10)[0]
        self.assertEqual(other.claim("worker-two"), [])
        self.assertFalse(self.store.settle(cast(str, delivery["id"]), "invalid-token", "delivered"))
        self.clock.now += 10
        self.assertFalse(self.store.settle(cast(str, delivery["id"]), cast(str, delivery["lease_token"]), "delivered"))
        reclaimed = other.claim("worker-two")[0]
        self.assertEqual(reclaimed["attempts"], 2)
        self.assertNotEqual(reclaimed["lease_token"], delivery["lease_token"])
        self.assertFalse(self.store.settle(cast(str, delivery["id"]), cast(str, delivery["lease_token"]), "delivered"))
        self.assertTrue(other.settle(cast(str, reclaimed["id"]), cast(str, reclaimed["lease_token"]), "delivered"))

    def test_retry_backoff_and_transition_cancel_leased_work(self) -> None:
        self.register()
        self.report()
        delivery = self.store.claim("worker")[0]
        self.assertTrue(self.store.settle(cast(str, delivery["id"]), cast(str, delivery["lease_token"]),
                                         "retry", retry_after_s=10))
        self.assertEqual(self.store.claim("worker"), [])
        self.clock.now += 10
        reclaimed = self.store.claim("worker")[0]
        self.transition(self.first_assignment(), "accept")
        self.assertFalse(self.store.settle(cast(str, reclaimed["id"]), cast(str, reclaimed["lease_token"]), "delivered"))
        self.assertEqual(self.record("deliveries", cast(str, delivery["id"]))["status"], "cancelled")

    def test_expired_phone_lease_is_uncertain_after_reopen_and_never_redialed(self) -> None:
        self.register(channel="phone")
        self.report()
        delivery = self.store.claim("phone-worker", lease_seconds=5)[0]
        self.store.close()
        self.clock.now += 121
        self.store = self.open_store()
        self.store.reconcile()
        self.assertEqual(self.record("deliveries", cast(str, delivery["id"]))["status"], "uncertain")
        self.assertEqual(self.store.claim("phone-worker"), [])
        self.assertEqual(self.record("deliveries", cast(str, delivery["id"]))["attempts"], 1)
        self.assertFalse(self.store.settle(cast(str, delivery["id"]), cast(str, delivery["lease_token"]), "retry"))
        self.assertEqual(self.record("actors", "medic")["availability"], "unknown")

    def test_uncertain_settlement_never_retries(self) -> None:
        self.register(channel="phone")
        self.report()
        delivery = self.store.claim("phone-worker")[0]
        self.assertTrue(self.store.settle(cast(str, delivery["id"]), cast(str, delivery["lease_token"]), "uncertain"))
        self.clock.now += 20
        self.assertEqual(self.store.claim("phone-worker"), [])

    def test_public_state_hides_contacts_lease_metadata_and_secrets(self) -> None:
        identifier = "tg:12345678901"
        self.register(identifier, channel="phone")
        self.report("Persona inconsciente. Contacto synthetic-address-tg:12345678901")
        delivery = self.store.claim("private-worker")[0]
        self.assertEqual(self.store.recipient(identifier)["address"], f"synthetic-address-{identifier}")
        self.store.settle(cast(str, delivery["id"]), cast(str, delivery["lease_token"]),
                          "failed", detail="private-provider-detail", provider_id="private-provider-id")
        public = json.dumps(self.store.state())
        for private in ("synthetic-address", "private-worker", "private-provider-detail", "private-provider-id",
                        "lease_token", "address", cast(str, delivery["lease_token"])):
            self.assertNotIn(private, public)
        self.assertEqual(self.record("actors", identifier)["id"], identifier)
        self.assertEqual(self.records("assignments")[0]["actor_id"], identifier)

    def test_merge_is_explicit_and_refuses_live_reservations(self) -> None:
        self.identify("alice")
        self.identify("bob")
        one = self.report(reporter="alice")
        two = self.report(reporter="bob")
        self.command("merge", incident_id=one, target_incident_id=two,
                     expected_version=self.record("incidents", one)["version"])
        self.assertEqual(self.record("incidents", one)["status"], "merged")
        self.command("update", incident_id=two, text="Nuevo dato del informante original",
                     expected_version=self.record("incidents", two)["version"],
                     scope="telegram", channel="telegram", principal="alice")
        self.register()
        three = self.report()
        with self.assertRaises(OperationalError) as unsafe:
            self.command("merge", incident_id=three, target_incident_id=two,
                         expected_version=self.record("incidents", three)["version"])
        self.assertEqual(unsafe.exception.code, "unsafe_merge")

    def test_public_snapshot_cannot_mutate_durable_state(self) -> None:
        self.register()
        iid = self.report()
        before = self.store.state()
        cast(list[Document], before["incidents"])[0]["text"] = "tampered"
        cast(list[Document], before["actors"])[0]["roles"] = ["organizador"]
        self.assertNotEqual(self.record("incidents", iid)["text"], "tampered")
        self.assertEqual(self.record("actors", "medic")["roles"], ["medico"])

    def test_fail_closed_input_bounds_and_festival_mismatch(self) -> None:
        commands: list[Document] = [
            {"command_id": "bad-bool", "kind": "report", "text": True},
            {"command_id": "huge", "kind": "report", "text": "a" * 4001},
            {"command_id": "bad-zone", "kind": "report", "text": "Fuego", "zone": "unknown"},
            {"command_id": "bad-kind", "kind": "execute_script"},
            {"command_id": "principal", "kind": "report", "text": "Fuego", "principal": "operator"},
            {"command_id": "nan", "kind": "report", "text": float("nan")},
            {"command_id": "huge-int", "kind": "report", "text": 10**5000},
        ]
        for command in commands:
            with self.assertRaises(OperationalError):
                self.store.execute(command)
        self.assertEqual(self.records("incidents"), [])
        with self.assertRaises(OperationalError) as mismatch:
            OperationalStore(self.path, {"zones": [{"id": "other", "name": "Other"}]})
        self.assertEqual(mismatch.exception.code, "festival_mismatch")


if __name__ == "__main__":
    unittest.main()
