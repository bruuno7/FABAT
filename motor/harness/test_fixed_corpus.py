from __future__ import annotations

import copy
import unittest

from motor.harness.fixed_corpus import build_corpus, manifest


class FixedCorpusTests(unittest.TestCase):
    def test_generation_is_exact_and_deterministic(self) -> None:
        cases = build_corpus(30, seed=1, run_seed=100)
        self.assertEqual(cases, build_corpus(30, seed=1, run_seed=100))
        self.assertEqual(len(cases), 30)
        self.assertEqual(len({c["id"] for c in cases}), 30)
        self.assertEqual([c["seed"] for c in cases], list(range(100, 130)))
        self.assertTrue(all(c["split"] == "train" for c in cases))

    def test_manifest_rejects_short_corpus_instead_of_silently_lowering_n(self) -> None:
        with self.assertRaises(ValueError):
            manifest(build_corpus(2), 30, 1, False)
        with self.assertRaises(ValueError):
            build_corpus(0)

    def test_fingerprint_changes_when_case_content_changes(self) -> None:
        cases = build_corpus(2)
        before = manifest(cases, 2, 1, False)
        other = copy.deepcopy(cases)
        other[0]["duration_min"] += 1
        after = manifest(other, 2, 1, False)
        self.assertNotEqual(before["case_fingerprint"], after["case_fingerprint"])
        self.assertEqual(before["case_ids"], after["case_ids"])
        self.assertEqual(before["run_seeds"], after["run_seeds"])

    def test_demo_control_is_explicit_and_distinct_from_generated_cases(self) -> None:
        cases = build_corpus(30, run_seed=100, demo_clones=True)
        report = manifest(cases, 30, 1, True)
        self.assertEqual(report["corpus"], "explicit_demo_clones")
        self.assertEqual(report["case_fingerprint"], "f6280d711a6031ad")
        self.assertIsNone(report["generator_seed"])
        self.assertNotEqual(report["case_fingerprint"],
                            manifest(build_corpus(30), 30, 1, False)["case_fingerprint"])


if __name__ == "__main__":
    unittest.main()
