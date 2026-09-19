"""Catálogo ejecutable de entradas; ningún contacto, .env ni servicio externo.

Cada fila CUBIERTO/PARCIAL genera un test HTTP independiente. PARCIAL solo
acredita la porción explicitada en CATALOGO-NOTIFICACIONES, nunca un conector
remoto ni precisión clínica. Ejecutar con el Python de motor/server.
"""
import json
import os
import time
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from motor.cases.taxonomy import TAXONOMY, ZONES
from motor.contracts import Action, ActionKind, ActionStatus, Autonomy
from motor.server.app import create_app
from motor.server.mock_telegram import TOKEN, create_mock_telegram
from motor.server.test_server import Served, free_port, wait_for


ROWS = []
# Oráculo del contrato, deliberadamente independiente de la tabla de producción.
EXPECTED_CHANNEL = {"voice": "voice", "web_call": "voice", "phone": "voice",
    "telegram": "whatsapp", "sms": "sms", "email": "sms", "web": "whatsapp",
    "chat": "whatsapp", "radio": "radio", "sensor": "sensor", "operator": "operator"}


def row(id, source, channel, kind, text, *, check="report", status="PARCIAL", zone="gate_b", **kw):
    ROWS.append(dict(id=id, source=source, channel=channel, kind=kind, text=text,
                     check=check, status=status, zone=zone, **kw))


for channel in ("voice", "web_call", "phone", "telegram", "sms", "email", "web", "chat", "radio", "sensor"):
    row("canal_" + channel, "público", channel, "heat_stroke", "Persona mareada por calor en puerta B")
for source in ("ambulancias", "médicos", "seguridad", "jefes de zona", "voluntarios", "técnicos", "barras", "accesos"):
    for channel in ("radio", "voice"):
        row("campo_" + source.replace(" ", "_") + "_" + channel, source, channel,
            "field_report", "Persona mareada por calor en puerta B")
for source, text in (("112", "Acceso rodado cortado en puerta B"), ("policía", "Pelea en puerta B"),
                     ("bomberos", "Sale humo en restauración"), ("AEMET", "Alerta de tormenta"),
                     ("Metro", "Corte de metro en la salida"), ("lanzaderas", "Lanzaderas interrumpidas"),
                     ("promotora", "Retraso del artista"), ("artista", "Cancelación del concierto"),
                     ("producción", "Corte de corriente en escenario"), ("proveedor de agua", "Agua agotada"),
                     ("proveedor eléctrico", "Generador sin combustible"), ("proveedor sanitario", "Material médico bajo mínimos")):
    row("externo_" + source.replace(" ", "_"), source, "email", "external_report", text)
for name, text in (("aforo", "Aforo 8000 personas en puerta B"), ("puerta", "Puerta B cerrada"),
                   ("densidad", "Densidad 6 personas por metro cuadrado en puerta B"),
                   ("meteo", "Alerta de tormenta viento 72 km/h"), ("agua", "Agua agotada en punto de agua norte"),
                   ("energía", "Apagón en restauración")):
    row("sensor_" + name, "sensor " + name, "sensor", name, text)

# Todos los tipos del generador, incluidos mode=state/report. En esos modos
# la frase demuestra recepción, NO reproduce por sí sola el efecto del caso.
for tid, spec in TAXONOMY.items():
    zone = spec.zones[0] if spec.zones else "general"
    row("tipo_" + tid, "operador", "operator", tid,
        spec.label + ". Lugar: " + ZONES[zone]["name"], zone=zone,
        family=spec.family.value, mode=spec.mode)

for name, text in (
    ("contradiccion", "Dicen que no responde, otro dice que está despierto en puerta B"),
    ("desmentido", "No hay incendio, era vapor en restauración"),
    ("rumor", "Me han dicho que hay una amenaza, no lo he visto"),
    ("broma", "Era una broma, aquí no pasa nada"),
    ("spam", "Compra entradas baratas oferta oferta"),
    ("idioma", "Someone collapsed at gate B and is not responding"),
    ("mezclado", "Una persona collapsed, no responde at gate B"),
    ("sin_ubicacion", "Hay alguien en el suelo"),
    ("ubicacion_vaga", "Hay alguien mal por allí cerca"),
    ("menor", "Menor perdido en baños MARCADOR_RESERVADO"),
    ("sensible", "Sumisión química en baños MARCADOR_RESERVADO"),
    ("agresion_sexual", "Agresión sexual en baños MARCADOR_RESERVADO"),
    ("multiincidente", "Pelea en puerta B y una persona no responde en restauración"),
    ("enorme", "ruido " * 1500 + "Una persona no responde en puerta B"),
    ("emojis", "🚨😱🆘💔"), ("audio_ininteligible", "[audio ininteligible]"),
    ("panico", "AYUDA AYUDA NO RESPIRA CORRED EN PUERTA B"),
):
    row("raro_" + name, "público", "web", name, text, check="chat",
        zone=None if name in ("sin_ubicacion", "ubicacion_vaga") else "gate_b")
for name in ("correccion_ubicacion", "actualizacion", "cancelacion"):
    row("raro_" + name, "público", "voice", name, "Persona mareada en puerta B", check="update")
row("duplicado", "público", "web", "duplicate_reports", "Persona mareada en puerta B", check="duplicate", status="CUBIERTO")
row("telegram_poll", "público", "telegram", "heat_stroke", "Persona mareada en puerta B", check="telegram")
row("contrato_public_report", "público", "radio", "public_report", "Persona mareada en puerta B", check="legacy_report")
row("operador_orden", "operador autenticado", "operator", "reroute", "Orden de desvío", check="order", status="CUBIERTO")
for name, data in (("vacio", {}), ("json_roto", None), ("objeto_texto", {"text": {"a": 1}}),
                   ("lista_zona", {"text": "Ayuda", "zone_hint": []})):
    row("invalido_" + name, "público", "web", name, "", check="invalid", payload=data)
for name, message, result, extra in (
    ("iniciada", "progress", None, {"stage": "call_started"}),
    ("transcript", "transcript", None, {"text": "Afirmativo", "role": "human"}),
    ("acepta", "dispatch_result", "accept", {"eta_min": 4}),
    ("rechaza", "dispatch_result", "reject", {"reason_text": "Acceso bloqueado", "reason_code": "route_blocked"}),
    ("no_respuesta", "dispatch_result", "no_answer", {"detail": "no_answer"}),
    ("buzon", "dispatch_result", "no_answer", {"detail": "voicemail"}),
    ("sip", "dispatch_result", "no_answer", {"detail": "channel_error"}),
    ("colgada", "dispatch_result", "no_answer", {"detail": "hung_up"}),
    ("clarify", "clarify_result", "answer", {"text": "En puerta B", "data": {"zone": "gate_b"}}),
    ("notify", "notify_result", "accept", {}),
    ("external", "external_result", "accept", {}),
    ("followup", "followup_result", "answer", {"text": "Estamos en puerta B"}),
):
    row("callback_" + name, "equipo", "voice", message, "", check="callback", status="CUBIERTO",
        message=message, result=result, extra=extra)
for name in ("dispatch_progress", "dispatch_result", "tardio", "duplicado", "otra_sesion", "sin_nonce"):
    row("plataforma_" + name, "HappyRobot", "web_call", name, "", check="platform", status="CUBIERTO")
row("plataforma_rechaza_telefono", "HappyRobot", "phone", "rechaza_telefono", "", check="platform", status="CUBIERTO")
for name in ("sensor_real", "radio_audio", "email_buzon", "sms_numero", "conector_112", "conector_AEMET", "webhook_firmado_proveedor"):
    row("pendiente_" + name, name, "conector externo", name, "", status="NO CUBIERTO", check="none")
for status in ("en_route", "on_scene", "stabilized", "transport", "needs_support", "route_blocked",
               "exhausted", "free", "note", "new_notice", "false_alarm"):
    row("personal_" + status, "unidad médica acreditada", "voice", "staff_status",
        "Pelea en restauración" if status == "new_notice" else "Parte de campo de prueba",
        check="staff", staff_status=status, zone="corridor_s" if status == "route_blocked" else "general")
row("personal_web_on_scene", "unidad médica acreditada", "web", "on_scene", "En el sitio, parte web",
    check="staff_web", staff_status="on_scene", zone="general")
for source, text in (("112", "Ambulancia externa en acceso A"),
                     ("AEMET", "Aviso de viento fuerte en el recinto"),
                     ("Metro", "Servicio de metro interrumpido en la salida")):
    row("aviso_externo_" + source, source, "webhook", "external_notice", text, check="external_notice", zone="gate_a")
for kind, source, channel, text in (
    ("decision", "director vinculado a solicitud", "phone", "Apruebo la parada"),
    ("decision_pending", "director vinculado a solicitud", "phone", "Necesito más información"),
    ("text_delivery_request", "workflow difusión", "webhook", "Camine hacia la salida indicada."),
    ("diffusion_result", "workflow difusión", "webhook", "Camine hacia la salida indicada."),
):
    row("ampliacion_" + kind, source, channel, kind, text, check="workflow_extension")


class NotificacionesTest(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"TELEGRAM_MODE": "off", "HR_HOOK_INTAKE": "",
            "MANDO_PUBLIC_URL": "http://127.0.0.1:1",
            "MANDO_OPERATOR_TOKEN": "operador-ficticio", "MANDO_PUBLIC_RATE_MAX": "100000"}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.contacts = patch("motor.server.comms_happyrobot.load_contacts", return_value={"resources": {}, "roles": {}})
        self.contacts.start()
        self.addCleanup(self.contacts.stop)
        self.app = create_app(threaded=False, secret="callback-ficticio", local_params=False)
        self.s = self.app.state.session
        self.c = TestClient(self.app, raise_server_exceptions=False)
        self.operator = {"X-Mando-Operator": "operador-ficticio"}
        self.hr = {"X-Mando-Token": "callback-ficticio"}
        self.addCleanup(self.s.close)
        self.addCleanup(self.app.state.chat.stop)
        self.addCleanup(self.c.close)

    def post(self, path, payload):
        r = self.c.post(path, json=payload, headers=self.hr if path.startswith("/hr") else self.operator)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def heartbeat(self):
        before = self.s.world.t
        self.post("/api/control", {"cmd": "step"})
        self.assertEqual(self.s.world.t, before + 1)
        self.assertEqual(self.s.agent_errors, 0, self.s.engine_error)
        stream = self.c.get("/api/stream?limit=1")
        self.assertEqual(stream.status_code, 200)
        self.assertIn("data:", stream.text)

    def report_payload(self, r):
        return {"type": "public_report", "event_id": r["id"], "channel": r["channel"],
                "report": {"text": r["text"], "source": r["source"], "zone_hint": r["zone"], "lang": "es"},
                "extracted": {"informant": r["source"]}}

    def flight(self):
        c = self.s.comms
        a = Action("notificacion", ActionKind.DISPATCH, self.s.world.t, resource="sec_1", zone="gate_b")
        c.calls[a.id] = {"action_id": a.id, "kind": "dispatch", "stage": "llamando", "zone": "gate_b", "resource": "sec_1"}
        c._inflight[a.id] = {"action": a, "resource": self.s.world.resources["sec_1"],
                             "started": time.monotonic(), "deadline": time.monotonic() + 60}
        c.payloads[a.id] = {"message": "dispatch_request", "action_id": a.id}
        wire = c.wire_payload(a.id)["action_id"]
        return c, a.id, wire

    def workflow_extension(self, r):
        """Contrato HTTP de borradores; transporte saliente interceptado al emitir.

        No se instala hr_routing/deliver_text ni se fabrican votos, aprobaciones,
        nonce o metadatos de llamada: send/wire_payload deben producirlos.
        """
        c, kind = self.s.comms, r["kind"]
        c.mode, c.voice_mode, c.launch_mode = "happyrobot", "phone", "hook"
        c.hooks.update(director="http://127.0.0.1:1/director", difusion="http://127.0.0.1:1/difusion")
        c.contacts = {"resources": {}, "roles": {"director": {"to_number": "+99900000000", "title": "Director ficticio"}},
                      "audiences": {"prueba": {"telegram": [1001]}}}
        c._allowed = {"+99900000000"}
        decision = kind in ("decision", "decision_pending")
        action = Action("extension-pending", ActionKind.STOP_SHOW if decision else ActionKind.BROADCAST,
            self.s.world.t, zone="gate_b", autonomy=Autonomy.APPROVE, status=ActionStatus.AWAITING_APPROVAL,
            params={} if decision else {"message": r["text"], "audience": "prueba"})
        self.s.agent.actions[action.id] = action
        # El transporte se intercepta antes de acceder a la red; los handlers y
        # contratos reales siguen instalados exclusivamente por create_app.
        with patch.object(c, "_post"), patch.dict(os.environ, {"MANDO_TWO_PERSON": "1"}):
            self.s._rebuild()
            if decision:
                request = Action("decision:" + action.id + ":director", ActionKind.NOTIFY, self.s.world.t,
                    params={"to": "director", "decision_for": action.id, "message": "Se pide decisión explícita"})
                if request.id not in c.calls:
                    c.send(request)
            else:
                request = action
                if kind == "diffusion_result":
                    c.send(request)
                    denied_wire = c.wire_payload(request.id)["action_id"]
                    denied = self.c.post("/hr/events", json={"type": kind, "action_id": denied_wire,
                        "error": "approval_required", "delivered": 0, "failed": 0}, headers=self.hr)
                    self.assertEqual(denied.status_code, 403, denied.text)
                    self.assertNotIn(action.id, self.s.approvals)
                approval = self.post("/api/approve", {"action_id": action.id, "ok": True, "note": "Texto de prueba autorizado"})
                self.assertTrue(approval["ok"])
                if kind == "diffusion_result":
                    c.send(request)
                if request.id not in c.calls:
                    c.send(request)
            wire = c.wire_payload(request.id)
            self.assertNotEqual(wire["action_id"], request.id)
            self.assertEqual(c._wire_to_action[wire["action_id"]], request.id)
            payload = {"type": kind, "action_id": wire["action_id"], "event_id": r["id"], "final": True}
            if decision:
                payload.update(message=kind, schema="mando.hr.v1", channel_used="phone", by_role="director",
                               decision="approve" if kind == "decision" else "unclear", note=r["text"])
            else:
                payload.update(message_text=r["text"], audience="prueba",
                    approved_by=self.s.approvals[action.id]["by"] if kind == "text_delivery_request" else "")
                if kind == "diffusion_result":
                    payload.update(error="approval_required", delivered=0, failed=0)
            self.assertEqual(self.c.post("/hr/events", json=payload, headers={"X-Mando-Token": "incorrecto"}).status_code, 401)
            out = self.post("/hr/events", payload)
            self.assertNotEqual(out.get("error"), "unknown_message", out)
            self.assertFalse(out.get("stale", False), out)
            if kind == "decision":
                self.assertTrue(out["ok"], out)
                self.assertEqual((out["pending"], out["votes"], out["required"]), (True, 1, 2))
                self.assertEqual(str(action.status), "awaiting_approval")
                self.assertNotIn(action.id, self.s.approvals)
                self.assertEqual(set(self.s.operators.votes[action.id]), {"phone-director"})
                self.assertTrue(self.post("/hr/events", payload)["duplicate"])
                self.assertEqual(len(self.s.operators.votes[action.id]), 1)
                for changed in ({"by_role": "sanitario"}, {"action_id": action.id}):
                    denied = self.c.post("/hr/events", json=dict(payload, **changed), headers=self.hr)
                    self.assertEqual(denied.status_code, 403, denied.text)
                second = self.post("/api/approve", {"action_id": action.id, "ok": True, "note": "Segunda firma distinta"})
                self.assertEqual((second["pending"], second["votes"]), (False, 2))
                self.assertTrue(self.s.approvals[action.id]["ok"])
                self.assertEqual({who["id"] for who in self.s.approvals[action.id]["operators"]}, {"phone-director", "operador-1"})
            elif kind == "decision_pending":
                self.assertTrue(out.get("pending"), out)
                self.assertEqual(str(action.status), "awaiting_approval")
                self.assertNotIn(action.id, self.s.approvals)
                self.assertFalse(self.s.operators.votes.get(action.id))
                self.assertNotIn(request.id, c._closed)
            elif kind == "text_delivery_request":
                self.assertEqual((out["delivered"], out["failed"], out["pending"]), (0, 1, False))
                self.assertFalse(out["ok"], "Telegram off no puede contarse como entrega")
                self.assertEqual(self.post("/hr/events", payload), out)
                self.assertEqual(c.text_receipts[action.id], out)
                changed = self.c.post("/hr/events", json=dict(payload, message_text="Texto no aprobado"), headers=self.hr)
                self.assertEqual(changed.status_code, 403, changed.text)
            else:
                # Aunque el backend sí autorizó, el borrador denuncia la falta
                # del campo approved_by; registrar el fallo no acredita entrega.
                self.assertTrue(out["ok"], out)
                self.assertEqual(self.s.approvals[action.id]["by"], "operador-1")
                self.assertEqual(len(self.s.approvals), 1)
                self.assertEqual((c.text_receipts[action.id]["delivered"], c.text_receipts[action.id]["failed"]), (0, 0))
                self.assertEqual(c.text_receipts[action.id]["error"], "approval_required")
                self.assertEqual(c.calls[action.id]["result"], "failed")
                self.assertTrue(self.post("/hr/events", payload)["duplicate"])
            self.assertEqual(self.s.world.reports, [])
        # Sin llamadas de salida durante comprobación del reloj/SSE.
        c.mode = "sim"
        self.heartbeat()

    def exercise(self, r):
        check = r["check"]
        if check == "workflow_extension":
            self.workflow_extension(r)
            return
        elif check in ("report", "duplicate"):
            out = self.post("/hr/events", self.report_payload(r))
            report = next(x for x in self.s.world.reports if x.id == out["report_id"])
            self.assertEqual(report.source, r["source"])
            self.assertEqual(str(report.channel), EXPECTED_CHANNEL[r["channel"]])
            self.assertEqual(self.s._report_meta[report.id]["via"], "web" if r["channel"] == "chat" else r["channel"])
            self.assertTrue(report.text)
            if check == "duplicate":
                n = len(self.s.world.reports)
                self.assertTrue(self.post("/hr/events", self.report_payload(r))["duplicate"])
                self.assertEqual(len(self.s.world.reports), n)
        elif check == "chat":
            if r["kind"] == "enorme":
                self.assertEqual(self.c.post("/api/chat", json={"text": r["text"]}).status_code, 413)
                self.heartbeat()
                return
            out = self.post("/api/chat", {"text": r["text"], "zone_hint": r["zone"], "source": r["source"], "channel": r["channel"]})
            self.assertTrue(out["session_id"])
            self.assertTrue(out["say"])
            sid = out["session_id"]
            no_initial_report = {"desmentido", "broma", "spam", "emojis", "audio_ininteligible", "sin_ubicacion", "ubicacion_vaga"}
            if r["kind"] in no_initial_report:
                self.assertIsNone(out["report_id"])
                self.assertEqual(self.s.world.reports, [])
            else:
                self.assertTrue(out["report_id"], out)
                self.assertTrue(out["reports"])
            if r["kind"] in ("sin_ubicacion", "ubicacion_vaga"):
                self.assertEqual(out["state"]["pending"]["slot"], "location_point")
                for text in ("Estoy en puerta C junto al cartel", "Está mareada, responde y respira normalmente"):
                    out = self.post("/api/chat", {"session_id": sid, "text": text})
                    self.assertEqual(out["session_id"], sid)
                self.assertTrue(out["report_id"], out)
                self.assertEqual({rep.zone_hint for rep in self.s.world.reports}, {"gate_c"})
            if r["kind"] in ("desmentido", "broma", "spam"):
                out = self.post("/api/chat", {"session_id": sid, "text": "No. Nadie está en peligro."})
                self.assertEqual(out["session_id"], sid)
                # Puede registrarse un desmentido; no puede inventar personas heridas.
                self.assertNotIn("hay heridos", out["say"].lower())
                self.assertTrue(all("datos: hay heridos" not in rep.text.lower() for rep in self.s.world.reports))
            for rep in self.s.world.reports:
                self.assertEqual(rep.source, r["source"])
                self.assertEqual(str(rep.channel), "whatsapp")
                self.assertEqual(self.s._report_meta[rep.id]["via"], "chat")
            if r["kind"] == "multiincidente":
                self.assertEqual(len(self.s.world.reports), 2)
                self.assertEqual(len(out["reports"]), 2)
                self.assertEqual({rep.zone_hint for rep in self.s.world.reports}, {"gate_b", "food"})
            if "MARCADOR_RESERVADO" in r["text"]:
                self.assertTrue(self.s.world.reports)
                self.assertTrue(all(self.s._report_meta[rep.id]["reserved"] for rep in self.s.world.reports))
                spoken = {k: out.get(k) for k in ("say", "messages", "instruction")}
                self.assertNotIn("MARCADOR_RESERVADO", json.dumps(spoken))
                self.assertNotIn("MARCADOR_RESERVADO", self.c.get("/api/state").text)
                self.assertNotIn("MARCADOR_RESERVADO", self.c.get("/api/stream?limit=1").text)
        elif check == "update":
            p = self.report_payload(r)
            p.update(report_ref=r["id"], partial=True, final=False)
            rid = self.post("/hr/events", p)["report_id"]
            truth = len(self.s.world.incidents)
            field, value = {"correccion_ubicacion": ("ubicacion", "puerta C"), "actualizacion": ("responsive", "no"),
                            "cancelacion": ("description", "Cancelación: ya no sucede")}[r["kind"]]
            updated = self.post("/hr/events", {"type": "public_report_update", "report_ref": r["id"], "field": field, "value": value})
            self.assertEqual(updated["report_id"], rid)
            self.assertEqual(self.s._report_meta[updated["update_id"]]["update_of"], rid)
            self.assertEqual(self.s._report_extra[rid][field], value)
            update = next(rep for rep in self.s.world.reports if rep.id == updated["update_id"])
            self.assertEqual(update.source, r["source"])
            self.assertEqual(str(update.channel), "voice")
            self.assertEqual(self.s._report_meta[update.id]["via"], "voice")
            self.assertIn("no responde" if field == "responsive" else value, update.text)
            self.assertEqual(len(self.s.world.incidents), truth)
            self.assertTrue(self.post("/hr/events", {"type": "report_status_query", "report_ref": r["id"]})["say_text"])
        elif check == "legacy_report":
            out = self.post("/hr/events", {"schema": "mando.hr.v1", "message": "public_report", "event_id": r["id"],
                "report": {"channel": "radio", "source": "público", "text": r["text"]}})
            rep = next(x for x in self.s.world.reports if x.id == out["report_id"])
            self.assertEqual(rep.source, "público")
            self.assertEqual(str(rep.channel), "radio")
        elif check == "invalid":
            try:
                response = self.c.post("/api/chat", content=b"{broken") if r["payload"] is None else self.c.post("/api/chat", json=r["payload"])
                self.assertIn(response.status_code, (400, 422), response.text)
            finally:
                self.heartbeat()
            return
        elif check == "callback":
            c, aid, _ = self.flight()
            payload = dict(message=r["message"], action_id=aid, event_id=r["id"], channel_used=r["channel"], **r["extra"])
            if r["result"]:
                payload["result"] = r["result"]
            if r["message"] == "progress":
                c.calls[aid]["stage"] = "pendiente"
            version = self.s.version
            out = self.post("/hr/events", payload)
            self.assertTrue(out["ok"], out)
            self.assertGreater(self.s.version, version)
            got = c.poll(self.s.world.t)
            if r["result"]:
                self.assertEqual([x["result"] for x in got], [r["result"]])
                self.assertEqual(got[0]["action_id"], aid)
                self.assertEqual(got[0]["channel"], EXPECTED_CHANNEL[r["channel"]])
                self.assertEqual(got[0]["eta_min"], r["extra"].get("eta_min"))
                if r["extra"].get("detail"):
                    self.assertEqual(got[0]["detail"], r["extra"]["detail"])
                if r["extra"].get("reason_code"):
                    self.assertEqual(got[0]["reason_code"], "route_blocked")
                    self.assertEqual(got[0]["data"]["reason_text"], "Acceso bloqueado")
            else:
                self.assertEqual(got, [])
                if r["message"] == "progress":
                    self.assertEqual(c.calls[aid]["stage"], "llamando")
                else:
                    self.assertIn("Afirmativo", json.dumps(c.calls[aid].get("transcript", [])))
        elif check == "platform":
            c, aid, wire = self.flight()
            p = {"type": "dispatch_result", "action_id": wire, "event_id": r["id"], "result": "accept", "eta_min": "4", "channel_used": r["channel"]}
            kind = r["kind"]
            if kind == "rechaza_telefono":
                p.update(result="reject", eta_min="", reason="Ruta bloqueada", reason_code="route_blocked")
            if kind == "dispatch_progress":
                p.update(type=kind, stage="order_confirmed")
            if kind in ("otra_sesion", "sin_nonce"):
                p["action_id"] = "old-session:" + aid if kind == "otra_sesion" else aid
                p["hr_run_id"] = "old-run"
                self.assertTrue(self.post("/hr/events", p)["stale"])
                self.assertIn(aid, c._inflight)
                self.assertEqual(c.poll(0), [])
            else:
                if kind == "tardio":
                    c._inflight[aid]["deadline"] = 0
                    c.sweep()
                    self.assertIn(aid, c._closed)
                    before = self.s.world.truth()
                    self.assertTrue(self.post("/hr/events", p)["ignored"])
                    self.assertEqual(c.poll(0), [])
                    self.assertEqual(self.s.world.truth(), before)
                else:
                    out = self.post("/hr/events", p)
                    self.assertTrue(out["ok"])
                    expected_eta = None if kind == "rechaza_telefono" else 4
                    self.assertEqual(out["eta_min"], expected_eta)
                    got = c.poll(0)
                    self.assertEqual([x["result"] for x in got], [p["result"]])
                    self.assertEqual(got[0]["action_id"], aid)
                    self.assertEqual(got[0]["channel"], "voice")
                    self.assertEqual(got[0]["eta_min"], expected_eta)
                    self.assertEqual(got[0]["data"].get("web_call", False), r["channel"] == "web_call")
                    if kind == "rechaza_telefono":
                        self.assertEqual(got[0]["data"]["reason_text"], "Ruta bloqueada")
                        self.assertEqual(got[0]["reason_code"], "route_blocked")
                    if kind == "duplicado":
                        self.assertTrue(self.post("/hr/events", p)["duplicate"])
                        self.assertEqual(c.poll(0), [])
        elif check == "order":
            action = {"kind": "reroute", "zone": "gate_b", "to": "gate_c", "fraction": .1}
            self.assertEqual(self.c.post("/api/whatif/order", json={"action": action}).status_code, 401)
            out = self.post("/api/whatif/order", {"action": action, "note": "Prueba aislada"})
            aid = out["order"]["id"]
            state = self.c.get("/api/state", headers=self.operator).json()
            order = next(item for item in state["operator_orders"] if item["id"] == aid)
            self.assertEqual(order["by"], "operador-1")
            self.assertEqual(order["action"], action)
            self.assertEqual(order["note"], "Prueba aislada")
            self.assertTrue(any(entry.get("ref") == aid and "CORRECCIÓN DEL OPERADOR" in entry.get("text", "") for entry in state["log"]))
            self.assertEqual(self.s.approvals[aid]["by"], "operador-1")
            self.assertTrue(self.s.approvals[aid]["ok"])
            applied = [item for item in self.s.world.truth()["actions"] if item.get("id") == aid]
            self.assertTrue(applied, self.s.world.truth()["actions"])
        elif check == "telegram":
            fake, port = create_mock_telegram(), free_port()
            with patch.dict(os.environ, {"TELEGRAM_MODE": "poll", "TELEGRAM_BOT_TOKEN": TOKEN,
                                       "TELEGRAM_API_BASE": f"http://127.0.0.1:{port}"}), Served(fake, port):
                tg_app = create_app(threaded=False, secret="callback-ficticio", local_params=False)
                self.addCleanup(tg_app.state.session.close)
                with TestClient(tg_app):
                    self.assertTrue(wait_for(lambda: tg_app.state.telegram.status == "on"))
                    httpx.post(f"http://127.0.0.1:{port}/mock/text", json={"chat_id": 4321, "text": r["text"]}).raise_for_status()
                    self.assertTrue(wait_for(lambda: bool(tg_app.state.session.world.reports)))
                    self.assertTrue(wait_for(lambda: bool(fake.state.sent)))
                    self.assertTrue(any(x.source.startswith("telegram:") for x in tg_app.state.session.world.reports))
                    self.assertTrue(any(x.get("via") == "telegram" for x in tg_app.state.session._report_meta.values()))
                    self.assertEqual(fake.state.sent[-1]["chat_id"], 4321)
            return
        elif check in ("staff", "staff_web"):
            initial = self.post("/api/report", {"text": "Persona mareada por calor en pista general", "zone": "general"})
            self.heartbeat()
            self.heartbeat()
            inc = next(i for i in self.s.agent.incidents.values() if initial["report_id"] in i.reports)
            action = next(a for a in self.s.agent.actions.values() if a.incident == inc.id and a.kind == ActionKind.DISPATCH
                          and str(self.s.world.resources[a.resource].kind) == "medical")
            unit = action.resource
            # Credencial emitida por la ruta real. Sin helper FieldStaff ni rutas
            # instaladas en el fixture: la ausencia de integración debe fallar.
            links = self.post("/api/personal/links", {"unit_id": unit, "role": "sanitario"})
            token = links.get("token")
            self.assertTrue(isinstance(token, str) and len(token) > 40, "La ruta debe emitir un token de unidad")
            before_count = len(self.s.world.reports)
            before_needs = dict(inc.needs)
            before_state = str(self.s.world.resources[unit].status)
            before_false_alarms = self.s.agent.counters["false_alarms"]
            before_resolved = self.s.agent.counters["resolved"]
            payload = {"unit_id": unit, "event_id": r["id"], "status": r["staff_status"], "zone": r["zone"],
                       "needs_support": r["staff_status"] == "needs_support", "free_text": r["text"],
                       "channel": "radio" if check == "staff_web" else "voice"}
            if check == "staff":
                payload.update(schema="mando.hr.v1", type="staff_status", hr_run_id="run-" + r["id"], unit_token=token)
                path, headers = "/hr/events", self.hr
                denied = self.c.post(path, json=payload, headers={"X-Mando-Token": "incorrecto"})
                self.assertEqual(denied.status_code, 401)
                denied = self.c.post(path, json=dict(payload, unit_token="incorrecto"), headers=headers)
            else:
                path, headers = "/api/personal/status", {"X-Mando-Unit": token}
                denied = self.c.post(path, json=payload, headers={"X-Mando-Unit": "incorrecto"})
            self.assertEqual(denied.status_code, 403, denied.text)
            invalid = self.c.post(path, json=dict(payload, needs_support="false"), headers=headers)
            self.assertEqual(invalid.status_code, 422, invalid.text)
            self.assertEqual(len(self.s.world.reports), before_count)
            response = self.c.post(path, json=payload, headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
            out = response.json()
            self.assertTrue(out["ok"])
            self.assertFalse(out.get("stale", False))
            self.assertEqual(out["status"], r["staff_status"])
            self.assertEqual(len(self.s.world.reports), before_count + 1)
            report = next(rep for rep in self.s.world.reports if rep.id == out["report_id"])
            self.assertEqual(report.source, unit)
            self.assertEqual(str(report.channel), payload["channel"])
            self.assertIn(r["text"], report.text)
            self.assertEqual(report.zone_hint, r["zone"])
            meta = self.s._report_meta[report.id]
            self.assertEqual(meta["via"], "personal")
            self.assertEqual(meta["staff_unit"], unit)
            self.assertEqual(meta["staff_status"], r["staff_status"])
            if r["staff_status"] != "new_notice":
                self.assertEqual(meta["update_of"], initial["report_id"])
            else:
                self.assertIsNone(meta["update_of"])
            expected = {"en_route": "en_route", "on_scene": "busy", "stabilized": "busy", "transport": "busy",
                        "needs_support": "busy", "route_blocked": "offline", "exhausted": "offline", "free": "available"}
            self.assertEqual(str(self.s.world.resources[unit].status), expected.get(r["staff_status"], before_state))
            if r["staff_status"] == "route_blocked":
                self.assertTrue(self.s.world.observe().zones["corridor_s"].flags["blocked"])
            duplicate = self.c.post(path, json=payload, headers=headers)
            self.assertEqual(duplicate.status_code, 200, duplicate.text)
            self.assertTrue(duplicate.json()["duplicate"])
            self.assertEqual(len(self.s.world.reports), before_count + 1)
            self.heartbeat()
            self.assertEqual(self.s._report_meta[report.id]["staff_status"], r["staff_status"])
            state = self.c.get("/api/state", headers=self.operator).json()
            self.assertTrue(any(e.get("kind") == "staff_status" and e.get("ref") == report.id for e in state["log"]))
            if r["staff_status"] == "needs_support":
                self.assertGreaterEqual(self.s.agent.incidents[inc.id].needs["medical"], before_needs["medical"] + 1)
            elif r["staff_status"] == "false_alarm":
                # Esta secuencia recibe la llegada del equipo antes del sitrep.
                # Mando distingue "ya no ocurre" de "nunca se confirmó".
                self.assertTrue(self.s.agent.meta[inc.id].seen_on_scene)
                self.assertEqual(str(self.s.agent.incidents[inc.id].status), "resolved")
                self.assertEqual(self.s.agent.counters["false_alarms"], before_false_alarms)
                self.assertEqual(self.s.agent.counters["resolved"], before_resolved + 1)
                self.assertEqual(inc.assigned, [])
                self.assertNotIn(inc.id, self.s.agent._waiting)
                self.assertFalse(any(a.incident == inc.id and a.kind == ActionKind.DISPATCH
                    and str(a.status) not in ("done", "cancelled", "failed", "rejected")
                    for a in self.s.agent.actions.values()))
                self.assertTrue(any(e.get("ref") == inc.id and "quien está en el sitio dice que no pasa nada" in e.get("text", "")
                                    for e in state["log"]))
            return
        elif check == "external_notice":
            payload = {"type": "external_notice", "schema": "mando.hr.v1", "event_id": r["id"],
                       "hr_run_id": "run-" + r["id"], "source": r["source"], "text": r["text"], "zone": r["zone"]}
            self.assertEqual(self.c.post("/hr/events", json=payload, headers={"X-Mando-Token": "incorrecto"}).status_code, 401)
            before = len(self.s.world.reports)
            out = self.post("/hr/events", payload)
            self.assertTrue(out["ok"])
            self.assertFalse(out.get("stale", False), "Un aviso externo autorizado debe entrar, no descartarse como stale")
            self.assertEqual(len(self.s.world.reports), before + 1)
            report = next(rep for rep in self.s.world.reports if rep.id == out["report_id"])
            self.assertEqual(report.source, r["source"])
            self.assertEqual(str(report.channel), "operator")
            self.assertEqual(report.zone_hint, r["zone"])
            self.assertIn(r["text"], report.text)
            self.assertEqual(self.s._report_meta[report.id]["via"], "external")
            self.assertEqual(self.s._report_meta[report.id]["source_label"], "servicios externos")
            self.assertTrue(self.post("/hr/events", payload)["duplicate"])
            self.assertEqual(len(self.s.world.reports), before + 1)
            self.assertFalse(any(a.kind == ActionKind.REQUEST_EXTERNAL and a.status == ActionStatus.EXECUTING
                                 for a in self.s.agent.actions.values()))
        self.heartbeat()
        self.heartbeat()

    def test_report_source_contract_is_preserved(self):
        r = self.post("/hr/events", {"type": "public_report", "channel": "radio",
            "report": {"text": "Persona mareada en puerta B", "source": "med_1"}})
        self.assertEqual(next(x.source for x in self.s.world.reports if x.id == r["report_id"]), "med_1")

    def test_parada_has_priority_over_queue(self):
        self.post("/api/report", {"text": "Cola en puerta B", "zone": "gate_b"})
        self.post("/api/report", {"text": "Persona no responde y no respira en restauración", "zone": "food"})
        self.heartbeat()
        self.heartbeat()
        incs = list(self.s.agent.incidents.values())
        cardiac = [i for i in incs if i.type == "cardiac_arrest"]
        queue = [i for i in incs if str(i.family) == "crowd"]
        self.assertTrue(cardiac and queue, [(i.type, i.priority) for i in incs])
        self.assertTrue(all(self.s.agent.meta[i.id].life_threat for i in cardiac))
        self.assertGreater(max(i.priority for i in cardiac), max(i.priority for i in queue))

    def test_callback_reject_is_consumed_by_mando_and_reassigned(self):
        # Registro real de llamada pendiente, sin descolgar ni solicitar tokens:
        # el transporte se mantiene en loopback y no se marca ningún número.
        with patch.dict(os.environ, {"HR_API_KEY": "clave-ficticia", "MANDO_VOICE_MODE": "web_call",
                                    "HR_API_BASE": "http://127.0.0.1:1", "HR_HOOK_DISPATCH": ""}):
            app = create_app(threaded=False, comms_mode="happyrobot", secret="callback-ficticio", local_params=False)
            s = app.state.session
            self.addCleanup(s.close)
            self.addCleanup(app.state.chat.stop)
            s.comms.contacts = {"resources": {rid: {"title": "Unidad de prueba " + rid} for rid in s.world.resources}, "roles": {}}
            with TestClient(app, raise_server_exceptions=False) as client:
                def post(path, payload):
                    response = client.post(path, json=payload, headers=self.hr if path.startswith("/hr") else self.operator)
                    self.assertEqual(response.status_code, 200, response.text)
                    return response.json()
                report = post("/api/report", {"text": "Persona mareada por calor en puerta B", "zone": "gate_b"})
                post("/api/control", {"cmd": "step", "n": 2})
                inc = next(i for i in s.agent.incidents.values() if report["report_id"] in i.reports)
                original = next(a for a in s.agent.actions.values() if a.incident == inc.id and a.kind == ActionKind.DISPATCH)
                previous = set(s.agent.actions)
                call = s.comms.calls[original.id]
                self.assertTrue(call["real"])
                self.assertTrue(call["web_call"])
                self.assertIsNone(call["result"])
                wire = s.comms.wire_payload(original.id)["action_id"]
                result = post("/hr/events", {"type": "dispatch_result", "action_id": wire, "event_id": "reject-mando-cycle",
                    "result": "reject", "reason": "No puedo atender esta orden", "eta_min": "", "channel_used": "web_call"})
                self.assertEqual(result["result"], "reject")
                # Nadie consume poll aquí: el único consumidor es agent.tick.
                self.assertIsNone(call["result"])
                post("/api/control", {"cmd": "step", "n": 2})
                self.assertEqual(s.agent_errors, 0, s.engine_error)
                self.assertEqual(s.comms.calls[original.id]["result"], "reject")
                alternatives = [a for a in s.agent.actions.values() if a.id not in previous and a.incident == inc.id
                                and a.kind == ActionKind.DISPATCH and a.resource != original.resource]
                self.assertTrue(alternatives, [(a.id, str(a.kind), a.incident, a.resource) for a in s.agent.actions.values()])
                self.assertTrue(any(s.comms.calls[a.id]["resource"] == a.resource for a in alternatives))
                state = client.get("/api/state", headers=self.operator).json()
                self.assertTrue(any(e.get("ref") == original.id and "rechaza" in e.get("text", "") for e in state["log"]))

    def test_grave_actions_wait_for_human(self):
        for kind in (ActionKind.STOP_SHOW, ActionKind.EVACUATE, ActionKind.REQUEST_EXTERNAL):
            with self.subTest(kind=kind):
                aid = "grave-" + str(kind)
                a = Action(aid, kind, self.s.world.t, zone="general", autonomy=Autonomy.APPROVE,
                           status=ActionStatus.AWAITING_APPROVAL, why="Prueba de cerrojo humano")
                self.s.agent.actions[aid] = a
                self.s._rebuild()
                self.assertEqual(self.c.post("/api/approve", json={"action_id": aid, "ok": True}).status_code, 401)
                self.assertEqual(a.status, ActionStatus.AWAITING_APPROVAL)
                self.post("/api/approve", {"action_id": aid, "ok": False, "note": "Veto de prueba"})
                self.assertFalse(self.s.approvals[aid]["ok"])

    def test_api_report_rejects_object_text(self):
        try:
            response = self.c.post("/api/report", json={"text": {"bad": 1}})
            self.assertIn(response.status_code, (400, 422), response.text)
        finally:
            self.heartbeat()

    def test_two_reports_same_fact_merge_in_mando(self):
        for source in ("seguridad", "asistente"):
            self.post("/api/report", {"text": "Una persona mareada por calor en puerta B", "zone": "gate_b", "source": source})
        self.heartbeat()
        self.heartbeat()
        incidents = list(self.s.agent.incidents.values())
        self.assertEqual(len(incidents), 1, [(i.type, i.reports) for i in incidents])
        self.assertEqual(len(incidents[0].reports), 2)

    def test_invalid_hr_callback_does_not_consume_event(self):
        c, aid, wire = self.flight()
        p = {"type": "dispatch_result", "action_id": wire, "event_id": "repairable",
             "result": "accept", "data": "broken"}
        self.assertEqual(self.c.post("/hr/events", json=p, headers=self.hr).status_code, 422)
        self.assertIn(aid, c._inflight)
        self.assertNotIn("repairable", c._seen_events)
        p["data"] = {}
        self.assertEqual(self.post("/hr/events", p)["result"], "accept")
        self.assertEqual(len(c.poll(0)), 1)
        self.heartbeat()

    def test_sensor_effects_via_operator_http(self):
        effects = [{"kind": "weather", "wind_kmh": 72, "rain": True},
                   {"kind": "zone_flag", "zone": "food", "flag": "power", "value": False},
                   {"kind": "zone_flag", "zone": "water_n", "flag": "water_l", "value": 0},
                   {"kind": "zone_state", "zone": "gate_b", "state": "restricted"}]
        for effect in effects:
            with self.subTest(effect=effect):
                before = self.s.world.truth()
                self.post("/api/strike", {"effect": effect, "origin": "operator"})
                self.assertNotEqual(self.s.world.truth(), before)
                state = self.c.get("/api/state", headers=self.operator).json()
                if effect["kind"] == "weather":
                    self.assertEqual(state["weather"]["wind_kmh"], 72)
                    self.assertTrue(state["weather"]["rain"])
                else:
                    zone = next(z for z in state["zones"] if z["id"] == effect["zone"])
                    if effect["kind"] == "zone_flag":
                        self.assertEqual(zone["flags"][effect["flag"]], effect["value"])
                    else:
                        self.assertEqual(zone["state"], "restricted")
                self.heartbeat()


def _case(r):
    def test(self):
        self.exercise(r)
    test.__doc__ = r["id"] + ": " + r["source"] + " / " + r["channel"] + " / " + r["kind"]
    return test


for _row in ROWS:
    if _row["status"] != "NO CUBIERTO":
        setattr(NotificacionesTest, "test_fila_" + _row["id"], _case(_row))


if __name__ == "__main__":
    unittest.main()
