"""Pruebas de la fase 3 del servidor. Desde la raíz del proyecto:

    uv run --project motor/server python -m unittest motor.server.test_phase3 -v

Todo en 127.0.0.1: Telegram es `mock_telegram`, HappyRobot es `mock_happyrobot`, y el cliente MCP es el del SDK oficial.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from motor.server import chat, doctor, memoria, telegram_bot
from motor.server.app import create_app
from motor.server.mock_happyrobot import create_mock
from motor.server.mock_telegram import TOKEN, create_mock_telegram
from motor.server.test_server import SECRET, Served, free_port, wait_for


class EnvTest(unittest.TestCase):
    ENV: dict[str, str] = {}

    def setUp(self) -> None:
        self._old = {k: os.environ.get(k) for k in self.ENV}
        os.environ.update(self.ENV)
        self._apps: list = []

    def tearDown(self) -> None:
        for app in self._apps:
            app.state.session.close()
            app.state.chat.stop()
            if app.state.telegram is not None:
                app.state.telegram.stop()
        for k, v in self._old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

    def app(self, case: str = "demo-gates", **kw):
        app = create_app(case, threaded=False, secret=SECRET, **kw)
        self._apps.append(app)
        return app


class TelegramTest(EnvTest):
    def setUp(self) -> None:
        self.tg_port = free_port()
        self.ENV = {"TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_API_BASE": f"http://127.0.0.1:{self.tg_port}", "TELEGRAM_POLL_TIMEOUT_S": "1",
                    "TELEGRAM_RATE_MAX": "50", "MANDO_ASK_WAIT_S": "30", "HR_HOOK_INTAKE": ""}
        super().setUp()
        # Estos casos prueban la ruta directa del bot; la integración real de intake tiene regresión propia.
        self.intake_patch = patch("motor.server.chat.load_intake", return_value=None)
        self.intake_patch.start()
        self.addCleanup(self.intake_patch.stop)
        self.fake = create_mock_telegram()
        self.base = self.ENV["TELEGRAM_API_BASE"]

    def push(self, kind: str, **body) -> None:
        self.assertEqual(httpx.post(f"{self.base}/mock/{kind}", json=body, timeout=5).status_code, 200)

    def replies(self, chat_id: int) -> list[str]:
        return [m["text"] for m in self.fake.state.sent if m["chat_id"] == chat_id]

    def wait_reply(self, chat_id: int, needle: str, seconds: float = 8.0) -> str:
        self.assertTrue(wait_for(lambda: any(needle in t for t in self.replies(chat_id)), seconds),
                        f"el bot no contestó «{needle}» a {chat_id}: {self.replies(chat_id)}")
        return next(t for t in self.replies(chat_id) if needle in t)

    def test_off_without_token(self) -> None:
        os.environ["TELEGRAM_BOT_TOKEN"] = ""
        app = self.app()
        self.assertIsNone(app.state.telegram)
        self.assertEqual(TestClient(app).get("/api/state").json()["telegram"], {"status": "off"})

    def test_report_ask_answer_and_closing(self) -> None:
        with Served(self.fake, self.tg_port):
            app = self.app("demo-1")
            s, bot = app.state.session, app.state.telegram
            self.assertTrue(wait_for(lambda: bot.status == "on"), bot.error)
            st = s.state()
            self.assertEqual((st["telegram"]["status"], st["telegram"]["bot"], st["links"]["telegram"]),
                             ("on", "mando_demo_bot", "https://t.me/mando_demo_bot"))
            self.assertNotIn(TOKEN, s.state_json())
            self.push("text", chat_id=1, text="/start")
            self.assertIn("SIMULACIÓN", self.wait_reply(1, "SIMULACIÓN"))
            self.push("text", chat_id=1, text="/zona puerta c")
            self.wait_reply(1, "Zona fijada: Puerta C")
            self.push("text", chat_id=1, text="Hay una persona en el suelo que no responde, ayuda")
            self.wait_reply(1, telegram_bot.ACK)
            self.wait_reply(1, "Si no respira normal y sabes hacer RCP")     # instrucción de la lista cerrada, texto exacto
            rep = next(r for r in s.state()["reports"] if r["via"] == "telegram")
            self.assertEqual((rep["channel"], rep["source"], rep["zone_hint"]), ("whatsapp", "telegram", "gate_c"))
            self.assertNotIn("Persona de prueba", s.state_json(), "ni el nombre ni el usuario de Telegram llegan a la pantalla")
            # otra persona, sin zona: Mando le PREGUNTA por Telegram y su respuesta vuelve como respuesta de comunicaciones
            self.push("text", chat_id=2, text="hay una pelea muy fuerte, se están pegando varios")
            self.wait_reply(2, telegram_bot.ACK)
            for _ in range(4):
                s.tick()
            self.wait_reply(2, "Centro de control:")
            ask = next(c for c in s.comms.calls.values() if c["kind"] == "ask" and c["channel"] == "telegram")
            self.assertIn(ask["action_id"], s.comms._inflight)
            self.push("text", chat_id=2, text="estoy en restauración, al lado de las barras")
            self.wait_reply(2, "Gracias. Lo paso al centro de control.")
            for _ in range(3):
                s.tick()
            self.assertEqual(s.comms.calls[ask["action_id"]]["result"], "answer")
            self.assertTrue(any("Respuesta a " + ask["action_id"] in e["text"] for e in s.state()["log"]), "Mando recibe la respuesta por poll()")
            self.assertEqual(len([r for r in s.state()["reports"] if r["via"] == "telegram"]), 2, "la respuesta NO entra como aviso nuevo")
            for _ in range(6):
                s.tick()
            self.wait_reply(1, "Equipo en camino.")
            self.push("text", chat_id=1, text="/estado")
            self.wait_reply(1, "Tu aviso:")
            funnel = s.state()["funnel"]
            self.assertEqual(funnel["by_channel"].get("telegram"), 2)
            self.assertGreaterEqual(funnel["reports"], funnel["changed_something"])

    def test_strike_menu_budget_location_limits_and_reserved(self) -> None:
        os.environ.update({"TELEGRAM_RATE_MAX": "9"})
        with Served(self.fake, self.tg_port):
            app = self.app("demo-1")
            s, bot = app.state.session, app.state.telegram
            self.assertTrue(wait_for(lambda: bot.status == "on"), bot.error)
            self.push("text", chat_id=7, text="/golpe")
            self.wait_reply(7, "Quedan 3 de 3")
            menu = next(m for m in self.fake.state.sent if m.get("reply_markup"))
            self.assertIn({"text": "Tormenta", "callback_data": "golpe:storm"}, [row[0] for row in menu["reply_markup"]["inline_keyboard"]])
            for n, key in enumerate(("storm", "voice_down", "food_blackout")):
                self.push("button", chat_id=7, data=f"golpe:{key}")
                self.wait_reply(7, f"Quedan {2 - n}.")
            self.push("button", chat_id=7, data="golpe:storm")
            self.wait_reply(7, "ya ha gastado sus 3 golpes")
            self.assertEqual(len(s.strikes), 3)
            # ubicación compartida → zona más cercana de la tabla fija de coordenadas ficticias
            lat, lon = telegram_bot.ZONE_COORDS["food"]
            self.assertEqual(telegram_bot.nearest_zone(lat, lon), ("food", False))
            self.assertTrue(telegram_bot.nearest_zone(40.4523, -3.7262)[1], "lejos del recinto ficticio: se pliega sobre el plano")
            self.push("location", chat_id=7, latitude=lat, longitude=lon)
            self.wait_reply(7, "Zona fijada: Restauración")
            # reservado: respuestas neutras, nunca se repite el contenido
            self.push("text", chat_id=8, text="un grupo está acosando a una chica y no la dejan irse, la están tocando")
            self.wait_reply(8, telegram_bot.ACK)
            for _ in range(3):
                s.tick()
            self.push("text", chat_id=8, text="/estado")
            self.assertTrue(wait_for(lambda: len(self.replies(8)) >= 3))
            for t in self.replies(8):
                self.assertNotRegex(t.lower(), r"acos|chica|tocando|agresi")
            # tamaño máximo y límite de frecuencia por usuario
            self.push("text", chat_id=9, text="x" * 900)
            self.wait_reply(9, "Mensaje demasiado largo")
            before = len(s.state()["reports"])
            for i in range(14):
                self.push("text", chat_id=9, text=f"/estado {i}")
            self.wait_reply(9, "Demasiados mensajes")
            time.sleep(0.5)
            self.assertEqual(sum("Demasiados mensajes" in t for t in self.replies(9)), 1, "avisa UNA vez: el bot no amplifica")
            self.assertEqual(len(s.state()["reports"]), before)
            self.assertEqual(bot.view()["too_long"], 1)
            self.assertGreaterEqual(bot.view()["rate_limited"], 1)


class PlatformPayloadTest(EnvTest):
    """Lo que devuelven DE VERDAD los workflows (`type`, todo cadenas), contra el mock que los imita."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        contacts = os.path.join(self.tmp.name, "contacts.json")
        with open(contacts, "w", encoding="utf-8") as f:
            json.dump({"resources": {f"sec_{i}": {"to_number": f"+3460000000{i}", "leader_name": "Prueba"} for i in range(1, 6)}}, f)
        self.port, self.mock_port = free_port(), free_port()
        self.ENV = {"MANDO_CONTACTS": contacts, "HR_HOOK_DISPATCH": f"http://127.0.0.1:{self.mock_port}/hooks/despacho", "HR_SECRET": SECRET,
                    "HR_SLOW_ON_CALL": "0", "MANDO_PUBLIC_URL": f"http://127.0.0.1:{self.port}", "MANDO_VOICE_MODE": "phone",
                    "HR_LAUNCH_MODE": "hook", "HR_API_BASE": "", "HR_API_KEY": "", "HR_FALLBACK_S": "30", "TELEGRAM_BOT_TOKEN": "",
                    "MANDO_ALLOWED_NUMBERS": ",".join(f"+3460000000{i}" for i in range(1, 6)), "MANDO_MCP_TOKEN": "token-mcp", "HR_HOOK_INTAKE": ""}
        super().setUp()
        self.mock = create_mock(delay_s=0.4, secret="otro-secreto-que-no-vale")

    def tearDown(self) -> None:
        super().tearDown()
        self.tmp.cleanup()

    def run_call(self, **config):
        self.mock.state.config.update(config)
        app = self.app(comms_mode="happyrobot", port=self.port)
        s = app.state.session
        with Served(self.mock, self.mock_port), Served(app, self.port):
            for _ in range(7):
                s.tick()
            self.assertTrue(wait_for(lambda: self.mock.state.received), "el hook no recibió nada")
            self.assertTrue(wait_for(lambda: any(p.get("type") == "dispatch_result" for p in self.mock.state.posted)))
            for _ in range(3):
                s.tick()
        return s

    def test_accept_without_minutes_gets_backend_eta(self) -> None:
        s = self.run_call(eta="")
        sent = next(r['payload'] for r in self.mock.state.received if 'Acude ya' in r['payload'].get('order_text', ''))
        self.assertEqual(list(sent), ["action_id", "to_number", "role", "order_text", "zone_spoken", "priority", "callback_url", "callback_token"])
        self.assertEqual((sent["callback_url"], sent["callback_token"]), (f"http://127.0.0.1:{self.port}/hr/events", SECRET))
        self.assertIn(sent["priority"], ("roja", "amarilla", "verde"), "la prioridad se DICE por teléfono: va como palabra")
        self.assertIn("Jefe de seguridad", sent["role"])
        mine = [p for p in self.mock.state.posted if p["action_id"] == sent["action_id"]]
        self.assertEqual([p["type"] for p in mine], ["dispatch_progress", "dispatch_result"], "en caliente y, al colgar, el final")
        self.assertTrue(all(isinstance(v, str) for k, v in mine[1].items() if k not in ("final", "data")), "todo cadenas, como la plataforma")
        call = next(c for c in s.comms.calls.values() if c["real"] and c['kind'] == 'dispatch')
        self.assertEqual(call["result"], "accept")
        self.assertIsInstance(call["eta_min"], int, "eta_min vacío → ETA estimada por el backend")
        self.assertIn("ETA estimada", call["text"])
        self.assertTrue(call["hr_run_id"].startswith("mock-run-"))
        self.assertTrue(any(l["who"] == "persona" for l in call.get("transcript", [])), "la transcripción del webhook final")
        self.assertNotIn("+3460000000", s.state_json(), "ningún teléfono llega a la pantalla")

    def test_unclear_is_no_answer_and_mando_moves_on(self) -> None:
        s = self.run_call(default="unclear")
        calls = [c for c in s.comms.calls.values() if c["kind"] == "dispatch"]
        self.assertEqual(calls[0]["result"], "no_answer", "unclear se trata como no_answer")
        self.assertTrue(any("no contesta" in e["text"] for e in s.state()["log"]))
        self.assertGreater(len(calls), 1, "Mando prueba con el siguiente recurso")

    def test_by_hand_idempotent_and_token(self) -> None:
        self.mock.state.config["silent"] = True
        app = self.app(comms_mode="happyrobot", port=self.port)
        s, c = app.state.session, TestClient(app)
        with Served(self.mock, self.mock_port):
            for _ in range(7):
                s.tick()
            self.assertTrue(wait_for(lambda: self.mock.state.received))
        aid = next(iter(s.comms._inflight))
        s.comms._bind_run(aid, "run-77")  # H6: run emitido por esta partida
        hot = {"schema": "mando.hr.v1", "type": "dispatch_progress", "message": "progress", "stage": "order_confirmed", "final": False,
               "channel_used": "phone", "action_id": aid, "result": "accept", "eta_min": "4", "reason": "", "hr_run_id": "run-77"}
        self.assertEqual(c.post("/hr/events", json=hot, headers={"X-Mando-Token": "malo"}).status_code, 401)
        out = c.post("/hr/events", json=hot, headers={"X-Mando-Token": SECRET}).json()
        self.assertEqual((out["ok"], out["result"], out["eta_min"]), (True, "accept", 4))
        self.assertTrue(c.post("/hr/events", json=hot, headers={"X-Mando-Token": SECRET}).json()["duplicate"])
        final = {"type": "dispatch_result", "action_id": "", "result": "accept", "eta_min": "4", "reason": "", "call_status": "completed",
                 "session_id": "ses-de-happyrobot", "transcript": "assistant: Orden para ti.\nuser: Afirmativo, cuatro minutos.", "hr_run_id": "run-77"}
        out = c.post("/hr/events", json=final, headers={"X-Mando-Token": SECRET}).json()
        self.assertTrue(out.get("already_confirmed"), "casado por hr_run_id, sin action_id; el final solo completa la ficha")
        s.tick()
        call = s.comms.calls[aid]
        self.assertEqual((call["result"], call["eta_min"], call["hr_run_id"]), ("accept", 4, "run-77"))
        self.assertEqual([l["who"] for l in call["transcript"]], ["mando", "persona"])
        self.assertEqual(sum(1 for e in s.state()["log"] if "acepta" in e["text"] and e.get("ref") == aid), 1, "una sola vez a Mando")

    def test_no_whitelist_no_calls(self) -> None:
        os.environ["MANDO_ALLOWED_NUMBERS"] = ""
        app = self.app(comms_mode="happyrobot", port=self.port)
        s = app.state.session
        with Served(self.mock, self.mock_port):
            for _ in range(9):
                s.tick()
            time.sleep(0.3)
        self.assertEqual(self.mock.state.received, [], "sin lista blanca no se marca a nadie")
        self.assertTrue(any("MANDO_ALLOWED_NUMBERS" in e["text"] for e in s.state()["log"]))

    def test_mcp_server_with_sdk_client(self) -> None:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client
        self.mock.state.config["silent"] = True
        app = self.app(comms_mode="happyrobot", port=self.port)
        s = app.state.session
        url = f"http://127.0.0.1:{self.port}/mcp"

        async def talk(aid: str) -> dict:
            out = {}
            async with streamablehttp_client(url, headers={"Authorization": "Bearer token-mcp"}) as (r, w, _):
                async with ClientSession(r, w) as cs:
                    await cs.initialize()
                    out["tools"] = sorted(t.name for t in (await cs.list_tools()).tools)

                    async def call(name: str, **args):
                        res = await cs.call_tool(name, args)
                        return json.loads(res.content[0].text)
                    out["orden"] = await call("obtener_orden", action_id=aid)
                    out["sin_cambio"] = await call("hay_cambio_de_plan", action_id=aid)
                    s.comms.change_orders(aid, "Cambio de planes: ve a Puerta C, no a Puerta B.")
                    out["cambio"] = await call("hay_cambio_de_plan", action_id=aid)
                    out["confirmar"] = await call("confirmar_orden", action_id=aid, resultado="accept", eta_min=5)
                    out["otra_vez"] = await call("confirmar_orden", action_id=aid, resultado="accept", eta_min=5)
                    out["mala"] = await call("confirmar_orden", action_id="A-no-existe", resultado="accept")
                    out["aviso"] = await call("registrar_aviso", texto="Sale humo de un puesto de comida", zona="restauración", canal="voice")
                    out["zona"] = await call("estado_zona", zona="puerta b")
                    out["aprobacion"] = await call("consultar_aprobacion", action_id=aid)
            return out

        with Served(self.mock, self.mock_port), Served(app, self.port):
            self.assertEqual(httpx.post(url, json={}).status_code, 401)
            os.environ["MANDO_MCP_TOKEN"] = ""
            self.assertEqual(httpx.post(url, json={}, headers={"Authorization": "Bearer token-mcp"}).status_code, 503)
            os.environ["MANDO_MCP_TOKEN"] = "token-mcp"
            for _ in range(7):
                s.tick()
            self.assertTrue(wait_for(lambda: s.comms._inflight))
            aid = next(iter(s.comms._inflight))
            out = asyncio.run(talk(aid))
            s.tick()
        self.assertEqual(out["tools"], ["confirmar_orden", "consultar_aprobacion", "estado_zona", "hay_cambio_de_plan", "obtener_orden", "registrar_aviso"])
        self.assertIn("Puerta", out["orden"]["order_text"] + out["orden"]["zone_spoken"].capitalize())
        self.assertEqual((out["sin_cambio"]["hay_cambio"], out["cambio"]["hay_cambio"]), (False, True))
        self.assertIn("Puerta C", out["cambio"]["orden_nueva"])
        self.assertEqual((out["confirmar"]["registrada"], out["otra_vez"]["ya_estaba_registrada"], out["mala"]["ok"]), (True, True, False))
        self.assertEqual((s.comms.calls[aid]["result"], s.comms.calls[aid]["eta_min"]), ("accept", 5))
        self.assertTrue(out["aviso"]["report_id"].startswith("j-"))
        self.assertEqual((out["zona"]["zona"], out["aprobacion"]["aprobada"]), ("Puerta B (principal)", False))
        self.assertNotIn("+346", json.dumps(out), "ninguna tool devuelve teléfonos")


class IntakeTest(EnvTest):
    ENV = {"TELEGRAM_BOT_TOKEN": "", "HR_HOOK_INTAKE": "", "HR_SECRET": SECRET, "MANDO_PUBLIC_URL": ""}

    def test_public_report_any_channel(self) -> None:
        app = self.app()
        c, s = TestClient(app), app.state.session
        ev = {"type": "public_report", "channel": "email", "location": "Puerta B", "description": "Una chica se ha mareado por el calor",
              "people": "1", "responsive": "si", "informant": "asistente", "pending": "", "category": "sanitario", "lang": "es",
              "text": "Una chica se ha mareado por el calor en la puerta B", "hr_run_id": "run-email-1", "reply_to": "ana@example.invalid"}
        self.assertEqual(c.post("/hr/events", json=ev).status_code, 401)
        out = c.post("/hr/events", json=ev, headers={"X-Mando-Token": SECRET}).json()
        self.assertTrue(out["report_id"])
        self.assertTrue(c.post("/hr/events", json=ev, headers={"X-Mando-Token": SECRET}).json()["duplicate"])
        voice = dict(ev, channel="voice", hr_run_id="run-voz-1", text="", description="Hay humo en un puesto de comida", location="restauración",
                     category="infraestructura", transcript="user: hay humo")
        self.assertTrue(c.post("/hr/events", json=voice, headers={"X-Mando-Token": SECRET}).json()["report_id"])
        s.tick()
        reps = {r["via"]: r for r in s.state()["reports"] if r["id"].startswith("j-")}
        self.assertEqual((reps["email"]["channel"], reps["voice"]["channel"]), ("sms", "voice"), "email no existe en el contrato: viaja como sms")
        self.assertEqual(reps["email"]["understood"], "happyrobot")
        self.assertNotIn("example.invalid", s.state_json(), "reply_to no llega a la pantalla")
        self.assertEqual(s.state()["funnel"]["by_channel"]["email"], 1)
        truth = s.world.truth()["incidents"]
        self.assertEqual({i["zone"] for k, i in truth.items() if k.startswith("jx")}, {"gate_b", "food"}, "la ubicación extraída sitúa el incidente")

    def test_delegated_understanding_and_local_fallback(self) -> None:
        port, mock_port = free_port(), free_port()
        os.environ.update({"HR_HOOK_INTAKE": f"http://127.0.0.1:{mock_port}/hooks/ingesta-texto", "MANDO_PUBLIC_URL": f"http://127.0.0.1:{port}",
                           "HR_INTAKE_TIMEOUT_S": "3"})
        mock = create_mock(delay_s=0.2, secret=SECRET)
        app = self.app(port=port)
        s = app.state.session
        with Served(mock, mock_port), Served(app, port):
            r = httpx.post(f"http://127.0.0.1:{port}/api/report", json={"text": "hay una pelea en la puerta c, se están pegando"}, timeout=10).json()
            self.assertEqual(r["understood"], "happyrobot")
            sent = mock.state.received[0]["payload"]
            self.assertEqual(sorted(sent), sorted(("text", "channel", "source", "zone_hint", "lang", "reply_to", "callback_url", "callback_token")))
            mock.state.config["intake_silent"] = True
            os.environ["HR_INTAKE_TIMEOUT_S"] = "0.5"
            r2 = httpx.post(f"http://127.0.0.1:{port}/api/report", json={"text": "sale humo de un puesto de comida"}, timeout=10).json()
            self.assertEqual(r2["understood"], "local")
        st = s.state()
        self.assertEqual(st["funnel"]["by_understood"], {"happyrobot": 1, "local": 1})
        texts = " ".join(e["text"] for e in st["log"])
        self.assertTrue(any(r.get("understood") == "happyrobot" for r in st["reports"]), "la procedencia se conserva sin revelar texto reservado")
        self.assertIn("entendido en local", texts)
        self.assertEqual(s.world.truth()["incidents"]["jx1"]["zone"], "gate_c", "la zona la sacó HappyRobot del texto")

    def test_guided_conversation_partial_update_status_and_chat_token(self) -> None:
        """PLATAFORMA_REAL §8 bis: el aviso entra EN CALIENTE (`partial`), las actualizaciones y el final van al MISMO aviso,
        `consultar_estado` recibe un `say_text` neutro, y el token del widget de chat (público) solo sirve para esto."""
        port, mock_port = free_port(), free_port()
        os.environ.update({"HR_CHAT_TOKEN": "token-publico-del-chat", "MANDO_PUBLIC_URL": f"http://127.0.0.1:{port}"})
        mock = create_mock(secret=SECRET)
        app = self.app(port=port)
        s = app.state.session
        try:
            with Served(mock, mock_port), Served(app, port):
                conv = httpx.post(f"http://127.0.0.1:{mock_port}/mock/conversation", timeout=20, json={
                    "callback_url": f"http://127.0.0.1:{port}/hr/events", "callback_token": "token-publico-del-chat", "channel": "chat",
                    "text": "hay un chico en el suelo que no responde", "location": "frente de escenario"}).json()
                hot = {"type": "dispatch_progress", "message": "progress", "action_id": "A-0001", "result": "accept", "eta_min": "2"}
                denied = httpx.post(f"http://127.0.0.1:{port}/hr/events", json=hot, headers={"X-Mando-Token": "token-publico-del-chat"})
        finally:
            os.environ.pop("HR_CHAT_TOKEN", None)
        self.assertEqual(denied.status_code, 403, "con el token del chat no se confirman órdenes")
        steps = {(x["type"], n): x for n, x in enumerate(conv["steps"])}
        self.assertEqual([x["status"] for x in conv["steps"]], [200, 200, 200, 200])
        first = conv["steps"][0]["reply"]["report_id"]
        self.assertTrue(first, "el aviso parcial entra al mundo sin esperar al final de la conversación")
        self.assertEqual(conv["steps"][1]["reply"]["report_id"], first)
        self.assertEqual(conv["steps"][3]["reply"]["report_id"], first, "el final completa el mismo aviso")
        say = conv["steps"][2]["reply"]["say_text"]
        self.assertTrue(say and len(say) < 90 and not any(ch.isdigit() for ch in say), f"corto, neutro y sin tiempos: {say!r}")
        truth = [k for k in s.world.truth()["incidents"] if k.startswith("jx")]
        self.assertEqual(len(truth), 1, "una conversación = un incidente verdadero, no tres")
        self.assertEqual(sorted(steps)[0][0], "public_report")

    def test_broken_json_from_the_platform_is_recovered(self) -> None:
        """PLATAFORMA_REAL §2 (riesgo sin verificar): si la plataforma no escapa comillas, el `transcript` rompe el JSON."""
        app = self.app()
        c, s = TestClient(app), app.state.session
        s.comms.calls["A-0042"] = {"action_id": "A-0042", "kind": "dispatch", "resource": "sec_2", "zone": "gate_b", "incident": None}
        s.comms._inflight["A-0042"] = {"action": None, "resource": None, "started": time.monotonic(), "deadline": time.monotonic() + 60}
        s.comms._bind_run("A-0042", "run-9")  # H6: el callback no aprende un run ajeno
        raw = ('{"schema":"mando.hr.v1","type":"dispatch_result","message":"dispatch_result","final":true,"channel_used":"phone",'
               '"action_id":"A-0042","result":"reject","eta_min":"","reason":"estoy con otro","call_status":"completed","hr_session_id":"s-1",'
               '"transcript":"assistant: Orden para ti.\nuser: me ha dicho "ni de broma", que no puede\n","hr_run_id":"run-9"}').replace("\\n", "\n")
        with self.assertRaises(ValueError):
            json.loads(raw)
        r = c.post("/hr/events", content=raw.encode(), headers={"X-Mando-Token": SECRET, "Content-Type": "application/json"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["result"], "reject")
        self.assertTrue(any("JSON ROTO" in e["text"] for e in s.server_log))
        self.assertEqual(c.post("/hr/events", content=b"esto no es nada", headers={"X-Mando-Token": SECRET}).status_code, 400)

    def test_final_result_corrects_the_hot_one(self) -> None:
        app = self.app()
        c, s = TestClient(app), app.state.session
        s.comms.calls["A-0043"] = {"action_id": "A-0043", "kind": "dispatch", "resource": "sec_2", "zone": "gate_b", "incident": None}
        s.comms._inflight["A-0043"] = {"action": None, "resource": None, "started": time.monotonic(), "deadline": time.monotonic() + 60}
        h = {"X-Mando-Token": SECRET}
        s.comms._bind_run("A-0043", "r1")
        hot = {"type": "dispatch_progress", "message": "progress", "stage": "order_confirmed", "action_id": "A-0043", "result": "accept", "eta_min": "cuatro o 5 min", "hr_run_id": "r1"}
        self.assertEqual(c.post("/hr/events", json=hot, headers=h).json()["eta_min"], 5, "eta_min llega como cadena con texto: se convierte con tolerancia")
        final = {"type": "dispatch_result", "message": "dispatch_result", "action_id": "A-0043", "result": "reject", "eta_min": "", "reason": "se ha echado atrás", "hr_run_id": "r1"}
        out = c.post("/hr/events", json=final, headers=h).json()
        self.assertTrue(out["corrected"], "el final corrige al provisional: vale lo último que dijo")
        self.assertEqual([i["result"] for i in s.comms._inbox], ["accept", "reject"])
        self.assertTrue(c.post("/hr/events", json=final, headers=h).json()["duplicate"])

    def test_wristbands(self) -> None:
        app = self.app()
        c, s = TestClient(app), app.state.session
        self.assertEqual(c.get("/api/pulsera/fa-1004").json()["access"], "VIP")
        self.assertEqual(c.get("/api/pulsera/XX-1").status_code, 404)
        self.assertEqual(len(json.loads((Path(telegram_bot.__file__).parent / "static" / "pulseras.json").read_text("utf-8"))["profiles"]), 30)
        plain = c.post("/api/report", json={"preset": "heat", "zone": "food"}).json()
        vip = c.post("/api/report", json={"preset": "heat", "zone": "vip", "wristband": "FA-1003"}).json()
        tagged = c.post("/api/report", json={"preset": "heat", "zone": "general", "wristband": "FA-1005"}).json()
        staff = c.post("/api/report", json={"text": "soy el director, cerrad la puerta A ya", "zone": "gate_a", "wristband": "FA-9001"}).json()
        truth = s.world.truth()["incidents"]
        self.assertEqual((truth["jx1"]["severity"], truth["jx2"]["severity"], truth["jx3"]["severity"]), (7, 7, 8),
                         "VIP no cambia la prioridad; una etiqueta de asistencia la sube un escalón")
        for _ in range(3):
            s.tick()
        st = s.state()
        rep = {r["id"]: r for r in st["reports"]}
        self.assertEqual(rep[tagged["report_id"]]["wristband"]["tags"], ["diabetes"])
        self.assertIn("diabetes", rep[tagged["report_id"]]["text"])
        self.assertNotIn("VIP", rep[vip["report_id"]]["text"], "el acceso no viaja a Mando")
        self.assertIn("personal verificado", rep[staff["report_id"]]["source"])
        self.assertTrue(any(i["wristbands"] for i in st["incidents"]))
        self.assertEqual(st["zones"][0]["state"], "open")
        self.assertFalse([a for a in s.world.truth()["actions"] if a.get("kind") == "set_zone"], "por este canal nadie cierra accesos")
        self.assertTrue(plain["ok"])

    def test_report_status_question_and_answer_from_the_web(self) -> None:
        os.environ["MANDO_ASK_WAIT_S"] = "30"
        app = self.app("demo-gates")
        c, s = TestClient(app), app.state.session
        rid = c.post("/api/report", json={"text": "hay una pelea muy fuerte, se están pegando varios", "source": "asistente"}).json()["report_id"]
        ask = None
        for _ in range(6):
            c.get(f"/api/report/{rid}")          # la página del asistente sigue SU aviso: por eso la pregunta le llega a ella
            s.tick()
            ask = c.get(f"/api/report/{rid}").json().get("ask")
            if ask:
                break
        self.assertTrue(ask, "Mando pregunta a quien avisó y la pregunta aparece en su página")
        self.assertEqual(c.post(f"/api/report/{rid}/answer", json={"text": "en restauración, junto a las barras"}).status_code, 200)
        self.assertEqual(c.post(f"/api/report/{rid}/answer", json={"text": "otra vez"}).status_code, 409)
        for _ in range(8):
            s.tick()
        info = c.get(f"/api/report/{rid}").json()
        for k in ("status", "status_text", "incident", "reports_total", "priority", "priority_why", "resource", "call", "safety", "reserved", "ask"):
            self.assertIn(k, info)
        self.assertEqual(info["safety"], "Aléjate y no te enfrentes. Ve hacia el personal con chaleco.")
        self.assertIsNone(info["ask"])
        self.assertTrue(info["resource"] and info["resource"]["role"].startswith("Jefe de"), info)
        self.assertIn(info["call"]["state"], ("llamando", "acepta", "rechaza", "no contesta"))
        hidden = c.post("/api/report", json={"text": "un grupo está acosando a una chica y la están tocando", "zone": "toilets"}).json()["report_id"]
        for _ in range(3):
            s.tick()
        masked = c.get(f"/api/report/{hidden}").json()
        if masked.get("reserved"):
            self.assertEqual((masked["label"], masked["resource"], masked["explain"]), ("Incidente reservado", None, ""))

    def test_strike_tells_what_it_broke(self) -> None:
        app = self.app("demo-gates")
        c, s = TestClient(app), app.state.session
        for _ in range(12):
            s.tick()
        r = c.post("/api/strike", json={"effect": {"kind": "zone_inflow", "zone": "gate_a", "per_min": 900, "n": 20}, "origin": "jury", "label": "Más gente a la puerta A"}).json()
        self.assertEqual((r["strike_id"], r["broke"]), (1, None))
        for _ in range(8):
            s.tick()
        out = c.get(r["follow"]).json()
        self.assertTrue(out["broke"] and out["broke"]["text"], "tras el golpe se rompe un supuesto escrito del plan")
        self.assertTrue(out["new_plan"], "y nace un plan nuevo con id")
        self.assertEqual(c.get("/api/strike/99").status_code, 404)


class WhatIfMemoryDoctorTest(EnvTest):
    ENV = {"TELEGRAM_BOT_TOKEN": "", "HR_HOOK_INTAKE": "", "MANDO_PUBLIC_URL": ""}

    def test_whatif_is_deterministic_and_never_touches_the_world(self) -> None:
        app = self.app("demo-gates")
        c, s = TestClient(app), app.state.session
        for _ in range(10):
            s.tick()
        before = json.dumps(s.world.truth(), sort_keys=True, default=str)
        q = {"kind": "reroute", "zone": "gate_b", "to": "gate_c", "fraction": 0.4}
        a, b = c.post("/api/whatif", json=q).json(), c.post("/api/whatif", json=q).json()
        self.assertEqual(a, b, "misma pregunta en el mismo minuto, misma respuesta")
        self.assertEqual(json.dumps(s.world.truth(), sort_keys=True, default=str), before, "el ensayo NUNCA toca el mundo real")
        self.assertEqual((a["minutes"], len(a["alternative"]["series"]["gate_b"]), len(a["mando"]["series"]["gate_c"])), (15, 15, 15))
        for k in ("peak_density", "minutes_over_4", "minutes_over_5", "crush_risk", "peak_zone"):
            self.assertIn(k, a["alternative"])
        self.assertNotEqual(a["alternative"]["series"]["gate_c"], a["mando"]["series"]["gate_c"], "el desvío se nota en el destino")
        self.assertEqual(c.post("/api/whatif", json={"kind": "evacuate"}).status_code, 400)
        self.assertEqual(c.post("/api/whatif", json={"kind": "stop_show"}).status_code, 200)
        self.assertEqual(TestClient(app, client=("192.168.1.9", 5000)).post("/api/whatif", json=q).status_code, 403)
        order = c.post("/api/whatif/order", json={"action": q, "note": "prefiero repartir"}).json()["order"]
        s.tick()
        st = s.state()
        self.assertEqual(next(z for z in st["zones"] if z["id"] == "gate_b")["flags"].get("reroute_to"), "gate_c")
        self.assertTrue(any("CORRECCIÓN DEL OPERADOR" in e["text"] for e in st["log"]))
        self.assertTrue(any("LECCIÓN CANDIDATA" in e["text"] for e in st["log"]))
        self.assertEqual(c.get("/api/memoria").json()["operator_lessons"][0]["id"], order["id"])

    def test_memory_panel_is_honest_and_tolerant(self) -> None:
        app = self.app()
        c = TestClient(app)
        old = (memoria.MEMORY_PATH, memoria.PROPOSALS_PATH, memoria.APPROVED_PATH, memoria.DAY2_PATH, memoria.DECISIONS_PATH, memoria.DAY2_FALLBACK_PATH, memoria.LOCAL_APPROVED_PATH)
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (memoria.MEMORY_PATH, memoria.PROPOSALS_PATH, memoria.APPROVED_PATH, memoria.DAY2_PATH,
             memoria.DECISIONS_PATH, memoria.DAY2_FALLBACK_PATH, memoria.LOCAL_APPROVED_PATH) = (d / "m.json", d / "p.json", d / "a.json", d / "d2.json", d / "dec.json", d / "fallback.json", d / "local-approved.json")
            try:
                empty = c.get("/api/memoria").json()
                self.assertEqual((empty["available"], empty["proposals"], empty["comparison"]), (False, [], None))
                self.assertEqual(c.get("/memoria").status_code, 200)
                (d / "m.json").write_text(json.dumps({"observations": [{"text": "La reposición de agua tardó 25 min, no 12", "n": 3}]}), "utf-8")
                (d / "p.json").write_text(json.dumps({"changes": [{"id": "agua-antes", "param": "resupply_lead_min", "key": "water_n", "old": 12, "new": 25,
                                                                   "text": "pedir agua antes", "evidence": {"minutes_mean": 25}, "n": 3}]}), "utf-8")
                (d / "a.json").write_text(json.dumps({"approved_changes": [], "values": {"x": 1}}), "utf-8")
                (d / "d2.json").write_text(json.dumps({"n": 40, "metrics": [{"name": "roturas de stock", "before": 5, "after": 4, "ci": [-3, 1],
                                                                              "significant": False}]}), "utf-8")
                full = c.get("/api/memoria").json()
                self.assertEqual(full["comparison"]["verdict"], "sin evidencia de mejora")
                self.assertEqual(TestClient(app, client=("192.168.1.9", 5000)).post("/api/memoria/decide", json={"id": "agua-antes", "approve": True}).status_code, 403)
                self.assertEqual(c.post("/api/memoria/decide", json={"id": "agua-antes", "approve": True, "by": "Ana"}).status_code, 200)
                self.assertEqual(json.loads((d / "a.json").read_text("utf-8")), {"approved_changes": [], "values": {"x": 1}},
                                 "params.approved.json es de Mando: el panel no lo reescribe")
                prop = c.get("/api/memoria").json()["proposals"][0]
                self.assertEqual((prop["decision"]["status"], prop["decision"]["by"], prop["param"], prop["from"], prop["value"]),
                                 ("approved", "Ana", "resupply_lead_min[water_n]", 12, 25))
                c.post("/api/memoria/decide", json={"id": "agua-antes", "approve": False})
                self.assertEqual(json.loads((d / "dec.json").read_text("utf-8"))["decisions"][0]["status"], "rejected")
                self.assertEqual(c.post("/api/memoria/decide", json={"id": "no-existe", "approve": True}).status_code, 404)
            finally:
                (memoria.MEMORY_PATH, memoria.PROPOSALS_PATH, memoria.APPROVED_PATH, memoria.DAY2_PATH, memoria.DECISIONS_PATH, memoria.DAY2_FALLBACK_PATH, memoria.LOCAL_APPROVED_PATH) = old

    def test_doctor_says_what_is_missing(self) -> None:
        tg_port, hr_port = free_port(), free_port()
        env = {"HR_SECRET": "un-secreto-largo-de-prueba", "MANDO_ALLOWED_NUMBERS": "+34600000002,112", "TELEGRAM_BOT_TOKEN": TOKEN,
               "TELEGRAM_API_BASE": f"http://127.0.0.1:{tg_port}", "HR_HOOK_DISPATCH": f"http://127.0.0.1:{hr_port}/hooks/despacho",
               "MANDO_VOICE_MODE": "phone"}
        mock = create_mock(secret=SECRET)
        with Served(create_mock_telegram(), tg_port), Served(mock, hr_port):
            rows = {name: (level, text) for level, name, text in reversed(doctor.checks(env))}
        self.assertEqual(rows["TELEGRAM_BOT_TOKEN"][0], doctor.OK)
        self.assertIn("@mando_demo_bot", rows["TELEGRAM_BOT_TOKEN"][1])
        self.assertEqual(rows["HR_HOOK_DISPATCH"][0], doctor.OK)
        self.assertEqual(mock.state.received, [], "comprobar el hook NO lanza ninguna llamada")
        self.assertEqual(rows["MANDO_PUBLIC_URL"][0], doctor.MISSING)
        self.assertEqual(rows["MANDO_ALLOWED_NUMBERS"][0], doctor.MISSING, "un 112 en la lista blanca es un error")
        self.assertNotIn("un-secreto-largo-de-prueba", json.dumps(rows))
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = doctor.main()
        self.assertEqual(code, 1)
        self.assertIn("FALTA:", buf.getvalue())


class FakeIntake:
    """Un `IntakeSession` de mentira con la interfaz acordada: emite el aviso en cuanto tiene lo mínimo (QUÉ) y sigue preguntando."""

    def __init__(self, channel="web", lang="es", zone_hint=None, profile=None, understand=None) -> None:
        self.zone_hint, self.what, self.where, self.asked = zone_hint, "", "", ""

    def receive(self, text: str) -> dict:
        reports = []
        if not self.what:
            self.what = text
            reports.append({"text": text, "channel": "whatsapp", "zone_hint": self.zone_hint})
            say, why, done = "Aviso recibido. ¿Dónde estás? Dime la zona o algo que veas cerca.", "falta DÓNDE", False
        elif not self.where:
            self.where = text
            reports.append({"text": f"{self.what}. Lugar: {text}", "channel": "whatsapp", "zone_hint": self.zone_hint})
            say, why, done = "Entendido. ¿Responde cuando le hablas?", "falta saber si responde", False
        else:
            say, why, done = "Gracias. Si cambia algo, escribe aquí.", None, True
        return {"say": say, "instruction": "Aléjate y no te enfrentes. Ve hacia el personal con chaleco.", "reports": reports,
                "state": {"que": self.what, "donde": self.where or None}, "why_next": why, "done": done}

    def mando_asks(self, question: str) -> dict:
        self.asked = question
        return {"say": "El centro de control pregunta: " + question}

    def notify(self, status: str) -> dict:
        return {"say": f"[{status}] " + chat.STATUS_ES[status]}


class ChatTest(EnvTest):
    ENV = {"TELEGRAM_BOT_TOKEN": "", "HR_HOOK_INTAKE": "", "MANDO_PUBLIC_URL": "", "MANDO_ASK_WAIT_S": "30"}

    def test_degrades_to_report_and_says_so(self) -> None:
        old, chat.load_intake = chat.load_intake, lambda: None
        try:
            c = TestClient(self.app())
            out = c.post("/api/chat", json={"text": "sale humo de un puesto de comida", "channel": "web", "zone_hint": "food"}).json()
            self.assertTrue(out["degraded"])
            self.assertIn("degrada a /api/report", out["why"])
            self.assertTrue(out["report_id"].startswith("j-"))
            self.assertEqual(out["instruction"]["steps"], ["Aléjate de ahí y no vuelvas. Avisa a los de alrededor."])
        finally:
            chat.load_intake = old

    def test_three_turn_conversation_ends_in_dispatch(self) -> None:
        old, chat.load_intake = chat.load_intake, lambda: FakeIntake
        try:
            app = self.app("demo-1")
            c, s = TestClient(app), app.state.session
            t1 = c.post("/api/chat", json={"text": "hay una pelea muy fuerte, se están pegando varios", "channel": "web"}).json()
            sid = t1["session_id"]
            self.assertEqual((t1["degraded"], t1["done"], len(t1["reports"])), (False, False, 1), "el primer aviso sale YA, sin esperar al final")
            self.assertIn("¿Dónde estás?", t1["say"])
            s.tick()
            t2 = c.post("/api/chat", json={"session_id": sid, "text": "en restauración, junto a las barras"}).json()
            self.assertEqual((t2["session_id"], t2["report_id"], len(t2["reports"])), (sid, t1["report_id"], 1))
            t3 = c.post("/api/chat", json={"session_id": sid, "text": "sí, responden, pero siguen pegándose"}).json()
            self.assertTrue(t3["done"])
            for _ in range(10):
                s.tick()
            st = s.state()
            mine = [r for r in st["reports"] if r.get("chat")]
            self.assertEqual(len(mine), 2)
            self.assertEqual(mine[1]["chat"]["update_of"], t1["report_id"], "la actualización queda enlazada al primer aviso")
            self.assertEqual(mine[0]["chat"]["state"]["donde"], "en restauración, junto a las barras", "las fichas se rellenan en vivo")
            self.assertTrue(mine[0]["chat"]["instruction"])
            inc = next(i for i in st["incidents"] if t1["report_id"] in i["reports"])
            self.assertTrue(any(a["kind"] == "dispatch" and a["incident"] == inc["id"] for a in st["actions"]), "la conversación acaba en DESPACHO")
            self.assertTrue(wait_for(lambda: any(e["type"] == "status" for e in app.state.chat.events_after(sid, 0)), 4))
            with c.stream("GET", f"/api/chat/{sid}/events?limit=1") as r:
                body = "".join(r.iter_text())
            self.assertIn("event: ", body)
            self.assertEqual(c.get("/api/chat/no-existe/events").status_code, 404)
        finally:
            chat.load_intake = old

    def test_mando_question_goes_into_the_conversation(self) -> None:
        old, chat.load_intake = chat.load_intake, lambda: FakeIntake
        try:
            app = self.app("demo-1")
            c, s, hub = TestClient(app), app.state.session, app.state.chat
            sid = c.post("/api/chat", json={"text": "hay una pelea muy fuerte, se están pegando varios"}).json()["session_id"]
            for _ in range(5):
                s.tick()
            asks = [e for e in hub.events_after(sid, 0) if e["type"] == "ask"]
            self.assertTrue(asks and asks[0]["text"].startswith("El centro de control pregunta:"), "el ASK de Mando entra en SU conversación")
            out = c.post("/api/chat", json={"session_id": sid, "text": "en restauración"}).json()
            self.assertTrue(out["answered_mando"])
            for _ in range(2):
                s.tick()
            self.assertEqual(s.comms.calls[asks[0]["action_id"]]["result"], "answer", "y la respuesta vuelve a Mando")
        finally:
            chat.load_intake = old


if __name__ == "__main__":
    unittest.main()
