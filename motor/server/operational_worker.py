"""Leased outbox delivery. External effects are opt-in and allowlisted."""

from __future__ import annotations

import json
import os
import re
import threading
from typing import cast

import httpx

from . import abanico
from .operational import OperationalError
from .operational_service import OperationalService
from .operational_types import JSON, Document


def normalized_phone(value: str) -> str:
    return "".join(char for char in value if char.isdigit() or char == "+")


class DeliveryWorker:
    def __init__(self, service: OperationalService, *, external: bool = False) -> None:
        self.service = service
        self.external = external
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        self.thread = threading.Thread(
            target=self._run, name="operational-outbox", daemon=True
        )
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=20)

    def _run(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.service.recover_inbox()
                deliveries = self.service.claim(
                    "operational-worker", limit=1, lease_seconds=30
                )
                for delivery in deliveries:
                    self._deliver(delivery)
                if not deliveries:
                    self.stop_event.wait(0.5)
            except OperationalError:
                self.stop_event.wait(2)

    def _deliver(self, delivery: Document) -> None:
        did = str(delivery["id"])
        lease = str(delivery["lease_token"])
        if not self.external:
            self.service.settle(
                did, lease, "delivered", detail="simulated", provider_id="simulated"
            )
            return
        try:
            channel = str(delivery["channel"])
            if channel == "telegram":
                provider = self._telegram(delivery)
            elif channel == "phone":
                provider = self._happyrobot(delivery, "HR_WORKFLOW_DISPATCH")
            elif channel == "happyrobot":
                provider = self._happyrobot(delivery, "HR_WORKFLOW_RAPIDO")
            else:
                provider = "local"
            self.service.settle(did, lease, "delivered", provider_id=provider)
        except OperationalError as exc:
            self.service.settle(did, lease, "failed", detail=exc.code)
        except httpx.HTTPStatusError as exc:
            status = (
                "failed"
                if 400 <= exc.response.status_code < 500
                and exc.response.status_code != 429
                else self._retry_status(delivery)
            )
            self.service.settle(
                did,
                lease,
                status,
                detail=f"HTTP {exc.response.status_code}",
                retry_after_s=min(60, 2 ** int(str(delivery["attempts"]))),
            )
        except (
            httpx.HTTPError,
            ValueError,
            KeyError,
            TypeError,
            json.JSONDecodeError,
        ) as exc:
            self.service.settle(
                did, lease, self._retry_status(delivery), detail=type(exc).__name__
            )

    @staticmethod
    def _retry_status(delivery: Document) -> str:
        if delivery["channel"] == "telegram":
            return "retry" if int(str(delivery["attempts"])) < 3 else "failed"
        return "uncertain"

    def _telegram(self, delivery: Document) -> str:
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        if not token:
            raise OperationalError("telegram_unconfigured", 503)
        recipient = self.service.recipient(str(delivery["recipient_id"]))
        payload = cast(Document, delivery.get("payload") or {})
        if delivery["purpose"] == "callback":
            request: Document = {
                "callback_query_id": payload["callback_query_id"],
                "text": delivery["text"],
                "show_alert": bool(payload.get("error")),
            }
            method = "answerCallbackQuery"
        else:
            request = {"chat_id": recipient["address"], "text": delivery["text"]}
            buttons = self._buttons(delivery)
            if buttons:
                request["reply_markup"] = {"inline_keyboard": cast(JSON, buttons)}
            method = "sendMessage"
        response = httpx.post(
            f"https://api.telegram.org/bot{token}/{method}",
            json=request,
            timeout=8,
        )
        response.raise_for_status()
        body = response.json()
        if body.get("ok") is not True:
            raise ValueError("telegram_rejected")
        result = body.get("result")
        return str(result.get("message_id") if isinstance(result, dict) else "callback")

    @staticmethod
    def _buttons(delivery: Document) -> list[list[Document]]:
        payload = cast(Document, delivery.get("payload") or {})
        aid = payload.get("assignment_id")
        version = payload.get("expected_version")
        purpose = delivery.get("purpose")
        if not aid or type(version) is not int:
            return []
        prefix = f"m:{{}}:{aid}:{version}"
        if purpose == "offer":
            return [
                [
                    {"text": "Aceptar", "callback_data": prefix.format("accept")},
                    {"text": "Rechazar", "callback_data": prefix.format("decline")},
                ]
            ]
        if purpose == "task":
            status = payload.get("status")
            if status in {"arrived", "located"}:
                action, label = (
                    ("locate", "Persona localizada")
                    if status == "arrived"
                    else ("complete", "Tarea completada")
                )
                return [[{"text": label, "callback_data": prefix.format(action)}]]
            if status not in {"accepted", "en_route"}:
                return []
            return [
                [
                    {
                        "text": f"ETA {minutes} min",
                        "callback_data": prefix.format("eta") + f":{minutes}",
                    }
                    for minutes in (4, 10, 15)
                ],
                [
                    {
                        "text": "He llegado al destino",
                        "callback_data": prefix.format("arrive"),
                    },
                    {
                        "text": "Revocar aceptación",
                        "callback_data": prefix.format("decline"),
                    },
                ],
            ]
        return []

    def _happyrobot(self, delivery: Document, variable: str) -> str:
        workflow = os.environ.get(variable, "").strip()
        if not workflow or not abanico.api_key() or not abanico.api_base():
            raise OperationalError("happyrobot_unconfigured", 503)
        did = str(delivery["id"])
        lease = str(delivery["lease_token"])
        context = self.service.execute(
            {
                "command_id": "start:" + did,
                "kind": "delivery_start",
                "delivery_id": did,
                "lease_token": lease,
            },
            principal="worker",
            scope="system",
        )
        callback = self.service.capability(did)
        base = os.environ.get("MANDO_PUBLIC_URL", "").rstrip("/")
        if not base.startswith("https://"):
            raise OperationalError("public_callback_unconfigured", 503)
        if delivery["channel"] == "phone":
            recipient = self.service.recipient(str(delivery["recipient_id"]))
            number = normalized_phone(str(recipient["address"]))
            if not re.fullmatch(r"\+[1-9]\d{7,14}", number):
                raise OperationalError("invalid_phone_number", 400)
            allowed = {
                normalized_phone(item)
                for item in os.environ.get("MANDO_ALLOWED_NUMBERS", "").split(",")
            }
            if number not in allowed:
                raise OperationalError("number_not_allowlisted", 403)
            payload: Document = {
                "action_id": did,
                "assignment_id": context["assignment_id"],
                "expected_assignment_version": context["initial_assignment_version"],
                "destination_zone_id": context["zone"],
                "correlation_id": did,
                "to_number": number,
                "role": "equipo operativo",
                "order_text": delivery["text"],
                "zone_spoken": context["zone"],
                "priority": "operativa",
                "callback_url": base + "/hr/events",
                "callback_token": callback,
            }
        else:
            details = self.service.context(did)
            incident = cast(Document, details["incident"])
            details.update(
                texto=incident["text"],
                canal="operational",
                zona_sugerida=incident["zone"],
                idioma="es",
                remitente="informante",
            )
            payload = {
                "texto": incident["text"],
                "canal": "operational",
                "zona_sugerida": incident["zone"],
                "idioma": "es",
                "remitente": "informante",
                "transcripcion": "",
                "correlation_id": did,
                "incident_id": details["incident_id"],
                "entrada_json": json.dumps(details, ensure_ascii=False),
                "callback_url": base,
                "callback_token": callback,
            }
        response = httpx.post(
            f"{abanico.api_base()}/workflows/{workflow}/runs",
            json={
                "environment": os.environ.get("HR_ENV") or "development",
                "payload": payload,
            },
            headers={"Authorization": f"Bearer {abanico.api_key()}"},
            timeout=8,
        )
        response.raise_for_status()
        result = response.json()
        queued = result.get("queued_run_ids")
        run_id = result.get("run_id") or (
            queued[0] if isinstance(queued, list) and queued else ""
        )
        if not isinstance(run_id, str) or not run_id:
            raise ValueError("missing_run_id")
        return run_id
