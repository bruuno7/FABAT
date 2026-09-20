"""Contratos de la demo aislada; proveedores simulados, sin llamadas ni Telegram externos."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from typing import cast
from unittest.mock import patch

from fastapi.testclient import TestClient

from .demo_jurado import configure, create_demo_app
from .operational import OperationalError
from .operational_service import OperationalService
from .operational_types import Document
from .operational_worker import DeliveryWorker

CONNECTED = {
    "MANDO_OPERATOR_TOKEN": "synthetic-demo-operator",
    "MANDO_PUBLIC_URL": "https://demo.example",
    "TELEGRAM_BOT_TOKEN": "synthetic-bot",
    "TELEGRAM_WEBHOOK_SECRET": "synthetic-webhook",
    "HR_API_KEY": "synthetic-key",
    "HR_API_BASE": "https://provider.example",
    "HR_ENV": "development",
    "HR_WORKFLOW_DISPATCH": "synthetic-workflow",
    "HR_SECRET": "synthetic-signing",
    "MANDO_ALLOWED_NUMBERS": "+15555550123",
}


class JuryDemoTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.data = Path(directory.name) / "demo"
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        worker = patch.object(DeliveryWorker, "start")
        worker.start()
        self.addCleanup(worker.stop)

    def open(self, connected: bool = False) -> tuple[TestClient, OperationalService]:
        if connected:
            os.environ.update(CONNECTED)
        app = create_demo_app(self.data, connected=connected)
        client = TestClient(app)
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        return client, cast(OperationalService, app.state.operational)

    def test_offline_clears_inherited_delivery_and_keeps_production_file(self) -> None:
        production = self.data.parent / "production.sqlite"
        production.write_bytes(b"do not touch")
        os.environ.update(CONNECTED, MANDO_OPERATIONAL_DB=str(production),
                          HR_WORKFLOW_RAPIDO="old", HR_WORKFLOW_TG_OFFER="old",
                          MANDO_EXTERNAL_DELIVERY="1")
        client, service = self.open()
        self.assertEqual(production.read_bytes(), b"do not touch")
        self.assertEqual(os.environ["MANDO_EXTERNAL_DELIVERY"], "0")
        self.assertNotIn("TELEGRAM_BOT_TOKEN", os.environ)
        self.assertNotIn("HR_API_KEY", os.environ)
        self.assertEqual(os.environ["HR_WORKFLOW_RAPIDO"], "")
        self.assertFalse(service.happyrobot_plans_telegram)
        actors = cast(list[Document], service.state()["actors"])
        self.assertEqual(len(actors), 4)
        self.assertTrue(all(actor["channel"] == "web" for actor in actors))
        self.assertEqual(client.post("/telegram/webhook", json={}).status_code, 403)

    def test_login_and_manual_roles_use_persistent_authority(self) -> None:
        client, service = self.open()
        self.assertEqual(client.get("/jurado").status_code, 200)
        self.assertEqual(client.get("/api/operations/state").status_code, 401)
        self.assertEqual(client.post("/api/operations/command", json={}).status_code, 401)
        self.assertEqual(client.post("/api/operator/login", json={"token": "jurado-local"}).status_code, 200)
        report = client.post("/api/operations/command", json={
            "command_id": "test-report", "kind": "report",
            "text": "SIMULACRO: una persona inconsciente, no respira, en puerta B.", "zone": "gate_b",
        })
        self.assertEqual(report.status_code, 200, report.text)
        assignments = cast(list[Document], service.state()["assignments"])
        assignment = next(row for row in assignments if row["actor_id"] == "demo-medico")
        stale_version = assignment["version"]
        for kind in ("accept", "eta", "arrive", "locate", "complete"):
            current = next(row for row in cast(list[Document], service.state()["assignments"]) if row["id"] == assignment["id"])
            fields: Document = {"assignment_id": current["id"], "expected_version": current["version"]}
            if kind == "eta":
                fields.update(eta_min=3, destination_confirmed=True, destination_zone_id="gate_b")
            response = client.post("/api/operations/command", json={
                "command_id": "test-" + kind, "kind": kind, **fields,
            })
            self.assertEqual(response.status_code, 200, response.text)
        stale = client.post("/api/operations/command", json={
            "command_id": "stale", "kind": "accept", "assignment_id": assignment["id"],
            "expected_version": stale_version,
        })
        self.assertEqual(stale.status_code, 409)

    def test_restart_does_not_reset_roles_or_incidents(self) -> None:
        _, service = self.open()
        service.execute({"command_id": "report", "kind": "report", "text": "Desmayo", "zone": "gate_b"})
        service.execute({"command_id": "custom", "kind": "register_actor", "actor_id": "demo-accesos",
                         "name": "Nombre conservado", "channel": "web", "roles": ["staff_entradas"],
                         "address": "", "zone": "gate_a", "availability": "unavailable"})
        service.close()
        _, reopened = self.open()
        state = reopened.state()
        self.assertEqual(len(cast(list[Document], state["incidents"])), 1)
        actor = next(row for row in cast(list[Document], state["actors"]) if row["id"] == "demo-accesos")
        self.assertEqual(actor["name"], "Nombre conservado")
        self.assertEqual(actor["availability"], "unavailable")

    def test_rejects_unknown_directory_and_mode_switch(self) -> None:
        self.data.mkdir()
        (self.data / "operations.sqlite").write_bytes(b"existing")
        with self.assertRaisesRegex(ValueError, "vacío"):
            configure(self.data, False)
        fresh = self.data.parent / "fresh"
        configure(fresh, False)
        os.environ.update(CONNECTED)
        with self.assertRaisesRegex(ValueError, "otro directorio"):
            configure(fresh, True)

    def test_connected_requires_config_https_and_non_default_token(self) -> None:
        with self.assertRaisesRegex(ValueError, "Falta configuración"):
            configure(self.data, True)
        os.environ.update(CONNECTED)
        os.environ["MANDO_PUBLIC_URL"] = "http://demo.example"
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            configure(self.data, True)
        os.environ.update(CONNECTED, MANDO_OPERATOR_TOKEN="jurado-local")
        with self.assertRaisesRegex(ValueError, "token privado"):
            configure(self.data, True)
        self.assertFalse(self.data.exists())

    def test_authenticated_telegram_deduplicates_and_offers_phone(self) -> None:
        client, service = self.open(True)
        service.execute({"command_id": "phone", "kind": "register_actor", "actor_id": "demo-medico",
                         "name": "Médico demo", "channel": "phone", "address": "+15555550123",
                         "roles": ["medico"], "zone": "medical_1", "availability": "available"})
        update = {"update_id": 1, "message": {"message_id": 1, "from": {"id": 42},
                  "chat": {"id": 42, "type": "private"},
                  "text": "SIMULACRO: una persona inconsciente, no respira, en puerta B."}}
        self.assertEqual(client.post("/telegram/webhook", json=update).status_code, 403)
        headers = {"X-Telegram-Bot-Api-Secret-Token": "synthetic-webhook"}
        first = client.post("/telegram/webhook", json=update, headers=headers)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertFalse(first.json()["duplicate"])
        second = client.post("/telegram/webhook", json=update, headers=headers)
        self.assertTrue(second.json()["duplicate"])
        self.assertEqual(len(cast(list[Document], service.state()["incidents"])), 1)
        deliveries = cast(list[Document], service.state()["deliveries"])
        self.assertEqual(len([row for row in deliveries if row["channel"] == "phone"]), 1)
        self.assertNotIn("+15555550123", str(service.state()))

    def test_telegram_rejects_invalid_but_retries_storage_failure(self) -> None:
        client, service = self.open(True)
        headers = {"X-Telegram-Bot-Api-Secret-Token": "synthetic-webhook"}
        invalid = client.post("/telegram/webhook", json={"update_id": 1}, headers=headers)
        self.assertEqual(invalid.status_code, 200)
        self.assertTrue(invalid.json()["rejected"])
        with patch.object(service, "receive_telegram", side_effect=OperationalError("storage_busy", 503)):
            failure = client.post("/telegram/webhook", json={}, headers=headers)
        self.assertEqual(failure.status_code, 503)
        oversized = client.post("/telegram/webhook", json={"text": "x" * 9000}, headers=headers)
        self.assertEqual(oversized.status_code, 413)


if __name__ == "__main__":
    unittest.main()
