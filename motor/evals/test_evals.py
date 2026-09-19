"""Pruebas de la batería de evals. No toca módulos ajenos.

    python3 -m unittest motor.evals.test_evals -v
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from motor.evals.common import EvalResult, fail_ex, iter_heldout, select_cases
from motor.evals.report import render_md, to_payload
from motor.evals.conversation import play, SCRIPTS
from motor.evals.platform import run as run_platform


class TestSchema(unittest.TestCase):
    def test_eval_result_fields(self):
        e = EvalResult(id="x", description="d", suite="s", n=3, passed=2,
                       failures=[fail_ex(1, "c-h000000", "ejemplo")])
        d = e.to_dict()
        for k in ("id", "descripcion", "n", "aprobados", "fallos", "ejemplos", "simulacion"):
            self.assertIn(k, d)
        self.assertTrue(d["simulacion"])
        self.assertEqual(d["fallos"], 1)
        self.assertEqual(d["ejemplos"][0]["seed"], 1)
        self.assertEqual(d["ejemplos"][0]["caso"], "c-h000000")

    def test_informe_starts_with_table_and_failures_section(self):
        e_ok = EvalResult(id="ok", description="pasa", suite="seguridad", n=2, passed=2)
        e_bad = EvalResult(id="bad", description="falla", suite="seguridad", n=2, passed=1,
                           failures=[fail_ex(1, "c-x", "roto")])
        md = render_md(to_payload([e_ok, e_bad], rapido=True, wall_s=0.1))
        self.assertIn("| id | suite | N | aprobados | fallos |", md)
        idx_fail = md.index("## Lo que falla hoy")
        idx_ok = md.index("`ok`")
        self.assertLess(idx_fail, md.index("## 1."))
        self.assertIn("c-x", md[idx_fail:])
        self.assertIn("simulación", md.lower())


class TestHeldoutSeed(unittest.TestCase):
    def test_heldout_seed_1_is_deterministic(self):
        a = [c["id"] for c in iter_heldout(3)]
        b = [c["id"] for c in iter_heldout(3)]
        self.assertEqual(a, b)
        self.assertTrue(all(c.get("split") == "heldout" for c in iter_heldout(2)))

    def test_select_cases_has_n_and_seed(self):
        cases = select_cases(n=4, scan=20)
        self.assertEqual(len(cases), 4)
        self.assertTrue(all("id" in c and "seed" in c for c in cases))


class TestConversationScript(unittest.TestCase):
    def test_rcp_first_turn(self):
        sc = next(s for s in SCRIPTS if s["id"] == "conv-parada-rcp")
        played = play(sc)
        self.assertTrue(played["turns"])
        inst = played["turns"][0].instruction
        self.assertIsNotNone(inst)
        self.assertIn("cpr", inst["id"])
        self.assertLessEqual(played["questions"], 5)
        self.assertTrue(all(t.say.count("?") <= 1 for t in played["turns"]))


class TestPlatformReadOnly(unittest.TestCase):
    def test_quotes_written_numbers_only(self):
        evals = run_platform()
        ids = {e.id for e in evals}
        self.assertIn("P-mapa-evals", ids)
        mapa = next(e for e in evals if e.id == "P-mapa-evals")
        if mapa.n and mapa.passed:
            self.assertEqual(mapa.extra.get("aprobados_documentados"), 26)
            self.assertEqual(mapa.extra.get("n_casos_documentados"), 32)


class TestRapidoSmoke(unittest.TestCase):
    def test_rapido_writes_files_under_60s(self):
        from motor.evals import run
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            t0 = __import__("time").perf_counter()
            result = run(rapido=True, out_dir=out)
            elapsed = __import__("time").perf_counter() - t0
            self.assertLess(elapsed, 60.0, f"--rapido tardó {elapsed:.1f}s")
            self.assertTrue((out / "informe.md").is_file())
            self.assertTrue((out / "resultados.json").is_file())
            payload = json.loads((out / "resultados.json").read_text(encoding="utf-8"))
            self.assertTrue(payload["simulacion"])
            self.assertGreaterEqual(len(payload["evals"]), 6)
            for e in payload["evals"]:
                for k in ("id", "descripcion", "n", "aprobados", "fallos"):
                    self.assertIn(k, e)
                for ex in e.get("ejemplos") or []:
                    self.assertIn("seed", ex)
                    self.assertIn("caso", ex)
            md = (out / "informe.md").read_text(encoding="utf-8")
            self.assertIn("## Lo que falla hoy", md)
            self.assertIn("| id | suite | N | aprobados | fallos |", md)
            self.assertIn("simulación", md.lower())
            self.assertEqual(result["payload"]["suma_n"], sum(e["n"] for e in payload["evals"]))
            self.assertLess(payload["wall_s"], 60.0)


if __name__ == "__main__":
    unittest.main()
