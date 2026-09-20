"""Verificación de la cadena Telegram ↔ HappyRobot ↔ MANDO (3 pruebas, sin red externa).

Levanta de verdad los tres procesos en localhost:

    Telegram (simulado)  →  puente real (Express)  →  MANDO real (FastAPI/SQLite)  →  HappyRobot falso (HTTP)

y comprueba, en este orden:

  1. Telegram llega a HappyRobot: un mensaje del bot se persiste en MANDO y el puente
     entrega el aviso (`public_report`) a HappyRobot.
  2. HappyRobot decide: MANDO NO elige a quién avisar, y la decisión de HappyRobot
     (su espejo) es lo que aparece en el estado que pinta la interfaz.
  3. Override del operador: si la Sala anula esa decisión, MANDO registra el hecho y
     entrega la coordinación a HappyRobot (él manda el mensaje y conversa con el
     informante), en vez de hablar por su propio bot.

Es SIMULACIÓN: no hay tokens reales, ni BotFather, ni llamadas a api.telegram.org ni a
la plataforma de HappyRobot. Ejecutar:

    ./motor/server/.venv/bin/python -m motor.server.test_chain_telegram_happyrobot
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast

REPO = Path(__file__).resolve().parents[2]
PUENTE = REPO / "puente"
TSX = PUENTE / "node_modules" / ".bin" / "tsx"

WEBHOOK_SECRET = "e2e-telegram-secret"
BRIDGE_SECRET = "e2e-bridge-secret"
HR_SECRET = "e2e-hr-secret"
OPERATOR_TOKEN = "e2e-operator-token"
REPORTER_CHAT = "55501"
STAFF_CHAT = "55502"
REPORT_TEXT = "Una persona se ha desmayado junto al escenario 1"
INCIDENT_MIRROR_ID = "tg-55501-1001"


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def http_json(
    url: str, body: dict[str, Any] | None = None, headers: dict[str, str] | None = None
) -> tuple[int, Any]:
    import urllib.error
    import urllib.request

    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    request.add_header("content-type", "application/json")
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read().decode()
            return response.status, (json.loads(raw) if raw.strip() else None)
    except urllib.error.HTTPError as error:
        raw = error.read().decode()
        try:
            return error.code, json.loads(raw) if raw.strip() else None
        except json.JSONDecodeError:
            return error.code, raw


class FakeHappyRobot:
    """Receptor falso: apunta cada POST y responde como la plataforma."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.port = free_port()
        parent = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self) -> None:  # noqa: N802 (API de BaseHTTPRequestHandler)
                length = int(self.headers.get("content-length") or 0)
                raw = self.rfile.read(length).decode() if length else ""
                try:
                    body = json.loads(raw) if raw.strip() else {}
                except json.JSONDecodeError:
                    body = {"_raw": raw}
                parent.calls.append({"path": self.path, "body": body})
                payload = {"run_id": "run-e2e-1", "queued_run_ids": ["run-e2e-1"]}
                encoded = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, *_args: Any) -> None:
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def matching(self, path: str) -> list[dict[str, Any]]:
        return [call for call in self.calls if call["path"] == path]

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


class ChainTest(unittest.TestCase):
    """Las tres pruebas comparten el montaje; cada una comprueba un eslabón."""

    @classmethod
    def setUpClass(cls) -> None:
        if not TSX.exists():
            raise unittest.SkipTest(
                f"Falta el puente instalado ({TSX}); ejecuta `npm ci` en puente/."
            )
        from .operational_http import create_operational_app

        cls.directory = TemporaryDirectory()
        cls._saved_env = dict(os.environ)
        # Este montaje cambia el entorno del proceso (es un despliegue real). Se registra
        # como limpieza de clase para que se restaure incluso si setUpClass falla a mitad:
        # si no, el entorno sucio haría fallar en cascada al resto de la suite.
        cls.addClassCleanup(cls._restore_env)
        cls.happyrobot = FakeHappyRobot()
        cls.mando_port = free_port()
        cls.bridge_port = free_port()

        # ── MANDO operativo (FastAPI + SQLite), como en el despliegue ──────────
        os.environ.update(
            {
                "MANDO_OPERATIONAL": "1",
                "MANDO_OPERATIONAL_DB": str(
                    Path(cls.directory.name) / "operations.sqlite"
                ),
                "MANDO_BRIDGE_SECRET": BRIDGE_SECRET,
                "HR_SECRET": HR_SECRET,
                "MANDO_EXTERNAL_DELIVERY": "1",
                "MANDO_PUBLIC_URL": "https://mando.invalid/festival",
                "HR_API_BASE": f"http://127.0.0.1:{cls.happyrobot.port}/api/v2",
                "HR_API_KEY": "e2e-key",
                "HR_ENV": "development",
                "HR_WORKFLOW_TG_OFFER": "wf-tg-offer",
                "HR_HOOK_TG_ROSTER": f"http://127.0.0.1:{cls.happyrobot.port}/roster",
                "HR_WORKFLOW_RAPIDO": "",
                "MANDO_HAPPYROBOT_DECIDES": "1",
                "MANDO_OPERATOR_TOKEN": OPERATOR_TOKEN,
                "MANDO_OPERATORS": "",
                "MANDO_CONTROL_CHAT_ID": "",
            }
        )
        import uvicorn

        config = uvicorn.Config(
            create_operational_app(port=cls.mando_port),
            host="127.0.0.1",
            port=cls.mando_port,
            log_level="error",
        )
        cls.mando = uvicorn.Server(config)
        cls.mando_thread = threading.Thread(target=cls.mando.run, daemon=True)
        cls.mando_thread.start()

        # ── Puente real (Express), apuntando a MANDO y a HappyRobot ────────────
        bridge_env = {
            **os.environ,
            "PORT": str(cls.bridge_port),
            "MANDO_OPERATIONAL": "1",
            "TELEGRAM_MODE": "webhook",
            "TELEGRAM_WEBHOOK_SECRET": WEBHOOK_SECRET,
            "MANDO_BACKEND_URL": f"http://127.0.0.1:{cls.mando_port}",
            "MANDO_BRIDGE_SECRET": BRIDGE_SECRET,
            "HR_SECRET": HR_SECRET,
            "HR_HOOK_TG": f"http://127.0.0.1:{cls.happyrobot.port}/intake",
            "HR_HOOK_TG_RESPONSE": f"http://127.0.0.1:{cls.happyrobot.port}/response",
            "HR_HOOK_TG_ROSTER": f"http://127.0.0.1:{cls.happyrobot.port}/roster",
            # Sin token: el puente no llama a api.telegram.org en estas pruebas.
            "TELEGRAM_BOT_TOKEN": "",
            "REQUIRE_SECRETS": "0",
        }
        bridge_env.pop("VERCEL", None)
        bridge_env.pop("NODE_ENV", None)
        cls.bridge = subprocess.Popen(
            [str(TSX), "src/index.ts"],
            cwd=str(PUENTE),
            env=bridge_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        cls._wait(
            f"http://127.0.0.1:{cls.bridge_port}/health", "el puente", expect=200
        )
        cls._wait(
            f"http://127.0.0.1:{cls.mando_port}/api/operations/state",
            "MANDO",
            headers={"X-Mando-Operator": OPERATOR_TOKEN},
            expect=200,
        )

    @classmethod
    def _restore_env(cls) -> None:
        os.environ.clear()
        os.environ.update(cls._saved_env)

    @classmethod
    def tearDownClass(cls) -> None:
        if getattr(cls, "bridge", None) is not None:
            cls.bridge.terminate()
            try:
                cls.bridge.wait(timeout=10)
            except subprocess.TimeoutExpired:
                cls.bridge.kill()
        if getattr(cls, "mando", None) is not None:
            cls.mando.should_exit = True
            cls.mando_thread.join(timeout=10)
        if getattr(cls, "happyrobot", None) is not None:
            cls.happyrobot.close()
        if getattr(cls, "directory", None) is not None:
            cls.directory.cleanup()
        # El entorno lo restaura la limpieza de clase registrada en setUpClass.

    # ── utilidades ────────────────────────────────────────────────────────────
    @classmethod
    def _wait(
        cls,
        url: str,
        what: str,
        *,
        headers: dict[str, str] | None = None,
        expect: int = 200,
        seconds: float = 25.0,
    ) -> None:
        deadline = time.monotonic() + seconds
        last: Any = None
        while time.monotonic() < deadline:
            try:
                status, last = http_json(url, headers=headers)
                if status == expect:
                    return
            except OSError as error:  # el puerto aún no escucha
                last = error
            time.sleep(0.2)
        raise AssertionError(f"{what} no respondió {expect} a tiempo (último: {last!r})")

    @classmethod
    def bridge_url(cls, path: str) -> str:
        return f"http://127.0.0.1:{cls.bridge_port}{path}"

    @classmethod
    def mando_url(cls, path: str) -> str:
        return f"http://127.0.0.1:{cls.mando_port}{path}"

    @classmethod
    def operator(cls) -> dict[str, str]:
        return {"X-Mando-Operator": OPERATOR_TOKEN}

    @classmethod
    def state(cls) -> dict[str, Any]:
        status, body = http_json(cls.mando_url("/api/operations/state"), headers=cls.operator())
        assert status == 200, body
        return cast(dict[str, Any], body)

    @classmethod
    def command(cls, kind: str, **fields: Any) -> dict[str, Any]:
        status, body = http_json(
            cls.mando_url("/api/operations/command"),
            {"command_id": f"e2e-{kind}-{time.monotonic_ns()}", "kind": kind, **fields},
            cls.operator(),
        )
        assert status == 200, body
        return cast(dict[str, Any], body)

    @classmethod
    def wait_for(cls, predicate, what: str, seconds: float = 20.0):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            value = predicate()
            if value:
                return value
            time.sleep(0.25)
        raise AssertionError(f"No se cumplió a tiempo: {what}")

    # ── prueba 1 ──────────────────────────────────────────────────────────────
    def test_01_telegram_llega_a_happyrobot(self) -> None:
        """Un mensaje del bot se persiste en MANDO y viaja a HappyRobot."""
        update = {
            "update_id": 1001,
            "message": {
                "message_id": 11,
                "date": 1789886400,
                "from": {"id": int(REPORTER_CHAT), "first_name": "Asistente"},
                "chat": {"id": int(REPORTER_CHAT), "type": "private"},
                "text": REPORT_TEXT,
            },
        }
        status, body = http_json(
            self.bridge_url("/telegram/webhook"),
            update,
            {"X-Telegram-Bot-Api-Secret-Token": WEBHOOK_SECRET},
        )
        self.assertEqual(status, 200, body)
        self.assertTrue(body["ok"], body)
        self.assertFalse(body["duplicate"], body)

        # MANDO es la autoridad: persistió el aviso antes de contestar.
        state = self.state()
        self.assertEqual(len(state["incidents"]), 1, state["incidents"])
        incident = state["incidents"][0]
        self.assertEqual(incident["text"], REPORT_TEXT)
        self.assertEqual(incident["zone"], "front_pit")

        # HappyRobot recibió el aviso para decidir a quién avisar.
        intake = self.wait_for(
            lambda: self.happyrobot.matching("/intake"), "el aviso en HappyRobot"
        )
        self.assertEqual(len(intake), 1, self.happyrobot.calls)
        report = intake[0]["body"]
        self.assertEqual(report["event"], "public_report")
        self.assertEqual(report["channel"], "telegram")
        self.assertEqual(report["reporter"]["chat_id"], REPORTER_CHAT)
        self.assertEqual(report["reporter"]["external_id"], f"tg:{REPORTER_CHAT}")
        self.assertEqual(report["correlation_id"], f"tg-{REPORTER_CHAT}-1001")

    # ── prueba 2 ──────────────────────────────────────────────────────────────
    def test_02_happyrobot_decide_y_mando_no_elige(self) -> None:
        """La decisión es de HappyRobot; MANDO sólo la refleja."""
        # MANDO no ha creado ninguna oferta para el aviso del bot.
        state = self.state()
        self.assertEqual(state["assignments"], [], state["assignments"])
        self.assertIn("coordinacion_happyrobot", state["incidents"][0]["why_waiting"])
        self.assertEqual(
            [d for d in state["deliveries"] if d["channel"] == "telegram"], []
        )

        # HappyRobot decide (lo que manda `fa-despacho-tg`) y el puente lo espeja.
        status, body = http_json(
            self.bridge_url("/hr/events"),
            {
                "event": "telegram_send",
                "chat_id": STAFF_CHAT,
                "text": "¿Puedes acudir? (simulación)",
                "correlation_id": INCIDENT_MIRROR_ID,
                "mirror": [
                    {
                        "type": "tg_incident",
                        "id": INCIDENT_MIRROR_ID,
                        "texto": REPORT_TEXT,
                        "tipo": "medica",
                        "zona": "front_pit",
                        "gravedad": "emergencia",
                        "alias_informante": "Asistente",
                    },
                    {
                        "type": "tg_assignment",
                        "incident_id": INCIDENT_MIRROR_ID,
                        "rol": "medico",
                        "estado": "accepted",
                        "alias": "Marta",
                        "eta_min": 3,
                        "from_zone": "gate_a",
                        "intento": 1,
                    },
                ],
            },
            {"x-hr-secret": HR_SECRET},
        )
        self.assertEqual(status, 200, body)
        self.assertTrue(body["mirror"]["ok"], body)
        self.assertTrue(body["telegram"]["skipped"], body)  # sin token real

        # La interfaz ya ve la decisión de HappyRobot, y MANDO sigue sin asignar.
        telegram = self.state()["telegram"]
        self.assertEqual(telegram["incidents"][INCIDENT_MIRROR_ID]["zona"], "front_pit")
        rows = telegram["assignments"]
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual(rows[0]["rol"], "medico")
        self.assertEqual(rows[0]["alias"], "Marta")
        self.assertEqual(rows[0]["estado"], "accepted")
        self.assertEqual(rows[0]["eta_min"], 3)
        self.assertEqual(rows[0]["desde_zona"], "gate_a")
        self.assertEqual(self.state()["assignments"], [])

    # ── prueba 3 ──────────────────────────────────────────────────────────────
    def test_03_override_del_operador_pasa_por_happyrobot(self) -> None:
        """Si la Sala anula la decisión, HappyRobot manda el mensaje y conversa."""
        incident = self.state()["incidents"][0]
        self.command(
            "register_actor",
            actor_id=f"tg:{STAFF_CHAT}",
            name="Marta",
            roles=["medico"],
            channel="telegram",
            address=STAFF_CHAT,
            zone="front_pit",
            availability="available",
        )
        self.command(
            "offer",
            incident_id=incident["id"],
            actor_id=f"tg:{STAFF_CHAT}",
            role="medico",
            expected_version=incident["version"],
        )

        # MANDO registra el hecho pero delega el mensaje en HappyRobot.
        delivery = self.wait_for(
            lambda: [
                d for d in self.state()["deliveries"] if d["channel"] == "happyrobot"
            ],
            "la entrega delegada a HappyRobot",
        )
        self.assertEqual(delivery[0]["purpose"], "offer", delivery)
        # El contacto privado no se publica en el estado: se enmascara.
        self.assertTrue(delivery[0]["recipient_id"].startswith("tg:"), delivery)
        self.assertNotIn(STAFF_CHAT, delivery[0]["recipient_id"])
        self.assertEqual(self.state()["assignments"][0]["status"], "offered")

        launched = self.wait_for(
            lambda: self.happyrobot.matching("/api/v2/workflows/wf-tg-offer/runs"),
            "el lanzamiento del despacho en HappyRobot",
        )
        payload = launched[0]["body"]["payload"]
        self.assertEqual(payload["mode"], "new")
        self.assertEqual(payload["rol"], "medico")
        self.assertEqual(payload["roles_orden"], "medico")
        self.assertEqual(payload["reporter_chat_id"], REPORTER_CHAT)
        self.assertEqual(payload["zona"], "front_pit")
        self.assertEqual(payload["override"], "true")
        self.assertTrue(payload["callback_url"].startswith("https://"))
        # HappyRobot recibe el texto a enviar y su correlación de vuelta.
        self.assertIn("¿Puedes atender el aviso", payload["texto"])
        self.assertTrue(payload["callback_token"])

        # Y el aviso va a ESA persona: MANDO le asigna el puesto en el roster de
        # HappyRobot antes de lanzar el despacho, para que no elija a otra del rol.
        claims = self.happyrobot.matching("/roster")
        self.assertTrue(claims, self.happyrobot.calls)
        self.assertEqual(
            claims[0]["body"],
            {"action": "claim", "role": "medico", "chat_id": STAFF_CHAT, "alias": "Marta"},
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
