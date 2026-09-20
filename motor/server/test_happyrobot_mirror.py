"""Espejo de solo lectura de la coordinación que decide HappyRobot por Telegram.

Simulación: no hay proveedores ni red. Comprueba que el espejo no crea autoridad
(no ofrece tareas, no reserva capacidad) y que la interfaz recibe lo que hace falta
para pintar el despacho sin exponer chat_id.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from typing import cast
from unittest.mock import patch

from fastapi.testclient import TestClient

from motor.happyrobot.sandbox import fa_common

from .app import create_app
from .operational_service import OperationalService
from .operational_worker import DeliveryWorker


class HappyRobotMirrorTest(unittest.TestCase):
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
        self.app = create_app(threaded=False)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.store: OperationalService = self.app.state.operational

    def mirror(
        self, events: list[dict[str, object]], token: str | None = "synthetic-bridge"
    ) -> object:
        headers = {"X-Mando-Bridge-Token": token} if token is not None else {}
        return self.client.post(
            "/api/operations/happyrobot", json={"events": events}, headers=headers
        )

    def snapshot(self) -> dict[str, object]:
        response = self.client.get("/api/operations/state")
        self.assertEqual(response.status_code, 200, response.text)
        return cast(dict[str, object], response.json())

    def test_bridge_token_is_required(self) -> None:
        self.assertEqual(
            self.mirror(
                [{"type": "tg_staff", "disponibles": 1, "total": 2}], None
            ).status_code,
            403,
        )
        self.assertEqual(
            self.mirror(
                [{"type": "tg_staff", "disponibles": 1, "total": 2}], "wrong"
            ).status_code,
            403,
        )

    def test_mirror_is_read_only_and_visible_in_state(self) -> None:
        response = self.mirror(
            [
                {
                    "type": "tg_incident",
                    "id": "tg-900-1700",
                    "texto": "Una persona se ha desmayado junto al escenario",
                    "tipo": "medica",
                    "zona": "front_pit",
                    "gravedad": "emergencia",
                    "prioridad": 8,
                    "alias_informante": "Asistente",
                    "recursos_requeridos": [{"rol": "medico", "cantidad": 1}],
                },
                {"type": "tg_staff", "disponibles": 4, "total": 5},
                {
                    "type": "tg_assignment",
                    "incident_id": "tg-900-1700",
                    "rol": "medico",
                    "estado": "pending",
                    "alias": "Marta",
                    "intento": 1,
                },
                {
                    "type": "tg_assignment",
                    "incident_id": "tg-900-1700",
                    "rol": "medico",
                    "estado": "accepted",
                    "alias": "Marta",
                    "eta_min": 3,
                    "from_zone": "gate_a",
                    "intento": 1,
                },
            ]
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(cast(dict[str, object], response.json())["applied"], 4)

        state = self.snapshot()
        telegram = cast(dict[str, object], state["telegram"])
        incidents = cast(dict[str, dict[str, object]], telegram["incidents"])
        self.assertEqual(incidents["tg-900-1700"]["tipo"], "medica")
        self.assertEqual(incidents["tg-900-1700"]["zona"], "front_pit")
        assignments = cast(list[dict[str, object]], telegram["assignments"])
        self.assertEqual(len(assignments), 1)
        self.assertEqual(assignments[0]["estado"], "accepted")
        self.assertEqual(assignments[0]["eta_min"], 3)
        self.assertEqual(assignments[0]["desde_zona"], "gate_a")
        self.assertEqual(cast(dict[str, object], telegram["staff"])["disponibles"], 4)

        # El espejo no es autoridad: no aparece ninguna asignación operativa ni reserva.
        self.assertEqual(cast(list[object], state["assignments"]), [])
        self.assertEqual(cast(list[object], state["incidents"]), [])

    def test_chat_id_is_never_published(self) -> None:
        self.mirror(
            [
                {
                    "type": "tg_assignment",
                    "incident_id": "tg-900-1700",
                    "rol": "medico",
                    "estado": "accepted",
                    "alias": "123456789",
                    "intento": 1,
                }
            ]
        )
        body = self.client.get("/api/operations/state").text
        self.assertNotIn("123456789", body)

    def test_sandbox_offer_mirror_is_accepted_verbatim(self) -> None:
        # El sandbox de HappyRobot emite el espejo; MANDO debe aceptarlo tal cual.
        incident = {
            "id": "tg-900-1700",
            "texto": "Persona caída junto al escenario",
            "tipo": "medica",
            "zona": "front_pit",
            "gravedad": "emergencia",
            "alias_informante": "Asistente",
        }
        assignment = {
            "id": "tg-900-1700~1",
            "rol": "medico",
            "chat_id": "100200300",
            "estado": "pending",
            "alias": "Marta",
            "intento": 1,
            "eta_min": None,
            "from_zone": None,
        }
        offer = fa_common.offer_message(assignment, incident)
        response = self.mirror(offer["mirror"])
        self.assertEqual(response.status_code, 200, response.text)

        assignment["estado"] = "done"
        progress = fa_common.attach_mirror(
            fa_common.progress_message(assignment, "Finalizado"),
            [fa_common.tg_assignment_event(incident, assignment)],
        )
        response = self.mirror(progress["mirror"])
        self.assertEqual(response.status_code, 200, response.text)
        telegram = cast(dict[str, object], self.snapshot()["telegram"])
        rows = cast(list[dict[str, object]], telegram["assignments"])
        self.assertEqual(rows[0]["estado"], "finalizado")

    def test_invalid_events_are_rejected(self) -> None:
        self.assertEqual(self.mirror([]).status_code, 400)
        self.assertEqual(
            self.mirror(
                [
                    {
                        "type": "tg_assignment",
                        "incident_id": "x",
                        "rol": "curandero",
                        "estado": "accepted",
                    }
                ]
            ).status_code,
            400,
        )
        self.assertEqual(
            self.mirror(
                [{"type": "tg_staff", "disponibles": 5, "total": 2}]
            ).status_code,
            400,
        )


if __name__ == "__main__":
    unittest.main()
