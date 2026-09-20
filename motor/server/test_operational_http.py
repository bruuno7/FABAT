"""Synthetic channel integration tests; no provider network requests."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from typing import cast
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from .app import create_app
from .operational import OperationalError
from .operational_service import OperationalService
from .operational_types import JSON, Document
from .operational_worker import DeliveryWorker


class OperationalHTTPTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.environment = patch.dict(
            os.environ,
            {
                "MANDO_OPERATIONAL": "1",
                "MANDO_OPERATIONAL_DB": str(
                    Path(self.directory.name) / "operations.sqlite"
                ),
                "MANDO_BRIDGE_SECRET": "synthetic-bridge",
                "HR_SECRET": "synthetic-callback-signing",
                "MANDO_EXTERNAL_DELIVERY": "0",
                "MANDO_PUBLIC_URL": "",
                "MANDO_OPERATORS": "",
                "MANDO_OPERATOR_TOKEN": "",
                "MANDO_CONTROL_CHAT_ID": "",
                "HR_WORKFLOW_RAPIDO": "",
            },
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)
        start = patch.object(DeliveryWorker, "start")
        start.start()
        self.addCleanup(start.stop)
        self.sequence = 0
        self.open()

    def open(self) -> None:
        self.app = create_app(threaded=False)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.store: OperationalService = self.app.state.operational

    def command(self, kind: str, **fields: JSON) -> Document:
        self.sequence += 1
        response = self.client.post(
            "/api/operations/command",
            json={
                "command_id": f"web-{self.sequence}",
                "kind": kind,
                **fields,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        return cast(Document, response.json())

    def snapshot(self) -> Document:
        response = self.client.get("/api/operations/state")
        self.assertEqual(response.status_code, 200, response.text)
        return cast(Document, response.json())

    def records(self, key: str) -> list[Document]:
        return cast(list[Document], self.snapshot()[key])

    def telegram(self, update: Document, expected: int = 200) -> Document:
        response = self.client.post(
            "/api/operations/telegram",
            json=update,
            headers={"X-Mando-Bridge-Token": "synthetic-bridge"},
        )
        self.assertEqual(response.status_code, expected, response.text)
        return cast(Document, response.json())

    @staticmethod
    def message(uid: int, actor: int, text: str) -> Document:
        return {
            "update_id": uid,
            "message": {
                "message_id": uid,
                "from": {"id": actor, "first_name": "Synthetic"},
                "chat": {"id": -900, "type": "group"},
                "text": text,
            },
        }

    def register(self, channel: str = "web", actor: str = "medic") -> None:
        self.command(
            "register_actor",
            actor_id=actor,
            name="Equipo de prueba",
            roles=["medico"],
            channel=channel,
            address=actor.removeprefix("tg:") if channel != "web" else "",
            availability="available",
            zone="front_pit",
        )

    def phone(self) -> tuple[Document, Document, str]:
        self.register("phone")
        self.command(
            "report", text="Una persona inconsciente no respira", zone="front_pit"
        )
        delivery = next(
            d for d in self.store.claim("test-worker") if d["channel"] == "phone"
        )
        context = self.store.execute(
            {
                "kind": "delivery_start",
                "command_id": "start:" + str(delivery["id"]),
                "delivery_id": delivery["id"],
                "lease_token": delivery["lease_token"],
            },
            scope="system",
            principal="worker",
        )
        token = self.store.capability(str(delivery["id"]))
        return delivery, context, token

    def callback(self, token: str, body: Document, expected: int = 200) -> Document:
        response = self.client.post(
            "/hr/events", json=body, headers={"X-Mando-Token": token}
        )
        self.assertEqual(response.status_code, expected, response.text)
        return cast(Document, response.json())

    def test_operator_authentication_and_mode_isolation(self) -> None:
        self.assertIn("MANDO", self.client.get("/sala").text)
        self.assertEqual(self.snapshot()["channels"], self.snapshot()["channels"])
        self.assertFalse(hasattr(self.app.state, "session"))
        self.assertEqual(
            self.client.post("/api/report", json={"text": "legacy"}).status_code, 404
        )
        with patch.dict(
            os.environ,
            {
                "MANDO_OPERATOR_TOKEN": "synthetic-operator",
                "MANDO_PUBLIC_URL": "https://example.invalid",
            },
        ):
            self.assertEqual(self.client.get("/api/operations/state").status_code, 401)
            response = self.client.get(
                "/api/operations/state",
                headers={"X-Mando-Operator": "synthetic-operator"},
            )
            self.assertEqual(response.status_code, 200)

    def test_durable_telegram_identity_duplicates_collision_and_restart(self) -> None:
        update = self.message(10, 51, "Una persona desmayada en escenario 1")
        first = self.telegram(update)
        self.assertFalse(first["duplicate"])
        self.assertEqual(self.records("actors")[0]["id"], "tg:51")
        revision = self.snapshot()["revision"]
        self.assertTrue(self.telegram(update)["duplicate"])
        self.assertEqual(self.snapshot()["revision"], revision)
        self.telegram(self.message(10, 52, "otro mensaje"), 409)
        self.client.__exit__(None, None, None)
        self.open()
        self.assertTrue(self.telegram(update)["duplicate"])
        self.assertEqual(len(self.records("incidents")), 1)
        self.assertNotIn("address", self.records("actors")[0])

    def test_missing_location_and_distinct_people(self) -> None:
        self.telegram(self.message(1, 10, "Hay una persona desmayada"))
        incident = self.records("incidents")[0]
        self.assertIsNone(incident["zone"])
        self.telegram(self.message(2, 10, "en escenario 1"))
        self.assertEqual(len(self.records("incidents")), 1)
        self.assertEqual(self.records("incidents")[0]["zone"], "front_pit")
        self.telegram(self.message(3, 10, "Hay otra persona desmayada en escenario 1"))
        self.assertEqual(len(self.records("incidents")), 2)

    def test_sender_without_from_cannot_claim_group_identity(self) -> None:
        self.telegram(
            {"update_id": 1, "message": {"chat": {"id": 5}, "text": "desmayo"}}, 400
        )
        self.assertEqual(len(self.records("actors")), 0)
        response = self.client.post(
            "/api/operations/telegram", json=self.message(2, 5, "desmayo")
        )
        self.assertEqual(response.status_code, 403)

    def test_phone_requires_destination_and_rejects_duplicate_or_old_callbacks(
        self,
    ) -> None:
        delivery, context, token = self.phone()
        body: Document = {
            "action_id": delivery["id"],
            "call_id": "synthetic-call",
            "assignment_id": context["assignment_id"],
            "result": "accept",
            "eta_min": 4,
            "sequence": 1,
            "destination_confirmed": True,
            "destination_zone_id": "home",
        }
        first = self.callback(token, body)
        self.assertFalse(first["applied"])
        self.assertEqual(self.records("assignments")[0]["status"], "offered")
        self.assertTrue(self.callback(token, body)["duplicate"])
        body.update(sequence=2, destination_zone_id="front_pit")
        self.assertTrue(self.callback(token, body)["applied"])
        assignment = self.records("assignments")[0]
        self.assertEqual(assignment["status"], "en_route")
        self.assertEqual(assignment["eta_min"], 4)
        self.callback(token, {**body, "sequence": 1, "result": "reject"}, 409)
        self.assertEqual(self.records("assignments")[0]["status"], "en_route")
        self.callback("synthetic-invalid", body, 403)
        self.callback(token, {**body, "sequence": 3, "action_id": "other"}, 409)
        stale = context["initial_assignment_version"] + 1
        self.callback(
            token, {**body, "sequence": 3, "expected_assignment_version": stale}, 409
        )
        self.callback(token, {**body, "sequence": 3, "assignment_id": "other"}, 409)
        self.assertEqual(self.records("assignments")[0]["status"], "en_route")

    def test_unclear_voicemail_and_call_end_do_not_accept_or_complete(self) -> None:
        _, _, token = self.phone()
        self.callback(token, {"sequence": 1, "result": "unclear", "eta_min": 5})
        self.assertEqual(self.records("assignments")[0]["status"], "offered")
        voicemail = self.callback(token, {"sequence": 2, "call_status": "voicemail"})
        self.assertEqual(voicemail["communication_result"], "no_answer")
        self.callback(token, {"sequence": 3, "call_status": "completed"})
        self.assertEqual(self.records("assignments")[0]["status"], "offered")

    def test_new_incident_during_call_and_revoked_acceptance(self) -> None:
        _, _, token = self.phone()
        self.callback(
            token,
            {
                "sequence": 1,
                "result": "accept",
                "destination_confirmed": True,
                "destination_zone_id": "front_pit",
                "new_report": {
                    "id": "second-victim",
                    "text": "Otra persona desmayada",
                    "zone": "gate_a",
                },
            },
        )
        self.assertEqual(len(self.records("incidents")), 2)
        self.assertEqual(self.records("assignments")[0]["status"], "accepted")
        self.callback(
            token, {"sequence": 2, "result": "reject", "reason": "No puedo continuar"}
        )
        self.assertEqual(self.records("assignments")[0]["status"], "declined")

    def test_callback_from_superseded_assignment_never_reactivates(self) -> None:
        _, _, token = self.phone()
        assignment = self.records("assignments")[0]
        self.command(
            "decline",
            assignment_id=assignment["id"],
            expected_version=assignment["version"],
            reason="Cambio del operador",
        )
        for sequence in (1, 2):
            result = self.callback(
                token,
                {
                    "sequence": sequence,
                    "result": "accept",
                    "destination_confirmed": True,
                    "destination_zone_id": "front_pit",
                },
            )
            self.assertTrue(result["stale"])
        self.assertEqual(self.records("assignments")[0]["status"], "declined")

    def test_provider_timeout_does_not_duplicate_phone_launch(self) -> None:
        self.register("phone")
        self.command("report", text="Una persona desmayada", zone="front_pit")
        worker = DeliveryWorker(self.store, external=True)
        phone = next(d for d in self.store.claim("worker") if d["channel"] == "phone")
        with patch.object(
            worker, "_happyrobot", side_effect=httpx.ReadTimeout("lost reply")
        ) as call:
            worker._deliver(phone)
        self.assertEqual(call.call_count, 1)
        rows = self.records("deliveries")
        self.assertEqual(
            next(d for d in rows if d["id"] == phone["id"])["status"], "uncertain"
        )
        self.assertFalse(
            any(d["channel"] == "phone" for d in self.store.claim("worker-again"))
        )

    def test_recovery_between_durable_intake_and_processing(self) -> None:
        update = self.message(300, 61, "Persona desmayada en escenario 1")
        with patch.object(
            self.store,
            "execute",
            side_effect=OperationalError("persistence_unavailable", 503),
        ):
            self.telegram(update, 503)
        self.assertEqual(self.records("incidents"), [])
        self.client.__exit__(None, None, None)
        self.open()
        self.store.recover_inbox()
        self.assertEqual(len(self.records("incidents")), 1)
        self.assertTrue(self.telegram(update)["duplicate"])

    def test_telegram_staff_lifecycle_identity_and_stale_button(self) -> None:
        self.register("telegram", "tg:61")
        self.command("report", text="Una persona desmayada", zone="front_pit")

        def press(uid: int, sender: int, action: str, assignment: Document) -> Document:
            return self.telegram(
                {
                    "update_id": uid,
                    "callback_query": {
                        "id": f"button-{uid}",
                        "from": {"id": sender},
                        "data": f"m:{action}:{assignment['id']}:{assignment['version']}",
                        "message": {
                            "message_id": 1,
                            "from": {"id": 999, "is_bot": True},
                        },
                    },
                }
            )

        original = self.records("assignments")[0]
        self.assertTrue(press(400, 62, "accept", original)["rejected"])
        self.assertEqual(self.records("assignments")[0]["status"], "offered")
        press(401, 61, "accept", original)
        self.assertTrue(press(402, 61, "accept", original)["rejected"])
        for uid, action, status in (
            (403, "arrive", "arrived"),
            (404, "locate", "located"),
            (405, "complete", "completed"),
        ):
            press(uid, 61, action, self.records("assignments")[0])
            self.assertEqual(self.records("assignments")[0]["status"], status)
        self.assertEqual(self.records("incidents")[0]["status"], "closed")

    def test_same_notice_in_progress_and_final_callback_is_one_incident(self) -> None:
        _, _, token = self.phone()
        notice: Document = {
            "id": "new-victim",
            "text": "Otra persona desmayada",
            "zone": "gate_a",
        }
        for sequence in (1, 2):
            self.callback(
                token, {"sequence": sequence, "result": "unclear", "new_report": notice}
            )
        self.assertEqual(len(self.records("incidents")), 2)

    def test_provider_acceptance_before_launch_response_and_distinct_call_id(
        self,
    ) -> None:
        self.command(
            "register_actor",
            actor_id="medic",
            name="Synthetic",
            channel="phone",
            address="+15550000001",
            roles=["medico"],
            availability="available",
        )
        self.command("report", text="Persona desmayada", zone="front_pit")
        delivery = next(
            d for d in self.store.claim("worker") if d["channel"] == "phone"
        )
        worker = DeliveryWorker(self.store, external=True)

        def transport(url: str, **options: object) -> httpx.Response:
            request = cast(Document, options["json"])
            payload = cast(Document, request["payload"])
            self.assertEqual(payload["assignment_id"], delivery["assignment_id"])
            self.callback(
                str(payload["callback_token"]),
                {
                    "sequence": 1,
                    "call_id": "call-42",
                    "hr_run_id": "run-42",
                    "result": "accept",
                    "destination_confirmed": True,
                    "destination_zone_id": "front_pit",
                    "eta_min": 4,
                },
            )
            return httpx.Response(
                200, json={"run_id": "run-42"}, request=httpx.Request("POST", url)
            )

        with (
            patch.dict(
                os.environ,
                {
                    "HR_WORKFLOW_DISPATCH": "synthetic",
                    "HR_API_BASE": "https://hr.invalid/api/v2",
                    "HR_API_KEY": "synthetic",
                    "MANDO_PUBLIC_URL": "https://mando.invalid",
                    "MANDO_ALLOWED_NUMBERS": "+15550000001",
                },
            ),
            patch(
                "motor.server.operational_worker.httpx.post", side_effect=transport
            ) as post,
        ):
            worker._deliver(delivery)
            self.assertEqual(post.call_count, 1)
        token = self.store.capability(str(delivery["id"]))
        self.callback(
            token,
            {
                "sequence": 2,
                "call_id": "call-42",
                "hr_run_id": "run-42",
                "result": "accept",
                "destination_confirmed": True,
                "destination_zone_id": "front_pit",
                "eta_min": 6,
            },
        )
        self.assertEqual(self.records("assignments")[0]["eta_min"], 6)

    def test_telegram_transient_failure_is_retryable(self) -> None:
        # Aviso registrado por el operador (no por el bot): MANDO sí oferta y sigue
        # usando su propio bot de Telegram cuando no delega en HappyRobot.
        self.register("telegram", "tg:71")
        self.command("report", text="Una persona desmayada", zone="front_pit")
        delivery = next(
            d for d in self.store.claim("worker") if d["channel"] == "telegram"
        )
        worker = DeliveryWorker(self.store, external=True)
        with (
            patch(
                "motor.server.operational_worker.httpx.post",
                side_effect=httpx.ReadTimeout("lost"),
            ),
            patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "synthetic"}),
        ):
            worker._deliver(delivery)
        row = next(d for d in self.records("deliveries") if d["id"] == delivery["id"])
        self.assertEqual(row["status"], "retry")

    def test_workflow_critic_and_human_approval_share_same_state(self) -> None:
        self.store.workflow_enabled = True
        self.command(
            "register_actor",
            actor_id="coordinator",
            name="Control sintético",
            channel="web",
            roles=["organizador"],
            availability="available",
        )
        self.command("report", text="Se necesita ayuda", zone="front_pit")
        delivery = next(
            d for d in self.store.claim("worker") if d["channel"] == "happyrobot"
        )
        context = self.store.execute(
            {
                "kind": "delivery_start",
                "command_id": "start-review",
                "delivery_id": delivery["id"],
                "lease_token": delivery["lease_token"],
            },
            scope="system",
        )
        token = self.store.capability(str(delivery["id"]))
        body: Document = {
            "fase": "rapida",
            "agente": "rapido",
            "incident_id": context["incident_id"],
            "correlation_id": delivery["id"],
            "requiere_persona": True,
            "reason": "Comprobar evacuación",
            "actions": [{"kind": "evacuate", "zone": "front_pit"}],
            "papeles": {
                name: {"ok": True}
                for name in (
                    "triaje",
                    "prioridad",
                    "recursos",
                    "avisos",
                    "vigia",
                    "critico",
                )
            },
        }
        result = self.client.post(
            "/hr/tools/decidir", json=body, headers={"X-Mando-Token": token}
        )
        self.assertEqual(result.status_code, 200, result.text)
        self.assertFalse(result.json()["aplicado"])
        self.assertEqual(self.records("approvals")[0]["status"], "pending")
        self.assertTrue(
            self.client.post(
                "/hr/tools/decidir", json=body, headers={"X-Mando-Token": token}
            ).json()["duplicate"]
        )
        approval = self.records("approvals")[0]
        self.command(
            "decide",
            approval_id=approval["id"],
            expected_version=approval["version"],
            content_hash=approval["content_hash"],
            approved=True,
        )
        self.assertEqual(self.records("approvals")[0]["status"], "approved")
        self.assertEqual(
            self.client.post(
                "/hr/tools/decidir",
                json=body,
                headers={"X-Mando-Token": "synthetic-wrong"},
            ).status_code,
            403,
        )

    def test_staff_with_active_task_does_not_open_a_new_incident(self) -> None:
        # Las preguntas/notas del personal en servicio no deben crear avisos nuevos.
        self.register("telegram", "tg:71")
        self.command("report", text="Una persona desmayada", zone="front_pit")
        # El planificador ya oferta al personal libre: tg:71 tiene una tarea activa.
        self.assertEqual(len(self.records("assignments")), 1)
        self.assertEqual(self.records("assignments")[0]["actor_id"], "tg:71")
        self.telegram(self.message(500, 71, "¿Cuántas personas afectadas?"))
        self.telegram(self.message(501, 71, "Salgo desde la puerta A"))
        self.assertEqual(len(self.records("incidents")), 1)

    def test_happyrobot_decides_for_bot_reports_and_mando_does_not_offer(self) -> None:
        # Decisión 100% HappyRobot: un aviso que entra por el bot no genera ofertas
        # de MANDO, ni siquiera habiendo personal libre de sobra.
        self.register("telegram", "tg:81")
        self.telegram(self.message(600, 90, "Persona desmayada en el escenario 1"))
        incident = self.records("incidents")[0]
        self.assertIn("coordinacion_happyrobot", incident["why_waiting"])
        self.assertEqual(self.records("assignments"), [])
        self.assertEqual(
            [d for d in self.records("deliveries") if d["channel"] == "telegram"], []
        )

    def test_operator_override_routes_the_offer_through_happyrobot(self) -> None:
        # El operador anula la decisión de HappyRobot: MANDO crea la asignación, pero
        # quien manda el mensaje y conversa es HappyRobot.
        self.store.telegram_via_happyrobot = True
        self.register("telegram", "tg:82")
        self.telegram(self.message(601, 91, "Persona desmayada en el escenario 1"))
        incident = self.records("incidents")[0]
        self.command(
            "offer",
            incident_id=incident["id"],
            actor_id="tg:82",
            role="medico",
            expected_version=incident["version"],
        )
        delivery = next(d for d in self.records("deliveries") if d["channel"] == "happyrobot")
        self.assertEqual(delivery["purpose"], "offer")
        self.assertEqual(delivery["recipient_id"], "tg:82")
        # MANDO no manda nada por su bot: delega el mensaje en HappyRobot.
        self.assertEqual(
            [d for d in self.records("deliveries") if d["channel"] == "telegram"], []
        )

        claimed = next(
            item for item in self.store.claim("worker") if item["id"] == delivery["id"]
        )
        self.assertEqual(claimed["payload"]["chat_id"], "82")

        seen: list[Document] = []

        def fake_post(url: str, **kwargs: object) -> httpx.Response:
            seen.append(cast(Document, kwargs["json"]))
            return httpx.Response(
                200, json={"run_id": "run-offer-1"}, request=httpx.Request("POST", url)
            )

        with (
            patch("motor.server.operational_worker.httpx.post", side_effect=fake_post),
            patch.dict(
                os.environ,
                {
                    "HR_WORKFLOW_TG_OFFER": "wf-tg-offer",
                    "HR_API_KEY": "synthetic-hr-key",
                    "HR_API_BASE": "https://hr.invalid/api/v2",
                    "MANDO_PUBLIC_URL": "https://mando.invalid/festival",
                },
            ),
        ):
            DeliveryWorker(self.store, external=True)._deliver(claimed)
        payload = cast(Document, seen[0]["payload"])
        self.assertEqual(payload["mode"], "new")
        self.assertEqual(payload["rol"], "medico")
        self.assertEqual(payload["roles_orden"], "medico")
        self.assertEqual(payload["reporter_chat_id"], "91")
        self.assertEqual(payload["correlation_id"], incident["id"])
        self.assertEqual(payload["zona"], "front_pit")
        self.assertEqual(payload["override"], "true")
        # HappyRobot es quien manda el mensaje y lleva la conversación.
        self.assertIn("¿Puedes atender el aviso", payload["texto"])
        self.assertEqual(
            next(d for d in self.records("deliveries") if d["id"] == delivery["id"])["status"],
            "delivered",
        )


    def test_reset_incidents_clears_state_and_is_operator_only(self) -> None:
        self.register("telegram", "tg:91")
        self.command("report", text="Una persona desmayada", zone="front_pit")
        self.assertNotEqual(self.records("incidents"), [])
        self.assertNotEqual(self.records("assignments"), [])

        # Sin confirmación explícita no se toca nada.
        with self.assertRaises(OperationalError) as denied:
            self.store.execute(
                {"command_id": "reset-1", "kind": "reset_incidents"},
                principal="operador-1",
                scope="operator",
                channel="web",
            )
        self.assertEqual(denied.exception.code, "confirmation_required")
        self.assertNotEqual(self.records("incidents"), [])

        # El alcance de Telegram no puede vaciar el estado.
        with self.assertRaises(OperationalError) as forbidden:
            self.store.execute(
                {"command_id": "reset-2", "kind": "reset_incidents", "confirm": True},
                principal="tg:91",
                scope="telegram",
                channel="telegram",
            )
        self.assertEqual(forbidden.exception.code, "forbidden")

        body = {
            "command_id": "reset-known",
            "kind": "reset_incidents",
            "confirm": True,
        }
        reset = self.client.post("/api/operations/command", json=body)
        self.assertEqual(reset.status_code, 200, reset.text)
        self.assertEqual(reset.json()["removed"]["incidents"], 1, reset.text)
        state = self.snapshot()
        for key in ("incidents", "assignments", "approvals", "deliveries"):
            self.assertEqual(state[key], [], key)
        self.assertEqual(state["telegram"]["assignments"], [])
        # Queda el rastro del reinicio y el personal sigue registrado.
        self.assertEqual([e["kind"] for e in state["events"]], ["reset_incidents"])
        self.assertEqual([a["id"] for a in state["actors"]], ["tg:91"])
        self.assertEqual(state["actors"][0]["availability"], "available")

        # La misma `command_id` no vuelve a reiniciar.
        again = self.client.post("/api/operations/command", json=body)
        self.assertEqual(again.status_code, 200, again.text)
        self.assertTrue(again.json()["duplicate"])


if __name__ == "__main__":
    unittest.main()
