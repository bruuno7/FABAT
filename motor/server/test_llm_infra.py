"""Tests del factory LLM y del expediente Exa (sin gastar créditos reales)."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class LlmFactoryTest(unittest.TestCase):
    def test_off_without_key(self):
        from . import llm_parser_factory
        with patch.dict(os.environ, {"MANDO_LLM": "1", "AGENTES_LLM_KEY": "", "HELMCODE_API_KEY": ""}, clear=False):
            # clear partial: ensure keys empty
            os.environ.pop("AGENTES_LLM_KEY", None)
            os.environ.pop("HELMCODE_API_KEY", None)
            os.environ["MANDO_LLM"] = "1"
            ok, why = llm_parser_factory.llm_configured()
            self.assertFalse(ok)
            self.assertIsNone(llm_parser_factory.make_client())
            self.assertIsNone(llm_parser_factory.build_cascade_parser())

    def test_key_but_mando_llm_off(self):
        from . import llm_parser_factory
        with patch.dict(os.environ, {"MANDO_LLM": "0", "AGENTES_LLM_KEY": "fake-key-for-test"}, clear=False):
            ok, why = llm_parser_factory.llm_configured()
            self.assertFalse(ok)
            self.assertIn("MANDO_LLM", why)
            self.assertIsNone(llm_parser_factory.make_client())

    def test_cascade_with_mock_client(self):
        from . import llm_parser_factory
        from motor.contracts import Channel, Report
        from motor.mando.test_mando import real_zones
        with patch.dict(os.environ, {
            "MANDO_LLM": "1",
            "AGENTES_LLM_KEY": "fake",
            "AGENTES_LLM_BASE": "https://example.invalid/v1",
        }, clear=False):
            with patch.object(llm_parser_factory, "_chat", return_value='{"type":"fight","family":"aggression","zone":"gate_b","severity":7,"confidence":0.8}'):
                p = llm_parser_factory.build_cascade_parser()
                self.assertIsNotNone(p)
                # texto genérico → cae al LLM mock
                out = p.parse(Report("r", 0, Channel.SMS, "una cosa rarísima que nadie catalogó nunca jamás"),
                              real_zones())
                self.assertEqual(out["family"], "aggression")
                self.assertEqual(out["zone"], "gate_b")

    def test_doctor_mentions_llm(self):
        from . import doctor
        with patch.dict(os.environ, {"TELEGRAM_MODE": "off", "AGENTES_LLM_KEY": "", "MANDO_LLM": "0"}, clear=False):
            os.environ.pop("AGENTES_LLM_KEY", None)
            os.environ.pop("HELMCODE_API_KEY", None)
            d = doctor.diagnosticar(sondear_red=False, env={**os.environ})
        keys = [c.clave for c in d.comprobaciones]
        self.assertIn("MANDO_LLM / Helmcode", keys)


class ExaPitchTest(unittest.TestCase):
    def test_local_report_without_spending(self):
        from . import exa_pitch
        with patch.dict(os.environ, {"EXA_API_KEY": "", "EXA_RUN": ""}, clear=False):
            os.environ.pop("EXA_API_KEY", None)
            os.environ.pop("EXA_RUN", None)
            report = exa_pitch.run(live=False)
            self.assertFalse(report["live"])
            self.assertEqual(len(report["claims"]), 4)
            with tempfile.TemporaryDirectory() as tmp:
                path = exa_pitch.write_markdown(report, Path(tmp) / "fuentes-pitch.md")
                text = path.read_text(encoding="utf-8")
                self.assertIn("astroworld-2021", text)
                self.assertIn("solo local", text)


if __name__ == "__main__":
    unittest.main()
