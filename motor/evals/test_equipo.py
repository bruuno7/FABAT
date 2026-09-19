"""Equipo que generaliza: prompts, banco, episodios, aprendizaje día 1→2, CLI.

python3 -m unittest motor.evals.test_equipo -v
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from motor.evals.escenarios_diversos import REQUIRED_TAGS, todos


def _prompt_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "happyrobot" / "equipo"


class TestPromptsGeneralizan(unittest.TestCase):
    def test_cada_agente_tiene_principios_y_el_mismo_esquema(self) -> None:
        names = ("triaje", "prioridad", "recursos", "avisos", "vigia", "critico", "equipo")
        for name in names:
            text = (_prompt_dir() / f"{name}.md").read_text(encoding="utf-8")
            self.assertIn("Vida primero", text, name)
            self.assertIn("irreversible", text.lower(), name)
            self.assertIn("información incompleta", text.lower(), name)
            self.assertIn("QUEDAN", text, name)
            self.assertIn("esperando", text.lower(), name)
            self.assertIn("UNA", text, name)
            self.assertIn("vigilar", text.lower(), name)
            self.assertIn("recomendación", text.lower(), name)
            self.assertIn('"agente"', text, name)
            self.assertIn("```json", text, name)

    def test_plataforma_conserva_claves_json(self) -> None:
        md = (_prompt_dir() / "EQUIPO-AGENTES.md").read_text(encoding="utf-8")
        for clave in ('"clasificacion"', '"cola"', '"asignaciones"', '"veredicto"', '"sigue_valido"'):
            self.assertIn(clave, md)
        self.assertIn("PRINCIPIOS", md)


class TestBancoEscenarios(unittest.TestCase):
    def test_al_menos_40_y_cubre_el_pliego(self) -> None:
        bank = todos()
        self.assertGreaterEqual(len(bank), 40, len(bank))
        tags = {t for e in bank for t in e.get("tags") or ()}
        missing = REQUIRED_TAGS - tags
        self.assertFalse(missing, missing)
        recintos = {e.get("recinto") for e in bank}
        self.assertTrue({"festival", "deporte", "feria", "edificio"} <= recintos, recintos)
        self.assertTrue(any(e.get("heldout_id") for e in bank))
        ids = [e["id"] for e in bank]
        self.assertEqual(len(ids), len(set(ids)))


class TestAprendizajeVisible(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = str(Path(self.tmp.name) / "eval.db")
        self.env = patch.dict(os.environ, {
            "MANDO_DB": self.db, "TELEGRAM_MODE": "off", "MANDO_LLM": "0",
        }, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_episodio_guarda_visto_razonado_y_final(self) -> None:
        from motor.evals.equipo import correr_uno
        from motor.evals.escenarios_diversos import por_id

        esc = por_id("d-incendio-restauracion")
        run = correr_uno(esc, fake=True)
        self.assertTrue(run["ok"], run)
        epis = run["episodios_completos"]
        nombres = {e.get("agente") for e in epis}
        for name in ("triaje", "prioridad", "recursos", "avisos", "vigia", "critico"):
            self.assertIn(name, nombres, nombres)
        for e in epis:
            self.assertTrue(e.get("entrada"), e.get("agente"))
            self.assertTrue(e.get("contexto"), e.get("agente"))
            self.assertTrue(e.get("razonamiento") or (e.get("decision") or {}).get("porque"), e.get("agente"))
            self.assertTrue(e.get("resultado") is not None, e.get("agente"))

    def test_leccion_aprobada_cambia_y_rechazada_no_y_se_revoca(self) -> None:
        from motor.evals.aprende import dia, proponer_y_aplicar
        from motor.evals.escenarios_diversos import por_id

        esc = por_id("d-incendio-restauracion")
        d1 = dia([esc], fake=True, etiqueta="dia1")
        self.assertEqual(d1["n"], 1)
        rec1 = set(d1["corridas"][0]["recursos_agente"])
        self.assertTrue(any(r.startswith("tech") for r in rec1), rec1)
        self.assertFalse(any(r.startswith("sec") for r in rec1), rec1)

        props = proponer_y_aplicar(d1, aprobar=("incendio",), rechazar=("voluntario",), by="test")
        self.assertTrue(props["aprobadas"], props)
        self.assertTrue(any("técnico" in (x["texto"] + " " + x.get("texto", "")).lower()
                            or "tecnico" in x["texto"].lower() for x in props["propuestas"]), props)
        self.assertTrue(all(x.get("evidencia", {}).get("ids") for x in props["propuestas"]), props)
        self.assertTrue(all((x.get("evidencia") or {}).get("n") for x in props["propuestas"]), props)

        d2 = dia([esc], fake=True, etiqueta="dia2")
        rec2 = set(d2["corridas"][0]["recursos_agente"])
        self.assertTrue(any(r.startswith("tech") for r in rec2), rec2)
        self.assertTrue(any(r.startswith("sec") for r in rec2), rec2)
        self.assertNotEqual(rec1, rec2)

        from motor.evals.aprende import revocar, session_eval
        s = session_eval()
        try:
            for lid in props["aprobadas"]:
                revocar(s, lid, by="test")
        finally:
            s.close()

        d3 = dia([esc], fake=True, etiqueta="dia3")
        rec3 = set(d3["corridas"][0]["recursos_agente"])
        self.assertFalse(any(r.startswith("sec") for r in rec3), rec3)

    def test_demo_imprime_el_arco_completo(self) -> None:
        from motor.evals.aprende import demo
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            out = demo()
        text = buf.getvalue()
        self.assertTrue(out["cambio"], out)
        for needle in ("DÍA 1", "LECCIÓN", "evidencia", "APROBADA", "DÍA 2", "distinta"):
            self.assertIn(needle, text, text)
        self.assertGreaterEqual(out["n_dia1"], 1)
        self.assertGreaterEqual(out["n_dia2"], 1)

    def test_banco_dia1_dia2_cambia_con_n(self) -> None:
        from motor.evals.aprende import aprender_banco
        from motor.evals.escenarios_diversos import todos

        bank = todos(40)
        out = aprender_banco(bank, fake=True, by="test")
        self.assertEqual(out["n"], 40)
        self.assertTrue(out["cambio"], out)
        self.assertTrue(any(c["id"] == "d-incendio-restauracion" for c in out["cambios"]), out["cambios"])
        self.assertTrue(out["aprobadas"], out["propuestas"])
        for p in out["propuestas"]:
            self.assertTrue((p.get("evidencia") or {}).get("ids"))
            self.assertGreaterEqual((p.get("evidencia") or {}).get("n") or 0, 1)
        incendio = next(c for c in out["cambios"] if c["id"] == "d-incendio-restauracion")
        self.assertTrue(any(str(r).startswith("tech") for r in incendio["rec1"]), incendio)
        self.assertFalse(any(str(r).startswith("sec") for r in incendio["rec1"]), incendio)
        self.assertTrue(any(str(r).startswith("sec") for r in incendio["rec2"]), incendio)
        if out["empeora"]:
            self.assertTrue(out["regresiones"] or not out["mejora"])


class TestCliDispatch(unittest.TestCase):
    def test_main_reconoce_subcomandos(self) -> None:
        from motor.evals import main
        with tempfile.TemporaryDirectory() as tmp:
            env = patch.dict(os.environ, {
                "MANDO_DB": str(Path(tmp) / "e.db"), "TELEGRAM_MODE": "off", "MANDO_LLM": "0",
            }, clear=False)
            env.start()
            try:
                code = main(["aprende", "--demo"])
                self.assertEqual(code, 0)
                code = main(["equipo", "--n", "3", "--fake", "--out", tmp])
                self.assertEqual(code, 0)
                informe = Path(tmp) / "equipo-agentes.md"
                self.assertTrue(informe.is_file(), informe)
            finally:
                env.stop()


if __name__ == "__main__":
    unittest.main()
