"""Regresiones de cierre: SQLite aislada, identidades sintéticas y red bloqueada."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import cast
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from .operational import ACTIVE, OperationalError
from .operational_http import canonical_phone, create_operational_app
from .operational_service import SPECIALISTS, OperationalService, channel_status
from .operational_types import JSON, Document
from .operational_worker import DeliveryWorker

FESTIVAL: Document = {"zones": [
    {"id": "front_pit", "name": "Escenario", "kind": "stage"},
    {"id": "gate_a", "name": "Puerta A", "kind": "gate"},
]}


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class ClosureTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "closure.sqlite"
        self.clock = Clock()
        self.sequence = 0
        environment = patch.dict(os.environ, {"MANDO_EXTERNAL_DELIVERY": "0"})
        environment.start()
        self.addCleanup(environment.stop)
        network = patch("motor.server.operational_worker.httpx.post", side_effect=AssertionError("Red prohibida"))
        network.start()
        self.addCleanup(network.stop)
        self.store = self.open_store()

    def open_store(self) -> OperationalService:
        store = OperationalService(self.path, FESTIVAL, clock=self.clock,
                                   callback_secret="synthetic-capability-secret")
        self.addCleanup(store.close)
        return store

    def command(self, kind: str, **fields: JSON) -> Document:
        self.sequence += 1
        return self.store.execute({"command_id": f"closure-{self.sequence}", "kind": kind, **fields},
                                  principal="coordinator")

    def rows(self, name: str) -> list[Document]:
        return cast(list[Document], self.store.state()[name])

    def row(self, name: str, identifier: JSON) -> Document:
        return next(row for row in self.rows(name) if row["id"] == identifier)

    def register(self, aid: str = "medic", role: str = "medico", channel: str = "web") -> None:
        self.command("register_actor", actor_id=aid, name="Equipo sintético", roles=[role],
                     channel=channel, address="+15550000001" if channel == "phone" else "web:" + aid,
                     zone="front_pit", availability="available")

    def report(self, text: str = "Persona inconsciente no respira", zone: str | None = "front_pit") -> str:
        return str(self.command("report", text=text, zone=zone)["incident_id"])

    def transition(self, aid: JSON, kind: str, **fields: JSON) -> Document:
        return self.command(kind, assignment_id=aid,
                            expected_version=self.row("assignments", aid)["version"], **fields)

    def start(self, channel: str, iid: str | None = None) -> tuple[Document, Document]:
        deliveries = self.store.claim("synthetic-worker")
        delivery = next(d for d in deliveries if d["channel"] == channel
                        and (iid is None or d["incident_id"] == iid))
        context = self.store.execute({"command_id": "start:" + str(delivery["id"]),
                                      "kind": "delivery_start", "delivery_id": delivery["id"],
                                      "lease_token": delivery["lease_token"]}, scope="system", principal="worker")
        return delivery, context

    def decision(self, did: JSON, iid: JSON) -> Document:
        return {"correlation_id": did, "incident_id": iid, "fase": "rapida", "agente": "rapido",
                "papeles": {role: {"ok": True} for role in SPECIALISTS},
                "actions": [{"kind": "stop_show"}], "requiere_persona": True,
                "reason": "Revisión sintética de seguridad"}

    def workflow(self, delivery: Document, body: Document) -> Document:
        self.sequence += 1
        return self.store.execute({"command_id": f"workflow-{self.sequence}", "kind": "workflow_decision",
                                   "delivery_id": delivery["id"], "body": body},
                                  scope="proposal", principal="happyrobot")

    def test_context_has_global_occupancy_and_stales_after_other_incident_changes(self) -> None:
        self.register()
        first = self.report("Persona con mareo leve")
        assignment = self.rows("assignments")[0]
        self.transition(assignment["id"], "accept")
        self.store.workflow_enabled = True
        second = self.report()
        delivery, _ = self.start("happyrobot", second)
        context = self.store.context(str(delivery["id"]))
        resource = cast(list[Document], context["resources"])[0]
        self.assertEqual(resource["occupancy"], "accepted")
        self.assertEqual(resource["incident_id"], first)
        self.assertFalse(resource["available_for_assignment"])
        self.assertEqual(len(cast(list[Document], context["incidents"])), 2)
        self.assertEqual(cast(list[Document], context["assignments"])[0]["id"], assignment["id"])
        self.assertTrue(context["reservations"])
        self.assertFalse(self.store.changes(str(delivery["id"]))["cambio"])
        self.command("update", incident_id=first, expected_version=self.row("incidents", first)["version"],
                     text="Persona con calor leve", confirmed=True)
        change = self.store.changes(str(delivery["id"]))
        self.assertTrue(change["cambio"])
        self.assertIn(first, cast(dict[str, list[str]], change["afectados"])["incidents"])
        self.assertNotEqual(change["context_version"], change["launch_context_version"])
        self.assertIn("incidents_changed", str(change["motivo"]))
        with self.assertRaises(OperationalError) as stale:
            self.workflow(delivery, self.decision(delivery["id"], second))
        self.assertEqual(stale.exception.code, "workflow_stale")
        self.assertEqual(self.row("assignments", assignment["id"])["status"], "accepted")
        self.assertEqual(self.rows("approvals"), [])

    def test_resource_change_replans_once_without_preempting_accepted_teams(self) -> None:
        self.register("medic-a")
        self.register("medic-b")
        iid = self.report("Persona con mareo leve")
        initial = self.rows("assignments")[0]
        self.command("availability", actor_id="medic-a", availability="unavailable",
                     expected_version=self.row("actors", "medic-a")["version"])
        active = [a for a in self.rows("assignments") if a["status"] in ACTIVE]
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["actor_id"], "medic-b")
        self.assertEqual(active[0]["incident_id"], iid)
        self.assertEqual(self.row("assignments", initial["id"])["reason"], "actor_unavailable")
        self.transition(active[0]["id"], "accept")
        urgent = self.report()
        self.assertNotEqual(urgent, iid)
        self.assertTrue(self.row("incidents", urgent)["why_waiting"])

    def test_corrected_role_keeps_active_team_then_removes_retired_demand(self) -> None:
        self.register("police", "policia")
        iid = self.report("Persona inconsciente y hay una pelea")
        assignment = next(a for a in self.rows("assignments") if a["role"] == "policia")
        self.transition(assignment["id"], "accept")
        self.command("update", incident_id=iid, expected_version=self.row("incidents", iid)["version"],
                     text="Persona mareada", confirmed=True)
        self.assertEqual(self.row("assignments", assignment["id"])["status"], "accepted")
        self.assertNotIn("policia", self.row("incidents", iid)["needs"])
        self.transition(assignment["id"], "decline", reason="Coordinación confirma retirada")
        self.assertEqual(self.row("assignments", assignment["id"])["status"], "declined")
        self.register("replacement-police", "policia")
        self.assertFalse([a for a in self.rows("assignments") if a["role"] == "policia" and a["status"] in ACTIVE])
        before = self.store.state()
        for _ in range(5):
            self.store.reconcile()
        self.assertEqual(self.store.state(), before)

    def test_uncertain_call_is_not_preempted_or_redialed_then_explicit_followup_recovers(self) -> None:
        self.register(channel="phone")
        iid = self.report("Persona con mareo leve")
        delivery, _ = self.start("phone")
        self.store.settle(str(delivery["id"]), str(delivery["lease_token"]), "uncertain")
        urgent = self.report()
        original = self.rows("assignments")[0]
        self.assertEqual(original["status"], "offered")
        self.assertEqual(len(self.rows("assignments")), 1)
        self.clock.now += 121
        self.store.reconcile()
        expired = self.row("assignments", original["id"])
        self.command("availability", actor_id="medic", availability="available",
                     expected_version=self.row("actors", "medic")["version"])
        self.assertFalse(any(d["channel"] == "phone" for d in self.store.claim("again")))
        self.assertEqual(len(self.rows("assignments")), 1)
        with self.assertRaises(OperationalError):
            self.command("followup", assignment_id=expired["id"], expected_version=1,
                         reason="Disponibilidad comprobada")
        self.command("followup", assignment_id=expired["id"], expected_version=expired["version"],
                     reason="Operador ha confirmado disponibilidad y nueva llamada")
        active = [a for a in self.rows("assignments") if a["status"] in ACTIVE]
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["incident_id"], urgent)
        self.assertTrue(self.row("incidents", iid)["why_waiting"])
        self.assertEqual(self.row("deliveries", delivery["id"])["status"], "uncertain")
        self.store.close()
        self.store = self.open_store()
        self.assertEqual(len([d for d in self.store.claim("after-restart") if d["channel"] == "phone"]), 1)
        self.assertTrue(self.row("assignments", expired["id"])["followup_confirmed"])

    def test_decline_followup_is_operator_only_versioned_and_idempotent(self) -> None:
        self.register()
        self.report()
        assignment = self.rows("assignments")[0]
        self.transition(assignment["id"], "decline", reason="No puedo ahora")
        version = self.row("assignments", assignment["id"])["version"]
        command: Document = {"command_id": "followup-explicit", "kind": "followup",
                             "assignment_id": assignment["id"], "expected_version": version,
                             "reason": "Disponible de nuevo confirmado por coordinación"}
        with self.assertRaises(OperationalError) as forbidden:
            self.store.execute(command, scope="phone", channel="phone", principal="medic")
        self.assertEqual(forbidden.exception.status, 403)
        result = self.store.execute(command)
        self.assertTrue(result["ok"])
        self.assertTrue(self.store.execute(command)["duplicate"])
        self.assertEqual(len(self.rows("assignments")), 2)
        self.assertEqual(self.rows("assignments")[-1]["status"], "offered")

    def test_grave_phone_notification_remains_visible_local_not_sent(self) -> None:
        self.register("coordinator-phone", "organizador", "phone")
        iid = self.report()
        result = self.command("propose", incident_id=iid,
                              expected_version=self.row("incidents", iid)["version"],
                              actions=[{"kind": "stop_show", "actor_id": "coordinator-phone"}],
                              requiere_persona=True, reason="Revisar parada con una persona")
        approval = self.row("approvals", result["approval_id"])
        self.assertEqual(self.rows("deliveries"), [])
        self.command("decide", approval_id=approval["id"], expected_version=approval["version"],
                     content_hash=approval["content_hash"], approved=True)
        notice = next(d for d in self.rows("deliveries") if d["purpose"] == "stop_show")
        self.assertEqual(notice["status"], "local_required")
        self.assertEqual(notice["channel"], "web")
        self.assertEqual(notice["recipient_id"], "coordinator-phone")
        self.assertEqual(notice["last_error"], "phone_purpose_unsupported")
        self.assertIn("parada", str(notice["text"]))
        self.assertEqual(notice["attempts"], 0)
        worker = DeliveryWorker(self.store, external=False)
        for pending in self.store.claim("simulation"):
            worker._deliver(pending)
        self.assertEqual(self.row("deliveries", notice["id"])["status"], "local_required")
        self.assertTrue(any(e["kind"] == "communication.local_required" for e in self.rows("events")))

    def test_workflow_timeout_is_persisted_versioned_and_emitted_once(self) -> None:
        self.store.workflow_enabled = True
        iid = self.report()
        delivery, _ = self.start("happyrobot", iid)
        before = self.store.state()
        self.clock.now += 901
        after = self.store.state()
        self.assertGreater(cast(int, after["revision"]), cast(int, before["revision"]))
        self.assertEqual(cast(list[Document], after["workflows"])[0]["status"], "timeout")
        self.assertEqual(len([e for e in self.rows("events") if e["kind"] == "workflow.timeout"]), 1)
        self.store.close()
        self.store = self.open_store()
        self.assertEqual(self.store.state(), after)
        self.assertFalse(any(d["channel"] == "happyrobot" for d in self.store.claim("no-auto-retry")))
        with self.assertRaises(OperationalError):
            self.workflow(delivery, self.decision(delivery["id"], iid))

    def test_pending_human_workflow_is_invalidated_by_global_changes(self) -> None:
        self.register("control", "organizador")
        self.store.workflow_enabled = True
        iid = self.report()
        delivery, _ = self.start("happyrobot", iid)
        self.workflow(delivery, self.decision(delivery["id"], iid))
        approval = self.rows("approvals")[0]
        self.assertEqual(approval["status"], "pending")
        self.report("Persona con mareo leve", "gate_a")
        self.assertEqual(self.row("approvals", approval["id"])["status"], "stale")
        self.assertTrue(any(e["kind"] == "workflow.stale" for e in self.rows("events")))
        with self.assertRaises(OperationalError):
            self.command("decide", approval_id=approval["id"], expected_version=approval["version"],
                         content_hash=approval["content_hash"], approved=True)
        self.assertFalse(any(d["purpose"] == "stop_show" for d in self.rows("deliveries")))

    def test_applied_human_workflow_does_not_become_stale_after_later_changes(self) -> None:
        self.register("control", "organizador", "phone")
        self.store.workflow_enabled = True
        iid = self.report()
        delivery, _ = self.start("happyrobot", iid)
        self.workflow(delivery, self.decision(delivery["id"], iid))
        approval = self.rows("approvals")[0]
        self.command("decide", approval_id=approval["id"], expected_version=approval["version"],
                     content_hash=approval["content_hash"], approved=True)
        self.report("Persona con mareo leve", "gate_a")
        workflow = next(w for w in self.rows("workflows") if w["delivery_id"] == delivery["id"])
        self.assertEqual(workflow["status"], "applied")
        self.assertEqual(self.row("approvals", approval["id"])["status"], "approved")
        self.assertFalse(any(d["channel"] == "phone" for d in self.rows("deliveries")))

    def test_rejected_command_audit_is_safe_durable_and_has_no_operational_effect(self) -> None:
        self.register()
        self.report()
        assignment = self.rows("assignments")[0]
        before = self.store.state()
        command: Document = {"command_id": "bad-transition", "kind": "decline", "assignment_id": assignment["id"],
                             "expected_version": 999, "reason": "PRIVATE +15550000009"}
        for _ in range(2):
            with self.assertRaises(OperationalError) as rejected:
                self.store.execute(command, principal="coordinator")
            self.assertEqual(rejected.exception.code, "stale_version")
        after = self.store.state()
        for collection in ("actors", "incidents", "assignments", "approvals", "deliveries"):
            self.assertEqual(before[collection], after[collection])
        events = [e for e in self.rows("events") if e["kind"] == "command.rejected"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["principal"], "coordinator")
        self.assertEqual(events[0]["summary"], "decline: stale_version")
        self.assertNotIn("PRIVATE", json.dumps(after))
        self.assertGreater(cast(int, after["revision"]), cast(int, before["revision"]))
        self.store.close()
        self.store = self.open_store()
        self.assertEqual(self.store.state(), after)

    def test_confirmed_correction_replaces_priority_needs_zone_and_cancels_only_offers(self) -> None:
        self.register()
        self.register("police", "policia")
        iid = self.report("Persona inconsciente no respira y hay una pelea")
        before = self.row("incidents", iid)
        self.assertTrue(before["life_threat"])
        self.command("update", incident_id=iid, expected_version=before["version"], confirmed=True,
                     text="Persona con mareo leve", zone="gate_a")
        after = self.row("incidents", iid)
        self.assertFalse(after["life_threat"])
        self.assertLess(cast(float, after["priority"]), cast(float, before["priority"]))
        self.assertEqual(after["zone"], "gate_a")
        self.assertEqual(after["needs"], {"medico": 1})
        active = [a for a in self.rows("assignments") if a["status"] in ACTIVE]
        self.assertEqual(len(active), 1)
        self.assertEqual((active[0]["role"], active[0]["zone"]), ("medico", "gate_a"))
        self.assertTrue(any(e["kind"] == "incident.assessment_corrected" for e in self.rows("events")))
        self.transition(active[0]["id"], "accept")
        with self.assertRaises(OperationalError) as moved:
            self.command("update", incident_id=iid, expected_version=self.row("incidents", iid)["version"],
                         confirmed=True, text="Persona con mareo leve", zone="front_pit")
        self.assertEqual(moved.exception.code, "destination_in_use")
        self.command("update", incident_id=iid, expected_version=self.row("incidents", iid)["version"],
                     confirmed=True, text="Ya está todo bien", zone="gate_a")
        self.assertEqual(self.row("assignments", active[0]["id"])["status"], "accepted")
        self.assertNotEqual(self.row("incidents", iid)["status"], "closed")

    def test_public_all_clear_waits_for_review_never_dispatches_or_closes(self) -> None:
        self.register("control", "organizador")
        result = self.store.receive_telegram({"update_id": 1, "message": {
            "from": {"id": 77}, "text": "Falsa alarma en puerta A, ya está todo bien"}})
        iid = str(result["incident_id"])
        incident = self.row("incidents", iid)
        self.assertTrue(incident["review_required"])
        self.assertEqual(incident["status"], "waiting")
        self.assertEqual(self.rows("assignments"), [])
        with self.assertRaises(OperationalError):
            self.store.execute({"command_id": "public-confirm", "kind": "update", "incident_id": iid,
                                "expected_version": incident["version"], "text": "Todo bien", "confirmed": True},
                               scope="telegram", channel="telegram", principal="tg:77")
        self.assertEqual(self.rows("assignments"), [])
        self.command("update", incident_id=iid, expected_version=incident["version"],
                     text="Falsa alarma, todo bien", confirmed=True)
        self.assertFalse(self.row("incidents", iid)["review_required"])
        self.assertNotEqual(self.row("incidents", iid)["status"], "closed")

    def test_telegram_location_is_acknowledged_without_inventing_zone_or_victim(self) -> None:
        self.store.receive_telegram({"update_id": 1, "message": {
            "from": {"id": 88}, "text": "Una persona desmayada"}})
        incident = self.rows("incidents")[0]
        update: Document = {"update_id": 2, "message": {
            "from": {"id": 88}, "location": {"latitude": 40.0, "longitude": -3.0}}}
        result = self.store.receive_telegram(update)
        self.assertTrue(result["location_requested"])
        self.assertTrue(self.store.receive_telegram(update)["duplicate"])
        self.assertEqual(len(self.rows("incidents")), 1)
        self.assertIsNone(self.row("incidents", incident["id"])["zone"])
        questions = [d for d in self.rows("deliveries") if "GPS" in str(d["text"])]
        self.assertEqual(len(questions), 1)
        self.assertIn("por escrito", str(questions[0]["text"]))
        self.store.receive_telegram({"update_id": 3, "message": {
            "from": {"id": 88}, "text": "en puerta A"}})
        self.assertEqual(self.row("incidents", incident["id"])["zone"], "gate_a")

    def test_context_and_provider_text_are_scrubbed_and_readiness_matches_worker(self) -> None:
        self.store.workflow_enabled = True
        self.report("Persona con mareo; contacto +15550000009")
        delivery, _ = self.start("happyrobot")
        context = self.store.context(str(delivery["id"]))
        self.assertNotIn("+15550000009", json.dumps(context))
        self.assertIn("oculto", json.dumps(context))
        env = {"HR_API_BASE": "", "HR_API_KEY": "synthetic-key", "HR_WORKFLOW_DISPATCH": "synthetic-dispatch",
               "HR_WORKFLOW_RAPIDO": "synthetic-review", "MANDO_PUBLIC_URL": "https://mando.invalid",
               "HR_SECRET": "synthetic-secret", "MANDO_ALLOWED_NUMBERS": "+15550000001", "MANDO_EXTERNAL_DELIVERY": "1"}
        with patch.dict(os.environ, env):
            self.assertFalse(cast(Document, channel_status()["phone"])["ready"])
            self.assertFalse(cast(Document, channel_status()["happyrobot"])["ready"])
            worker = DeliveryWorker(self.store, external=False)
            with self.assertRaises(OperationalError) as unconfigured:
                worker._happyrobot(delivery, "HR_WORKFLOW_RAPIDO")
            self.assertEqual(unconfigured.exception.code, "happyrobot_unconfigured")
        self.store.workflow_enabled = False
        self.register(channel="phone")
        self.report("Persona inconsciente; teléfono +15550000009")
        phone = next(d for d in self.store.claim("phone-worker") if d["channel"] == "phone")
        with (patch.dict(os.environ, {**env, "HR_API_BASE": "https://hr.invalid/api/v2"}),
              patch("motor.server.operational_worker.httpx.post") as post):
            post.return_value = httpx.Response(200, json={"run_id": "synthetic-run"},
                                               request=httpx.Request("POST", "https://hr.invalid"))
            DeliveryWorker(self.store, external=False)._happyrobot(phone, "HR_WORKFLOW_DISPATCH")
            payload = cast(Document, post.call_args.kwargs["json"])["payload"]
            self.assertNotIn("+15550000009", str(cast(Document, payload)["order_text"]))
            self.assertTrue(cast(Document, channel_status()["phone"])["ready"])

    def test_workflow_phase_and_six_specialists_remain_strict(self) -> None:
        self.register("control", "organizador")
        self.store.workflow_enabled = True
        iid = self.report()
        delivery, _ = self.start("happyrobot")
        valid = self.decision(delivery["id"], iid)
        overrides: list[Document] = [
            {"fase": "revision", "agente": "equipo"}, {"papeles": {"critico": {"ok": True}}},
            {"papeles": {role: {"ok": role != "critico"} for role in SPECIALISTS}},
        ]
        for override in overrides:
            with self.assertRaises(OperationalError):
                self.workflow(delivery, {**valid, **override})
            self.assertEqual(self.rows("approvals"), [])
        self.assertFalse(self.workflow(delivery, valid)["aplicado"])
        self.assertEqual(self.rows("approvals")[0]["status"], "pending")
        self.assertFalse(any(d["purpose"] == "stop_show" for d in self.rows("deliveries")))


class ClosureHTTPTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        environment = patch.dict(os.environ, {
            "MANDO_OPERATIONAL_DB": str(Path(directory.name) / "http.sqlite"),
            "MANDO_OPERATOR_TOKEN": "synthetic-operator", "MANDO_OPERATORS": "",
            "MANDO_PUBLIC_URL": "https://mando.invalid", "MANDO_EXTERNAL_DELIVERY": "0",
            "MANDO_CONTROL_CHAT_ID": "", "HR_WORKFLOW_RAPIDO": "", "HR_SECRET": "synthetic-callback",
        })
        environment.start()
        self.addCleanup(environment.stop)
        startup = patch.object(DeliveryWorker, "start")
        startup.start()
        self.addCleanup(startup.stop)
        network = patch("motor.server.operational_worker.httpx.post", side_effect=AssertionError("Red prohibida"))
        network.start()
        self.addCleanup(network.stop)
        self.app = create_operational_app()
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.store: OperationalService = self.app.state.operational
        self.store.execute({"command_id": "medic", "kind": "register_actor", "actor_id": "medic",
                            "name": "Sintético", "roles": ["medico"], "channel": "phone",
                            "address": "+15550000001", "availability": "available"})
        self.store.execute({"command_id": "report", "kind": "report", "text": "Una persona desmayada",
                            "zone": "front_pit"})
        delivery = next(d for d in self.store.claim("worker") if d["channel"] == "phone")
        self.did = str(delivery["id"])
        self.store.execute({"command_id": "start", "kind": "delivery_start", "delivery_id": self.did,
                            "lease_token": delivery["lease_token"]}, scope="system")
        self.headers = {"X-Mando-Token": self.store.capability(self.did)}

    def callback(self, body: Document) -> httpx.Response:
        return self.client.post("/hr/events", json=body, headers=self.headers)

    def test_local_configured_token_is_required_and_logout_clears_session(self) -> None:
        with patch.dict(os.environ, {"MANDO_PUBLIC_URL": ""}):
            self.assertEqual(self.client.get("/api/operations/state").status_code, 401)
            self.assertEqual(self.client.get("/api/operations/state", headers={"X-Mando-Operator": "wrong"}).status_code, 403)
            login = self.client.post("/api/operator/login", json={"token": "synthetic-operator"})
            self.assertEqual(login.status_code, 200)
            self.assertEqual(self.client.get("/api/operations/state").status_code, 200)
            logout = self.client.post("/salir", follow_redirects=False)
            self.assertEqual(logout.status_code, 303)
            self.assertEqual(logout.headers["location"], "/acceso")
            self.assertFalse(self.client.cookies.get("mando_operator"))
            self.assertEqual(self.client.get("/api/operations/state").status_code, 401)

    def test_phone_ids_sequences_collision_correlation_and_final(self) -> None:
        body: Document = {"event_id": "event-one", "correlation_id": self.did,
                          "sequence": 1, "result": "unclear"}
        self.assertEqual(canonical_phone(body), body)
        self.assertEqual(self.callback(body).status_code, 200)
        self.assertTrue(self.callback(body).json()["duplicate"])
        collision = self.callback({**body, "result": "accept"})
        self.assertEqual(collision.status_code, 409)
        self.assertEqual(collision.json()["error"], "command_id_collision")
        out_of_order = self.callback({**body, "event_id": "event-two"})
        self.assertEqual(out_of_order.status_code, 409)
        self.assertEqual(out_of_order.json()["error"], "call_out_of_order")
        for invalid in (None, True, "2", 0, -1):
            self.assertEqual(self.callback({**body, "event_id": "invalid-seq", "sequence": invalid}).status_code, 400)
        mismatch = self.callback({**body, "event_id": "wrong-correlation", "sequence": 2,
                                  "correlation_id": "another-delivery"})
        self.assertEqual(mismatch.status_code, 409)
        final = self.callback({**body, "event_id": "event-final", "sequence": 2, "final": True})
        self.assertEqual(final.status_code, 200)
        late = self.callback({**body, "event_id": "late-progress", "sequence": 3})
        self.assertEqual(late.status_code, 409)
        self.assertEqual(late.json()["error"], "call_finalized")
        assignment = cast(list[Document], self.store.state()["assignments"])[0]
        self.assertEqual(assignment["status"], "offered")
        self.assertIsNone(assignment["eta_min"])

    def test_alias_identity_and_change_tool_use_authenticated_context(self) -> None:
        self.assertEqual(self.client.get("/interfaz").status_code, 401)
        self.assertEqual(self.client.get("/interfaz", headers={"X-Mando-Operator": "synthetic-operator"}).status_code, 200)
        self.assertEqual(self.client.get("/api/operations/state").status_code, 401)
        response = self.client.get("/api/operations/state", headers={"X-Mando-Operator": "synthetic-operator"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json()["operator"]), {"id", "name", "role"})
        self.assertNotIn("synthetic-operator", response.text)
        self.store.workflow_enabled = True
        self.store.execute({"command_id": "new-review", "kind": "report", "text": "Persona con calor",
                            "zone": "gate_a"})
        delivery = next(d for d in self.store.claim("workflow-worker") if d["channel"] == "happyrobot")
        did = str(delivery["id"])
        self.store.execute({"command_id": "start-review", "kind": "delivery_start", "delivery_id": did,
                            "lease_token": delivery["lease_token"]}, scope="system")
        headers = {"X-Mando-Token": self.store.capability(did)}
        before = self.client.post("/hr/tools/cambio", json={}, headers=headers)
        self.assertFalse(before.json()["cambio"])
        self.store.execute({"command_id": "independent-report", "kind": "report",
                            "text": "Persona con calor", "zone": "gate_a"})
        after = self.client.post("/hr/tools/cambio", json={}, headers=headers)
        self.assertTrue(after.json()["cambio"])
        self.assertTrue(after.json()["motivo"])
        self.assertTrue(after.json()["afectados"]["incidents"])
        self.assertGreater(after.json()["revision"], before.json()["revision"])
        self.assertEqual(len(cast(list[Document], self.store.state()["incidents"])), 3)


if __name__ == "__main__":
    unittest.main()
