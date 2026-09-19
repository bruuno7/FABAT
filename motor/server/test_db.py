"""Persistencia histórica del estado público de MANDO."""
from __future__ import annotations

import csv
from contextlib import closing
import io
import json
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from motor.server.app import create_app
from motor.server.db import History, Recorder


def state(scene: str = "s-1", minute: int = 4, *, reserved: bool = False) -> dict:
    report_text = "(aviso reservado)" if reserved else "Persona mareada junto al escenario"
    incident_label = "Incidente reservado" if reserved else "Golpe de calor"
    return {
        "session": {"id": scene, "case": "demo-1", "seed": 7, "comms_mode": "sim", "done": False},
        "t": minute,
        "reports": [{"id": "r-1", "t": 1, "channel": "web", "source": "", "via": "web",
                     "text": report_text, "zone_hint": None if reserved else "general", "incident": "i-1",
                     "phone": "+34600111222", "unit_token": "token-no-guardar"}],
        "incidents": [{"id": "i-1", "family": "medical", "type": "reserved" if reserved else "heat_stroke",
                       "label": incident_label, "zone": None if reserved else "general", "severity": 7,
                       "priority": 8.5, "status": "assigned", "t_open": 1, "first_action_t": 2,
                       "reports": ["r-1"], "reserved": reserved}],
        "plans": [{"id": "p-1", "incident": "i-1", "version": 1, "objective": "Atender",
                   "why": "Riesgo térmico", "supersedes": None,
                   "assumptions": [{"id": "u-1", "text": "Pasillo norte transitable", "valid": True}],
                   "steps": ["a-1"]}],
        "actions": [{"id": "a-1", "incident": "i-1", "plan": "p-1", "t": 2, "kind": "dispatch",
                     "resource": "med_1", "zone": "general", "autonomy": "auto", "status": "executing",
                     "why": "Más cercano"}],
        "calls": {"calls": [{"action_id": "a-1", "incident": "i-1", "workflow": "dispatch",
                             "to": "Jefa sanitaria", "result": "accept", "text": "Acepta",
                             "t": 2, "t_end": 3, "turn_latency_ms": 280, "hr_run_id": "run-1"}]},
        "operators": {
            "presence": [{"operator": {"id": "op-1", "name": "Marta", "role": "sanitario"},
                          "incident": "i-1"}],
            "events": [{"seq": 1, "operator": {"id": "op-1", "name": "Marta", "role": "sanitario"},
                        "verb": "aprobación completada", "ref": "a-1", "t": 3, "real_s": 8.2,
                        "note": "Adelante"}],
        },
        "forecasts": [{"id": "f-1", "zone": "general", "metric": "density", "threshold": 4.0,
                       "eta_min": 9, "status": "CUMPLIDO", "created_t": 1}],
        "service_health": {"comms_down": {"voice": False}},
        "happyrobot": {"dispatch": {"state": "operativo", "latency_ms": 310}},
        "strikes": [{"id": "g-1", "t": 3, "label": "Ambulancia bloqueada", "origin": "jury",
                     "effect": {"kind": "resource_offline"}}],
        "log": [
            {"t": 2, "kind": "plan", "ref": "p-1", "text": "Plan creado", "data": {"incident": "i-1"}},
            {"t": 3, "kind": "staff_status", "ref": "r-2", "text": "Equipo en ruta",
             "unit_id": "med_1", "incident": "i-1", "status": "en_route", "zone": "general"},
        ],
    }


class DatabaseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "mando.db"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def record(self, *states: dict, queue_size: int = 16) -> Recorder:
        recorder = Recorder(self.path, queue_size=queue_size)
        for item in states:
            recorder.offer(item)
        recorder.close()
        return recorder

    def count(self, table: str) -> int:
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]

    def test_same_state_twice_is_idempotent_and_creates_full_schema(self) -> None:
        self.record(state(), state())
        expected = {"escenas", "avisos", "incidentes", "aviso_incidente", "planes", "supuestos",
                    "acciones", "llamadas", "decisiones", "previsiones", "partes_personal",
                    "operadores", "servicios_muestras", "golpes", "eventos"}
        with closing(sqlite3.connect(self.path)) as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertTrue(expected <= tables)
            self.assertGreater(db.execute("PRAGMA user_version").fetchone()[0], 0)
            self.assertEqual(db.execute("PRAGMA foreign_keys").fetchone()[0], 0)
        for table in expected - {"servicios_muestras", "eventos"}:
            self.assertEqual(self.count(table), 1, table)
        self.assertEqual(self.count("servicios_muestras"), 2)
        self.assertEqual(self.count("eventos"), 2)

    def test_history_survives_reopen_and_scenes_stay_separate(self) -> None:
        self.record(state("s-1"))
        self.record(state("s-2", 1))
        history = History(self.path)
        scenes = history.scenes()
        self.assertEqual({row["id"] for row in scenes}, {"s-1", "s-2"})
        self.assertEqual(history.incidents(scene="s-1")["total"], 1)
        self.assertEqual(history.incidents(scene="s-2")["items"][0]["escena_id"], "s-2")

    def test_failed_database_never_raises_or_blocks_offer(self) -> None:
        warnings: list[str] = []
        recorder = Recorder(Path(self.tmp.name), on_warning=warnings.append)
        started = time.monotonic()
        for _ in range(50):
            recorder.offer(state())
        elapsed = time.monotonic() - started
        recorder.close()
        self.assertLess(elapsed, 0.2)
        self.assertTrue(warnings)
        self.assertGreater(recorder.errors, 0)

    def test_reserved_and_secret_content_never_appears_in_database(self) -> None:
        self.record(state(reserved=True))
        raw = self.path.read_bytes()
        self.assertNotIn("600111222".encode(), raw)
        self.assertNotIn(b"token-no-guardar", raw)
        self.assertNotIn("Persona mareada".encode(), raw)
        self.assertIn("aviso reservado".encode(), raw)

    def test_fifty_offers_are_non_blocking_and_oldest_is_dropped(self) -> None:
        recorder = Recorder(self.path, queue_size=2)
        started = time.monotonic()
        for minute in range(50):
            recorder.offer(state(minute=minute))
        elapsed = time.monotonic() - started
        recorder.close()
        self.assertLess(elapsed, 0.2)
        self.assertGreater(recorder.dropped, 0)
        self.assertEqual(History(self.path).scenes()[0]["fin_min"], 49)

    def test_filters_pagination_and_sql_injection_in_q(self) -> None:
        other = state()
        other["incidents"] = [dict(other["incidents"][0], id="i-2", family="crowd", zone="gate_b",
                                   label="Presión en Puerta B", severity=9, status="resolved", t_open=6)]
        other["reports"] = []
        other["plans"] = []
        other["actions"] = []
        other["calls"] = {"calls": []}
        other["operators"] = {"presence": [], "events": []}
        other["forecasts"] = []
        other["strikes"] = []
        other["log"] = []
        self.record(state(), other)
        history = History(self.path)
        self.assertEqual(history.incidents(scene="s-1", family="medical")["total"], 1)
        self.assertEqual(history.incidents(scene="s-1", status="resolved", zone="gate_b")["total"], 1)
        self.assertEqual(history.incidents(scene="s-1", since=5, until=7)["items"][0]["id"], "i-2")
        self.assertEqual(history.incidents(scene="s-1", q="Puerta", page=1, size=1)["total"], 1)
        injected = history.incidents(scene="s-1", q="' OR 1=1 --")
        self.assertEqual(injected["total"], 0)
        self.assertEqual(self.count("incidentes"), 2)

    def test_detail_summary_and_exports_are_queryable(self) -> None:
        self.record(state())
        history = History(self.path)
        detail = history.incident("s-1", "i-1")
        self.assertEqual(detail["incident"]["id"], "i-1")
        for key in ("timeline", "plans", "calls", "decisions", "reports"):
            self.assertTrue(detail[key], key)
        summary = history.summary("s-1")
        self.assertEqual(summary["incidentes"]["n"], 1)
        self.assertEqual(summary["primera_accion_mediana_min"], {"value": 1.0, "n": 1})
        self.assertEqual(summary["llamadas"]["aceptadas"], 1)
        self.assertEqual(summary["previsiones_acertadas"], {"value": 1.0, "n": 1})
        exported = json.loads(history.export_json("s-1"))
        self.assertEqual(exported["scene"]["id"], "s-1")
        rows = list(csv.DictReader(io.StringIO(history.export_csv("s-1"))))
        self.assertEqual(rows[0]["id"], "i-1")

    def test_close_cannot_let_an_offer_fall_behind_stop_sentinel(self) -> None:
        entered = threading.Event()
        release = threading.Event()

        class SlowString:
            def __str__(self) -> str:
                entered.set()
                release.wait(2)
                return "dato"

        recorder = Recorder(self.path, queue_size=2)
        delayed = state("race")
        delayed["slow"] = SlowString()
        producer = threading.Thread(target=recorder.offer, args=(delayed,))
        closer = threading.Thread(target=recorder.close)
        producer.start()
        self.assertTrue(entered.wait(1))
        closer.start()
        time.sleep(0.02)
        release.set()
        producer.join(2)
        closer.join(2)
        self.assertFalse(producer.is_alive())
        self.assertFalse(closer.is_alive())
        self.assertEqual(History(self.path).scenes()[0]["id"], "race")

    def test_rollback_invalidates_difference_cache(self) -> None:
        recorder = Recorder(self.path)
        original = recorder._upsert
        failed = threading.Event()

        def fail_once(db, table, columns, values, conflict, *, scene, key, updates=None):
            if table == "avisos" and not failed.is_set():
                recorder._changed(scene, table, key, values)
                failed.set()
                raise sqlite3.OperationalError("fallo inyectado")
            return original(db, table, columns, values, conflict, scene=scene, key=key, updates=updates)

        recorder._upsert = fail_once
        recorder.offer(state())
        end = time.monotonic() + 2
        while not recorder.errors and time.monotonic() < end:
            time.sleep(0.01)
        self.assertEqual(recorder.errors, 1)
        recorder._upsert = original
        recorder.offer(state())
        recorder.close()
        self.assertEqual(self.count("incidentes"), 1)
        self.assertEqual(self.count("avisos"), 1)

    def test_close_flushes_every_state_already_accepted(self) -> None:
        recorder = Recorder(self.path, queue_size=2)
        original = recorder._record
        entered = threading.Event()
        release = threading.Event()

        def blocked(db, item):
            if item["session"]["id"] == "s-1" and not entered.is_set():
                entered.set()
                release.wait(2)
            return original(db, item)

        recorder._record = blocked
        recorder.offer(state("s-1"))
        self.assertTrue(entered.wait(1))
        recorder.offer(state("s-2"))
        recorder.offer(state("s-3"))
        closer = threading.Thread(target=recorder.close)
        closer.start()
        time.sleep(0.02)
        release.set()
        closer.join(2)
        self.assertFalse(closer.is_alive())
        self.assertEqual({row["id"] for row in History(self.path).scenes()}, {"s-1", "s-2", "s-3"})

    def test_export_is_not_limited_to_first_two_hundred_incidents(self) -> None:
        bulk = state()
        bulk["reports"] = []
        bulk["plans"] = []
        bulk["actions"] = []
        bulk["calls"] = {"calls": []}
        bulk["operators"] = {"presence": [], "events": []}
        bulk["forecasts"] = []
        bulk["strikes"] = []
        bulk["log"] = []
        bulk["incidents"] = [
            dict(bulk["incidents"][0], id=f"i-{number:03d}", reports=[]) for number in range(205)
        ]
        self.record(bulk)
        history = History(self.path)
        exported = json.loads(history.export_json("s-1"))
        self.assertEqual(len(exported["incidents"]), 205)
        for table in ("avisos", "aviso_incidente", "planes", "supuestos", "acciones", "llamadas",
                      "decisiones", "previsiones", "partes_personal", "operadores",
                      "servicios_muestras", "golpes", "eventos"):
            self.assertIn(table, exported)
        self.assertEqual(len(list(csv.DictReader(io.StringIO(history.export_csv("s-1"))))), 205)
        with self.assertRaises(KeyError):
            history.export_csv("no-existe")

    def test_incident_timeline_treats_id_wildcards_literally(self) -> None:
        payload = state()
        payload["incidents"].append(dict(payload["incidents"][0], id="ix1", reports=[]))
        payload["log"] = [
            {"t": 2, "kind": "plan", "ref": "p-a", "text": "Solo i_1", "data": {"incident": "i_1"}},
            {"t": 3, "kind": "plan", "ref": "p-b", "text": "Solo ix1", "data": {"incident": "ix1"}},
        ]
        payload["incidents"][0]["id"] = "i_1"
        payload["reports"][0]["incident"] = "i_1"
        payload["plans"][0]["incident"] = "i_1"
        payload["actions"][0]["incident"] = "i_1"
        payload["calls"]["calls"][0]["incident"] = "i_1"
        self.record(payload)
        timeline = History(self.path).incident("s-1", "i_1")["timeline"]
        self.assertEqual([item["texto"] for item in timeline], ["Solo i_1"])

    def test_terminal_action_keeps_its_first_end_minute(self) -> None:
        finished = state(minute=4)
        finished["actions"][0]["status"] = "done"
        later = state(minute=10)
        later["actions"][0]["status"] = "done"
        self.record(finished, later)
        with closing(sqlite3.connect(self.path)) as db:
            end = db.execute("SELECT fin_min FROM acciones WHERE escena_id=? AND id=?",
                             ("s-1", "a-1")).fetchone()[0]
        self.assertEqual(end, 4)

    def test_json_export_builds_summary_from_same_read_snapshot(self) -> None:
        self.record(state())
        history = History(self.path)

        def separate_summary(_scene):
            raise AssertionError("export_json no debe abrir otra instantánea para el resumen")

        history.summary = separate_summary
        exported = json.loads(history.export_json("s-1"))
        self.assertEqual(exported["summary"]["incidentes"]["n"], 1)


class DatabaseApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "api.db"
        self.env = patch.dict("os.environ", {"MANDO_DB": str(self.path), "TELEGRAM_MODE": "off"})
        self.env.start()
        self.app = create_app("demo-gates", threaded=False, local_params=False)
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.app.state.session.close()
        self.app.state.chat.stop()
        self.app.state.simulacro.close()
        self.env.stop()
        self.tmp.cleanup()

    def wait_recorded(self) -> None:
        end = time.monotonic() + 2
        while time.monotonic() < end:
            try:
                if History(self.path).scenes():
                    return
            except (sqlite3.Error, RuntimeError):
                pass
            time.sleep(0.01)
        self.fail("el estado inicial no llegó al historial")

    def test_app_records_state_serves_page_routes_and_exports(self) -> None:
        self.app.state.session.tick()
        self.wait_recorded()
        self.assertEqual(self.client.get("/historial").status_code, 200)
        scenes = self.client.get("/api/historial/escenas")
        self.assertEqual(scenes.status_code, 200, scenes.text)
        scene = scenes.json()["items"][0]["id"]
        self.assertEqual(self.client.get("/api/historial/incidentes", params={"escena": scene}).status_code, 200)
        self.assertEqual(self.client.get("/api/historial/decisiones", params={"escena": scene}).status_code, 200)
        self.assertEqual(self.client.get("/api/historial/recursos", params={"escena": scene}).status_code, 200)
        self.assertEqual(self.client.get("/api/historial/servicios", params={"escena": scene}).status_code, 200)
        self.assertEqual(self.client.get("/api/historial/resumen", params={"escena": scene}).status_code, 200)
        exported = self.client.get("/api/historial/export.json", params={"escena": scene})
        self.assertEqual(exported.status_code, 200, exported.text)
        self.assertIn("attachment", exported.headers["content-disposition"])
        self.assertEqual(self.client.get("/api/historial/export.csv", params={"escena": scene}).status_code, 200)

    def test_reset_closes_old_scene_and_opens_new_one(self) -> None:
        self.wait_recorded()
        old = self.app.state.session.session_id
        response = self.client.post("/api/control", json={"cmd": "reset"})
        self.assertEqual(response.status_code, 200, response.text)
        new = response.json()["session"]["id"]
        self.assertNotEqual(old, new)
        end = time.monotonic() + 2
        while time.monotonic() < end:
            scenes = {row["id"]: row for row in History(self.path).scenes()}
            if old in scenes and new in scenes:
                break
            time.sleep(0.01)
        self.assertIn(old, scenes)
        self.assertIn(new, scenes)
        self.assertIsNotNone(scenes[old]["fin"])

    def test_history_is_operator_only_when_server_is_public(self) -> None:
        self.app.state.session.close()
        self.app.state.chat.stop()
        self.app.state.simulacro.close()
        with patch.dict("os.environ", {"MANDO_PUBLIC_URL": "https://test.invalid",
                                        "MANDO_OPERATOR_TOKEN": "operator-test"}):
            app = create_app("demo-gates", threaded=False, local_params=False)
            client = TestClient(app, base_url="https://test.invalid")
            try:
                self.assertEqual(client.get("/historial").status_code, 401)
                self.assertEqual(client.get("/api/historial/escenas").status_code, 401)
                self.assertEqual(client.get("/api/historial/escenas",
                                            headers={"X-Mando-Operator": "operator-test"}).status_code, 200)
            finally:
                app.state.session.close()
                app.state.chat.stop()
                app.state.simulacro.close()

    def test_broken_database_does_not_stop_clock_or_public_state(self) -> None:
        self.app.state.session.close()
        self.app.state.chat.stop()
        self.app.state.simulacro.close()
        with patch.dict("os.environ", {"MANDO_DB": self.tmp.name}):
            app = create_app("demo-gates", threaded=False, local_params=False)
            try:
                recorder = app.state.session.recorder
                end = time.monotonic() + 2
                while not recorder.errors and time.monotonic() < end:
                    time.sleep(0.01)
                self.assertGreater(recorder.errors, 0)
                app.state.session.tick()
                public = app.state.session.state()
                self.assertEqual(public["t"], 1)
                self.assertTrue(any(item.get("kind") == "database" for item in public["log"]))
            finally:
                app.state.session.close()
                app.state.chat.stop()
                app.state.simulacro.close()


if __name__ == "__main__":
    unittest.main()
