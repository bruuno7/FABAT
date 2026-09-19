"""Una sola SQLite: historial + ledger + episodios de agentes + lecciones."""
from __future__ import annotations

import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from motor.server.db import History, Recorder
from motor.server.ledger import Ledger
from motor.server.test_db import state


class MemoriaUnicaTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "mando.db"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_un_fichero_tiene_historial_ledger_agentes_y_lecciones(self) -> None:
        rec = Recorder(self.path)
        rec.offer(state())
        rec.close()
        led = Ledger(self.path)
        self.addCleanup(led.close)
        self.assertTrue(led.enabled, led.warning)
        led.session_start("s-1", case_id="demo-1")
        led.append_event(
            "s-1", "send_real", "a-1",
            {"kind": "dispatch", "to_number": "+34600000099"},  # revisor: ok teléfono inventado
            incidente_id="i-1", aviso_id="r-1", plan_id="p-1", accion_id="a-1", llamada_id="c-1",
        )
        led.upsert_episode("s-1", "a-1", kind="dispatch", zone="gate_b", resource="med_1",
                           real=True, result="accept")
        led.save_cerebro_episode(
            "s-1", "ce-triaje-1", tipo="crowd", zona="gate_b",
            razonamiento="aviso nuevo, no fusionar",
            decision={"prioridad": 6}, agente="triaje", confianza=0.8,
            supuestos=["La puerta B sigue abierta"],
        )
        led.upsert_leccion("L-1", "No desviar B hacia C saturada",
                           evidencia={"ids": ["ce-triaje-1"], "n": 1}, estado="propuesta")
        led.close()

        with closing(sqlite3.connect(self.path)) as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for name in ("escenas", "incidentes", "avisos", "planes", "acciones", "llamadas",
                         "eventos", "sessions", "events", "episodes", "cerebro_episodes",
                         "cerebro_lecciones"):
                self.assertIn(name, tables, name)
            self.assertGreaterEqual(int(db.execute("PRAGMA user_version").fetchone()[0]), 2)
            cols = {r[1] for r in db.execute("PRAGMA table_info(events)")}
            for col in ("aviso_id", "incidente_id", "plan_id", "accion_id", "llamada_id"):
                self.assertIn(col, cols, col)
            row = db.execute(
                "SELECT incidente_id, aviso_id, plan_id, accion_id, llamada_id, payload_json FROM events"
            ).fetchone()
            self.assertEqual(row[:5], ("i-1", "r-1", "p-1", "a-1", "c-1"))
            self.assertNotIn("+34600000099", row[5])  # revisor: ok teléfono inventado
            self.assertNotIn("to_number", row[5])
            agente, conf, sup = db.execute(
                "SELECT agente, confianza, supuestos_json FROM cerebro_episodes WHERE id=?",
                ("ce-triaje-1",),
            ).fetchone()
            self.assertEqual(agente, "triaje")
            self.assertEqual(conf, 0.8)
            self.assertIn("puerta B", sup)
            self.assertEqual(
                db.execute("SELECT estado, by_who FROM cerebro_lecciones WHERE id='L-1'").fetchone()[0],
                "propuesta",
            )

        self.assertEqual(History(self.path).incidents(scene="s-1")["total"], 1)
        led2 = Ledger(self.path)
        self.addCleanup(led2.close)
        casos = led2.search_cerebro(tipo="crowd", zona="gate_b")
        self.assertTrue(any(c["id"] == "ce-triaje-1" for c in casos), casos)
        self.assertEqual(casos[0].get("agente"), "triaje")

    def test_mando_db_es_la_ruta_unica(self) -> None:
        from motor.server import memoria_db
        with patch.dict("os.environ", {"MANDO_DB": str(self.path)}, clear=False):
            p = memoria_db.resolve_path()
        self.assertEqual(p, self.path)

    def test_si_la_base_falla_offer_no_lanza(self) -> None:
        rec = Recorder(Path(self.tmp.name))
        started = time.monotonic()
        rec.offer(state())
        rec.close()
        self.assertLess(time.monotonic() - started, 0.2)
        self.assertGreater(rec.errors, 0)
