"""Regresiones de cierre: procedencia de ubicación con conversaciones sintéticas."""
from __future__ import annotations

import unittest

from motor.contracts import Observation
from motor.mando import Mando
from motor.intake.test_intake import ZONES, session


class LocationProvenanceClosureTests(unittest.TestCase):
    def test_same_zone_confirmation_promotes_channel_hint_and_ignores_incidental_zone(self) -> None:
        intake = session(session_id="synthetic-location", zone_hint="gate_b")
        first = intake.receive("mi amigo se ha desmayado")
        self.assertEqual(first.state["slots"]["location"]["source"], "channel")
        confirmed = intake.receive("estamos en puerta B")
        location = confirmed.state["slots"]["location"]
        self.assertEqual(location["value"]["zone"], "gate_b")
        self.assertIn(location["source"], ("user", "answer"))
        self.assertEqual(location["turn"], 2)
        self.assertFalse(confirmed.reports)  # solo procedencia, sin aviso nuevo
        incidental = intake.receive("sí respira, su amigo ha ido al baño")
        self.assertEqual(incidental.state["slots"]["location"]["value"]["zone"], "gate_b")
        self.assertTrue(all(r.zone_hint == "gate_b" for r in incidental.reports))
        agent = Mando(watch_zones=False)
        for turn in (first, confirmed, incidental):
            agent.tick(Observation(0, ZONES, {}, turn.reports, []))
        self.assertEqual(len(agent.live), 1)
        self.assertEqual(agent.live[0].zone, "gate_b")

    def test_explicit_correction_updates_same_incident(self) -> None:
        intake = session(session_id="synthetic-correction", zone_hint="gate_b")
        turns = [intake.receive("mi amigo se ha desmayado"), intake.receive("estamos en puerta B")]
        corrected = intake.receive("Me he equivocado de ubicación: estamos en puerta C")
        turns.append(corrected)
        self.assertEqual(corrected.state["slots"]["location"]["value"]["zone"], "gate_c")
        self.assertEqual(len(corrected.reports), 1)
        self.assertEqual(corrected.reports[0].zone_hint, "gate_c")
        self.assertTrue(corrected.reports[0].id.startswith(turns[0].reports[0].id + ".u"))
        agent = Mando(watch_zones=False)
        for turn in turns:
            agent.tick(Observation(0, ZONES, {}, turn.reports, []))
        self.assertEqual(len(agent.live), 1)
        self.assertEqual(agent.live[0].zone, "gate_c")

    def test_uncertain_or_questioning_correction_does_not_move_confirmed_zone(self) -> None:
        for text in ("Quizás en realidad estamos en puerta C", "¿En realidad estamos en puerta C?",
                     "No sé si en realidad estamos en puerta C", "En realidad no estamos en puerta C",
                     "su amigo ha ido al baño"):
            with self.subTest(text=text):
                intake = session(zone_hint="gate_b")
                intake.receive("mi amigo se ha desmayado")
                intake.receive("estamos en puerta B")
                turn = intake.receive(text)
                self.assertEqual(turn.state["slots"]["location"]["value"]["zone"], "gate_b")


if __name__ == "__main__":
    unittest.main()
