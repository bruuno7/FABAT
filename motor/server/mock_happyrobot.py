"""HappyRobot de mentira, en local. Imita lo que el adaptador usa de la plataforma, con las mismas rutas:

    POST /hooks/{slug}  (y /hook/{slug})          Incoming hook. Responde sin run_id: su respuesta real no está documentada.
    POST /api/v2/workflows/{id}/runs              {payload, environment} con Bearer → {run_id, queued_run_ids, status, message}
    POST /api/v2/voice/tokens/                    {workflow_id, data} → {url, token, room_name, run_id} (llamada web nueva)
                                                  {session_id, should_takeover} → escucha o TOMA de una llamada viva
    GET  /api/v2/runs/{run_id}/sessions           sesiones del run
    GET  /api/v2/sessions/{id}/stream             SSE: `message` {role, content} y `session_ended`
    GET  /api/v2/sessions/{id}/messages           transcripción al cerrar
    POST /api/v2/signals                          {key: "session.<id>", payload}: el agente dice la orden nueva en la llamada

Y devuelve `progress` y `*_result` a `callback_url/hr/events` con `hr_run_id`, como haría `current.run_id`.

DESPACHO (fase 3): si el cuerpo que llega son los parámetros del trigger real (`action_id, to_number, role, order_text,
zone_spoken, priority, callback_url, callback_token`, sin `message`), imita a `mando-despacho-telefono`: POST a
`callback_url` TAL CUAL, cabecera `X-Mando-Token` = `callback_token`, todo cadenas: `dispatch_progress` en caliente
(`stage: order_confirmed`) y `dispatch_result` al colgar (`result: accept|reject|unclear`, `eta_min`, `reason`,
`call_status`, `hr_session_id`, `transcript`, `hr_run_id`). Guion extra: `{"eta": "" }` = acepta sin decir minutos.

    uv run --project motor/server python -m motor.server.mock_happyrobot --port 8765 --delay 4
    HR_API_BASE=http://127.0.0.1:8765/api/v2  HR_API_KEY=mock  HR_WORKFLOW_WEBCALL=fa-webcall  ...

Como no hay LiveKit de mentira, en una llamada web la persona contesta con `POST /mock/answer/{run_id} {"result": ...}`
(lo hace la página `/llamada/<id>` cuando detecta `url` = `mock://`). Guion: `POST /mock/config {"default": "accept",
"by_resource": {"sec_2": "reject"}, "silent": false, "omit_action_id": false}`.
Las latencias que manda son inventadas y van marcadas con `mock: true`: NO son cifras para el pitch.
"""
from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import os
import threading
import time
from typing import Any

import httpx
from .hr_routing import WORKFLOW_NAMES
from .hr_config import workflow_ids
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

_RESULT_OF = {"dispatch_request": "dispatch_result", "clarify_request": "clarify_result",
              "notify_request": "notify_result", "external_request": "external_result",
              "followup_request": "followup_result"}


def create_mock(delay_s: float = 3.0, secret: str | None = None) -> FastAPI:
    app = FastAPI(title="mock-happyrobot")
    app.state.config = {"default": "accept", "by_resource": {}, "delay_s": delay_s, "silent": False, "omit_action_id": False}
    app.state.received = []          # todo lo que entra, para las pruebas
    app.state.posted = []            # todo lo que el mock ha devuelto al backend
    app.state.signals = []
    app.state.sessions = {}          # session_id -> {run_id, status, messages, payload, taken_over}
    app.state.runs = {}              # run_id -> session_id
    app.state.workflows = {**{k: k for k in workflow_ids()}, **WORKFLOW_NAMES}
    counter = itertools.count(1)

    def token() -> str:
        return secret if secret is not None else (os.environ.get("HR_SECRET") or os.environ.get("MANDO_HR_TOKEN") or "")

    def post(base: str, body: dict[str, Any], tok: str | None = None) -> dict:
        if app.state.config.get("omit_action_id"):
            body = dict(body, action_id=None)  # obliga al backend a casar por hr_run_id
        url = base.rstrip("/")
        if not url.endswith("/hr/events"):   # contrato: base; workflows reales: la URL completa
            url += "/hr/events"
        try:
            response = httpx.post(url, json=body, headers={"X-Mando-Token": tok if tok is not None else token()}, timeout=5)
            app.state.posted.append(body)
            return response.json() if response.is_success else {}
        except (httpx.HTTPError, ValueError):
            pass  # el backend se ha parado: no hay a quién contestar
        return {}

    def is_workflow(payload: dict[str, Any]) -> bool:
        return "message" not in payload and "order_text" in payload

    def finish_workflow(payload: dict[str, Any], run_id: str, result: str, hot: bool = True) -> None:
        """Como el workflow real: aviso en caliente cuando la persona dice sí o no, y el resultado al colgar."""
        cfg, session_id = app.state.config, app.state.runs[run_id]
        base, tok = str(payload.get("callback_url") or ""), str(payload.get("callback_token") or "")
        web = not payload.get("to_number")
        eta = str(cfg.get("eta", "3")) if result == "accept" else ""
        reason = "Atendiendo otro incidente" if result == "reject" else ""
        said = {"accept": "Afirmativo." + (f" {eta} minutos." if eta else ""), "reject": "Negativo. Estoy con otro incidente.",
                "unclear": "¿Quién es? No te oigo nada."}.get(result, "")
        if said:
            say(session_id, "user", said)
        common = {"schema": "mando.hr.v1", "channel_used": "web_call" if web else "phone",
                  "action_id": str(payload.get("action_id") or ""), "hr_run_id": run_id}
        if hot and result in ("accept", "reject"):
            post(base, dict(common, type="dispatch_progress", message="progress", stage="order_confirmed", final=False,
                            result=result, eta_min=eta, reason=reason), tok)
            time.sleep(float(cfg.get("delay_s", 3)) * 0.1)
        s = app.state.sessions[session_id]
        transcript = "\n".join(f"{m['role']}: {m['content']}" for m in s["messages"])
        status = "no-answer" if result == "no_answer" else "completed"
        post(base, dict(common, type="dispatch_result", message="dispatch_result", final=True,
                        result="" if result == "no_answer" else result, eta_min=eta, reason=reason, call_status=status,
                        hr_session_id=session_id, transcript=transcript, data={"mock": True, "turn_latency_ms": 640}), tok)
        s["status"] = "completed"

    def new_run(payload: dict[str, Any]) -> tuple[str, str]:
        n = next(counter)
        run_id, session_id = f"mock-run-{n:04d}", f"mock-ses-{n:04d}"
        app.state.runs[run_id] = session_id
        app.state.sessions[session_id] = {"run_id": run_id, "status": "in-progress", "messages": [], "payload": payload,
                                          "taken_over": False}
        return run_id, session_id

    def say(session_id: str, role: str, content: str) -> None:
        s = app.state.sessions[session_id]
        s["messages"].append({"id": f"m-{len(s['messages']) + 1}", "session_id": session_id, "role": role, "content": content,
                              "is_filler": False, "turn_index": len(s["messages"])})

    def envelope(payload: dict[str, Any], run_id: str) -> dict[str, Any]:
        return {"schema": "mando.hr.v1", "session_id": payload.get("session_id"), "action_id": payload.get("action_id"),
                "t_sent": payload.get("t"), "mode": payload.get("mode", "live"), "hr_run_id": run_id,
                "hr_session_id": app.state.runs.get(run_id)}

    def finish(payload: dict[str, Any], run_id: str, result: str) -> None:
        """La persona ya ha contestado: se cierra la conversación y sale el webhook final."""
        if is_workflow(payload):
            return finish_workflow(payload, run_id, result)
        base, msg = str(payload.get("callback_url") or ""), str(payload.get("message"))
        session_id = app.state.runs[run_id]
        body = dict(envelope(payload, run_id), message=_RESULT_OF.get(msg, "dispatch_result"), event_id=f"{run_id}-final",
                    seq=9, final=True, channel_used="web_call" if payload.get("to_number") is None and msg == "dispatch_request"
                    else payload.get("channel", "voice"), attempts=1, data={"mock": True, "turn_latency_ms": 640})
        if msg in ("clarify_request", "followup_request"):
            ok = result != "no_answer"
            body.update(result="answer" if ok else "no_answer", detail="answered" if ok else "no_answer",
                        text="Confirmado, es aquí. Hace falta un equipo." if ok else "",
                        status_code="on_scene" if msg == "followup_request" and ok else None)
        elif result == "reject":
            body.update(result="reject", detail="rejected", text="Negativo, estoy con otro incidente. No puedo ir.",
                        reason_code="busy_other_incident", reason_text="Atendiendo otro incidente", eta_min=None)
        elif result == "no_answer":
            body.update(result="no_answer", detail="no_answer", text="", eta_min=None)
        else:
            body.update(result="accept", detail="accepted" if msg != "notify_request" else "delivered",
                        text="Afirmativo, vamos para allá. Tres minutos." if msg == "dispatch_request" else "Recibido.",
                        eta_min=3 if msg in ("dispatch_request", "external_request") else None,
                        confirmed_by_repetition=True, call_duration_s=round(float(app.state.config.get("delay_s", 3))))
        if body.get("text"):
            say(session_id, "user", body["text"])
        post(base, body)
        app.state.sessions[session_id]["status"] = "completed"

    def run_outbound(payload: dict[str, Any], run_id: str) -> None:
        cfg = app.state.config
        if cfg.get("silent"):
            return  # imita a la plataforma encolando sin error: recibe y no devuelve nada
        session = app.state.sessions[app.state.runs[run_id]]
        slot = session.get('workflow')
        base, tok = payload.get('callback_url', ''), payload.get('callback_token', '')
        common = dict(action_id=payload.get('action_id'), hr_run_id=run_id, hr_session_id=app.state.runs[run_id])
        if slot == 'director':
            decision = cfg.get('decision', 'unclear')
            body = dict(common, type='decision' if decision in ('approve', 'veto') else 'decision_pending',
                        decision=decision, by_role=payload.get('role'), note=cfg.get('decision_note', 'Decisión simulada'))
            post(base, body, tok)
            session['status'] = 'completed'
            return
        if slot == 'difusion' or 'audience' in payload:
            if not payload.get('approved_by'):
                result = dict(delivered=0, failed=0, error='approval_required')
            else:
                request = {k: v for k, v in payload.items() if k not in ('callback_token', 'callback_url')}
                result = post(base, dict(request, **common, type='text_delivery_request'), tok)
            if 'delivered' in result and 'failed' in result:
                post(base, dict(result, **common, type='diffusion_result'), tok)
            session['status'] = 'completed'
            return
        delay = float(cfg.get("delay_s", 3.0))
        if is_workflow(payload):   # el workflow real no manda «llamando» ni «ha descolgado»: solo el aviso en caliente y el final
            result = next((v for k, v in (cfg.get("by_role") or {}).items() if k.lower() in str(payload.get("role", "")).lower()),
                          cfg.get("default", "accept"))
            time.sleep(delay * 0.4)
            if result != "no_answer":
                say(app.state.runs[run_id], "assistant", f"Centro de control, sistema automático. {payload.get('order_text')} ¿Afirmativo o negativo?")
            time.sleep(delay * 0.5)
            if not app.state.sessions[app.state.runs[run_id]]["taken_over"]:
                finish(payload, run_id, result)
            return
        base, env = str(payload.get("callback_url") or ""), envelope(payload, run_id)
        voice = payload.get("channel", "voice") == "voice"
        time.sleep(delay * 0.2)
        if voice:
            post(base, dict(env, message="progress", event_id=f"{run_id}-started", seq=0, final=False,
                            stage="call_started", channel_used="voice", text=None))
            time.sleep(delay * 0.3)
        result = cfg["by_resource"].get(payload.get("resource_id"), cfg.get("default", "accept"))
        if voice and result != "no_answer":
            post(base, dict(env, message="progress", event_id=f"{run_id}-answered", seq=0, final=False,
                            stage="call_answered", channel_used="voice", text=None))
            say(app.state.runs[run_id], "assistant", str(payload.get("order_text") or payload.get("question_text")
                                                         or payload.get("message_text") or "Mensaje de Mando."))
        time.sleep(delay * 0.5)
        if not app.state.sessions[app.state.runs[run_id]]["taken_over"]:
            finish(payload, run_id, result)

    def bearer(request: Request) -> None:
        if not request.headers.get("authorization", "").lower().startswith("bearer "):
            raise HTTPException(401, "Falta Authorization: Bearer")

    # ---------------------------------------------------------------- workflow de TEXTO (entendimiento delegado)
    _CATEGORY = (("sanitario", ("no respira", "no responde", "mare", "desmay", "sangr", "calor", "herid", "infarto")),
                 ("aglomeracion", ("aplast", "empuj", "avalancha", "agobi", "cola", "atasc")),
                 ("agresion", ("pelea", "pegando", "acos", "agred")), ("infraestructura", ("valla", "humo", "fuego", "luz", "apag")),
                 ("meteorologico", ("viento", "tormenta", "lluvia", "rayo")), ("recursos", ("agua", "botell", "sin comida")))
    _PLACES = ("puerta a", "puerta b", "puerta c", "frente de escenario", "escenario", "pista general", "zona vip", "restauración",
               "baños", "punto de agua norte", "punto de agua sur", "pasillo norte", "pasillo sur", "plataforma pmr")

    def run_intake(payload: dict[str, Any], run_id: str) -> None:
        """Imita `mando-ingesta-texto`: AI Extract + AI Classify sobre el texto y `public_report` de vuelta, todo cadenas."""
        cfg = app.state.config
        if cfg.get("silent") or cfg.get("intake_silent"):
            return
        time.sleep(float(cfg.get("intake_delay_s", 0.2)))
        text = str(payload.get("text") or "")
        low = text.lower()
        category = next((c for c, words in _CATEGORY if any(w in low for w in words)), "otro")
        place = next((p for p in _PLACES if p in low), "")
        channel, source, lang = str(payload.get("channel") or "telegram"), str(payload.get("source") or "asistente"), str(payload.get("lang") or "es")
        post(str(payload.get("callback_url") or ""), {   # forma EXACTA de PLATAFORMA_REAL.md §4: `type` y `message`, `report` + `extracted`, todo cadenas
            "schema": "mando.hr.v1", "type": "public_report", "message": "public_report", "final": True, "event_id": run_id, "hr_run_id": run_id,
            "channel": channel, "reply_to": str(payload.get("reply_to") or ""), "category": category,
            "report": {"channel": channel, "text": text, "zone_hint": str(payload.get("zone_hint") or ""), "source": source, "lang": lang},
            "extracted": {"category": category, "location": place, "description": text[:200], "people": "1" if "un " in low or "una " in low else "",
                          "responsive": "no" if "no responde" in low or "no respira" in low else "", "reporter": source, "lang": lang,
                          "missing": "" if place else "ubicación", "sensitive": "true" if category == "agresion" else "false"}},
            str(payload.get("callback_token") or ""))
        app.state.sessions[app.state.runs[run_id]]["status"] = "completed"

    # ---------------------------------------------------------------- lanzar
    def mark_workflow(run_id, slug):
        ids = workflow_ids()
        slot = next((k for k, name in app.state.workflows.items() if slug in (k, name, ids.get(k))), slug)
        app.state.sessions[app.state.runs[run_id]]['workflow'] = slot

    @app.get('/mock/workflows')
    def inventory():
        return app.state.workflows

    async def hook(slug: str, request: Request) -> dict[str, Any]:
        payload = await request.json()
        if "reply_to" in payload and "text" in payload and "order_text" not in payload:
            run_id, _ = new_run(payload)
            app.state.received.append({"via": "hook", "hook": slug, "payload": payload, "run_id": run_id, "intake": True})
            threading.Thread(target=run_intake, args=(payload, run_id), daemon=True).start()
            return {"status": "ok"}
        run_id, _ = new_run(payload)
        mark_workflow(run_id, slug)
        app.state.received.append({"via": "hook", "hook": slug, "payload": payload, "run_id": run_id,
                                   "x_api_key": request.headers.get("x-api-key")})
        threading.Thread(target=run_outbound, args=(payload, run_id), daemon=True).start()
        return {"status": "ok"}  # sin run_id a propósito: el adaptador no puede depender de esta respuesta

    app.add_api_route("/hook/{slug}", hook, methods=["POST"])
    app.add_api_route("/hooks/{slug}", hook, methods=["POST"])
    app.add_api_route("/hooks/development/{slug}", hook, methods=["POST"])

    @app.post("/api/v2/workflows/{workflow}/runs")
    async def runs(workflow: str, request: Request) -> dict[str, Any]:
        bearer(request)
        body = await request.json()
        payload = body.get("payload") or {}
        run_id, _ = new_run(payload)
        mark_workflow(run_id, workflow)
        app.state.received.append({"via": "runs", "workflow": workflow, "payload": payload, "run_id": run_id,
                                   "environment": body.get("environment")})
        threading.Thread(target=run_outbound, args=(payload, run_id), daemon=True).start()
        return {"run_id": run_id, "queued_run_ids": [run_id], "status": "queued", "message": "ok"}

    # ---------------------------------------------------------------- llamada web, escucha y toma
    @app.post("/api/v2/voice/tokens/")
    async def voice_tokens(request: Request) -> dict[str, Any]:
        bearer(request)
        body = await request.json()
        if bool(body.get("workflow_id")) == bool(body.get("session_id")):
            raise HTTPException(400, "workflow_id o session_id, uno de los dos")
        if body.get("session_id"):
            s = app.state.sessions.get(body["session_id"])
            if s is None:
                raise HTTPException(404, "sesión no encontrada")
            if s["status"] != "in-progress":
                raise HTTPException(409, "la sesión no está en curso")
            if body.get("should_takeover"):
                s["taken_over"] = True  # el agente de voz se cae y sigue la persona
            app.state.received.append({"via": "voice_tokens", "session_id": body["session_id"], "should_takeover": bool(body.get("should_takeover"))})
            return {"url": "mock://livekit", "token": f"mock-{'take' if body.get('should_takeover') else 'listen'}", "room_name": s["run_id"]}
        if body.get("should_takeover"):
            raise HTTPException(400, "should_takeover exige session_id")
        payload = body.get("data") or {}
        run_id, session_id = new_run(payload)
        app.state.received.append({"via": "voice_tokens", "workflow": body["workflow_id"], "payload": payload, "run_id": run_id})
        say(session_id, "assistant", str(payload.get("order_text") or "Orden de Mando.") + " ¿Aceptas?")
        return {"url": "mock://livekit", "token": "mock-token", "room_name": run_id, "run_id": run_id}

    @app.post("/mock/answer/{run_id}")
    async def answer(run_id: str, request: Request) -> dict[str, Any]:
        """Lo que diría la persona por el micrófono, sin LiveKit: accept | reject | no_answer."""
        body = await request.json()
        session_id = app.state.runs.get(run_id)
        if session_id is None:
            raise HTTPException(404, "run desconocido")
        payload = app.state.sessions[session_id]["payload"]
        threading.Thread(target=finish, args=(payload, run_id, str(body.get("result") or "accept")), daemon=True).start()
        return {"ok": True}

    @app.get("/api/v2/runs/{run_id}/sessions")
    def run_sessions(run_id: str, request: Request) -> dict[str, Any]:
        bearer(request)
        sid = app.state.runs.get(run_id)
        data = [{"id": sid, "run_id": run_id, "status": app.state.sessions[sid]["status"], "type": "voice"}] if sid else []
        return {"data": data, "pagination": {"page": 1, "page_size": 50, "total_records": len(data)}}

    @app.get("/api/v2/sessions/{session_id}/messages")
    def messages(session_id: str, request: Request) -> dict[str, Any]:
        bearer(request)
        s = app.state.sessions.get(session_id)
        if s is None:
            raise HTTPException(404, "sesión no encontrada")
        return {"data": s["messages"]}

    @app.get("/api/v2/sessions/{session_id}/stream")
    async def stream(session_id: str, request: Request) -> StreamingResponse:
        bearer(request)
        s = app.state.sessions.get(session_id)
        if s is None:
            raise HTTPException(404, "sesión no encontrada")

        async def gen():
            sent = 0
            for _ in range(1200):
                while sent < len(s["messages"]):
                    yield f"event: message\ndata: {json.dumps(s['messages'][sent], ensure_ascii=False)}\n\n"
                    sent += 1
                if s["status"] != "in-progress":
                    yield "event: session_ended\ndata: {}\n\n"
                    return
                await asyncio.sleep(0.05)
        return StreamingResponse(gen(), media_type="text/event-stream")

    # ---------------------------------------------------------------- signals
    @app.post("/api/v2/signals")
    @app.post("/api/v2/signals/")
    async def signals(request: Request) -> dict[str, Any]:
        bearer(request)
        body = await request.json()
        if not isinstance(body.get("payload"), dict):
            raise HTTPException(400, "payload es obligatorio")
        app.state.signals.append(body)
        key = str(body.get("key") or "")
        if key.startswith("session."):
            s = app.state.sessions.get(key[8:])
            if s is not None and s["status"] == "in-progress":
                say(key[8:], "assistant", str(body["payload"].get("text") or "Cambio de orden."))
                say(key[8:], "user", "Recibido.")
        return {"signal_id": f"sig_{len(app.state.signals):04d}", "status": "published",
                "published_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

    @app.post("/mock/conversation")
    async def conversation(request: Request) -> dict[str, Any]:
        """Imita a `mando-ingesta-voz` v2 / `mando-asistente-chat` (PLATAFORMA_REAL.md §8 bis): las tres tools y el POST final,
        con el MISMO `report_ref` en toda la conversación. Cuerpo: {callback_url, callback_token, channel?, text, location?}.
        Devuelve lo que contestó el backend a cada POST (incluido el `say_text` de `consultar_estado`)."""
        d = await request.json()
        run_id, _ = new_run(d)
        url, tok, ch = str(d.get("callback_url") or ""), str(d.get("callback_token") or ""), str(d.get("channel") or "voice")
        common = {"schema": "mando.hr.v1", "report_ref": run_id, "hr_run_id": run_id, "channel": ch}
        steps = [dict(common, type="public_report", message="public_report", partial=True, final=False, reply_to="",
                      report={"channel": ch, "text": str(d.get("text") or ""), "zone_hint": "", "source": "asistente"},
                      extracted={"location": "", "description": str(d.get("text") or ""), "danger_now": "si", "responsive": "",
                                 "breathing_normally": "", "sensitive": "false"})]
        if d.get("location"):
            steps.append(dict(common, type="public_report_update", partial=True, final=False, field="ubicacion", value=str(d["location"])))
        steps.append(dict(common, type="report_status_query", reason="pregunta si ya viene alguien"))
        steps.append(dict(common, type="public_report", message="public_report", partial=False, final=True, reply_to="", category="sanitario",
                          report={"channel": ch, "text": str(d.get("text") or ""), "zone_hint": "", "source": "asistente"},
                          extracted={"category": "sanitario", "location": str(d.get("location") or ""), "description": str(d.get("text") or "")}))
        out = []
        async with httpx.AsyncClient(timeout=10) as client:
            for body in steps:
                r = await client.post(url, json=body, headers={"X-Mando-Token": tok})
                out.append({"type": body["type"], "status": r.status_code, "reply": r.json() if r.content else None})
                app.state.posted.append(body)
        return {"report_ref": run_id, "steps": out}

    @app.post("/mock/config")
    async def config(request: Request) -> dict[str, Any]:
        app.state.config.update(await request.json())
        return app.state.config

    @app.head("/hooks/{slug}")
    @app.get("/hooks/{slug}")
    def hook_probe(slug: str) -> dict[str, Any]:
        """`doctor` comprueba que el hook es alcanzable SIN lanzar nada: un GET/HEAD no crea ningún run."""
        return {"status": "ok", "probe": True}

    @app.get("/mock/posted")
    def posted() -> list[dict[str, Any]]:
        return app.state.posted

    @app.get("/mock/received")
    def received() -> list[dict[str, Any]]:
        return app.state.received

    from .mock_staff import install as install_staff_mock
    install_staff_mock(app)
    return app


def main() -> None:
    import uvicorn
    ap = argparse.ArgumentParser(description="HappyRobot falso en local")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--delay", type=float, default=4.0, help="segundos reales que «dura» cada llamada")
    args = ap.parse_args()
    uvicorn.run(create_mock(args.delay), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
