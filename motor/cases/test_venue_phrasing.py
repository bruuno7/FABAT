"""Coverage over the venue definition and every generated language."""
from __future__ import annotations

import random
import unittest

from motor.cases.generator import build_case
from motor.cases.phrasing import LANG_WEIGHTS, LOC_PUBLIC, LOC_STAFF, public_report, staff_report
from motor.cases.taxonomy import ZONES
from motor.cases.validate import validate_case
from motor.contracts import Channel, Report, Zone
from motor.mando import HeuristicParser
from motor.server.telegram_bot import match_zone


class VenuePhrasingTests(unittest.TestCase):
    def test_all_venue_zones_support_every_generated_language(self) -> None:
        for zone in ZONES:
            with self.subTest(zone=zone, voice="staff"):
                self.assertTrue(LOC_STAFF[zone])
                self.assertTrue(staff_report(random.Random(137), "heat_stroke", zone)["text"])
            for lang, _ in LANG_WEIGHTS:
                with self.subTest(zone=zone, lang=lang):
                    self.assertTrue(LOC_PUBLIC[lang][zone])
                    report = public_report(random.Random(137), "heat_stroke", zone,
                                           lang=lang, location="exact", noise=0)
                    self.assertEqual(report["lang"], lang)
                    self.assertTrue(any(phrase.casefold() in report["text"].casefold()
                                        for phrase in LOC_PUBLIC[lang][zone]))

    def test_exact_generator_reproducer(self) -> None:
        case = build_case(137, 1, "train")
        self.assertEqual(validate_case(case), [])
        self.assertEqual(case, build_case(137, 1, "train"))

    def test_stage_two_phrases_round_trip_in_all_languages(self) -> None:
        zones = {zid: Zone(zid, z["name"], z["kind"], z["area_m2"], z["capacity"])
                 for zid, z in ZONES.items()}
        parser = HeuristicParser()
        for lang, _ in LANG_WEIGHTS:
            for phrase in LOC_PUBLIC[lang]["stage_2"]:
                with self.subTest(lang=lang, phrase=phrase):
                    parsed = parser.parse(Report("test", 0, Channel.WHATSAPP, phrase, lang=lang), zones)
                    self.assertEqual(parsed["zone"], "stage_2")

    def test_telegram_stage_aliases_use_the_requested_stage(self) -> None:
        zones = {z: row["name"] for z, row in ZONES.items()}
        for phrase, expected in (("escenario", "front_pit"), ("ESCENARIO UNO", "front_pit"),
                                 ("escenario principal", "front_pit"), ("escenario dos", "stage_2"),
                                 ("escenario secundario", "stage_2"), ("secundario", "stage_2"),
                                 ("stage_2", "stage_2")):
            with self.subTest(phrase=phrase):
                self.assertEqual(match_zone(phrase, zones), expected)
        self.assertIsNone(match_zone("escenario dos", {"front_pit": "Escenario principal"}))


if __name__ == "__main__":
    unittest.main()
