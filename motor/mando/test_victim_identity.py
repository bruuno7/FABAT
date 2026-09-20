"""Identity regressions; all reports and resources are local fixtures."""
from __future__ import annotations

import unittest

from motor.contracts import Action, ActionKind, Channel, Family, Incident, Observation, Report, Resource, ResourceKind, Zone
from motor.mando import Mando


class VictimIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = Mando()
        self.zone = Zone("general", "Pista general", "general", 13000, 27000, 100)
        self.resources = {
            f"med_{n}": Resource(f"med_{n}", ResourceKind.MEDICAL, f"Medical {n}", "general")
            for n in range(1, 4)
        }

    def send(self, rid: str, text: str, *, source: str = "telegram:test", t: int = 0,
             zone: str | None = "general", channel: Channel = Channel.WHATSAPP) -> list[Action]:
        report = Report(rid, t, channel, text, source, zone_hint=zone)
        return self.agent.tick(Observation(t, {"general": self.zone}, self.resources, [report], [], {}, {}))

    def patients(self) -> list[Incident]:
        return [inc for inc in self.agent.incidents.values() if inc.family == Family.MEDICAL]

    def test_explicit_other_person_preserves_two_tasks_same_source(self) -> None:
        actions = self.send("one", "Una persona se ha desmayado")
        actions += self.send("two", "Otra persona se ha desmayado")
        self.assertEqual(len(self.patients()), 2)
        self.assertEqual(sum(inc.needs.get("medical", 0) for inc in self.patients()), 2)
        dispatched = [a for a in actions if a.kind == ActionKind.DISPATCH]
        self.assertEqual(len({a.incident for a in dispatched}), 2)
        self.assertEqual(len({a.resource for a in dispatched}), 2)

    def test_source_retransmissions_are_idempotent_even_for_other_person(self) -> None:
        self.send("one", "Una persona se ha desmayado")
        self.send("two", "Otra persona se ha desmayado")
        before = self.agent.snapshot()
        for _ in range(5):
            actions = self.send("two", "Otra persona se ha desmayado")
            self.assertFalse([a for a in actions if a.kind in (ActionKind.DISPATCH, ActionKind.MERGE)])
        self.assertEqual(len(self.patients()), 2)
        self.assertEqual([i["reports"] for i in before["incidents"]],
                         [i["reports"] for i in self.agent.snapshot()["incidents"]])

    def test_same_zone_and_source_do_not_establish_victim_identity(self) -> None:
        self.send("one", "Una persona se ha desmayado")
        actions = self.send("two", "Hay una persona desmayada")
        self.assertEqual(len(self.patients()), 2)
        self.assertIn("identity", self.agent.meta[self.patients()[1].id].missing)
        self.assertTrue([a for a in actions if a.kind == ActionKind.ASK
                         and a.params.get("purpose") == "identity"])
        self.assertTrue([a for a in actions if a.kind == ActionKind.DISPATCH])

    def test_anonymous_identical_text_keeps_possible_second_victim(self) -> None:
        for rid in ("one", "two"):
            self.send(rid, "Una persona se ha desmayado", source="asistente")
        self.assertEqual(len(self.patients()), 2)

    def test_explicit_same_person_can_merge_across_channels_and_sources(self) -> None:
        self.send("one", "Una persona se ha desmayado")
        first = self.patients()[0]
        actions = self.send("two", f"La misma persona de {first.id} sigue desmayada", source="seguridad 1", channel=Channel.VOICE)
        self.assertEqual(len(self.patients()), 1)
        self.assertEqual(self.patients()[0].reports, ["one", "two"])
        self.assertTrue([a for a in actions if a.kind == ActionKind.MERGE])
        self.assertFalse([a for a in actions if a.kind == ActionKind.DISPATCH])

    def test_explicit_reference_selects_victim_among_multiple_candidates(self) -> None:
        self.send("one", "Una persona se ha desmayado")
        first = self.patients()[0]
        self.send("two", "Otra persona se ha desmayado")
        self.send("three", f"La misma persona del incidente {first.id} sigue desmayada")
        self.assertEqual(len(self.patients()), 2)
        self.assertEqual(first.reports, ["one", "three"])

    def test_uncertain_reference_in_ingestion_preserves_separate_demand(self) -> None:
        self.send("one", "Una persona se ha desmayado")
        first = self.patients()[0]
        self.send("two", f"Quizás la misma persona {first.id} sigue desmayada")
        self.send("three", f"No sé si es la misma persona {first.id}, está desmayada")
        self.assertEqual(len(self.patients()), 3)
        self.assertEqual(sum(i.needs.get("medical", 0) for i in self.patients()), 3)
        self.assertEqual(first.reports, ["one"])
        self.assertEqual(self.agent.counters["merges"], 0)

    def test_same_person_without_unique_candidate_keeps_demand(self) -> None:
        self.send("one", "Una persona se ha desmayado")
        self.send("two", "Otra persona se ha desmayado")
        actions = self.send("three", "La misma persona sigue desmayada")
        self.assertEqual(len(self.patients()), 3)
        self.assertTrue([a for a in actions if a.kind == ActionKind.ASK])

    def test_negated_same_person_is_distinct(self) -> None:
        self.send("one", "Una persona se ha desmayado")
        self.send("two", "No es la misma persona, hay una persona desmayada")
        self.assertEqual(len(self.patients()), 2)

    def test_explicit_other_person_overrides_a_nearby_incident_reference(self) -> None:
        self.send("one", "Una persona se ha desmayado")
        first = self.patients()[0]
        self.send("two", f"Otra persona desmayada junto a {first.id}")
        self.assertEqual(len(self.patients()), 2)
        self.assertEqual(self.agent.counters["merges"], 0)

    def test_learning_zone_does_not_fold_medical_victims(self) -> None:
        self.send("one", "Una persona se ha desmayado")
        self.send("two", "Otra persona se ha desmayado", zone=None)
        second = self.patients()[1]
        second.zone = "general"
        self.assertFalse(self.agent._fold_duplicate(second))
        self.assertEqual(len(self.agent.live), 2)


if __name__ == "__main__":
    unittest.main()
