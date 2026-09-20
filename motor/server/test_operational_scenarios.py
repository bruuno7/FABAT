"""Pruebas sintéticas: concurrencia SQLite real, recuperación y contratos observables."""
from __future__ import annotations

import copy
import json
import multiprocessing
import os
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from typing import cast
from unittest.mock import patch

from .operational import OperationalError
from .operational_scenarios import (
    Clock,
    InvariantFailure,
    check_invariants,
    domain,
    generate,
    main,
    minimize,
    offline,
    open_service,
    persisted,
    record,
    records,
    register_command,
    replay,
    report_command,
)
from .operational_service import OperationalService
from .operational_types import Document, State
from .operational_worker import DeliveryWorker


def telegram_update(uid: int = 701) -> Document:
    return {"update_id": uid, "message": {"message_id": uid, "from": {"id": 99001, "first_name": "Sintético"},
            "chat": {"id": 99001, "type": "private"}, "text": "Otra persona desmayada en escenario 1"}}


def crash_child(path: str, boundary: str) -> None:
    """Proceso independiente: salida abrupta, sin close/finally ni proveedor externo."""
    with offline():
        service = open_service(Path(path), Clock())
        if boundary == "inbox":
            with patch.object(service, "execute", side_effect=lambda *args, **kwargs: os._exit(71)):
                service.receive_telegram(telegram_update())
        elif boundary in {"before_commit", "after_commit"}:
            if boundary == "before_commit":
                def interrupt(statement: str) -> None:
                    if statement == "COMMIT":
                        os._exit(71)
                service._db.set_trace_callback(interrupt)
            service.execute(report_command("crash-report"))
        else:
            delivery = next(item for item in service.claim("crash-worker") if item["channel"] == "phone")
            if boundary != "before_send":
                # Recibo durable del proveedor FAKE, no una petición HTTP ni una llamada.
                with closing(sqlite3.connect(Path(path).with_name("fake-provider.sqlite"))) as provider, provider:
                    provider.execute("CREATE TABLE IF NOT EXISTS receipts (delivery TEXT PRIMARY KEY)")
                    provider.execute("INSERT INTO receipts VALUES (?)", (delivery["id"],))
            if boundary == "after_settle":
                service.settle(str(delivery["id"]), str(delivery["lease_token"]), "delivered", provider_id="fake-run")
        os._exit(71)


class OperationalScenariosTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory(prefix="mando-scenarios-test-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.path = self.root / "operations.sqlite"
        self.clock = Clock()
        guard = offline()
        guard.__enter__()
        self.addCleanup(guard.__exit__, None, None, None)
        self.service = self.open(self.path)
        self.sequence = 0

    def open(self, path: Path) -> OperationalService:
        service = open_service(path, self.clock)
        self.addCleanup(service.close)
        return service

    def command(self, command: Document, service: OperationalService | None = None) -> Document:
        self.sequence += 1
        before = persisted(self.path) if service is None else None
        result = (service or self.service).execute({"command_id": f"test-{self.sequence}", **command})
        if before is not None:
            check_invariants(before, persisted(self.path))
        return result

    def register(self, identifier: str = "medic", role: str = "medico", channel: str = "web") -> None:
        self.command(register_command(identifier, role, channel))

    def test_generator_is_reproducible_and_every_recipe_reaches_the_service(self) -> None:
        events = generate(17, 30)
        self.assertEqual(events, generate(17, 30))
        self.assertNotEqual(events, generate(19, 30))
        trace, counts, failure = replay(self.root / "smoke.sqlite", events)
        self.assertIsNone(failure, trace[-1])
        self.assertEqual(len(trace), 30)
        self.assertGreater(cast(int, counts["rejected"]), 0)
        self.assertTrue(all("result" in entry for entry in trace))
        self.assertFalse(any("skipped" in cast(Document, entry["result"]) for entry in trace))

    def test_uncertain_phone_deliveries_are_not_retried_by_generated_events(self) -> None:
        events: list[Document] = [
            {"op": "register", "actor": "police", "role": "policia", "channel": "phone", "id": "register"},
            {"op": "report", "text": "Aglomeración peligrosa", "id": "crowd"},
            {"op": "uncertain", "id": "lost"}, {"op": "drain", "id": "retry"},
            {"op": "reopen", "id": "restart"}, {"op": "drain", "id": "retry-after-restart"},
        ]
        path = self.root / "uncertain.sqlite"
        trace, _, failure = replay(path, events)
        self.assertIsNone(failure, trace)
        self.assertEqual(cast(Document, trace[2]["result"])["simulated_lost_responses"], 1)
        delivery = next(iter(persisted(path)["deliveries"].values()))
        self.assertEqual(delivery["status"], "uncertain")
        self.assertEqual(delivery["attempts"], 1)

    def test_failed_batch_writes_trace_minimal_and_nonzero_exit(self) -> None:
        output = self.root / "failed-batch"
        recipe: list[Document] = [{"op": "register", "actor": "irrelevant", "id": "one"},
                                 {"op": "report", "id": "unexpected-success", "expect": "reject"}]
        with patch("motor.server.operational_scenarios.generate", return_value=recipe):
            self.assertEqual(main(["--output", str(output), "--seeds", "1", "--events", "2"]), 1)
        manifest = json.loads((output / "manifest.json").read_text())
        self.assertFalse(manifest["ok"])
        failure = manifest["failures"][0]
        trace = json.loads(Path(failure["trace"]).read_text())
        minimal = json.loads(Path(failure["minimal"]).read_text())
        self.assertEqual(trace[-1]["failure"], "invalid_command_accepted:report")
        self.assertEqual(len(minimal["events"]), 1)
        self.assertEqual(replay(self.root / "reproduced.sqlite", minimal["events"])[2], failure["failure"])

    def test_reducer_preserves_failure_and_removes_irrelevant_events(self) -> None:
        events: list[Document] = [{"op": "register", "actor": "irrelevant", "id": "one"},
                                 {"op": "report", "id": "unexpected-success", "expect": "reject"},
                                 {"op": "drain", "id": "unreached"}]
        reduced, attempts = minimize(events, "invalid_command_accepted:report")
        self.assertEqual(len(reduced), 1)
        self.assertGreater(attempts, 0)
        self.assertEqual(replay(self.root / "reduced.sqlite", reduced)[2], "invalid_command_accepted:report")

    def test_oracle_detects_corrupt_reservations_loss_versions_and_unauthorized_effects(self) -> None:
        self.register()
        self.command(report_command("victim"))
        before = persisted(self.path)
        cases: list[State] = []
        broken = copy.deepcopy(before)
        broken["reservations"].clear()
        cases.append(broken)
        broken = copy.deepcopy(before)
        broken["incidents"].clear()
        cases.append(broken)
        broken = copy.deepcopy(before)
        next(iter(broken["actors"].values()))["version"] = 0
        cases.append(broken)
        broken = copy.deepcopy(before)
        next(iter(broken["deliveries"].values()))["purpose"] = "evacuate"
        cases.append(broken)
        for broken in cases:
            with self.assertRaises(InvariantFailure):
                check_invariants(before, broken)

    def race(self, commands: list[Document]) -> list[Document]:
        # Ocho objetos y conexiones distintos, no ocho llamadas al mismo RLock.
        services = [self.open(self.path) for _ in range(8)]
        barrier = threading.Barrier(8, timeout=15)
        before = persisted(self.path)

        def attempt(index: int) -> Document:
            barrier.wait()
            try:
                return services[index].execute(commands[index])
            except OperationalError as exc:
                return {"error": exc.code, "status": exc.status}

        with ThreadPoolExecutor(max_workers=8) as executor:
            outcomes = list(executor.map(attempt, range(8)))
        check_invariants(before, persisted(self.path))
        self.assertTrue(all(service.state()["revision"] == self.service.state()["revision"] for service in services))
        return outcomes

    def test_eight_connections_duplicate_command_and_competing_approvals(self) -> None:
        self.register()
        self.register("coordinator", "organizador")
        command = report_command("race-report")
        outcomes = self.race([command] * 8)
        self.assertEqual(sum(row.get("duplicate") is False for row in outcomes), 1)
        self.assertEqual(sum(row.get("duplicate") is True for row in outcomes), 7)
        self.assertEqual(len(records(self.service, "incidents")), 1)
        self.assertEqual(len(records(self.service, "assignments")), 1)
        incident = records(self.service, "incidents")[0]
        proposal = self.command({"kind": "propose", "incident_id": incident["id"], "expected_version": incident["version"],
                                 "actions": [{"kind": "stop_show", "actor_id": "coordinator"}],
                                 "requiere_persona": False, "reason": "Prueba sintética"})
        approval = record(self.service, "approvals", str(proposal["approval_id"]))
        decision: Document = {"kind": "decide", "approval_id": approval["id"], "expected_version": approval["version"],
                              "approved": True, "content_hash": approval["content_hash"]}
        outcomes = self.race([{**decision, "command_id": f"approval-race-{i}"} for i in range(8)])
        self.assertEqual(sum(row.get("ok") is True for row in outcomes), 1)
        self.assertEqual(sum(row.get("status") == 409 for row in outcomes), 7)
        self.assertEqual(len([row for row in records(self.service, "deliveries") if row["purpose"] == "stop_show"]), 1)

    def test_eight_connections_compete_for_one_exclusive_actor(self) -> None:
        self.register()
        outcomes = self.race([report_command(f"different-victim-{i}") for i in range(8)])
        self.assertTrue(all(row.get("ok") is True for row in outcomes))
        state = persisted(self.path)
        self.assertEqual(len(state["incidents"]), 8)
        self.assertEqual(len(state["assignments"]), 1)
        self.assertEqual(len(state["reservations"]), 2)

    def test_live_wal_backup_restore_replay_and_pending_inbox_outbox(self) -> None:
        self.register()
        report = report_command("backup-victim")
        self.command(report)
        with (patch.object(self.service, "execute", side_effect=OperationalError("synthetic_interruption", 503)),
              self.assertRaises(OperationalError)):
            self.service.receive_telegram(telegram_update())
        before = persisted(self.path)
        self.assertTrue(Path(str(self.path) + "-wal").exists())
        backup_path = self.root / "backup.sqlite"
        with closing(sqlite3.connect(self.path)) as source, closing(sqlite3.connect(backup_path)) as backup:
            self.assertEqual(source.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            source.backup(backup)
            self.assertEqual(backup.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        restored_path = self.root / "restored.sqlite"
        with closing(sqlite3.connect(backup_path)) as backup, closing(sqlite3.connect(restored_path)) as restored_db:
            backup.backup(restored_db)
            self.assertEqual(restored_db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        restored = self.open(restored_path)
        self.assertEqual(before, persisted(restored_path))
        self.assertTrue(restored.execute(report)["duplicate"])
        restored.recover_inbox()
        self.assertEqual(len(records(restored, "incidents")), 2)
        self.assertTrue(restored.receive_telegram(telegram_update())["duplicate"])
        worker = DeliveryWorker(restored, external=False)
        deliveries = restored.claim("restore-worker")
        self.assertGreater(len(deliveries), 0)
        for delivery in deliveries:
            worker._deliver(delivery)
        self.assertEqual(restored.claim("restore-again"), [])
        restored.close()
        reopened = self.open(restored_path)
        self.assertEqual(len(records(reopened, "incidents")), 2)
        self.assertTrue(reopened.execute(report)["duplicate"])
        self.assertEqual(before, persisted(self.path))  # La copia no tocó el original vivo.

    def test_process_crash_commit_and_fake_send_boundaries(self) -> None:
        context = multiprocessing.get_context("spawn")
        for boundary in ("before_commit", "after_commit", "inbox", "before_send", "after_send", "after_settle"):
            with self.subTest(boundary=boundary):
                directory = self.root / boundary
                directory.mkdir()
                path = directory / "operations.sqlite"
                service = self.open(path)
                self.command(register_command("phone-medic", channel="phone"), service)
                if "send" in boundary or boundary == "after_settle":
                    service.execute(report_command("crash-report"))
                before = persisted(path)
                service.close()
                child = context.Process(target=crash_child, args=(str(path), boundary))
                child.start()
                child.join(timeout=20)
                if child.is_alive():
                    child.kill()
                    child.join()
                    self.fail("El proceso de crash no alcanzó la frontera")
                self.assertEqual(child.exitcode, 71)
                recovered = self.open(path)
                if boundary == "before_commit":
                    self.assertEqual(before, persisted(path))
                    self.assertFalse(recovered.execute(report_command("crash-report"))["duplicate"])
                elif boundary == "inbox":
                    self.assertEqual(len(records(recovered, "incidents")), 0)
                    recovered.recover_inbox()
                    self.assertEqual(len(records(recovered, "incidents")), 1)
                    self.assertTrue(recovered.receive_telegram(telegram_update())["duplicate"])
                else:
                    self.assertTrue(recovered.execute(report_command("crash-report"))["duplicate"])
                    if boundary == "after_commit":
                        self.assertTrue(any(row["status"] == "pending" for row in records(recovered, "deliveries")))
                    else:
                        self.clock.now = 1031
                        recovered.reconcile()
                        deliveries = records(recovered, "deliveries")
                        expected = "delivered" if boundary == "after_settle" else "uncertain"
                        self.assertEqual(deliveries[0]["status"], expected)
                        self.assertEqual(recovered.claim("after-crash"), [])
                        provider_path = path.with_name("fake-provider.sqlite")
                        if boundary == "before_send":
                            self.assertFalse(provider_path.exists())
                        else:
                            with closing(sqlite3.connect(provider_path)) as provider:
                                self.assertEqual(provider.execute("SELECT count(*) FROM receipts").fetchone()[0], 1)
                check_invariants(before, persisted(path))
                self.clock.now = 1000

    def test_metamorphic_retransmit_reorder_independent_and_rename(self) -> None:
        def evaluate(name: str, renamed: bool = False, reverse: bool = False, duplicates: bool = False) -> list[str]:
            path = self.root / (name + ".sqlite")
            service = self.open(path)
            for identifier, role in (("medical", "medico"), ("police", "policia")):
                self.command(register_command(("renamed-" if renamed else "") + identifier, role), service)
            commands = [report_command(("other-" if renamed else "") + "medical-report", "Persona desmayada", "front_pit"),
                        report_command(("other-" if renamed else "") + "crowd-report", "Aglomeración peligrosa", "gate_a")]
            for command in reversed(commands) if reverse else commands:
                service.execute(command)
                if duplicates:
                    before = persisted(path)
                    self.assertTrue(service.execute(command)["duplicate"])
                    self.assertEqual(before, persisted(path))
            state = persisted(path)
            check_invariants(state, state)
            # Proyección de política sin IDs, versiones ni UUID: misma demanda y atención.
            return sorted(json.dumps({"text": incident["text"], "zone": incident["zone"],
                "needs": incident["needs"], "status": incident["status"],
                "assignments": sorted((assignment["role"], assignment["status"], assignment["zone"])
                    for assignment in state["assignments"].values() if assignment["incident_id"] == incident["id"])},
                sort_keys=True) for incident in state["incidents"].values())
        baseline = evaluate("base")
        self.assertEqual(baseline, evaluate("retransmit", duplicates=True))
        self.assertEqual(baseline, evaluate("reorder", reverse=True))
        self.assertEqual(baseline, evaluate("rename", renamed=True))

    def phone(self) -> tuple[Document, Document, str]:
        self.register(channel="phone")
        self.command(report_command("phone-report"))
        delivery = next(row for row in self.service.claim("phone-worker") if row["channel"] == "phone")
        context = self.service.execute({"command_id": "start:" + str(delivery["id"]), "kind": "delivery_start",
                                       "delivery_id": delivery["id"], "lease_token": delivery["lease_token"]}, scope="system")
        return delivery, context, self.service.capability(str(delivery["id"]))

    def test_callback_tokens_replay_order_wrong_destination_and_new_victim(self) -> None:
        delivery, context, token = self.phone()
        self.assertEqual(self.service.authorize_callback(token)["delivery_id"], delivery["id"])
        with self.assertRaises(OperationalError) as denied:
            self.service.authorize_callback("synthetic-wrong-token")
        self.assertEqual(denied.exception.status, 403)

        def callback(cid: str, body: Document) -> Document:
            return self.service.execute({"command_id": cid, "kind": "phone_event", "delivery_id": delivery["id"], "body": body},
                scope="phone", principal=str(context["actor_id"]), channel="phone")

        notice: Document = {"id": "another-victim", "text": "Persona desmayada", "zone": "front_pit"}
        body: Document = {"action_id": delivery["id"], "assignment_id": context["assignment_id"],
                          "expected_assignment_version": context["initial_assignment_version"],
                          "sequence": 1, "result": "accept", "destination_confirmed": True,
                          "destination_zone_id": "gate_a", "eta_min": 4}
        self.assertFalse(callback("wrong-destination", body)["applied"])
        self.assertEqual(records(self.service, "assignments")[0]["status"], "offered")
        body.update(sequence=2, destination_zone_id="front_pit", new_report=notice)
        result = callback("accepted", body)
        self.assertTrue(result["applied"])
        self.assertEqual(len(records(self.service, "incidents")), 2)
        self.assertEqual(records(self.service, "assignments")[0]["status"], "en_route")
        before = persisted(self.path)
        self.assertTrue(callback("accepted", body)["duplicate"])
        self.assertEqual(before, persisted(self.path))
        for invalid in ({**body, "sequence": 1}, {**body, "sequence": 3, "assignment_id": "wrong"},
                        {**body, "sequence": 3, "expected_assignment_version": 99}):
            with self.assertRaises(OperationalError):
                callback("bad-" + str(len(records(self.service, "events"))), invalid)
            self.assertEqual(domain(before), domain(persisted(self.path)))
        callback("final", {**body, "sequence": 3, "result": "unknown"})
        self.assertEqual(len(records(self.service, "incidents")), 2)
        self.assertEqual(records(self.service, "assignments")[0]["status"], "en_route")
        check_invariants(before, persisted(self.path))

    def test_non_acceptance_phone_results_never_invent_eta_or_arrival(self) -> None:
        delivery, context, _ = self.phone()
        for sequence, result in enumerate(("unclear", "unknown", "no_answer", "timeout", "provider_failed"), 1):
            before = persisted(self.path)
            response = self.service.execute({"command_id": f"result-{sequence}", "kind": "phone_event", "delivery_id": delivery["id"],
                "body": {"sequence": sequence, "result": result, "eta_min": 4, "destination_confirmed": True,
                         "destination_zone_id": "front_pit"}}, scope="phone", principal=str(context["actor_id"]), channel="phone")
            self.assertEqual(response["communication_result"], result)
            assignment = records(self.service, "assignments")[0]
            self.assertEqual(assignment["status"], "offered")
            self.assertIsNone(assignment["eta_min"])
            check_invariants(before, persisted(self.path))


if __name__ == "__main__":
    unittest.main()
