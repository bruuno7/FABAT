"""Confirmar la ubicación sugerida protege el incidente de menciones incidentales."""
import unittest

from motor.intake.test_intake import session, slots


class LocationSourceTest(unittest.TestCase):
    def test_confirmed_hint_is_not_moved_by_an_unrelated_place(self):
        intake = session(zone_hint="gate_b")
        first = intake.receive("Hay una pelea en puerta B")
        self.assertEqual(slots(first)["location"]["zone"], "gate_b")
        next_turn = intake.receive("No hay armas, mi amigo ha ido al baño")
        self.assertEqual(slots(next_turn)["location"]["zone"], "gate_b")
        self.assertFalse(any(r.zone_hint == "toilets" for r in next_turn.reports))


if __name__ == "__main__":
    unittest.main()
