"""Pruebas del generador de casos. Desde la raíz: python3 -m unittest motor.cases.test_cases -v"""
from __future__ import annotations

import json
import time
import unittest
from collections import Counter

from motor.cases.generator import (
    build_case, build_load_case, compute_difficulty, generate, generate_load, iter_cases, max_concurrent, signature,
    space_size, true_incidents,
)
from motor.cases.taxonomy import (
    DEMO_EXCLUDED_TYPES, FESTIVAL, HELDOUT_ONLY_CHAINS, INCIDENT_TYPES, NEIGHBORS, SENSITIVE_TYPES, SHOW_PHASES, TAXONOMY,
    TRAIN_EXCLUDED_FAMILY_PAIRS, ZONES, combo_universe, is_heldout_chain, parse_rule, phase_at,
)
from motor.cases.validate import validate_case
from motor.contracts import Family

N_TRAIN, N_HELDOUT = 3000, 1000


class CasesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.train = generate(N_TRAIN, seed=1, split="train")
        cls.heldout = generate(N_HELDOUT, seed=1, split="heldout")
        cls.demo = list(iter_cases(split="demo"))
        cls.load = generate_load(per_level=150, seed=1)

    # ---- taxonomía
    def test_taxonomy_size_and_families(self) -> None:
        self.assertGreaterEqual(len(TAXONOMY), 45)
        per_family = Counter(t.family for t in TAXONOMY.values())
        for fam in Family:
            self.assertGreaterEqual(per_family[fam], 5, f"familia {fam} con pocos tipos")
        for must_have in ("cardiac_arrest", "front_pit_critical_density", "ambulance_blocked_by_crowd", "team_no_answer",
                          "team_rejects", "all_busy_higher_priority", "chemical_submission", "lost_child", "suspicious_object",
                          "storm_structures", "power_outage_food", "cashless_down", "transport_cut_exit", "mass_entry_attempt",
                          "shift_end_no_relief"):
            self.assertIn(must_have, TAXONOMY)

    def test_suspicious_object_escalates_instead_of_deciding(self) -> None:
        t = TAXONOMY["suspicious_object"]
        self.assertTrue(t.approval)
        self.assertTrue(any(r.startswith("request_external police") and "with approval" in r for r in t.must))
        self.assertTrue(any(r.startswith("evacuate") and "without approval" in r for r in t.must_not))

    def test_rules_parse(self) -> None:
        r = parse_rule("dispatch medical to i2 within 3 min")
        self.assertEqual((r["verb"], r["target"], r["incident"], r["within"]), ("dispatch", "medical", "i2", 3))
        r = parse_rule("evacuate front_pit for i1 with approval")
        self.assertEqual((r["verb"], r["zone"], r["approval"]), ("evacuate", "front_pit", "with"))

    # ---- determinismo
    def test_deterministic_by_seed(self) -> None:
        again = generate(200, seed=1, split="train")
        self.assertEqual([json.dumps(c, sort_keys=True) for c in again],
                         [json.dumps(c, sort_keys=True) for c in self.train[:200]])
        self.assertEqual(build_case(1234, 1, "heldout"), build_case(1234, 1, "heldout"))
        other = generate(200, seed=2, split="train")
        self.assertNotEqual([c["events"] for c in other], [c["events"] for c in self.train[:200]])

    def test_iter_cases_start_matches_generate(self) -> None:
        self.assertEqual(list(iter_cases(seed=1, split="train", start=50, n=5)), self.train[50:55])

    # ---- formato
    def test_all_cases_validate(self) -> None:
        for case in self.train + self.heldout + self.demo + self.load:
            self.assertEqual(validate_case(case), [], case["id"])

    def test_validator_catches_errors(self) -> None:
        bad = json.loads(json.dumps(self.train[0]))
        bad["events"][0]["t"] = bad["duration_min"] + 5
        bad["initial"]["resources_offline"] = ["sec_99"]
        bad["events"].append({"t": 1, "kind": "world", "effect": {"kind": "meteorito"}})
        errors = " ".join(validate_case(bad))
        for needle in ("fuera de", "sec_99", "no admitido"):
            self.assertIn(needle, errors)

    def test_unique_ids_and_distinct_cases(self) -> None:
        ids = [c["id"] for c in self.train + self.heldout + self.demo]
        self.assertEqual(len(ids), len(set(ids)))
        bodies = {json.dumps(c["events"], sort_keys=True) for c in self.train}
        self.assertEqual(len(bodies), N_TRAIN)
        self.assertGreater(len({signature(c) for c in self.train}), 0.95 * N_TRAIN)

    # ---- partición
    def test_train_and_heldout_combos_disjoint(self) -> None:
        a = {tuple(x) for c in self.train for x in c["meta"]["combos"]}
        b = {tuple(x) for c in self.heldout for x in c["meta"]["combos"]}
        self.assertFalse(a & b)
        self.assertFalse(combo_universe("train") & combo_universe("heldout"))
        self.assertTrue(a <= combo_universe("train"))
        self.assertTrue(b <= combo_universe("heldout"))
        # Cobertura sistemática: la rueda pasa por todas las combinaciones de cada partición.
        self.assertEqual(a, combo_universe("train"))
        self.assertGreaterEqual(len(b) / len(combo_universe("heldout")), 0.9)

    def test_heldout_only_types_and_chains_never_in_train(self) -> None:
        held_types = {t.id for t in TAXONOMY.values() if t.heldout_only}
        self.assertGreaterEqual(len(held_types), 9)
        self.assertEqual({t.family for t in TAXONOMY.values() if t.heldout_only}, set(Family))
        train_types = {t for c in self.train for t in c["meta"]["types"]}
        self.assertFalse(train_types & held_types)
        train_chains = {tuple(l) for c in self.train for l in c["meta"]["chain"]}
        self.assertTrue(train_chains)
        self.assertFalse([l for l in train_chains if is_heldout_chain(*l)])
        heldout_chains = {tuple(l) for c in self.heldout for l in c["meta"]["chain"]}
        self.assertTrue(heldout_chains & HELDOUT_ONLY_CHAINS)
        self.assertTrue(held_types <= {t for c in self.heldout for t in c["meta"]["types"]})

    def test_family_pairs_excluded_from_train(self) -> None:
        for c in self.train:
            fams = set(c["families"])
            for pair in TRAIN_EXCLUDED_FAMILY_PAIRS:
                self.assertFalse(pair <= fams, c["id"])
        self.assertTrue(any(pair <= set(c["families"]) for c in self.heldout for pair in TRAIN_EXCLUDED_FAMILY_PAIRS))

    def test_demo_has_never_seen_case(self) -> None:
        self.assertTrue(8 <= len(self.demo) <= 12)
        unseen = [c for c in self.demo if c["meta"].get("never_seen")]
        self.assertEqual(len(unseen), 1)
        fams = set(unseen[0]["families"])
        self.assertGreaterEqual(sum(pair <= fams for pair in TRAIN_EXCLUDED_FAMILY_PAIRS), 2)
        train_sets = {frozenset(c["families"]) for c in self.train}
        self.assertNotIn(frozenset(fams), train_sets)

    # ---- cobertura y dificultad
    def test_coverage_all_families_and_types(self) -> None:
        both = self.train + self.heldout
        self.assertEqual({f for c in both for f in c["families"]}, {f.value for f in Family})
        seen = {t for c in both for t in c["meta"]["types"]}
        self.assertEqual(set(TAXONOMY) - seen, set())
        train_seen = {t for c in self.train for t in c["meta"]["types"]}
        self.assertEqual({t for t in INCIDENT_TYPES if not TAXONOMY[t].heldout_only} - train_seen, set())

    def test_dimensions_all_present(self) -> None:
        for key, size in (("phase", 4), ("weather", 4), ("info_quality", 6), ("resource_state", 6)):
            self.assertEqual(len({c["meta"][key] for c in self.train}), size, key)
        self.assertEqual({c["day"] for c in self.train}, {1, 2, 3})
        langs = Counter(r["lang"] for c in self.train for ev in c["events"] for r in ev.get("reports", []))
        self.assertEqual(set(langs), {"es", "en", "fr", "de", "pt"})
        self.assertGreater(langs["es"], langs["en"])
        self.assertGreater(langs["en"], langs["fr"])

    def test_difficulty_is_computed_and_not_degenerate(self) -> None:
        for split in (self.train, self.heldout):
            dist = Counter(c["difficulty"] for c in split)
            self.assertEqual(set(dist), {1, 2, 3, 4, 5})
            for level, count in dist.items():
                self.assertGreater(count / len(split), 0.05, f"nivel {level} casi vacío")
                self.assertLess(count / len(split), 0.45, f"nivel {level} acapara")
        for case in self.train[:300] + self.demo:
            self.assertEqual(compute_difficulty(case)[0], case["difficulty"])
        # Más incidentes simultáneos = más difícil, de media.
        by_n = {n: [c["difficulty"] for c in self.train if len(c["meta"]["combos"]) // len(c["meta"]["perturbations"]) == n] for n in (1, 3)}
        self.assertGreaterEqual(min(c["difficulty"] for c in self.load), 4)
        self.assertLess(sum(by_n[1]) / len(by_n[1]), sum(by_n[3]) / len(by_n[3]))

    def test_expected_rules_point_to_real_incidents(self) -> None:
        for case in self.train[:500]:
            self.assertIn("evacuate without approval", case["expected"]["must_not"])
            self.assertTrue(case["expected"]["must"], case["id"])

    # ---- coherencia con festival.json (fase 2)
    def test_zones_and_neighbors_come_from_festival(self) -> None:
        self.assertEqual(set(ZONES), {z["id"] for z in FESTIVAL["zones"]})
        self.assertIn("corridor_s", NEIGHBORS["medical_1"])
        self.assertIn("corridor_n", NEIGHBORS["medical_2"])
        for e in FESTIVAL["edges"]:
            self.assertIn(e["b"], NEIGHBORS[e["a"]])
            self.assertIn(e["a"], NEIGHBORS[e["b"]])

    def test_phase_matches_program_and_stop_show_only_during_show(self) -> None:
        self.assertEqual(phase_at(3, "23:50"), "egress")
        self.assertEqual(phase_at(3, "01:10"), "closed")
        self.assertEqual(phase_at(3, "18:00"), "concerts")
        for case in self.train + self.heldout + self.demo + self.load:
            self.assertEqual(phase_at(case["day"], case["start_hhmm"]), case["meta"]["phase"], case["id"])
            opened = {i["id"]: i["t_open"] for i in true_incidents(case)}
            for rule in case["expected"]["must"]:
                if rule.startswith("stop_show"):
                    t = opened[parse_rule(rule)["incident"]]
                    self.assertIn(phase_at(case["day"], case["start_hhmm"], t), SHOW_PHASES, case["id"])
        self.assertTrue(any(r.startswith("stop_show") for c in self.train for r in c["expected"]["must"]))
        bad = json.loads(json.dumps(next(c for c in self.demo if c["id"] == "c-d000008")))
        bad["start_hhmm"] = "23:50"  # día 2 a las 23:50 ya es salida: ni la fase ni el stop_show cuadran
        errors = " ".join(validate_case(bad))
        self.assertIn("el programa da 'egress'", errors)
        self.assertIn("no hay concierto que parar", errors)

    def test_demo_is_free_of_sensitive_content(self) -> None:
        self.assertEqual(SENSITIVE_TYPES, {"sexual_assault_report", "chemical_submission", "weapon_seen", "bomb_threat_call", "lost_child"})
        for case in self.demo:
            self.assertFalse({i["type"] for i in true_incidents(case)} & DEMO_EXCLUDED_TYPES, case["id"])
        unseen = next(c for c in self.demo if c["meta"].get("never_seen"))
        self.assertIn("staff_assaulted", unseen["meta"]["types"])
        self.assertTrue({"weather", "aggression"} <= set(unseen["families"]))
        bad = json.loads(json.dumps(self.demo[0]))
        bad["events"][0]["reports"][0]["text"] = "un tío ha sacado una navaja"
        self.assertTrue(any("contenido vetado" in e for e in validate_case(bad)))

    def test_sensitive_types_carry_discreet_protocol(self) -> None:
        for tid in SENSITIVE_TYPES:
            t = TAXONOMY[tid]
            self.assertTrue(any(r.startswith(("notify violet_point", "notify security_lead")) for r in t.must), tid)
            for rule in ("broadcast for {i}", "echo report_content of {i} to informant", "request_external police for {i} without approval"):
                self.assertIn(rule, t.must_not, tid)
            self.assertFalse(any(r.startswith("request_external") and "with approval" not in r for r in t.must), tid)
        self.assertTrue(any(tid in c["meta"]["types"] for c in self.train for tid in SENSITIVE_TYPES))

    # ---- carga simultánea (fase 2)
    def test_load_cases_shape(self) -> None:
        self.assertEqual(len(self.load), 600)
        self.assertEqual(len({c["id"] for c in self.load}), 600)
        per = Counter((c["meta"]["load"], c["meta"]["surprise_t"] is not None) for c in self.load)
        self.assertEqual(per, Counter({(lv, s): 75 for lv in (5, 6, 7, 8) for s in (False, True)}))
        kinds = Counter(c["meta"]["surprise_kind"] for c in self.load)
        self.assertGreater(kinds["incident"], 100)
        self.assertGreater(kinds["world"], 100)
        for c in self.load:
            m, sure = c["meta"], [i for i in true_incidents(c) if not i["conditional"]]
            fronts = [i for i in sure if m["window"][0] <= i["t_open"] <= m["window"][1]]
            self.assertTrue(10 <= m["window"][1] - m["window"][0] <= 15, c["id"])
            self.assertGreaterEqual(len(fronts), m["load"], c["id"])
            self.assertGreaterEqual(max_concurrent(c), m["load"] + (m["surprise_kind"] == "incident"), c["id"])
            self.assertEqual(m["max_concurrent"], max_concurrent(c))
            self.assertTrue(m["scarce_kinds"], c["id"])
            for k in m["scarce_kinds"]:
                self.assertGreater(m["demand"][k], m["supply"][k])
            self.assertGreaterEqual(m["distinct_families"], 4, c["id"])
            self.assertLessEqual(min(i["severity"] for i in sure), 5, c["id"])   # hay una tarea menor a la que quitarle el equipo
            self.assertGreaterEqual(max(i["severity"] for i in sure), 8, c["id"])  # y algo grave que no puede esperar
            self.assertTrue(any(r.startswith("recall lower_priority") for r in c["expected"]["must"]), c["id"])
            if m["surprise_t"] is not None:
                hits = [e for e in c["events"] if e["kind"] == "world" and e["t"] == m["surprise_t"]
                        and (e.get("tag") == "surprise" or e["effect"]["kind"] == "incident")]
                self.assertTrue(hits, c["id"])
                self.assertTrue(m["window"][0] < m["surprise_t"] <= m["window"][1], c["id"])
        self.assertGreater(sum(c["meta"]["distinct_families"] >= 5 for c in self.load) / 600, 0.95)

    def test_load_priority_is_scoreable(self) -> None:
        for c in self.load + self.demo:
            exp, sev = c["expected"], {i["id"]: i["severity"] for i in true_incidents(c)}
            self.assertEqual([i for tier in exp["priority_tiers"] for i in tier], exp["priority"])
            order = [sev[i] for i in exp["priority"]]
            self.assertEqual(order, sorted(order, reverse=True), c["id"])
            for a, b in zip(exp["priority_tiers"], exp["priority_tiers"][1:]):
                self.assertGreater(min(sev[i] for i in a), max(sev[i] for i in b), c["id"])
            self.assertTrue(set(exp["may_wait"]) <= set(exp["priority_tiers"][-1]))
        self.assertTrue(all(c["expected"]["may_wait"] for c in self.load))

    def test_load_respects_partition_and_is_deterministic(self) -> None:
        self.assertEqual(Counter(c["split"] for c in self.load), Counter({"train": 400, "heldout": 200}))
        held_types = {t.id for t in TAXONOMY.values() if t.heldout_only}
        for c in self.load:
            combos = {tuple(x) for x in c["meta"]["combos"]}
            self.assertTrue(combos <= combo_universe(c["split"]), c["id"])
            if c["split"] == "train":
                self.assertFalse(set(c["meta"]["types"]) & held_types, c["id"])
                self.assertFalse(any(pair <= set(c["families"]) for pair in TRAIN_EXCLUDED_FAMILY_PAIRS), c["id"])
        self.assertEqual(build_load_case(7, 1, "heldout", 8, True), build_load_case(7, 1, "heldout", 8, True))
        self.assertEqual(json.dumps(generate_load(8, 1)), json.dumps(generate_load(8, 1)))

    def test_demo_load_cases(self) -> None:
        six = [c for c in self.demo if c["meta"].get("load") == 6]
        self.assertEqual(len(six), 2)
        for c in six:
            self.assertEqual(c["meta"]["max_concurrent"], 6)
            self.assertIsNone(c["meta"]["surprise_t"])
        jury = next(c for c in six if c["meta"]["surprise_kind"] == "injected_by_person")
        self.assertGreaterEqual(len(jury["meta"]["surprise_menu"]), 4)
        self.assertFalse([e for e in jury["events"] if e.get("tag") == "surprise"])

    def test_cases_run_in_world(self) -> None:
        try:
            from motor.world import World
        except ImportError:
            self.skipTest("motor.world no está disponible")
        sample = self.demo + self.load[::10] + self.train[::40] + self.heldout[::20]
        for case in sample:
            world = World.from_case(case)
            self.assertEqual(world.observe().clock["show_phase"], case["meta"]["phase"], case["id"])
            while not world.done():
                world.step()
            truth = world.truth()
            self.assertFalse([x for x in truth["injected"] if x.get("error")], case["id"])
            sure = {i["id"] for i in true_incidents(case) if not i["conditional"]}
            self.assertTrue(sure <= set(truth["incidents"]), case["id"])

    # ---- tamaño y velocidad
    def test_space_is_large_and_generation_is_fast(self) -> None:
        self.assertGreater(space_size("train")["total"], 100_000 * 100)
        self.assertGreater(space_size("heldout")["total"], 100_000)
        t0 = time.perf_counter()
        n = sum(1 for _ in iter_cases(seed=9, split="train", n=5000))
        self.assertEqual(n, 5000)
        self.assertLess(time.perf_counter() - t0, 10.0)


if __name__ == "__main__":
    unittest.main()
