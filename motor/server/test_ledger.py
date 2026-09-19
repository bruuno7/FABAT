"""Ledger SQLite: persistencia de episodios tras reinicio y conteos."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from .test_server import SECRET


class LedgerUnitTest(unittest.TestCase):
    def test_open_session_event_episode_and_stats(self):
        from .ledger import Ledger
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.sqlite"
            led = Ledger(path)
            self.addCleanup(led.close)
            self.assertTrue(led.enabled, led.warning)
            led.session_start("s-1", case_id="demo-1", voice_mode="phone", speed=1.0, comms_mode="happyrobot")
            led.append_event("s-1", "send_real", "a1", {"kind": "dispatch", "to_number": "+34600000099"})  # revisor: ok teléfono inventado para el test del scrub
            led.upsert_episode("s-1", "a1", kind="dispatch", zone="gate_b", resource="med_1",
                               real=True, result="accept", eta_min=5, text="Afirmativo. +34600000099")  # revisor: ok teléfono inventado para el test del scrub
            st = led.stats()
            self.assertEqual(st["sessions"], 1)
            self.assertEqual(st["events"], 1)
            self.assertEqual(st["episodes"], 1)
            self.assertEqual(st["real_ok"], 1)
            self.assertEqual(st["by_kind"].get("dispatch"), 1)
            # Privacidad: el payload no guarda to_number
            import sqlite3
            con = sqlite3.connect(path)
            try:
                row = con.execute("SELECT payload_json FROM events").fetchone()[0]
                self.assertNotIn("+34600000099", row)  # revisor: ok teléfono inventado para el test del scrub
                self.assertNotIn("to_number", row)
                text = con.execute("SELECT text_scrubbed FROM episodes").fetchone()[0]
                self.assertIn("teléfono oculto", text)
            finally:
                con.close()
            led.close()

    def test_persists_after_reopen(self):
        from .ledger import Ledger
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.sqlite"
            a = Ledger(path)
            a.session_start("s-persist")
            a.upsert_episode("s-persist", "ep-9", kind="dispatch", real=True, result="accept")
            a.close()
            b = Ledger(path)
            self.assertTrue(b.enabled)
            st = b.stats()
            self.assertEqual(st["episodes"], 1)
            self.assertEqual(st["real_ok"], 1)
            b.close()

    def test_degrades_when_path_not_writable(self):
        from .ledger import Ledger
        # Fichero que no se puede crear como directorio padre inexistente bajo un "archivo"
        with tempfile.TemporaryDirectory() as tmp:
            blocker = Path(tmp) / "not_a_dir"
            blocker.write_text("x", encoding="utf-8")
            led = Ledger(blocker / "nested" / "ledger.sqlite")
            self.assertFalse(led.enabled)
            led.session_start("s")
            led.append_event("s", "send_real", "a")
            self.assertEqual(led.stats()["episodes"], 0)


class LedgerCommsIntegrationTest(unittest.TestCase):
    def test_send_real_and_result_writes_episode_surviving_close(self):
        from .app import Session, load_case
        from .ledger import Ledger
        from motor.contracts import Action, ActionKind
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.sqlite"
            env = {
                "MANDO_VOICE_MODE": "phone",
                "HR_API_KEY": "fake-key",
                "HR_SECRET": SECRET,
                "HR_HOOK_DISPATCH": "http://127.0.0.1:1/hook",
                "MANDO_ALLOWED_NUMBERS": "+34600000002",  # revisor: ok teléfono inventado para el test de integración
                "MANDO_HR_PHONE_KINDS": "dispatch,recall,resupply",
                "MANDO_HR_MAX_INFLIGHT": "2",
                "MANDO_LEDGER_PATH": str(path),
            }
            with patch.dict(os.environ, env, clear=True):
                s = Session(load_case("demo-1"), threaded=False, comms_mode="happyrobot")
                self.addCleanup(s.close)
                self.assertTrue(s.ledger.enabled, s.ledger.warning)
                r = next(iter(s.world.resources.values()))
                s.comms.contacts = {"resources": {r.id: {"to_number": "+34600000002", "title": "Resp"}}, "roles": {}}  # revisor: ok teléfono inventado para el test de integración
                with patch.object(s.comms, "_post"):
                    a = Action("d-ledger", ActionKind.DISPATCH, s.world.t, resource=r.id, zone="gate_b",
                               params={"message": "Ve a B"})
                    s.comms.send(a, r)
                    self.assertTrue(s.comms.calls[a.id]["real"])
                    wire = s.comms.wire_payload(a.id)["action_id"]
                    s.comms.on_event({
                        "type": "dispatch_result",
                        "action_id": wire,
                        "session_id": s.session_id,
                        "result": "accept",
                        "eta_min": 4,
                        "event_id": "ev-ledger-1",
                    })
                    # poll cierra vía _track_result (upsert idempotente; sin segundo evento result)
                    s.comms.poll(s.world.t)
                st = s.ledger.stats()
                self.assertGreaterEqual(st["events"], 1)
                self.assertEqual(st["episodes"], 1)
                self.assertEqual(st["real_ok"], 1)
                s.close()
                # Reinicio: otro proceso / otro handle sobre el mismo fichero
                again = Ledger(path)
                self.assertEqual(again.stats()["episodes"], 1)
                self.assertEqual(again.stats()["real_ok"], 1)
                again.close()

    def test_sim_send_closes_episode_with_t_and_seed(self):
        """SimComms vía HappyRobotComms debe dejar episodio real=0 con t y seed."""
        from .app import Session, load_case
        from motor.contracts import Action, ActionKind
        import sqlite3
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.sqlite"
            with patch.dict(os.environ, {"MANDO_LEDGER_PATH": str(path), "TELEGRAM_MODE": "off"}, clear=True):
                s = Session(load_case("demo-1"), threaded=False, comms_mode="sim")
                try:
                    r = next(iter(s.world.resources.values()))
                    a = Action("sim-ep-1", ActionKind.DISPATCH, s.world.t, resource=r.id, zone="gate_b",
                               params={"message": "Ve a B"})
                    s.comms.send(a, r)
                    found = []
                    for _ in range(10):
                        s.world.step()
                        found = s.comms.poll(s.world.t)
                        if found:
                            break
                    self.assertTrue(found, "SimComms no devolvió resultado")
                    st = s.ledger.stats()
                    self.assertEqual(st["episodes"], 1)
                    con = sqlite3.connect(path)
                    try:
                        row = con.execute(
                            "SELECT real, result, t, seed FROM episodes WHERE action_id=?", ("sim-ep-1",)
                        ).fetchone()
                    finally:
                        con.close()
                    self.assertIsNotNone(row)
                    self.assertEqual(row[0], 0)
                    self.assertTrue(row[1])
                    self.assertIsNotNone(row[2])
                    self.assertEqual(row[3], s.world.seed)
                    self.assertGreaterEqual(st["events"], 1)
                finally:
                    s.close()

    def test_default_path_under_unittest_avoids_production(self):
        from . import ledger as ledger_mod
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("MANDO_LEDGER_PATH", None)
            p = ledger_mod.default_path()
            self.assertIn("mando-ledger-test-", str(p))
            self.assertNotIn(str(Path("motor") / "server" / "data"), str(p))


class LedgerExportTest(unittest.TestCase):
    def test_export_merges_contacts_into_memory_day1(self):
        from .ledger import Ledger
        from motor.mando.memory import OperationalMemory
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "ledger.sqlite"
            mem = Path(tmp) / "memory.day1.json"
            led = Ledger(db)
            led.session_start("s-x")
            led.upsert_episode("s-x", "a1", kind="dispatch", resource="med_1", resource_kind="medic",
                               real=True, result="accept", eta_min=3)
            led.upsert_episode("s-x", "a2", kind="dispatch", resource="med_1", resource_kind="medic",
                               real=True, result="no_answer", fell_back=True)
            out = led.export_to_memory(mem, merge=False)
            self.assertTrue(out["ok"])
            self.assertEqual(out["n_episodes"], 2)
            data = OperationalMemory.load(mem)
            ch = data.data["contacts"]["med_1"]["channels"]["voice"]
            self.assertEqual(ch["sent"], 2)
            self.assertEqual(ch["accept"], 1)
            self.assertEqual(ch["no_answer"], 1)
            self.assertEqual(data.data["contacts"]["med_1"]["kind"], "medic")
            # merge suma otra vez
            out2 = led.export_to_memory(mem, merge=True)
            self.assertEqual(out2["n_episodes"], 2)
            data2 = OperationalMemory.load(mem)
            self.assertEqual(data2.data["contacts"]["med_1"]["channels"]["voice"]["sent"], 4)
            led.close()

    def test_cli_stats_and_export(self):
        from . import ledger as ledger_mod
        import io
        from contextlib import redirect_stdout
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "l.sqlite"
            mem = Path(tmp) / "m.json"
            led = ledger_mod.Ledger(db)
            led.upsert_episode("s", "e1", kind="dispatch", resource="r1", resource_kind="sec",
                               real=True, result="accept")
            led.close()
            buf = io.StringIO()
            with redirect_stdout(buf), patch.dict(os.environ, {"MANDO_LEDGER_PATH": str(db)}, clear=False):
                rc = ledger_mod.main(["stats", "--path", str(db)])
                self.assertEqual(rc, 0)
                rc = ledger_mod.main(["export", "--path", str(db), "--memory", str(mem), "--no-merge"])
                self.assertEqual(rc, 0)
            self.assertTrue(mem.exists())


class DoctorLedgerTest(unittest.TestCase):
    def test_doctor_reports_ledger(self):
        from . import doctor
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.sqlite"
            env = {"MANDO_LEDGER_PATH": str(path), "TELEGRAM_MODE": "off"}
            with patch.dict(os.environ, env, clear=False):
                d = doctor.diagnosticar(sondear_red=False, env={**os.environ, **env})
            keys = [c.clave for c in d.comprobaciones]
            self.assertIn("ledger.sqlite", keys)
            row = next(c for c in d.comprobaciones if c.clave == "ledger.sqlite")
            self.assertEqual(row.estado, "ok")


if __name__ == "__main__":
    unittest.main()
