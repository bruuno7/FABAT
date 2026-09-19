"""Pruebas del servidor. Desde la raíz del proyecto:

    uv run --project motor/server python -m unittest motor.server.test_server -v

Todo ocurre en 127.0.0.1: el «HappyRobot» es `mock_happyrobot` en un puerto libre.
"""
from __future__ import annotations

import json
import os
import socket
import tempfile
import threading
import time
import unittest

import uvicorn
from fastapi.testclient import TestClient

import httpx

from motor.server import regression_live, views
from motor.server.app import create_app
from motor.server.mock_happyrobot import create_mock

SECRET = "secreto-de-prueba"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Served:
    """Una app ASGI servida de verdad en 127.0.0.1 (hace falta para que el mock pueda devolver el webhook)."""

    def __init__(self, app, port: int) -> None:
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self) -> "Served":
        self.thread.start()
        for _ in range(100):
            if self.server.started:
                return self
            time.sleep(0.05)
        raise RuntimeError("el servidor de prueba no arranca")

    def __exit__(self, *exc) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=5)


def wait_for(cond, seconds: float = 8.0) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


class ServerTest(unittest.TestCase):
    def setUp(self) -> None:
        # threaded=False: el reloj solo avanza cuando la prueba lo pide (determinista)
        self.app = create_app("demo-gates", threaded=False, secret=SECRET)
        self.c = TestClient(self.app)

    def tearDown(self) -> None:
        self.app.state.session.close()

    def step(self, n: int = 1) -> dict:
        r = self.c.post("/api/control", json={"cmd": "step", "n": n})
        self.assertEqual(r.status_code, 200, r.text)
        return self.c.get("/api/state").json()

    def test_pages(self) -> None:
        for path in ("/", "/sala", "/centro", "/clasico", "/?escena=1", "/jurado", "/caos", "/informe", "/curva", "/duelo", "/llamada/abc",
                     "/static/app.js", "/static/style.css", "/static/plano.js", "/static/llamada.js", "/static/sala.js", "/static/sala.css"):
            r = self.c.get(path)
            self.assertEqual(r.status_code, 200, path)
        # `/` es la Sala de control; el centro de atención sigue entero en /centro y la vista técnica en /clasico.
        self.assertIn("Sala de control", self.c.get("/").text)
        self.assertIn('/static/sala.js', self.c.get("/").text)
        self.assertIn('href="/clasico"', self.c.get("/").text)
        self.assertEqual(self.c.get("/").text, self.c.get("/sala").text)
        self.assertIn("Atención de incidentes", self.c.get("/centro").text)
        self.assertIn('/static/centro.js', self.c.get("/centro").text)
        self.assertIn('href="/clasico"', self.c.get("/centro").text)
        self.assertIn("PLAN ACTUAL", self.c.get("/clasico").text)
        self.assertIn("break-overlay", self.c.get("/clasico").text)
        self.assertIn('href="/centro"', self.c.get("/clasico").text)
        self.assertNotIn('id="channel"', self.c.get("/jurado").text, "fuera el selector de canal falso")
        self.assertTrue(self.c.get("/qr?path=/llamada/abc").headers["X-Jurado-Url"].endswith("/llamada/abc"))
        self.assertEqual(self.c.get("/qr?path=http://malo").status_code, 400)
        self.assertNotIn("http://", self.c.get("/").text.replace("http://www.w3.org", ""))  # sin CDNs
        qr = self.c.get("/qr")
        self.assertEqual(qr.status_code, 200)
        self.assertIn("<svg", qr.text)
        self.assertTrue(qr.headers["X-Jurado-Url"].endswith("/asistente"), "fase 3: el QR por defecto lleva a la app del asistente")
        self.assertTrue(self.c.get("/qr?path=/jurado").headers["X-Jurado-Url"].endswith("/jurado"))

    def test_state_ticks_and_stream(self) -> None:
        st = self.c.get("/api/state").json()
        self.assertEqual(st["session"]["case"], "demo-gates")
        self.assertEqual(len(st["zones"]), 17)
        self.assertEqual(st["t"], 0)
        for key in ("resources", "incidents", "plans", "approvals", "actions", "log", "metrics", "weather", "clock", "calls", "reports"):
            self.assertIn(key, st)
        self.assertNotIn("contact", st["resources"][0])  # los teléfonos no salen a la pantalla
        st = self.step(12)
        self.assertEqual(st["t"], 12)
        self.assertTrue(st["incidents"], "Mando debería tener ya el incidente de la Puerta B")
        self.assertTrue(st["plans"][0]["assumptions"], "el plan lleva escritos sus supuestos")
        self.assertIn("explain", st["incidents"][0])
        self.assertEqual(st["metrics"]["unsafe_actions"], 0)
        with self.c.stream("GET", "/api/stream?limit=1") as r:
            body = "".join(r.iter_text())
        self.assertIn("event: state", body)
        data = json.loads(body.split("data: ", 1)[1].split("\n\n", 1)[0])
        self.assertEqual(data["t"], 12)

    def test_assumption_breaks_and_replans(self) -> None:
        st = self.step(60)
        self.assertGreaterEqual(st["metrics"]["replans"], 1)
        broken = [p for p in st["plans"] if p.get("invalidated_by")]
        self.assertTrue(broken, "en demo-gates se rompe al menos un supuesto")
        self.assertTrue(any(p.get("supersedes") == broken[0]["id"] for p in st["plans"]), "y hay plan nuevo que lo sustituye")
        self.assertTrue(any(e["kind"] == "assumption_broken" for e in st["log"]))

    def test_jury_report_and_strike(self) -> None:
        self.step(2)
        r = self.c.post("/api/report", json={"channel": "whatsapp", "zone": "food", "preset": "smoke"}).json()
        self.assertTrue(r["ok"])
        rid = r["report_id"]
        free = self.c.post("/api/report", json={"channel": "sms", "text": "<script>alert(1)</script> no sé qué pasa pero hay lío"}).json()
        self.assertIsNone(free["recognized"])
        st = self.step(2)
        self.assertIn(rid, [x["id"] for x in st["reports"]])
        self.assertTrue(any(rid in i.get("reports", []) for i in st["incidents"]), "Mando convierte el aviso del jurado en incidente")
        self.assertTrue(self.c.get(f"/api/report/{rid}").json()["found"])
        s = self.c.post("/api/strike", json={"preset": "block_ambulance", "origin": "jury"})
        self.assertEqual(s.status_code, 200, s.text)
        st = self.step(1)
        amb = next(x for x in st["resources"] if x["id"] == "amb_1")
        self.assertEqual(amb["status"], "offline")
        self.assertTrue(any(e["kind"] == "chaos" for e in st["log"]))
        self.assertEqual(st["metrics"]["strikes"], 1)
        self.assertEqual(self.c.post("/api/strike", json={"effect": {"kind": "borrar_todo"}}).status_code, 400)
        sug = self.c.get("/api/chaos/suggest").json()
        self.assertTrue(sug["suggestions"])
        self.assertIn("effect", sug["suggestions"][0])

    def _until_approval(self, case_id: str, limit: int = 40) -> dict:
        self.assertEqual(self.c.post("/api/session", json={"case_id": case_id}).status_code, 200)
        for _ in range(limit):
            st = self.step(1)
            if st["approvals"]:
                return st
        self.fail(f"{case_id} no pidió ninguna aprobación en {limit} min")

    def test_approve_and_veto(self) -> None:
        st = self._until_approval("demo-2")
        a = st["approvals"][0]
        self.assertIn("card", a)
        self.assertNotIn("params", a)
        self.assertEqual(self.c.post("/api/approve", json={"action_id": "no-existe", "ok": True}).status_code, 409)
        self.assertEqual(self.c.post("/api/approve", json={"action_id": a["id"], "ok": True, "note": "adelante"}).status_code, 200)
        st = self.step(2)
        act = next(x for x in st["actions"] if x["id"] == a["id"])
        self.assertIn(act["status"], ("executing", "done"))
        self.assertEqual(st["metrics"]["unsafe_actions"], 0)
        self.assertEqual(st["metrics"]["decision_latency_n"], 1)
        self.assertIsNotNone(st["metrics"]["decision_latency_min"])
        st = self._until_approval("demo-1")
        a = st["approvals"][0]
        self.assertEqual(self.c.post("/api/approve", json={"action_id": a["id"], "ok": False, "note": "aún no"}).status_code, 200)
        st = self.step(1)
        self.assertEqual(next(x for x in st["actions"] if x["id"] == a["id"])["status"], "rejected")
        self.assertTrue(self.c.get("/api/informe").json()["approvals"])

    def test_fronts_and_readable_names(self) -> None:
        self.c.post("/api/session", json={"case_id": "demo-2"})
        st = self.step(12)
        self.assertTrue(st["fronts"])
        for key in ("priority", "label", "zone_name", "state", "resources", "eta", "why_waiting", "unforeseen"):
            self.assertIn(key, st["fronts"][0])
        self.assertEqual([f["priority"] for f in st["fronts"]], sorted((f["priority"] for f in st["fronts"]), reverse=True))
        self.assertGreaterEqual(st["metrics"]["fronts_peak"], len(st["fronts"]))
        r = self.c.post("/api/report", json={"zone": "food", "preset": "smoke"}).json()
        st = self.step(2)
        self.assertTrue(any(f["unforeseen"] for f in st["fronts"]), "el imprevisto del jurado entra resaltado en el tablero")
        text = " ".join(e["text"] for e in st["log"]) + " ".join(p["objective"] + p["why"] for p in st["plans"])
        for raw in ("front_pit", "gate_b", "corridor_s", "med_1", "sec_2"):
            self.assertNotIn(raw, text, "en pantalla van nombres, no ids")
        self.assertTrue(r["ok"])

    def test_views_are_tolerant(self) -> None:
        h = views.Humanizer({"general": "Pista general", "gate_a": "Puerta A (norte)"}, {"sec_2": "Seguridad 2"})
        self.assertEqual(h("¿EVACUAR general? sec_2 va a gate_a"), "¿EVACUAR Pista general? Seguridad 2 va a Puerta A (norte)")
        self.assertEqual(h("megafonía general en Pista general"), "megafonía general en Pista general")
        action = {"id": "A-1", "t": 10, "params": {"decision_card": {
            "to": {"role": "Director del Plan de Actuación", "deputy": "Jefa de seguridad"}, "window_min": 4, "escalate_t": 14,
            "if_approved": {"text": "4,0/m² en 6 min", "peak_density": 4.0}, "if_vetoed": "6,5/m² en 9 min"}}}
        card = views.decision_card(action, 12)
        self.assertEqual((card["remaining_min"], card["escalated"], card["deputy"]), (2, False, "Jefa de seguridad"))
        self.assertTrue(views.decision_card(action, 14)["escalated"])
        self.assertEqual(card["if_vetoed"]["text"], "6,5/m² en 9 min")
        self.assertIsNone(views.decision_card({"params": {}}, 0))
        real = views.decision_card({"t": 2, "params": {"decision_card": {"addressee": "Director del Plan de Actuación", "deputy": "Jefe de seguridad",
                "if_approved": {"peak_density": 4.18, "minutes_over_4": 12, "crush_at_min": None, "minutes": 12},
                "if_vetoed": {"peak_density": 6.5, "minutes_over_4": 12, "crush_at_min": 9, "minutes": 12},
                "rehearsed": True, "window_min": 12, "asked_at": 2, "escalate_at": 8, "escalated_at": None}}}, 5)
        self.assertEqual((real["role"], real["remaining_min"], real["escalated"], real["rehearsed"]), ("Director del Plan de Actuación", 9, False, True))
        self.assertEqual(real["if_approved"]["figures"][0], {"k": "personas/m² de pico", "v": 4.18})
        self.assertIn("aplastamiento en 9 min", real["if_vetoed"]["text"])
        line = [{"kind": "plan", "ref": "P-9", "data": {"rehearsal": True}, "text":
                 "ENSAYO (12 min) para Puerta B: 60 % a Puerta A → Puerta A 6,4/m² en 12 min ✗ · reparto A+C → Puerta C 3,1/m² en 12 min ✓"}]
        parsed = views.rehearsal({"id": "P-9"}, line)
        self.assertEqual([(o["label"], o["ok"]) for o in parsed], [("60 % a Puerta A", False), ("reparto A+C", True)])
        fr = views.fronts({"fronts": [{"incident": "M-1", "status": "in_progress", "team": [{"resource": "med_3", "status": "busy", "eta": 0}],
                                       "why_waiting": "espera ambulancia"}]},
                          [{"id": "M-1", "status": "in_progress", "zone": "general", "priority": 9.0, "reports": []}], [],
                          {"med_3": {"name": "Equipo médico 3", "status": "busy", "eta": 0}}, {"general": "Pista general"}, 5)
        self.assertEqual((fr[0]["resources"], fr[0]["state"], fr[0]["why_waiting"]), (["Equipo médico 3"], "atendido en el sitio", "espera ambulancia"))
        reh = views.rehearsal({"id": "P-1", "rehearsal": [{"label": "todo a Puerta A", "peak_density": 6.4, "ok": False},
                                                         {"label": "reparto A+C", "peak_density": 3.1, "ok": True, "chosen": True}]}, [])
        self.assertEqual([(o["value"], o["ok"]) for o in reh], [(6.4, False), (3.1, True)])
        self.assertIsNone(views.rehearsal({"id": "P-2"}, []), "sin ensayo no se inventa ninguno")
        incs = [{"id": "M-1", "reserved": True, "label": "agresión", "zone": "toilets", "explain": "x", "reports": ["r1"]}]
        reps = [{"id": "r1", "incident": "M-1", "text": "detalle sensible", "zone_hint": "toilets", "source": "asistente"}]
        log = [{"text": "M-1 detalle", "data": {"incident": "M-1"}}]
        views.mask_reserved(incs, reps, [], log)
        self.assertEqual((incs[0]["label"], incs[0]["zone"], reps[0]["text"], log[0]["text"]),
                         ("Incidente reservado", None, "(aviso reservado)", "Actuación sobre un incidente reservado"))

    def test_duel_same_case_same_strikes(self) -> None:
        self.assertEqual(self.c.post("/api/duel/session", json={"case_id": "demo-gates"}).status_code, 200)
        self.c.post("/api/duel/control", json={"cmd": "step", "n": 10})
        self.c.post("/api/strike", json={"preset": "storm", "origin": "jury"})
        self.c.post("/api/duel/control", json={"cmd": "step", "n": 50})
        d = self.c.get("/api/duel/state").json()
        self.assertEqual((d["left"]["kind"], d["right"]["kind"]), ("baseline-reroute", "mando"))
        self.assertEqual(len(d["left"]["strikes"]), 1)
        self.assertEqual(len(d["right"]["strikes"]), 1)
        self.assertEqual(d["t"], 60)
        self.assertGreater(d["left"]["score"]["peak_density"], d["right"]["score"]["peak_density"],
                           "la lista fija satura una puerta con su propio desvío y Mando no")
        self.assertGreater(d["left"]["score"]["minutes_over_5"], d["right"]["score"]["minutes_over_5"])
        with self.c.stream("GET", "/api/duel/stream?limit=1") as r:
            self.assertIn("event: state", "".join(r.iter_text()))
        self.c.post("/api/duel/control", json={"cmd": "close"})

    def test_jury_budget_lock_and_deterministic_replay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old_dir, regression_live.DIR = regression_live.DIR, regression_live.Path(tmp)
            try:
                self.c.post("/api/session", json={"case_id": "demo-1"})
                self.step(6)
                for k in ("block_ambulance", "voice_down", "storm"):
                    r = self.c.post("/api/strike", json={"preset": k, "origin": "jury", "author": "Iván L."})
                    self.assertEqual(r.status_code, 200, r.text)
                    self.step(2)
                self.assertEqual(r.json()["left"], 0)
                self.assertEqual(self.c.post("/api/strike", json={"preset": "storm", "origin": "jury"}).status_code, 429)
                st = self.step(60)
                board = st["scoreboard"]
                self.assertEqual(board["jury"] + board["mando"], 3)
                self.assertEqual((board["left"], board["budget"]), (0, 3))
                first = {k: st["metrics"][k] for k in ("critical_failed", "replans", "peak_density", "minutes_over_5", "calls_total")}
                lock = self.c.post("/api/regression/lock", json={"author": "Iván L."}).json()["test"]
                self.assertEqual(lock["author"], "Iván L.")
                self.assertEqual(len(lock["inputs"]), 3)
                self.assertEqual(self.c.get("/api/state").json()["scoreboard"]["locked"]["n"], lock["n"])
                self.assertEqual(self.c.post("/api/regression/run", json={"n": lock["n"]}).status_code, 200)
                st = self.step(80)
                self.assertTrue(st["session"]["done"])
                self.assertEqual({k: st["metrics"][k] for k in first}, first, "misma partida, mismo resultado: es determinista")
                self.assertEqual(len(st["strikes"]), 3)
                self.assertIsNotNone(st["session"]["replay"]["result"])
                self.assertEqual(self.c.get("/api/regression").json()[0]["last_run"]["passed"], st["session"]["replay"]["result"]["passed"])
                self.assertEqual(self.c.post("/api/regression/run", json={"n": 9999}).status_code, 404)
            finally:
                regression_live.DIR = old_dir

    def test_public_cannot_operate(self) -> None:
        """Un móvil del público (otra IP) puede avisar y golpear, pero no aprobar, mover el reloj ni tomar llamadas."""
        phone = TestClient(self.app, client=("192.168.1.77", 50000))
        self.assertEqual(phone.post("/api/report", json={"text": "hay una pelea", "zone": "food"}).status_code, 200)
        self.assertEqual(phone.post("/api/strike", json={"preset": "storm", "origin": "jury"}).status_code, 200)
        for path, payload in (("/api/approve", {"action_id": "A-1", "ok": True}), ("/api/control", {"cmd": "play"}),
                              ("/api/session", {"case_id": "demo-1"}), ("/api/regression/lock", {"author": "x"}),
                              ("/api/call/A-1/token", {"takeover": True}), ("/api/duel/control", {"cmd": "play"}),
                              ("/api/strike", {"preset": "storm", "origin": "chaos"})):
            self.assertEqual(phone.post(path, json=payload).status_code, 403, path)
        self.assertEqual(phone.get("/api/webcalls").status_code, 403)
        os.environ["MANDO_OPERATOR_TOKEN"] = "operadora"
        try:
            ok = phone.post("/api/control", json={"cmd": "pause"}, headers={"X-Mando-Operator": "operadora"})
            self.assertEqual(ok.status_code, 200)
        finally:
            del os.environ["MANDO_OPERATOR_TOKEN"]

    def test_webhook_auth_and_idempotency(self) -> None:
        ev = {"schema": "mando.hr.v1", "message": "progress", "event_id": "e-1", "action_id": "A-0001", "stage": "call_started", "mode": "live"}
        self.assertEqual(self.c.post("/hr/events", json=ev).status_code, 401)
        self.assertEqual(self.c.post("/hr/events", json=ev, headers={"X-Mando-Token": "malo"}).status_code, 401)
        ok = self.c.post("/hr/events", json=ev, headers={"X-Mando-Token": SECRET}).json()
        self.assertEqual((ok["ok"], ok["duplicate"]), (True, False))
        self.assertTrue(self.c.post("/hr/events", json=ev, headers={"X-Mando-Token": SECRET}).json()["duplicate"])
        rep = {"schema": "mando.hr.v1", "message": "public_report", "event_id": "e-2", "final": True, "seq": 9, "mode": "live", "complete": True,
               "report": {"channel": "whatsapp", "text": "Hay un chico en el suelo que no responde, delante del escenario", "source": "asistente",
                          "lang": "es", "zone_hint": "front_pit"}, "extracted": {"severity_level": "life_threat"}}
        out = self.c.post("/hr/events", json=rep, headers={"X-Mando-Token": SECRET}).json()
        self.assertTrue(out["report_id"])
        st = self.step(1)
        self.assertIn(out["report_id"], [x["id"] for x in st["reports"]])
        no = self.c.post("/hr/approval_check", json={"schema": "mando.hr.v1", "action_id": "A-9999", "approval_id": "ap-0001"},
                         headers={"X-Mando-Token": SECRET}).json()
        self.assertFalse(no["approved"])


class HappyRobotCircuitTest(unittest.TestCase):
    """send → hook del mock → webhook de resultado → poll, con HTTP de verdad en 127.0.0.1."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        contacts = os.path.join(self.tmp.name, "contacts.json")
        with open(contacts, "w", encoding="utf-8") as f:
            json.dump({"resources": {f"sec_{i}": {"to_number": f"+3460000000{i}", "leader_name": "Prueba"} for i in range(1, 6)}}, f)
        self.port, self.mock_port = free_port(), free_port()
        self.env = {"MANDO_CONTACTS": contacts, "HR_HOOK_DISPATCH": f"http://127.0.0.1:{self.mock_port}/hook/dispatch",
                    "HR_SECRET": SECRET, "HR_SLOW_ON_CALL": "0", "MANDO_CALLBACK_URL": f"http://127.0.0.1:{self.port}",
                    "MANDO_VOICE_MODE": "phone", "HR_LAUNCH_MODE": "hook", "HR_API_BASE": f"http://127.0.0.1:{self.mock_port}/api/v2",
                    "HR_API_KEY": "clave-de-prueba", "HR_WORKFLOW_DISPATCH": "fa-despacho", "HR_WORKFLOW_WEBCALL": "fa-webcall",
                    # fase 3: la lista blanca es OBLIGATORIA; sin ella no se marca a nadie (ver test_phase3)
                    "MANDO_ALLOWED_NUMBERS": ",".join(f"+3460000000{i}" for i in range(1, 6)), "MANDO_PUBLIC_URL": ""}
        self.old = {k: os.environ.get(k) for k in self.env}
        os.environ.update(self.env)
        self.mock = create_mock(delay_s=0.4, secret=SECRET)

    def tearDown(self) -> None:
        for k, v in self.old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self.tmp.cleanup()

    def _run(self, fallback_s: str) -> tuple[dict, list]:
        os.environ["HR_FALLBACK_S"] = fallback_s
        app = create_app("demo-gates", threaded=False, comms_mode="happyrobot", secret=SECRET, port=self.port)
        session = app.state.session
        try:
            with Served(self.mock, self.mock_port), Served(app, self.port):
                for _ in range(7):   # en el minuto 5 Mando manda a Seguridad 4 a la Puerta B
                    session.tick()
                self.assertTrue(wait_for(lambda: self.mock.state.received), "el hook del mock no recibió nada")
                real = [c for c in session.comms.calls.values() if c["real"] or c["fell_back"]]
                self.assertTrue(real, "ninguna llamada salió por HappyRobot")
                aid = real[0]["action_id"]
                # sin hilo de reloj (threaded=False) el barrido de llamadas caducadas lo hace la prueba
                self.assertTrue(wait_for(lambda: session.comms.sweep() or aid in session.comms._closed),
                                "no llegó resultado ni caída a simulación")
                wait_for(lambda: session.comms.sweep() or not session.comms._inflight, 4)
                # fase 3: el resultado llega en caliente y el webhook final (con la transcripción) un poco después
                wait_for(lambda: all(x["status"] != "in-progress" for x in self.mock.state.sessions.values()), 4)
                for _ in range(4):
                    session.tick()
                return session.state(), list(self.mock.state.received)
        finally:
            os.environ.pop("HR_FALLBACK_S", None)
            session.close()

    def test_full_circuit(self) -> None:
        st, received = self._run("30")
        body = received[0]["payload"]
        # fase 3: al hook van EXACTAMENTE los parámetros del trigger del workflow real `mando-despacho-telefono`
        self.assertEqual(sorted(body), sorted(("action_id", "to_number", "role", "order_text", "zone_spoken", "priority",
                                               "callback_url", "callback_token")))
        self.assertEqual((body["callback_url"], body["callback_token"]), (f"http://127.0.0.1:{self.port}/hr/events", SECRET))
        call = next(c for c in st["calls"]["calls"] if c["real"])
        self.assertEqual(call["result"], "accept")
        self.assertEqual(call["eta_min"], 3)
        self.assertGreaterEqual(st["calls"]["real_sent"], 1)
        self.assertEqual(st["calls"]["fallbacks"], 0)
        self.assertGreaterEqual(st["metrics"]["voice_turn_latency_n"], 1)
        self.assertTrue(any("acepta" in e["text"] for e in st["log"]), "Mando recibe el ACEPTA por poll()")

    def test_hook_carries_api_key_and_run_is_followed(self) -> None:
        st, received = self._run("30")
        self.assertEqual(received[0]["via"], "hook")
        self.assertEqual(received[0]["x_api_key"], "clave-de-prueba", "Enhanced Security: cabecera x-api-key")
        call = next(c for c in st["calls"]["calls"] if c["real"])
        self.assertTrue(call.get("hr_run_id", "").startswith("mock-run-"), "el webhook devuelve current.run_id y se casa con la acción")
        self.assertTrue(any(l["who"] == "mando" for l in call.get("transcript", [])), "transcripción por el SSE de la sesión")
        self.assertNotIn("hr_session_id", call)

    def test_runs_mode_matches_by_run_id(self) -> None:
        """`POST /workflows/{id}/runs` devuelve run_id; aunque el webhook llegue SIN action_id, se casa por el run."""
        os.environ["HR_LAUNCH_MODE"] = "runs"
        self.mock.state.config["omit_action_id"] = True
        st, received = self._run("30")
        self.assertEqual((received[0]["via"], received[0]["workflow"], received[0]["environment"]), ("runs", "fa-despacho", "development"))
        call = next(c for c in st["calls"]["calls"] if c["real"])
        self.assertEqual(call["result"], "accept")

    def test_web_call_signal_and_takeover(self) -> None:
        """Llamada web como canal principal: enlace secreto → DESCOLGAR → token → Signal en plena llamada → toma → ACEPTA."""
        os.environ["MANDO_VOICE_MODE"] = "web_call"
        app = create_app("demo-gates", threaded=False, comms_mode="happyrobot", secret=SECRET, port=self.port)
        session, comms = app.state.session, app.state.session.comms
        base = f"http://127.0.0.1:{self.port}"
        try:
            with Served(self.mock, self.mock_port), Served(app, self.port):
                for _ in range(7):
                    session.tick()
                pending = comms.pending_webcalls()
                self.assertTrue(pending, "la orden de voz queda como llamada web pendiente")
                self.assertIn("Jefe de", pending[0]["title"], "quien contesta tiene cargo")
                self.assertEqual(self.mock.state.received, [], "no se pide token hasta que alguien descuelga")
                public = httpx.get(base + "/api/state").text
                self.assertNotIn(pending[0]["call_id"], public, "el enlace secreto no sale en el estado público")
                self.assertNotIn("mock-token", public)
                info = httpx.get(f"{base}/api/webcall/{pending[0]['call_id']}").json()
                self.assertFalse(info["answered"])
                tok = httpx.post(f"{base}/api/webcall/{pending[0]['call_id']}/answer").json()
                self.assertEqual((tok["url"], tok["token"]), ("mock://livekit", "mock-token"))
                sent = self.mock.state.received[0]
                self.assertEqual((sent["via"], sent["workflow"]), ("voice_tokens", "fa-webcall"))
                self.assertIn("order_text", sent["payload"])
                self.assertNotIn("to_number", sent["payload"], "en llamada web no viaja ningún teléfono: `data` = las 7 claves del trigger")
                self.assertEqual(len(sent["payload"]), 7)
                aid = pending[0]["action_id"]
                self.assertTrue(wait_for(lambda: comms.calls[aid].get("hr_session_id")), "no se encontró la sesión del run")
                self.assertTrue(comms.change_orders(aid, "Cambio de planes: ve a Puerta C, no a Puerta A."))
                self.assertEqual(self.mock.state.signals[0]["key"], "session." + comms.calls[aid]["hr_session_id"])
                self.assertTrue(wait_for(lambda: any("Puerta C" in l["text"] for l in comms.calls[aid].get("transcript", []))),
                                "la orden nueva se oye dentro de la misma llamada")
                listen = httpx.post(f"{base}/api/call/{aid}/token", json={"takeover": False}).json()
                self.assertEqual(listen["token"], "mock-listen")
                self.assertEqual(httpx.post(f"{base}/api/webcall/{pending[0]['call_id']}/mock_answer", json={"result": "accept"}).status_code, 200)
                self.assertTrue(wait_for(lambda: aid in comms._closed), "no llegó el resultado de la llamada web")
                for _ in range(3):
                    session.tick()
                st = session.state()
                call = next(c for c in st["calls"]["calls"] if c["action_id"] == aid)
                self.assertEqual((call["result"], call["web_call"], call["signal"]["ok"]), ("accept", True, True))
                self.assertEqual(st["metrics"]["signals"], 1)
                self.assertIsNotNone(st["metrics"]["signal_rtt_ms"])
                self.assertEqual(httpx.post(f"{base}/api/call/{aid}/token", json={"takeover": True}).status_code, 502,
                                 "una llamada ya cerrada no se puede tomar (409 de la plataforma)")
        finally:
            session.close()

    def test_broken_assumption_reaches_whoever_is_on_the_phone(self) -> None:
        """demo-1: la ambulancia se queda atrapada con equipos AL TELÉFONO por ese incidente → Signal automático."""
        os.environ.update({"MANDO_VOICE_MODE": "web_call", "HR_FALLBACK_S": "600"})
        with open(os.environ["MANDO_CONTACTS"], "w", encoding="utf-8") as f:
            json.dump({"resources": {r: {"web_call": True} for r in ("med_1", "med_2", "med_3", "amb_1", "sec_1", "sec_2", "sec_3", "sec_4", "sec_5")}}, f)
        app = create_app("demo-1", threaded=False, comms_mode="happyrobot", secret=SECRET, port=self.port)
        session = app.state.session
        try:
            with Served(self.mock, self.mock_port), Served(app, self.port):
                for _ in range(20):
                    session.tick()
                    for w in session.comms.pending_webcalls():
                        session.comms.answer_webcall(w["call_id"])   # descuelgan y siguen al teléfono
                    time.sleep(0.05)
                self.assertTrue(wait_for(lambda: self.mock.state.signals), "se rompió un supuesto y nadie avisó a quien estaba al teléfono")
                sig = self.mock.state.signals[0]
                self.assertTrue(sig["key"].startswith("session.mock-ses-"))
                self.assertIn("Ambulancia interna", sig["payload"]["text"])
                self.assertNotIn("amb_1", sig["payload"]["text"])
                self.assertTrue(any("CAMBIO DE ORDEN" in e["text"] for e in session.state()["log"]))
        finally:
            os.environ.pop("HR_FALLBACK_S", None)
            session.close()

    def test_platform_silent_falls_back_to_sim(self) -> None:
        self.mock.state.config["silent"] = True
        st, _ = self._run("1")
        self.assertGreaterEqual(st["calls"]["fallbacks"], 1)
        self.assertTrue(any("SIMULACIÓN" in e["text"] for e in st["log"]))
        call = next(c for c in st["calls"]["calls"] if c["fell_back"])
        self.assertIsNotNone(call["result"], "la simulación contesta: la demo no se queda colgada")


if __name__ == "__main__":
    unittest.main()
