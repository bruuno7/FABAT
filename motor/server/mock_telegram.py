"""Bot API de Telegram de mentira, en local. Mismo patrón que `mock_happyrobot`: imita SOLO lo que usa `telegram_bot.py`.

    POST /bot<token>/getMe                 → {ok, result: {username}}
    POST /bot<token>/getUpdates            → long polling con `offset` y `timeout` (aquí se espera como mucho 1 s por vuelta)
    POST /bot<token>/sendMessage           → se guarda en `sent` (lo que el bot CONTESTA)
    POST /bot<token>/answerCallbackQuery

Para las pruebas y para recorrer el circuito a mano, sin Telegram:
    POST /mock/text     {"chat_id": 1, "text": "…"}           alguien escribe al bot
    POST /mock/location {"chat_id": 1, "latitude": …, "longitude": …}
    POST /mock/button   {"chat_id": 1, "data": "golpe:storm"}  alguien pulsa un botón inline
    GET  /mock/sent                                            todo lo que ha contestado el bot

    uv run --project motor/server python -m motor.server.mock_telegram --port 8766
    TELEGRAM_API_BASE=http://127.0.0.1:8766 TELEGRAM_BOT_TOKEN=123:falso  uv run … python -m motor.server …
"""
from __future__ import annotations

import argparse
import asyncio
import itertools
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

TOKEN = "123:falso"


def create_mock_telegram(token: str = TOKEN, username: str = "mando_demo_bot") -> FastAPI:
    app = FastAPI(title="mock-telegram")
    app.state.updates = []     # pendientes de entregar
    app.state.sent = []        # sendMessage recibidos
    app.state.calls = []       # (método, cuerpo) de todo lo que pide el bot
    app.state.webhook_url = ""
    ids = itertools.count(1000)

    def push(update: dict[str, Any]) -> dict[str, Any]:
        update["update_id"] = next(ids)
        app.state.updates.append(update)
        return {"ok": True, "update_id": update["update_id"]}

    def message(chat_id: int, **extra: Any) -> dict[str, Any]:
        return {"message": {"message_id": next(ids), "date": 0, "chat": {"id": chat_id, "type": "private"},
                            "from": {"id": chat_id, "is_bot": False, "first_name": "Persona de prueba"}, **extra}}

    @app.post("/bot{tok}/{method}")
    async def api(tok: str, method: str, request: Request) -> Any:
        if tok != token:
            return JSONResponse({"ok": False, "error_code": 401, "description": "Unauthorized"}, status_code=401)
        try:
            body = await request.json()
        except Exception:
            body = {}
        app.state.calls.append((method, body))
        if method == "getMe":
            return {"ok": True, "result": {"id": 1, "is_bot": True, "first_name": "Mando (demo)", "username": username}}
        if method == "getWebhookInfo":
            return {"ok": True, "result": {"url": app.state.webhook_url, "pending_update_count": 0}}
        if method == "getUpdates":
            offset, timeout = int(body.get("offset") or 0), min(float(body.get("timeout") or 0), 1.0)
            if offset < 0:
                return {"ok": True, "result": app.state.updates[offset:]}
            app.state.updates[:] = [u for u in app.state.updates if u["update_id"] >= offset]   # confirmar = borrar, como Telegram
            waited = 0.0
            while not app.state.updates and waited < timeout:
                await asyncio.sleep(0.05)
                waited += 0.05
            return {"ok": True, "result": list(app.state.updates)}
        if method == "sendMessage":
            app.state.sent.append(body)
            return {"ok": True, "result": {"message_id": next(ids)}}
        if method == "answerCallbackQuery":
            return {"ok": True, "result": True}
        return JSONResponse({"ok": False, "error_code": 404, "description": "Not Found: method not found"}, status_code=404)

    @app.post("/mock/text")
    async def text(request: Request) -> dict[str, Any]:
        d = await request.json()
        return push(message(int(d.get("chat_id", 1)), text=str(d.get("text") or "")))

    @app.post("/mock/location")
    async def location(request: Request) -> dict[str, Any]:
        d = await request.json()
        return push(message(int(d.get("chat_id", 1)), location={"latitude": d["latitude"], "longitude": d["longitude"]}))

    @app.post("/mock/button")
    async def button(request: Request) -> dict[str, Any]:
        d = await request.json()
        chat_id = int(d.get("chat_id", 1))
        return push({"callback_query": {"id": str(next(ids)), "data": str(d.get("data") or ""), "from": {"id": chat_id},
                                        "message": {"message_id": 1, "chat": {"id": chat_id, "type": "private"}}}})

    @app.get("/mock/sent")
    def sent() -> list[dict[str, Any]]:
        return app.state.sent

    return app


def main() -> None:
    import uvicorn
    ap = argparse.ArgumentParser(description="Bot API de Telegram falsa, en local")
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--token", default=TOKEN)
    args = ap.parse_args()
    uvicorn.run(create_mock_telegram(args.token), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
