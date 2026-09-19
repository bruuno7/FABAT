"""FastAPI surface for the durable operational authority."""
# mypy: disable-error-code=untyped-decorator

from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import cast

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from motor.world import load_festival

from .multi import identity
from .operational import OperationalError, _hash
from .operational_service import (
    SPECIALISTS,
    OperationalService,
    channel_status,
    document,
)
from .operational_types import JSON, Document
from .operational_worker import DeliveryWorker
from .security import SecurityGuard, require_operator

HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"


async def json_body(request: Request, maximum: int = 65536) -> Document:
    if "application/json" not in request.headers.get("content-type", ""):
        raise OperationalError("unsupported_media_type", 400)
    body = await request.body()
    if len(body) > maximum:
        raise OperationalError("input_too_large", 400)
    try:
        value = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError) as exc:
        raise OperationalError("invalid_json", 400) from exc
    return document(cast(JSON, value), "body")


def canonical_phone(body: Document) -> Document:
    result: Document = {}
    for key in (
        "action_id",
        "assignment_id",
        "call_id",
        "hr_run_id",
        "message",
        "call_status",
        "result",
        "reason",
        "sequence",
        "eta_min",
        "destination_confirmed",
        "destination_zone_id",
        "operational_action",
        "action_confirmed",
    ):
        if key in body:
            result[key] = body[key]
    if isinstance(body.get("new_report"), dict):
        report = cast(Document, body["new_report"])
        result["new_report"] = {
            key: report[key] for key in ("id", "text", "zone") if key in report
        }
    return result


def tool_body(body: Document) -> Document:
    cleaned = {
        key: value
        for key, value in body.items()
        if key
        not in {
            "callback_token",
            "token",
            "transcripcion",
            "transcript",
            "recording_url",
        }
    }
    if "papeles" not in cleaned and any(name in cleaned for name in SPECIALISTS):
        cleaned["papeles"] = {
            name: cleaned[name] for name in SPECIALISTS if name in cleaned
        }
    return cleaned


def error_response(exc: OperationalError) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": exc.code, "message": exc.message},
        status_code=exc.status,
        headers={"Cache-Control": "no-store"},
    )


def create_operational_app(*, port: int = 8000) -> FastAPI:
    data_path = Path(
        os.environ.get("MANDO_OPERATIONAL_DB", HERE / "data" / "operations.sqlite")
    )
    data_path.parent.mkdir(parents=True, exist_ok=True)
    festival = cast(Document, load_festival())
    service = OperationalService(
        data_path,
        festival,
        callback_secret=os.environ.get("HR_SECRET", ""),
        workflow_enabled=bool(os.environ.get("HR_WORKFLOW_RAPIDO")),
        control_chat=os.environ.get("MANDO_CONTROL_CHAT_ID", ""),
    )
    worker = DeliveryWorker(
        service, external=os.environ.get("MANDO_EXTERNAL_DELIVERY") == "1"
    )

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        worker.start()
        try:
            yield
        finally:
            worker.stop()
            service.close()

    app = FastAPI(
        title="MANDO operational", docs_url=None, redoc_url=None, lifespan=lifespan
    )
    app.add_middleware(SecurityGuard)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    app.state.operational = service
    app.state.delivery_worker = worker
    app.state.port = port
    app.state.telegram = None

    @app.exception_handler(OperationalError)
    async def operational_error(_: Request, exc: OperationalError) -> JSONResponse:
        return error_response(exc)

    @app.get("/")
    @app.get("/sala")
    def sala() -> FileResponse:
        return FileResponse(STATIC / "sala-operativa.html")

    @app.get("/api/operations/state", response_model=None)
    def state(request: Request) -> Document:
        require_operator(request)
        result = service.state()
        result["channels"] = channel_status()
        return result

    @app.get("/api/operations/stream")
    async def stream(request: Request) -> StreamingResponse:
        require_operator(request)

        async def events() -> AsyncIterator[str]:
            revision = -1
            while not await request.is_disconnected():
                current = await run_in_threadpool(service.state)
                if current["revision"] != revision:
                    revision = cast(int, current["revision"])
                    current["channels"] = channel_status()
                    yield f"id: {revision}\nevent: state\ndata: {json.dumps(current, ensure_ascii=False)}\n\n"
                else:
                    yield ": keepalive\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/operations/command", response_model=None)
    async def command(request: Request) -> Document:
        require_operator(request)
        who = identity(request)
        body = await json_body(request, 16384)
        return await run_in_threadpool(
            service.execute,
            body,
            principal=str(who["id"]),
            scope="operator",
            channel="web",
        )

    @app.post("/api/operations/telegram", response_model=None)
    async def telegram(request: Request) -> Document:
        expected = os.environ.get("MANDO_BRIDGE_SECRET", "")
        supplied = request.headers.get("x-mando-bridge-token", "")
        if not expected or not hmac.compare_digest(
            expected.encode(), supplied.encode()
        ):
            raise OperationalError("bridge_forbidden", 403)
        update = await json_body(request)
        return await run_in_threadpool(
            service.receive_telegram,
            update,
        )

    async def callback_context(
        request: Request, body: Document
    ) -> tuple[Document, str]:
        token = request.headers.get("x-mando-token") or request.headers.get(
            "x-hr-secret"
        )
        token = token or str(body.pop("callback_token", "") or body.pop("token", ""))
        if not token:
            raise OperationalError("missing_callback_token", 403)
        context = await run_in_threadpool(service.authorize_callback, token)
        return context, token

    @app.post("/hr/events", response_model=None)
    async def phone_event(request: Request) -> Document:
        raw = await json_body(request)
        context, _ = await callback_context(request, raw)
        if context["channel"] != "phone":
            raise OperationalError("call_correlation_invalid", 403)
        body = canonical_phone(raw)
        sequence = body.get(
            "sequence", 1 if body.get("message") == "dispatch_progress" else 2
        )
        event = str(
            body.get("event_id")
            or f"{sequence}:{body.get('result') or body.get('call_status') or 'unknown'}"
        )
        command_id = "hr:" + _hash([context["delivery_id"], event])[:64]
        return await run_in_threadpool(
            service.execute,
            {
                "command_id": command_id,
                "kind": "phone_event",
                "delivery_id": context["delivery_id"],
                "body": body,
            },
            principal=str(context["actor_id"]),
            scope="phone",
            channel="phone",
        )

    async def workflow_context(
        request: Request, raw: Document
    ) -> tuple[Document, Document]:
        context, _ = await callback_context(request, raw)
        if context["channel"] != "happyrobot":
            raise OperationalError("workflow_correlation_invalid", 403)
        return context, tool_body(raw)

    @app.post("/hr/tools/contexto", response_model=None)
    @app.post("/hr/tools/analizar_situacion", response_model=None)
    @app.post("/hr/tools/acciones_posibles", response_model=None)
    async def workflow_read(request: Request) -> Document:
        raw = await json_body(request)
        context, _ = await workflow_context(request, raw)
        result = await run_in_threadpool(service.context, str(context["delivery_id"]))
        result["ok"] = True
        return result

    @app.post("/hr/tools/decidir", response_model=None)
    async def workflow_decide(request: Request) -> Document:
        raw = await json_body(request)
        context, body = await workflow_context(request, raw)
        event = str(body.get("event_id") or body.get("request_id") or "decision")
        return await run_in_threadpool(
            service.execute,
            {
                "command_id": "wf:" + _hash([context["delivery_id"], event])[:64],
                "kind": "workflow_decision",
                "delivery_id": context["delivery_id"],
                "body": body,
            },
            principal="happyrobot",
            scope="proposal",
            channel="web",
        )

    @app.post("/hr/tools/memoria/guardar", response_model=None)
    async def workflow_memory(request: Request) -> Document:
        raw = await json_body(request)
        context, body = await workflow_context(request, raw)
        event = str(body.get("event_id") or body.get("request_id") or "memory")
        return await run_in_threadpool(
            service.execute,
            {
                "command_id": "memory:" + _hash([context["delivery_id"], event])[:60],
                "kind": "workflow_memory",
                "delivery_id": context["delivery_id"],
                "body": body,
            },
            principal="happyrobot",
            scope="proposal",
            channel="web",
        )

    @app.post("/hr/tools/cambio", response_model=None)
    async def workflow_change(request: Request) -> Document:
        raw = await json_body(request)
        context, _ = await workflow_context(request, raw)
        result = await run_in_threadpool(service.context, str(context["delivery_id"]))
        return {"ok": True, "cambio": False, "revision": result["revision"]}

    return app
