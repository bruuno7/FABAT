"""Regresiones de cierre: entradas sintéticas, sin red ni proveedores externos."""
from __future__ import annotations

import unittest
from dataclasses import replace

from motor.contracts import ActionKind, ActionStatus, Channel, Family, IncidentStatus, Observation, Report, ResourceKind
from motor.intake.test_intake import session
from motor.mando import HeuristicParser, Mando
from motor.mando.test_mando import FakeComms, _zones, new, run


class LexiconClosureTests(unittest.TestCase):
    def test_uno_does_not_contain_a_negation(self) -> None:
        parser = HeuristicParser()
        for text in (
            "uno respira bien, el otro está mareado en puerta B",
            "uno reacciona, el otro está mareado en puerta B",
            "uno responde, el otro está mareado en puerta B",
            "Bruno respira bien, está mareado en puerta B",
        ):
            with self.subTest(text=text):
                parsed = parser.parse(Report("r", 0, Channel.WHATSAPP, text), _zones())
                self.assertEqual(parsed["type"], "dizziness")
                self.assertFalse(parsed["life_threat"])
                self.assertNotIn("ambulance", parsed["needs"])

    def test_real_absence_of_breathing_remains_urgent(self) -> None:
        for text in (
            "no respira en puerta B",
            "uno respira bien; el otro no respira en puerta B",
            "Bruno no está respirando en puerta B",
            "NO RESPIRA! en puerta B",
        ):
            with self.subTest(text=text):
                agent = Mando(watch_zones=False)
                agent.tick(Observation(0, _zones(), {}, [Report("r", 0, Channel.WHATSAPP, text)], []))
                incident = next(iter(agent.incidents.values()))
                self.assertEqual(incident.type, "cardiac_arrest")
                self.assertGreaterEqual(incident.priority, 9)
                self.assertTrue(agent.meta[incident.id].life_threat)


class IntakeCorrelationClosureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = Mando(watch_zones=False)

    def send(self, *reports: Report) -> None:
        self.agent.tick(Observation(max(r.t for r in reports), _zones(), {}, list(reports), []))

    def test_partial_location_and_escalation_share_original_incident(self) -> None:
        intake = session(session_id="synthetic-a")
        reports = []
        for t, text in enumerate(("mi amigo se ha desmayado", "junto a la barra", "no respira")):
            turn = intake.receive(text, t=t)
            self.assertTrue(turn.reports)
            reports.extend(turn.reports)
            self.send(*turn.reports)
        self.assertEqual(len(self.agent.live), 1)
        incident = self.agent.live[0]
        self.assertEqual(incident.reports, [r.id for r in reports])
        self.assertEqual(incident.zone, "food")
        self.assertEqual(incident.type, "cardiac_arrest")
        self.assertEqual(incident.needs, {"medical": 1, "ambulance": 1})
        self.assertNotIn("identity", self.agent.meta[incident.id].missing)
        self.send(*reports)  # retransmisión de transporte, no más avisos ni demanda
        self.assertEqual(incident.reports, [r.id for r in reports])

    def test_same_words_in_different_sessions_do_not_merge(self) -> None:
        for sid in ("synthetic-a", "synthetic-b"):
            intake = session(session_id=sid)
            self.send(*intake.receive("mi amigo se ha desmayado en la barra").reports)
            self.send(*intake.receive("no respira").reports)
        self.assertEqual(len(self.agent.live), 2)
        self.assertTrue(all(len(i.reports) == 2 for i in self.agent.live))
        self.assertTrue(all(i.type == "cardiac_arrest" for i in self.agent.live))

    def test_update_requires_existing_root_matching_header_source_and_channel(self) -> None:
        intake = session(session_id="synthetic-a")
        root = intake.receive("mi amigo se ha desmayado").reports[0]
        update = intake.receive("junto a la barra").reports[0]
        invalid = (
            replace(update, source="asistente synthetic-b"),
            replace(update, channel=Channel.SMS),
            replace(update, id="R-synthetic-b-1.u1"),
            replace(update, text=update.text.replace(root.id, "R-other-1")),
            replace(update, text=update.text + " Otra persona desmayada."),
        )
        for report in invalid:
            with self.subTest(report=report):
                self.agent = Mando(watch_zones=False)
                self.send(root)
                self.send(report)
                self.assertEqual(len(self.agent.live), 2)
                self.assertEqual(self.agent.live[0].reports, [root.id])
        self.agent = Mando(watch_zones=False)
        self.send(update)  # sin raíz conocida se abre separado, no se fabrica una correlación
        self.assertEqual(len(self.agent.live), 1)
        self.assertEqual(self.agent.live[0].reports, [update.id])
        self.send(root)
        self.assertEqual(len(self.agent.live), 2)
        self.agent = Mando(watch_zones=False)
        self.send(root)
        self.send(update)
        self.assertEqual(len(self.agent.live), 1)
        self.assertEqual(self.agent.live[0].reports, [root.id, update.id])

    def test_invalid_update_cannot_fall_back_to_text_similarity(self) -> None:
        root = Report("R-synthetic-a-1", 0, Channel.WHATSAPP,
                      "Aviso R-synthetic-a-1: hay una pelea en la barra", "asistente synthetic-a")
        update = Report("R-synthetic-a-1.u1", 1, Channel.WHATSAPP,
                        "ACTUALIZACIÓN del aviso R-synthetic-a-1: pelea en la barra", "asistente synthetic-b")
        self.send(root, update)
        self.assertEqual(len(self.agent.live), 2)

    def test_two_roots_from_same_session_still_represent_two_victims(self) -> None:
        for n in (1, 2):
            root = f"R-synthetic-a-{n}"
            self.send(Report(root, 0, Channel.WHATSAPP, f"Aviso {root}: desmayo en la barra.",
                             "asistente synthetic-a"))
            self.send(Report(f"{root}.u1", 1, Channel.WHATSAPP,
                             f"ACTUALIZACIÓN del aviso {root}: no respira. Zona food.",
                             "asistente synthetic-a", zone_hint="food"))
        patients = [i for i in self.agent.live if i.family == Family.MEDICAL]
        self.assertEqual(len(patients), 2)
        self.assertEqual(sum(i.needs["medical"] for i in patients), 2)
        self.assertEqual([len(i.reports) for i in patients], [2, 2])


class IdentityAnswerClosureTests(unittest.TestCase):
    def test_confirmed_identity_releases_waiting_demand_without_recalling_team(self) -> None:
        comms = FakeComms()
        world, agent = new(team={"med_1": (ResourceKind.MEDICAL, "food")}, comms=comms)
        world.report("Una persona se ha desmayado en la barra")
        original = run(world, agent)
        first = agent.live[0]
        comms.answers = [f"Sí, es la misma persona del incidente {first.id}"]
        world.report("Hay una persona desmayada en la barra")
        questions = run(world, agent)
        duplicate = next(i for i in agent.live if i is not first)
        answer = next(a for a in questions if a.params.get("purpose") == "identity")
        after = run(world, agent)
        self.assertEqual(agent.live, [first])
        self.assertEqual(first.reports, ["r1", "r2"])
        self.assertEqual(first.needs, {"medical": 1})
        self.assertEqual(duplicate.needs, {})
        self.assertNotIn("identity", agent.meta[duplicate.id].missing)
        self.assertEqual(agent.meta[duplicate.id].merged_into, first.id)
        self.assertEqual(agent.assign["med_1"][0], first.id)
        self.assertFalse([a for a in after if a.kind in (ActionKind.RECALL, ActionKind.DISPATCH)])
        merge = next(a for a in after if a.kind == ActionKind.MERGE)
        self.assertEqual(merge.params["identity_answer"], answer.id)
        self.assertEqual(merge.params["merged"], duplicate.id)
        self.assertEqual(next(a for a in original if a.kind == ActionKind.DISPATCH).incident, first.id)
        self.assertEqual(first.status, IncidentStatus.IN_PROGRESS)
        comms._pending.append({"action_id": answer.id, "result": "answer",
                               "text": f"La misma persona de {first.id}"})
        replay = run(world, agent)
        self.assertFalse([a for a in replay if a.kind == ActionKind.MERGE])
        self.assertEqual(agent.counters["merges"], 1)

    def test_two_started_dispatches_keep_reservations_and_accept_original_callbacks(self) -> None:
        comms = FakeComms()
        world, agent = new(comms=comms)
        world.report("Una persona se ha desmayado en la barra")
        first_actions = run(world, agent)
        first = agent.live[0]
        comms.answers = [f"Es la misma víctima de {first.id}"]
        world.report("Hay una persona desmayada en la barra")
        second_actions = run(world, agent)
        dispatches = [a for a in first_actions + second_actions if a.kind == ActionKind.DISPATCH]
        self.assertEqual(len(dispatches), 2)
        original_refs = [(a.id, a.incident, a.resource) for a in dispatches]
        after = run(world, agent, 3)
        self.assertEqual(agent.live, [first])
        self.assertEqual(first.needs, {"medical": 1})
        self.assertEqual(set(first.assigned), {a.resource for a in dispatches})
        self.assertEqual({iid for iid, _ in agent.assign.values()}, {first.id})
        self.assertEqual([(a.id, a.incident, a.resource) for a in dispatches], original_refs)
        self.assertTrue(all(a.status == ActionStatus.DONE for a in dispatches))
        self.assertTrue(all(a.id in agent.accepted for a in dispatches))
        self.assertFalse([a for a in after if a.kind in (ActionKind.RECALL, ActionKind.DISPATCH)])
        self.assertEqual(first.status, IncidentStatus.IN_PROGRESS)
        run(world, agent, 35)
        self.assertEqual(first.status, IncidentStatus.RESOLVED)
        self.assertFalse(agent.assign)

    def test_ambiguous_negative_unknown_or_multiple_references_do_not_merge(self) -> None:
        for answer in (
            "Sí", "Es la misma persona", "M-001", "Quizás sea la misma persona M-001",
            "No sé si es la misma persona M-001", "No es la misma persona M-001",
            "Otra persona junto a M-001", "La misma víctima M-999",
            "La misma persona de M-001 o M-999", "¿Es la misma persona M-001?",
            "La misma persona M-002", "Probablemente la misma persona M-001",
            "Creo que es la misma persona M-001", "I think it is the same person M-001",
        ):
            with self.subTest(answer=answer):
                comms = FakeComms()
                world, agent = new(comms=comms)
                world.report("Una persona se ha desmayado en la barra")
                run(world, agent)
                comms.answers = [answer]
                world.report("Hay una persona desmayada en la barra")
                run(world, agent, 2)
                self.assertEqual(len(agent.live), 2)
                self.assertEqual(sum(i.needs.get("medical", 0) for i in agent.live), 2)
                self.assertIn("identity", agent.meta["M-002"].missing)
                self.assertEqual(agent.counters["merges"], 0)


if __name__ == "__main__":
    unittest.main()
