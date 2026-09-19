"""Contrato Sala/Telegram → run rápido → tools MANDO (HTTP simulado, sin red)."""
from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from motor.server.app import create_app
from motor.server.rapido import configuration


class RapidoTest(unittest.TestCase):
    def setUp(self) -> None:
        env = patch.dict(os.environ, {
            "MANDO_CEREBRO": "agente", "HR_WORKFLOW_RAPIDO": "workflow-rapido",
            "HR_API_BASE": "https://hr.test/api/v2", "HR_API_KEY": "api-key-test",
            "HR_ENV": "development", "HR_SECRET": "callback-test",
            "MANDO_PUBLIC_URL": "https://mando.test", "MANDO_OPERATOR_TOKEN": "operator-test",
            "MANDO_CEREBRO_TIMEOUT_S": "0.5", "TELEGRAM_MODE": "off",
            "MANDO_DB": "off", "MANDO_LEDGER_PATH": "", "MANDO_TG_ROSTER": "off",
        })
        env.start()
        self.addCleanup(env.stop)
        poll = patch("motor.server.rapido.POLL_S", 0.01)
        poll.start()
        self.addCleanup(poll.stop)
        self.app = create_app("demo-gates", threaded=False, comms_mode="sim", secret="callback-test")
        self.s = self.app.state.session
        self.c = TestClient(self.app)
        self.addCleanup(self.app.state.chat.stop)
        self.addCleanup(lambda: self.s.close())
        self.addCleanup(self.c.close)
        self.payloads: list[dict] = []
        self.remote_status = "running"
        self.callback = False
        self.launch_error = False
        self.queued = False
        client = httpx.Client
        clients = patch("motor.server.rapido.httpx.Client", side_effect=lambda **kw: client(
            transport=httpx.MockTransport(self.http), **kw))
        clients.start()
        self.addCleanup(clients.stop)
        self.h = {"X-Mando-Operator": "operator-test"}

    def http(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            self.assertEqual(str(request.url), "https://hr.test/api/v2/workflows/workflow-rapido/runs")
            self.assertEqual(request.headers["authorization"], "Bearer api-key-test")
            data = json.loads(request.content)
            self.payloads.append(data)
            if self.launch_error:
                return httpx.Response(503, json={"detail": "api-key-test must never be logged"})
            return httpx.Response(200, json={"queued_run_ids": ["run-test"]} if self.queued else {"run_id": "run-test"})
        self.assertEqual(str(request.url), "https://hr.test/api/v2/runs/run-test")
        if self.callback:
            self.callback = False
            self.decide()
        return httpx.Response(200, json={"status": self.remote_status})

    def launch(self, **extra) -> httpx.Response:
        data = {"text": "Hay una pelea en la puerta B", "zone": "gate_b", "request_id": "sala-test"}
        data.update(extra)
        return self.c.post("/api/workflows/rapido", json=data, headers=self.h)

    def wait(self) -> None:
        for thread in self.s.rapido.threads:
            thread.join(timeout=3)
            self.assertFalse(thread.is_alive())

    def row(self) -> dict:
        return self.s.rapido.view()["runs"][0]

    def decide(self, **extra) -> dict:
        data = {"agente": "rapido", "fase": "rapida", "incident_id": self.row()["incident_id"],
                "tipo": "security", "zona": "gate_b", "prioridad": 8,
                "porque": "Contener la pelea con seguridad", "recursos": ["sec_2"]}
        data.update(extra)
        response = self.c.post("/hr/tools/decidir", json=data, headers={"X-Mando-Token": "callback-test"})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_launch_callback_and_revision_keep_same_incident(self) -> None:
        self.callback = True
        response = self.launch()
        self.assertEqual(response.status_code, 200, response.text)
        self.wait()
        row = self.row()
        self.assertEqual(row["status"], "decision_recibida")
        self.assertTrue(row["rapida"])
        self.assertFalse(row["revision"])
        payload = self.payloads[0]["payload"]
        self.assertEqual(self.payloads[0]["environment"], "development")
        self.assertEqual(payload["callback_url"], "https://mando.test")
        self.assertEqual(payload["callback_token"], "callback-test")
        self.assertEqual(set(payload), {"entrada_json", "callback_url", "callback_token", "texto", "canal",
                                       "zona_sugerida", "idioma", "remitente", "correlation_id", "transcripcion"})
        self.assertEqual(json.loads(payload["entrada_json"])["incident_id"], row["incident_id"])
        self.assertEqual(payload["canal"], "web")
        self.assertEqual(payload["remitente"], "informante")
        self.decide(fase="revision", agente="equipo", veredicto="confirma")
        self.assertTrue(self.row()["revision"])
        self.assertEqual(len(self.payloads), 1)
        self.assertEqual(self.c.get("/api/state").json()["workflow_rapido"]["runs"][0]["status"],
                         "decision_recibida")
        self.assertEqual(self.s.comms.view()["real_sent"], 0)

    def test_retry_request_and_next_ticks_do_not_launch_again(self) -> None:
        self.callback = True
        first = self.launch()
        self.wait()
        second = self.launch()
        self.assertEqual(second.json()["report_id"], first.json()["report_id"])
        self.assertTrue(second.json()["duplicate"])
        self.s.tick()
        self.s.tick()
        self.assertEqual(len(self.payloads), 1)
        self.assertEqual(self.launch(text="Otro aviso").status_code, 409)

    def test_missing_configuration_and_bad_input_have_no_effects(self) -> None:
        before = len(self.s.world.reports)
        with patch.dict(os.environ, {"HR_WORKFLOW_RAPIDO": ""}):
            self.assertEqual(self.launch().status_code, 503)
        for data in ({"text": ""}, {"text": "x" * 401}, {"zone": "unknown"},
                     {"request_id": "../bad"}, {"zone": []}):
            with self.subTest(data=data):
                self.assertEqual(self.launch(**data).status_code, 422)
        self.assertEqual(len(self.s.world.reports), before)
        self.assertEqual(self.payloads, [])

    def test_operator_is_required(self) -> None:
        self.h = {}
        self.assertEqual(self.launch().status_code, 401)
        self.assertEqual(self.payloads, [])

    def test_telegram_callback_enters_same_runner_once(self) -> None:
        self.callback = True
        event = {"schema": "mando.hr.v1", "type": "public_report", "event_id": "tg-event-1",
                 "channel": "telegram", "report": {"text": "Pelea en la puerta B", "zone_hint": "gate_b",
                                                   "source": "asistente", "channel": "telegram"}}
        headers = {"X-Mando-Token": "callback-test"}
        first = self.c.post("/hr/events", json=event, headers=headers)
        self.assertEqual(first.status_code, 200, first.text)
        self.s.tick()
        self.s.tick()
        self.wait()
        second = self.c.post("/hr/events", json=event, headers=headers)
        self.assertTrue(second.json()["duplicate"])
        self.s.tick()
        self.assertEqual(len(self.payloads), 1)
        self.assertEqual(self.payloads[0]["payload"]["canal"], "telegram")
        self.assertEqual(self.row()["status"], "decision_recibida")

    def test_success_without_callback_times_out(self) -> None:
        self.remote_status = "succeeded"
        self.assertEqual(self.launch().status_code, 200)
        self.wait()
        self.assertEqual(self.row()["status"], "timeout")
        self.assertFalse(self.row()["rapida"])
        self.assertEqual(len(self.payloads), 1)

    def test_failed_launch_is_not_retried_or_leaked(self) -> None:
        self.launch_error = True
        self.assertEqual(self.launch().status_code, 200)
        self.wait()
        self.assertEqual(self.row()["status"], "fallido")
        self.s.tick()
        self.assertEqual(len(self.payloads), 1)
        state = self.c.get("/api/state").text
        for secret in ("api-key-test", "callback-test", "operator-test"):
            self.assertNotIn(secret, state)

    def test_queued_run_id_and_failed_run_are_visible(self) -> None:
        self.queued = True
        self.remote_status = "failed"
        self.launch()
        self.wait()
        self.assertEqual(self.row()["run_id"], "run-test")
        self.assertEqual(self.row()["status"], "fallido")

    def test_bad_callback_url_and_abanico_do_not_launch(self) -> None:
        for env in ({"MANDO_PUBLIC_URL": "https://mando.test/hr/events"},
                    {"MANDO_PUBLIC_URL": "https://user:secret@mando.test"},
                    {"HR_ENV": "invalid"}, {"MANDO_CEREBRO": "abanico"}):
            with self.subTest(env=env), patch.dict(os.environ, env):
                self.assertFalse(configuration()["ready"])
                self.assertEqual(self.launch().status_code, 503)
        self.assertEqual(self.payloads, [])

    def test_late_callback_does_not_repeat_dispatch(self) -> None:
        self.launch()
        self.wait()
        self.assertEqual(self.row()["status"], "timeout")
        self.decide()
        actions = list(self.s.agent.actions)
        self.decide()
        self.assertEqual(list(self.s.agent.actions), actions)
        self.assertEqual(self.row()["status"], "decision_recibida")

    def test_correlation_binds_new_to_existing_and_rejects_other_incident(self) -> None:
        self.launch()
        self.wait()
        row = self.row()
        before = len(self.s.agent.incidents)
        result = self.decide(incident_id="nuevo", correlation_id=row["correlation_id"])
        self.assertEqual(result["incident_id"], row["incident_id"])
        self.assertEqual(len(self.s.agent.incidents), before)
        bad = self.c.post("/hr/tools/decidir", headers={"X-Mando-Token": "callback-test"}, json={
            "agente": "rapido", "fase": "rapida", "incident_id": "other",
            "correlation_id": row["correlation_id"], "porque": "Otro incidente",
        })
        self.assertEqual(bad.status_code, 422)
        self.assertEqual(len(self.s.agent.incidents), before)

    def test_reset_rejects_callback_from_old_session(self) -> None:
        self.launch()
        self.wait()
        row = self.row()
        result = self.c.post("/api/control", headers=self.h, json={"cmd": "reset"})
        self.assertEqual(result.status_code, 200, result.text)
        self.s = self.app.state.session
        before = len(self.s.agent.incidents)
        late = self.c.post("/hr/tools/decidir", headers={"X-Mando-Token": "callback-test"}, json={
            "agente": "rapido", "fase": "rapida", "incident_id": row["incident_id"],
            "correlation_id": row["correlation_id"], "porque": "Callback antiguo",
        })
        self.assertEqual(late.status_code, 422)
        self.assertEqual(len(self.s.agent.incidents), before)

    def test_blocked_decision_is_received_without_claiming_success(self) -> None:
        self.launch()
        self.wait()
        with patch("motor.server.enjambre.gate_decidir", return_value={
            "ok": False, "texto": "Objeción pendiente", "bloqueadas": [], "aceptadas": [],
        }):
            result = self.decide()
        self.assertFalse(result["ok"])
        self.assertTrue(self.row()["rapida"])
        self.assertEqual(self.row()["status"], "decision_bloqueada")
        self.assertEqual(self.row()["error"], "")


if __name__ == "__main__":
    unittest.main()
