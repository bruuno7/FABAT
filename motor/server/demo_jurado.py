"""Demo aislada de ResQval: python -m motor.server.demo_jurado --data <directorio>."""

from __future__ import annotations

import argparse
import hmac
import json
import os
import re
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

import uvicorn
from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse

from .operational import OperationalError
from .operational_http import STATIC, create_operational_app
from .operational_service import OperationalService, document
from .operational_types import JSON, Document

PROFILES = (
    ("demo-organizador", "Organización · demo", "organizador", "gate_b"),
    ("demo-medico", "Equipo médico · demo", "medico", "medical_1"),
    ("demo-seguridad", "Seguridad · demo", "policia", "gate_a"),
    ("demo-accesos", "Accesos · demo", "staff_entradas", "gate_b"),
)
REQUIRED = (
    "MANDO_OPERATOR_TOKEN", "MANDO_PUBLIC_URL", "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_WEBHOOK_SECRET", "HR_API_KEY", "HR_API_BASE", "HR_ENV",
    "HR_WORKFLOW_DISPATCH", "HR_SECRET", "MANDO_ALLOWED_NUMBERS",
)


def configure(data: Path, connected: bool) -> None:
    mode = "connected" if connected else "simulation"
    if connected:
        missing = [key for key in REQUIRED if not os.environ.get(key, "").strip()]
        if missing:
            raise ValueError("Falta configuración: " + ", ".join(missing))
        origin = urlsplit(os.environ["MANDO_PUBLIC_URL"])
        if origin.scheme != "https" or not origin.netloc or origin.path not in ("", "/") or origin.query or origin.fragment or origin.username:
            raise ValueError("MANDO_PUBLIC_URL debe ser un origen HTTPS sin ruta.")
        if os.environ["MANDO_OPERATOR_TOKEN"] == "jurado-local":
            raise ValueError("Configura un token privado para la demo conectada.")
        secret = os.environ["TELEGRAM_WEBHOOK_SECRET"]
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", secret):
            raise ValueError("TELEGRAM_WEBHOOK_SECRET no tiene un formato válido.")
        numbers = os.environ["MANDO_ALLOWED_NUMBERS"].split(",")
        if not all(re.fullmatch(r"\+[1-9]\d{7,14}", number.strip()) for number in numbers):
            raise ValueError("MANDO_ALLOWED_NUMBERS requiere móviles E.164 separados por comas.")
    marker = data / "demo-mode"
    if data.exists() and not marker.is_file() and any(data.iterdir()):
        raise ValueError("Elige un directorio vacío: no se reutilizan bases ajenas a esta demo.")
    if marker.exists() and marker.read_text(encoding="utf-8") != mode:
        raise ValueError("Usa otro directorio al cambiar entre simulación y canales reales.")
    data.mkdir(parents=True, exist_ok=True, mode=0o700)
    marker.write_text(mode, encoding="utf-8")
    os.environ.update(
        MANDO_OPERATIONAL="1",
        MANDO_OPERATIONAL_DB=str(data.resolve() / "operations.sqlite"),
        MANDO_EXTERNAL_DELIVERY="1" if connected else "0",
        MANDO_HAPPYROBOT_DECIDES="0",
        MANDO_CONTROL_CHAT_ID="",
        MANDO_OPERATORS="",
        HR_WORKFLOW_RAPIDO="",
        HR_WORKFLOW_TG_OFFER="",
        TELEGRAM_MODE="off",
        PYTHON_DOTENV_DISABLED="1",
    )
    if connected:
        os.environ["MANDO_BRIDGE_SECRET"] = os.environ["TELEGRAM_WEBHOOK_SECRET"]
    else:
        for key in REQUIRED:
            if key != "MANDO_OPERATOR_TOKEN":
                os.environ.pop(key, None)
        os.environ.pop("MANDO_BRIDGE_SECRET", None)
        os.environ["MANDO_OPERATOR_TOKEN"] = os.environ.get("MANDO_OPERATOR_TOKEN") or "jurado-local"


def seed(service: OperationalService) -> None:
    actors = cast(list[Document], service.state()["actors"])
    existing = {row["id"] for row in actors}
    for actor, name, role, zone in PROFILES:
        if actor not in existing:
            service.execute(
                {"command_id": "demo-seed:" + actor, "kind": "register_actor",
                 "actor_id": actor, "name": name, "roles": [role], "zone": zone,
                 "channel": "web", "address": "", "availability": "available"},
                principal="demo-setup", scope="operator",
            )


def create_demo_app(data: Path, *, connected: bool = False, port: int = 8000) -> FastAPI:
    configure(data, connected)
    app = create_operational_app(port=port)
    service: OperationalService = app.state.operational
    seed(service)

    @app.get("/jurado")
    def guide() -> FileResponse:
        return FileResponse(STATIC / "demo-jurado.html", headers={"Cache-Control": "no-store"})

    @app.post("/telegram/webhook", response_model=None)
    async def telegram(request: Request) -> Document | JSONResponse:
        expected = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "") if connected else ""
        supplied = request.headers.get("x-telegram-bot-api-secret-token", "")
        if not expected or not hmac.compare_digest(expected.encode(), supplied.encode()):
            raise OperationalError("telegram_forbidden", 403)
        if "application/json" not in request.headers.get("content-type", ""):
            raise OperationalError("unsupported_media_type", 400)
        raw = bytearray()
        async for chunk in request.stream():
            if len(raw) + len(chunk) > 8192:
                raise OperationalError("input_too_large", 413)
            raw.extend(chunk)
        try:
            body = document(cast(JSON, json.loads(raw)), "body")
        except (json.JSONDecodeError, UnicodeDecodeError, RecursionError) as exc:
            raise OperationalError("invalid_json", 400) from exc
        try:
            return await run_in_threadpool(service.receive_telegram, body)
        except OperationalError as exc:
            if 400 <= exc.status < 500:
                return JSONResponse({"ok": False, "rejected": True, "error": exc.code})
            raise

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--connected", action="store_true", help="Activa Telegram y llamadas reales autorizadas.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    args = parser.parse_args()
    try:
        app = create_demo_app(args.data, connected=args.connected, port=args.port)
    except ValueError as exc:
        parser.error(str(exc))
    print("Demo conectada: contactos ficticios hasta configurarlos en la Sala." if args.connected
          else "SIMULACIÓN: sin mensajes ni llamadas reales. Acceso local por defecto: jurado-local.")
    print(f"Guía: http://127.0.0.1:{args.port}/jurado")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
