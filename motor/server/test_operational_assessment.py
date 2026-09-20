"""Generic reports retain their specialist family without inventing a diagnosis."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import cast

from .operational import OperationalStore
from .operational_types import Document


class OperationalAssessmentTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = OperationalStore(Path(directory.name) / "operations.sqlite", {
            "zones": [{"id": "front_pit", "name": "Escenario", "kind": "stage"}],
        })
        self.addCleanup(self.store.close)
        self.store.execute({
            "command_id": "coordinator", "kind": "register_actor",
            "actor_id": "coordinator", "name": "Coordinación sintética",
            "roles": ["organizador"], "channel": "web", "address": "coordinator",
            "availability": "available", "zone": "front_pit",
        })

    def test_unrecognized_diagnosis_keeps_specialist_shortage(self) -> None:
        for index, (text, role) in enumerate((
            ("Aglomeración peligrosa", "policia"),
            ("Persona necesita ayuda médica", "medico"),
            ("Están insultando a una persona", "policia"),
        )):
            with self.subTest(text=text):
                result = self.store.execute({
                    "command_id": f"report-{index}", "kind": "report",
                    "text": text, "zone": "front_pit",
                })
                state = self.store.state()
                incidents = cast(list[Document], state["incidents"])
                incident = next(i for i in incidents if i["id"] == result["incident_id"])
                self.assertEqual(incident["needs"], {role: 1})
                self.assertIn("no_available_" + role, str(incident["why_waiting"]))
                self.assertEqual(state["assignments"], [])

    def test_generic_medical_report_waits_for_location(self) -> None:
        self.store.execute({
            "command_id": "medic", "kind": "register_actor", "actor_id": "medic",
            "name": "Sanitario sintético", "roles": ["medico"], "channel": "web",
            "address": "medic", "availability": "available", "zone": "front_pit",
        })
        self.store.execute({
            "command_id": "medical-report", "kind": "report",
            "text": "Persona necesita ayuda médica", "zone": None,
        })
        state = self.store.state()
        incident = cast(list[Document], state["incidents"])[0]
        self.assertEqual(incident["needs"], {"medico": 1})
        self.assertTrue(str(incident["why_waiting"]).startswith("location_required:"))
        self.assertEqual(state["assignments"], [])

    def test_unspecified_help_stays_with_coordination(self) -> None:
        self.store.execute({
            "command_id": "unspecified", "kind": "report",
            "text": "Necesito ayuda", "zone": "front_pit",
        })
        state = self.store.state()
        incident = cast(list[Document], state["incidents"])[0]
        self.assertEqual(incident["needs"], {"organizador": 1})
        assignment = cast(list[Document], state["assignments"])[0]
        self.assertEqual(assignment["actor_id"], "coordinator")
