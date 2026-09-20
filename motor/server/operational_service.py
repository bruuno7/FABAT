"""Channel commands and provider correlations committed with operational state."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import ClassVar, cast

from . import abanico
from .operational import (
    ACTIVE,
    FIELDS,
    MIRROR_ESTADOS,
    MIRROR_GRAVEDAD,
    MIRROR_TIPOS,
    MIRROR_TYPES,
    PERMISSIONS,
    ROLES,
    OperationalError,
    OperationalStore,
    _boolean,
    _choice,
    _document,
    _encode,
    _hash,
    _id,
    _integer,
    _public,
    _reference,
    _text,
)
from .operational_types import JSON, Assignment, Document, State

RESULTS = {
    "accept",
    "reject",
    "unclear",
    "unknown",
    "no_answer",
    "timeout",
    "provider_failed",
}
SPECIALISTS = {"triaje", "prioridad", "recursos", "avisos", "vigia", "critico"}
TRANSITIONS = {"accept", "decline", "eta", "arrive", "locate", "complete"}


def document(value: JSON, field: str) -> Document:
    if not isinstance(value, dict):
        raise OperationalError("invalid_" + field, 400)
    return value


def phone_result(body: Document) -> str:
    result = body.get("result")
    if result in (None, ""):
        status = str(body.get("call_status") or "").lower()
        return {
            "no_answer": "no_answer",
            "no-answer": "no_answer",
            "busy": "no_answer",
            "voicemail": "no_answer",
            "timeout": "timeout",
            "failed": "provider_failed",
        }.get(status, "unknown")
    return _choice(result, RESULTS, "result")


def telegram_command(update: Document) -> Document:
    uid = _integer(update.get("update_id"), "update_id", 0)
    callback = document(update.get("callback_query", {}), "callback")
    message = document(callback.get("message", update.get("message", {})), "message")
    sender = document(callback.get("from", message.get("from")), "sender")
    actor = _integer(sender.get("id"), "sender_id")
    if sender.get("is_bot") is True:
        raise OperationalError("bot_sender", 403)
    text = message.get("text") or message.get("caption") or ""
    location_only = not text and isinstance(message.get("location"), dict)
    if not text and message.get("photo"):
        text = "Foto recibida; falta una descripción del incidente y su ubicación."
    return {
        "command_id": f"tg:{uid}",
        "kind": "telegram_event",
        "payload_hash": _hash(update),
        "actor_id": f"tg:{actor}",
        "address": str(actor),
        "name": str(sender.get("first_name") or "Informante")[:120],
        "text": _text(text, "text", 2000, empty=True),
        "callback": _text(callback.get("data", ""), "callback", 64, empty=True),
        "callback_id": _text(callback.get("id", ""), "callback_id", 200, empty=True),
        "location_only": location_only,
        "reply_to": document(message.get("reply_to_message", {}), "reply").get(
            "message_id"
        ),
    }


class OperationalService(OperationalStore):
    command_fields: ClassVar[dict[str, set[str]]] = FIELDS | {
        "telegram_event": {
            "actor_id",
            "address",
            "name",
            "text",
            "callback",
            "callback_id",
            "reply_to",
            "payload_hash",
            "location_only",
        },
        "delivery_start": {"delivery_id", "lease_token"},
        "phone_event": {"delivery_id", "body"},
        "workflow_decision": {"delivery_id", "body"},
        "workflow_memory": {"delivery_id", "body"},
    }
    command_permissions: ClassVar[dict[str, set[str]]] = {
        **PERMISSIONS,
        "telegram": PERMISSIONS["telegram"] | {"telegram_event"},
        "phone": PERMISSIONS["phone"] | {"phone_event"},
        "system": PERMISSIONS["system"] | {"delivery_start"},
        "proposal": PERMISSIONS["proposal"] | {"workflow_decision", "workflow_memory"},
    }

    def __init__(
        self,
        path: str | Path,
        festival: Document,
        *,
        clock: Callable[[], float] = time.time,
        callback_secret: str = "",
        workflow_enabled: bool = False,
        control_chat: str = "",
        happyrobot_plans_telegram: bool = False,
        telegram_via_happyrobot: bool = False,
    ) -> None:
        super().__init__(
            path,
            festival,
            clock=clock,
            happyrobot_plans_telegram=happyrobot_plans_telegram,
            telegram_via_happyrobot=telegram_via_happyrobot,
        )
        self.callback_secret = callback_secret
        self.workflow_enabled = workflow_enabled
        self.control_id = "control-" + _hash(control_chat)[:16] if control_chat else ""
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS operational_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        if self.control_id:
            self.execute(
                {
                    "command_id": self.control_id,
                    "kind": "identify",
                    "actor_id": self.control_id,
                    "channel": "telegram",
                    "address": control_chat,
                    "name": "Centro de control",
                },
                principal=self.control_id,
                scope="system",
                channel="telegram",
            )

    def _meta(self, key: str) -> Document:
        row = cast(
            tuple[str] | None,
            self._db.execute(
                "SELECT value FROM operational_metadata WHERE key=?",
                (key,),
            ).fetchone(),
        )
        return cast(Document, json.loads(row[0])) if row else {}

    def _save_meta(self, key: str, value: Document) -> None:
        self._db.execute(
            "INSERT INTO operational_metadata VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, _encode(value)),
        )

    def receive_telegram(self, update: Document) -> Document:
        command = telegram_command(update)
        key = "inbox:" + str(command["command_id"])
        with self._lock:
            with self._transaction() as (_, now):
                existing = self._meta(key)
                if existing and existing["hash"] != command["payload_hash"]:
                    raise OperationalError("command_collision", 409)
                if not existing:
                    self._save_meta(
                        key,
                        {
                            "update": update,
                            "hash": command["payload_hash"],
                            "status": "pending",
                            "received_at": now,
                        },
                    )
            try:
                result = self.execute(
                    command,
                    principal=str(command["actor_id"]),
                    scope="telegram",
                    channel="telegram",
                )
            except OperationalError as exc:
                if exc.status < 500:
                    with self._transaction() as (_, _now):
                        record = self._meta(key)
                        record.update(status="rejected", error=exc.code)
                        self._save_meta(key, record)
                raise
            with self._transaction() as (_, _now):
                record = self._meta(key)
                record["status"] = "processed"
                self._save_meta(key, record)
            return result

    def recover_inbox(self) -> None:
        with self._lock:
            rows = cast(
                list[tuple[str]],
                self._db.execute(
                    "SELECT value FROM operational_metadata WHERE key LIKE 'inbox:%' "
                    "AND json_extract(value, '$.status')='pending' ORDER BY rowid LIMIT 10"
                ).fetchall(),
            )
        for row in rows:
            pending = cast(Document, json.loads(row[0]))
            try:
                self.receive_telegram(document(pending["update"], "update"))
            except OperationalError as exc:
                if exc.status >= 500:
                    raise

    def receive_happyrobot(self, payload: Document) -> Document:
        """Espejo de solo lectura: HappyRobot decide por Telegram y MANDO solo lo refleja.

        No crea ofertas, no reserva capacidad ni toca versiones de asignación: la
        autoridad operativa sigue siendo MANDO. La interfaz pinta este espejo y sus
        botones de coordinación quedan reservados al override humano.
        """
        events = payload.get("events")
        if not isinstance(events, list) or not 1 <= len(events) <= 50:
            raise OperationalError("invalid_mirror", 400)
        with self._transaction() as (data, now):
            mirror = self._mirror(data)
            for raw in events:
                self._mirror_event(mirror, document(raw, "mirror_event"), now)
            mirror["updated_at"] = now
        return {"ok": True, "applied": len(events)}

    @staticmethod
    def _mirror(data: State) -> Document:
        mirror = data.get("hr_mirror")
        if not isinstance(mirror, dict):
            mirror = {"incidents": {}, "assignments": [], "staff": None}
            data["hr_mirror"] = mirror
        if not isinstance(mirror.get("incidents"), dict):
            mirror["incidents"] = {}
        if not isinstance(mirror.get("assignments"), list):
            mirror["assignments"] = []
        return mirror

    @staticmethod
    def _mirror_int(value: object, field: str, low: int, high: int) -> int:
        if isinstance(value, str):
            value = value.strip()
            if not value or value.lower() == "null":
                raise OperationalError("invalid_" + field, 400)
            try:
                value = int(value, 10)
            except ValueError:
                raise OperationalError("invalid_" + field, 400) from None
        return _integer(value, field, low, high)

    @staticmethod
    def _mirror_recursos(value: object) -> list[Document]:
        if value is None:
            return []
        if not isinstance(value, list) or len(value) > 8:
            raise OperationalError("invalid_recursos_requeridos", 400)
        out: list[Document] = []
        for raw in value:
            item = document(raw, "recurso")
            if set(item) - {"rol", "cantidad"}:
                raise OperationalError("invalid_recursos_requeridos", 400)
            out.append({
                "rol": _choice(item.get("rol"), ROLES, "rol"),
                "cantidad": OperationalService._mirror_int(item.get("cantidad", 1), "cantidad", 1, 10),
            })
        return out

    @staticmethod
    def _mirror_event(mirror: Document, event: Document, now: float) -> None:
        kind = _choice(event.get("type"), MIRROR_TYPES, "type")
        if kind == "tg_staff":
            disponibles = OperationalService._mirror_int(event.get("disponibles"), "disponibles", 0, 500)
            total = OperationalService._mirror_int(event.get("total"), "total", 0, 500)
            if disponibles > total:
                raise OperationalError("invalid_mirror", 400)
            mirror["staff"] = {"disponibles": disponibles, "total": total, "t": now}
            return
        incidents = cast(dict[str, Document], mirror["incidents"])
        if kind == "tg_incident":
            iid = _id(event.get("id"), "id")
            incidents[iid] = {
                "id": iid,
                "texto": _text(event.get("texto") or "", "texto", 400, empty=True),
                "tipo": _choice(event.get("tipo", "otro"), MIRROR_TIPOS, "tipo"),
                "zona": _text(event.get("zona") or "", "zona", 60, empty=True) or None,
                "gravedad": _choice(event.get("gravedad", "sin_clasificar"), MIRROR_GRAVEDAD, "gravedad"),
                "alias_informante": _text(event.get("alias_informante") or "", "alias_informante", 40, empty=True),
                "recursos_requeridos": OperationalService._mirror_recursos(event.get("recursos_requeridos")),
                "t": now,
            }
            return
        iid = _id(event.get("incident_id"), "incident_id")
        rol = _choice(event.get("rol"), ROLES, "rol")
        estado = _choice(event.get("estado"), MIRROR_ESTADOS, "estado")
        alias = _text(event.get("alias") or "", "alias", 40, empty=True)
        eta_raw = event.get("eta_min")
        eta = None if eta_raw in (None, "") else OperationalService._mirror_int(eta_raw, "eta_min", 0, 240)
        intento = OperationalService._mirror_int(event.get("intento", 1), "intento", 1, 20)
        incidents.setdefault(iid, {
            "id": iid, "texto": "", "tipo": "otro", "zona": None, "gravedad": "sin_clasificar",
            "alias_informante": "", "recursos_requeridos": [], "t": now,
        })
        rows = cast(list[Document], mirror["assignments"])
        row = next((r for r in rows if r.get("incident_id") == iid and r.get("rol") == rol
                    and r.get("alias", "") == alias and r.get("intento") == intento), None)
        if row is None:
            row = {"incident_id": iid, "rol": rol, "alias": alias, "intento": intento}
            rows.append(row)
        row.update(estado=estado, eta_min=eta,
                   desde_zona=_text(event.get("from_zone") or "", "from_zone", 60, empty=True) or None,
                   motivo=_text(event.get("motivo") or "", "motivo", 200, empty=True), t=now)
        del rows[:-100]

    def capability(self, delivery_id: str) -> str:
        if not self.callback_secret:
            raise OperationalError("callback_secret_unconfigured", 503)
        return hmac.new(
            self.callback_secret.encode(),
            ("call:" + delivery_id).encode(),
            hashlib.sha256,
        ).hexdigest()

    def authorize_callback(self, token: str) -> Document:
        with self._transaction() as (_, now):
            binding = self._meta("cap:" + hashlib.sha256(token.encode()).hexdigest())
            delivery_id = str(binding.get("delivery_id") or "")
            if not delivery_id or not hmac.compare_digest(
                self.capability(delivery_id), token
            ):
                raise OperationalError("invalid_callback_token", 403)
            context = self._meta("launch:" + delivery_id)
            if not context or cast(float, context["deadline"]) < now:
                raise OperationalError("callback_expired", 409)
            return context

    @staticmethod
    def _planning_context(data: State) -> Document:
        # Sin revisiones de transporte: reclamar una entrega no invalida el plan.
        return _document({
            "incidents": {iid: {k: v for k, v in _document(i).items() if k in {
                "id", "version", "zone", "priority", "status", "needs", "life_threat", "review_required",
            }} for iid, i in data["incidents"].items()},
            "resources": {aid: {k: v for k, v in _document(a).items() if k in {
                "id", "version", "roles", "zone", "availability",
            }} for aid, a in data["actors"].items() if a["roles"]},
            "assignments": {aid: {k: v for k, v in _document(a).items() if k in {
                "id", "version", "incident_id", "actor_id", "role", "zone", "status", "eta_min",
            }} for aid, a in data["assignments"].items()},
            "reservations": data["reservations"],
        })

    def _changes(self, data: State, launch: Document) -> Document:
        current = self._planning_context(data)
        original = document(launch.get("planning_context", {}), "planning_context")
        affected: Document = {}
        for group, values in current.items():
            before = document(original.get(group, {}), group)
            after = document(values, group)
            changed = [key for key in sorted(before.keys() | after.keys()) if before.get(key) != after.get(key)]
            if changed:
                affected[group] = cast(JSON, changed)
        reasons = [f"{group}_changed" for group in affected]
        return {
            "cambio": bool(affected), "motivos": cast(JSON, reasons), "afectados": affected,
            "motivo": "; ".join(reasons) if reasons else "context_unchanged",
            "context_version": _hash(current),
            "launch_context_version": _hash(original),
        }

    def changes(self, delivery_id: str) -> Document:
        self.reconcile()
        with self._transaction() as (data, _):
            launch = self._meta("launch:" + delivery_id)
            if not launch:
                raise OperationalError("correlation_missing", 409)
            incident = data["incidents"][str(launch["incident_id"])]
            return {"ok": True, **self._changes(data, launch), "revision": data["revision"],
                    "expected_version": launch["expected_version"], "current_version": incident["version"],
                    "incident_id": incident["id"], "correlation_id": delivery_id,
                    "siguiente_accion": "Revisar el plan vigente en MANDO; no repetir llamadas inciertas."}

    def context(self, delivery_id: str) -> Document:
        self.reconcile()
        with self._transaction() as (data, _):
            context = self._meta("launch:" + delivery_id)
            incident = data["incidents"].get(str(context.get("incident_id")))
            if not incident:
                raise OperationalError("correlation_missing", 409)
            resources: list[Document] = []
            for actor in data["actors"].values():
                if not actor["roles"]:
                    continue
                aid = data["reservations"].get("actor:" + actor["id"])
                assignment = data["assignments"].get(aid or "")
                resources.append({
                    **{k: v for k, v in _document(actor).items() if k != "address"},
                    "available_for_assignment": actor["availability"] == "available" and not aid
                    and not self._requires_followup(data, actor["id"], incident["id"]),
                    "occupancy": assignment["status"] if assignment else "free",
                    "assignment_id": aid, "incident_id": assignment["incident_id"] if assignment else None,
                    "requires_followup": self._requires_followup(data, actor["id"], incident["id"]),
                })
            incidents = [{k: v for k, v in _document(i).items() if k not in {
                "reporter_id", "reporter_ids", "updates", "tasks",
            }} for i in data["incidents"].values() if i["status"] not in {"closed", "merged"} or i["id"] == incident["id"]]
            snapshot = _document({
                "correlation_id": delivery_id, "incident_id": incident["id"],
                "expected_version": context["expected_version"], "current_version": incident["version"],
                "revision": data["revision"], **self._changes(data, context),
                "incident": next(i for i in incidents if i["id"] == incident["id"]),
                "incidents": incidents, "resources": resources,
                "assignments": [{k: v for k, v in _document(a).items() if k not in {"communication", "reason"}}
                                for a in data["assignments"].values() if a["status"] in ACTIVE],
                "reservations": data["reservations"],
                "actions": ["offer", "notify", "evacuate", "stop_show", "request_external"],
                "required_specialists": sorted(SPECIALISTS), "authority": "MANDO",
            })
            return cast(Document, _public(snapshot, [a["address"] for a in data["actors"].values()]))

    def _dispatch(
        self,
        data: State,
        command: Document,
        principal: str,
        scope: str,
        channel: str,
        now: float,
    ) -> Document:
        kind = str(command["kind"])
        if kind == "register_actor" and command.get("channel") == "telegram":
            address = str(command.get("address") or "")
            if (
                not re.fullmatch(r"[1-9]\d*", address)
                or command.get("actor_id") != "tg:" + address
            ):
                raise OperationalError("telegram_identity_must_match_from_id", 400)
        if kind == "telegram_event":
            if principal != command["actor_id"] or channel != "telegram":
                raise OperationalError("identity_forbidden", 403)
            return self._telegram(data, command, principal, now)
        if kind == "delivery_start":
            return self._start_delivery(data, command, now)
        if kind == "phone_event":
            return self._phone(data, command, principal, now)
        if kind in {"workflow_decision", "workflow_memory"}:
            return self._workflow(data, command, now)
        return super()._dispatch(data, command, principal, scope, channel, now)

    def _failure(
        self, data: State, command: Document, error: OperationalError, now: float
    ) -> None:
        if command["kind"] == "workflow_decision":
            did = str(command["delivery_id"])
            context = self._meta("launch:" + did)
            if context and context["status"] not in {"pending_human", "applied", "stale", "timeout"}:
                context.update(status="failed", last_error=error.code)
                self._save_meta("launch:" + did, context)
                self._event(
                    data,
                    now,
                    "workflow.failed",
                    "happyrobot",
                    str(context["incident_id"]),
                )

    def _report(
        self,
        data: State,
        command: Document,
        principal: str,
        scope: str,
        channel: str,
        now: float,
    ) -> Document:
        result = super()._report(data, command, principal, scope, channel, now)
        iid = str(result["incident_id"])
        incident = data["incidents"][iid]
        self._control(data, now, iid, "Nuevo aviso: " + incident["text"])
        if self.workflow_enabled:
            did = _reference("workflow", str(command["command_id"]))
            data["deliveries"][did] = {
                "id": did,
                "version": 1,
                "channel": "happyrobot",
                "recipient_id": "",
                "purpose": "review",
                "text": incident["text"],
                "incident_id": iid,
                "assignment_id": None,
                "status": "pending",
                "attempts": 0,
                "payload": {},
                "last_error": "",
                "private_detail": "",
                "provider_id": "",
                "lease_token": "",
                "lease_until": 0,
                "worker": "",
                "next_attempt_at": now,
            }
        return result

    def _control(self, data: State, now: float, iid: str, text: str) -> None:
        if self.control_id:
            self._say(data, now, self.control_id, "control", text, iid)

    def _telegram(
        self, data: State, command: Document, principal: str, now: float
    ) -> Document:
        self._register(
            data,
            {
                "kind": "identify",
                "actor_id": principal,
                "channel": "telegram",
                "address": command["address"],
                "name": command["name"],
            },
            principal,
            "telegram",
        )
        if command.get("location_only") is True:
            self._say(data, now, principal, "question",
                      "Ubicación GPS recibida. Indica por escrito la zona del recinto y qué ocurre; "
                      "no podemos convertir coordenadas en una zona con seguridad.", "")
            return {"actor_id": principal, "location_requested": True}
        text = str(command["text"])
        callback = str(command["callback"])
        if callback:
            parts = callback.split(":")
            if len(parts) < 4 or parts[0] != "m" or not parts[3].isdigit():
                raise OperationalError("invalid_button", 400)
            verb, aid, version = parts[1], parts[2], int(parts[3])
            if verb not in TRANSITIONS:
                raise OperationalError("invalid_button", 400)
            transition: Document = {
                "kind": verb,
                "assignment_id": aid,
                "expected_version": version,
            }
            if verb == "decline":
                transition["reason"] = "Rechazo explícito del personal"
            if verb == "eta":
                if len(parts) != 5 or not parts[4].isdigit():
                    raise OperationalError("invalid_eta", 400)
                assignment = data["assignments"].get(aid)
                if not assignment:
                    raise OperationalError("assignment_missing", 409)
                transition.update(
                    eta_min=int(parts[4]),
                    destination_confirmed=True,
                    destination_zone_id=assignment["zone"],
                )
            try:
                result = self._transition(data, transition, principal, "telegram", now)
            except OperationalError as exc:
                self._say(
                    data,
                    now,
                    principal,
                    "callback",
                    "La acción ya no es válida. Actualiza el estado antes de volver a intentarlo.",
                    "",
                    payload={
                        "callback_query_id": command["callback_id"],
                        "error": exc.code,
                    },
                )
                return {"actor_id": principal, "rejected": True, "error": exc.code}
            if command["callback_id"]:
                self._say(
                    data,
                    now,
                    principal,
                    "callback",
                    "Acción registrada.",
                    "",
                    payload={"callback_query_id": command["callback_id"]},
                )
            self._staff_followup(data, data["assignments"][aid], now)
            return result
        actor = data["actors"][principal]
        verb = text.split(maxsplit=1)[0].split("@")[0].lower() if text else ""
        if verb in {"/start", "/ayuda", "/help", "/rol", "/estado", "/alta"}:
            tasks = [
                a
                for a in data["assignments"].values()
                if a["actor_id"] == principal and a["status"] in ACTIVE
            ]
            self._say(
                data,
                now,
                principal,
                "help",
                f"Identidad: {principal}. Roles: {', '.join(actor['roles']) or 'informante'}.\n"
                "Describe qué ocurre y la zona. Responde a la pregunta de ubicación si falta.\n"
                "/disponible · /baja · /estado. Los roles los concede coordinación.",
                tasks[0]["incident_id"] if tasks else "",
            )
            for task in tasks:
                self._staff_followup(data, task, now)
            return {"actor_id": principal}
        if verb in {"/disponible", "/baja"}:
            return super()._dispatch(
                data,
                {
                    "kind": "availability",
                    "actor_id": principal,
                    "expected_version": actor["version"],
                    "availability": "available"
                    if verb == "/disponible"
                    else "unavailable",
                },
                principal,
                "telegram",
                "telegram",
                now,
            )
        if verb.startswith("/"):
            raise OperationalError("unsupported_telegram_command", 422)
        _text(text, "text")
        reply_to = command.get("reply_to")
        reply = (
            self._meta(f"tg-message:{command['address']}:{reply_to}")
            if reply_to
            else {}
        )
        candidates = [
            i
            for i in data["incidents"].values()
            if principal in i["reporter_ids"]
            and i["status"] not in {"closed", "merged"}
        ]
        zone, _, needs, _ = self._parse(text, None)
        target = data["incidents"].get(str(reply.get("incident_id")))
        if target and principal not in target["reporter_ids"]:
            raise OperationalError("incident_forbidden", 403)
        if target is None and zone and not needs:
            missing = [i for i in candidates if i["zone"] is None]
            target = missing[0] if len(missing) == 1 else None
        if target and not re.search(r"\botra?\b", text, re.IGNORECASE):
            result = super()._dispatch(
                data,
                {
                    "kind": "update",
                    "incident_id": target["id"],
                    "expected_version": target["version"],
                    "text": text if self._all_clear(text, zone) else target["text"] + "\n" + text,
                    "zone": zone or target["zone"],
                },
                principal,
                "telegram",
                "telegram",
                now,
            )
            self._control(
                data, now, target["id"], "El informante ha actualizado la incidencia."
            )
            return result
        if any(
            a["actor_id"] == principal and a["status"] in ACTIVE
            for a in data["assignments"].values()
        ):
            # Quien ya tiene una tarea activa es personal en servicio: su texto
            # (preguntas, notas, respuestas) lo lleva HappyRobot, no abre un aviso
            # nuevo en MANDO.
            return {"actor_id": principal, "ignored": True}
        return self._report(
            data,
            {
                "kind": "report",
                "command_id": command["command_id"],
                "text": text,
                "zone": zone,
            },
            principal,
            "telegram",
            "telegram",
            now,
        )

    def _staff_followup(self, data: State, assignment: Assignment, now: float) -> None:
        actor = data["actors"][assignment["actor_id"]]
        if actor["channel"] == "telegram":
            self._say(
                data,
                now,
                actor["id"],
                "task",
                f"{assignment['status']} · destino {assignment['zone']}. "
                "Confirma solo el hito que hayas realizado.",
                assignment["incident_id"],
                assignment,
                {"status": assignment["status"]},
            )
        self._control(
            data,
            now,
            assignment["incident_id"],
            f"Equipo {actor['name']}: {assignment['status']} · {assignment['zone']}.",
        )

    def _start_delivery(self, data: State, command: Document, now: float) -> Document:
        did = _id(command.get("delivery_id"), "delivery_id")
        delivery = data["deliveries"].get(did)
        if (
            not delivery
            or delivery["status"] != "leased"
            or delivery["lease_until"] <= now
            or not hmac.compare_digest(
                str(command.get("lease_token", "")), delivery["lease_token"]
            )
        ):
            raise OperationalError("delivery_lease_lost", 409)
        if self._meta("launch:" + did):
            raise OperationalError("delivery_already_started", 409)
        incident = self._incident(data, delivery["incident_id"])
        assignment = data["assignments"].get(delivery["assignment_id"] or "")
        if delivery["channel"] == "phone" and (
            not assignment or assignment["status"] != "offered"
        ):
            raise OperationalError("call_not_offer", 409)
        context: Document = {
            "delivery_id": did,
            "incident_id": incident["id"],
            "channel": delivery["channel"],
            "expected_version": incident["version"],
            "assignment_id": assignment["id"] if assignment else None,
            "actor_id": assignment["actor_id"] if assignment else "happyrobot",
            "assignment_version": assignment["version"] if assignment else None,
            "initial_assignment_version": assignment["version"] if assignment else None,
            "zone": incident["zone"],
            "deadline": now + 900,
            "sequence": 0,
            "status": "launched",
            "last_result": "",
            "call_id": "",
            "planning_context": self._planning_context(data),
        }
        capability = self.capability(did)
        self._save_meta(
            "cap:" + hashlib.sha256(capability.encode()).hexdigest(),
            {"delivery_id": did},
        )
        self._save_meta("launch:" + did, context)
        self._event(
            data,
            now,
            delivery["channel"] + ".started",
            "system",
            incident["id"],
            assignment["id"] if assignment else None,
        )
        return context

    def _phone(
        self, data: State, command: Document, principal: str, now: float
    ) -> Document:
        did = _id(command.get("delivery_id"), "delivery_id")
        context = self._meta("launch:" + did)
        body = document(command.get("body"), "body")
        if (
            not context
            or context["channel"] != "phone"
            or context["actor_id"] != principal
        ):
            raise OperationalError("call_correlation_invalid", 403)
        if cast(float, context["deadline"]) < now:
            raise OperationalError("call_expired", 409)
        for key, expected in (
            ("action_id", did),
            ("correlation_id", did),
            ("assignment_id", context["assignment_id"]),
            ("expected_assignment_version", context["initial_assignment_version"]),
        ):
            if body.get(key) not in (None, "", expected):
                raise OperationalError("call_correlation_invalid", 409)
        if "event_id" in body:
            _id(body["event_id"], "event_id")
        sequence = _integer(body.get("sequence"), "sequence", 1, 1000)
        final = _boolean(body.get("final", False), "final")
        if context.get("final") is True:
            raise OperationalError("call_finalized", 409)
        if sequence <= cast(int, context["sequence"]):
            raise OperationalError("call_out_of_order", 409)
        call_id = _text(
            body.get("call_id") or body.get("hr_run_id") or did, "call_id", 200
        )
        delivery = data["deliveries"][did]
        known_id = context["call_id"]
        if known_id and known_id != call_id:
            raise OperationalError("call_id_mismatch", 409)
        if (
            body.get("hr_run_id")
            and delivery["provider_id"]
            and body["hr_run_id"] != delivery["provider_id"]
        ):
            raise OperationalError("run_id_mismatch", 409)
        result = phone_result(body)
        # Un callback autenticado acredita que la oferta llegó al proveedor, no aceptación.
        delivery.update({"status": "delivered", "lease_token": "", "lease_until": 0,
                         "version": delivery["version"] + 1})
        if body.get("hr_run_id"):
            delivery["provider_id"] = _text(body["hr_run_id"], "hr_run_id", 200)
        assignment = data["assignments"][str(context["assignment_id"])]
        notice = body.get("new_report")
        new_incident: JSON = None
        if notice is not None:
            report = document(notice, "new_report")
            notice_id = _id(report.get("id"), "report_id")
            key = f"phone-notice:{did}:{notice_id}"
            prior = self._meta(key)
            if prior and prior["hash"] != _hash(report):
                raise OperationalError("report_collision", 409)
            if prior:
                new_incident = prior["incident_id"]
            else:
                new_incident = self._report(
                    data,
                    {
                        "kind": "report",
                        "command_id": _reference("phone-report", f"{did}:{notice_id}"),
                        "text": report.get("text"),
                        "zone": report.get("zone"),
                    },
                    principal,
                    "phone",
                    "phone",
                    now,
                )["incident_id"]
                self._save_meta(
                    key, {"hash": _hash(report), "incident_id": new_incident}
                )
        stale = (
            context["status"] == "stale"
            or assignment["version"] != context["assignment_version"]
            or assignment["status"] not in ACTIVE
            or (assignment["status"] == "offered" and assignment["expires_at"] <= now)
        )
        applied = False
        if not stale:
            self._transition(
                data,
                {
                    "kind": "call_result",
                    "assignment_id": assignment["id"],
                    "expected_version": assignment["version"],
                    "result": result,
                    "metadata": {
                        "call_id": call_id,
                        "sequence": sequence,
                        "delivery_id": did,
                    },
                },
                principal,
                "phone",
                now,
            )
            confirmed = (
                body.get("destination_confirmed") is True
                and body.get("destination_zone_id") == assignment["zone"]
            )
            if result == "accept" and confirmed:
                if assignment["status"] == "offered":
                    self._transition(
                        data,
                        {
                            "kind": "accept",
                            "assignment_id": assignment["id"],
                            "expected_version": assignment["version"],
                        },
                        principal,
                        "phone",
                        now,
                    )
                    applied = True
                if body.get("eta_min") is not None and assignment["status"] in {
                    "accepted",
                    "en_route",
                }:
                    self._transition(
                        data,
                        {
                            "kind": "eta",
                            "assignment_id": assignment["id"],
                            "expected_version": assignment["version"],
                            "eta_min": body["eta_min"],
                            "destination_confirmed": True,
                            "destination_zone_id": assignment["zone"],
                        },
                        principal,
                        "phone",
                        now,
                    )
                    applied = True
            elif result == "reject" and assignment["status"] in {
                "offered",
                "accepted",
                "en_route",
            }:
                self._transition(
                    data,
                    {
                        "kind": "decline",
                        "assignment_id": assignment["id"],
                        "expected_version": assignment["version"],
                        "reason": _text(
                            body.get("reason") or "Rechazo explícito en llamada",
                            "reason",
                            500,
                        ),
                    },
                    principal,
                    "phone",
                    now,
                )
                applied = True
            action = body.get("operational_action")
            if (
                action in {"arrive", "locate", "complete"}
                and body.get("action_confirmed") is True
            ):
                if body.get("destination_zone_id") != assignment["zone"]:
                    raise OperationalError("destination_mismatch")
                self._transition(
                    data,
                    {
                        "kind": action,
                        "assignment_id": assignment["id"],
                        "expected_version": assignment["version"],
                    },
                    principal,
                    "phone",
                    now,
                )
                applied = True
            self._staff_followup(data, assignment, now)
        context.update(
            sequence=sequence,
            call_id=call_id,
            last_result=result,
            assignment_version=assignment["version"],
            status="stale" if stale else "result",
            final=final,
        )
        self._save_meta("launch:" + did, context)
        self._event(
            data,
            now,
            "phone." + ("stale" if stale else result),
            principal,
            assignment["incident_id"],
            assignment["id"],
        )
        return {
            "incident_id": assignment["incident_id"],
            "assignment_id": assignment["id"],
            "communication_result": result,
            "applied": applied,
            "stale": stale,
            "new_incident_id": new_incident,
        }

    def _workflow(self, data: State, command: Document, now: float) -> Document:
        did = _id(command.get("delivery_id"), "delivery_id")
        context = self._meta("launch:" + did)
        if (
            not context
            or context["channel"] != "happyrobot"
            or cast(float, context["deadline"]) < now
        ):
            raise OperationalError("workflow_correlation_invalid", 409)
        body = document(command.get("body"), "body")
        if body.get("correlation_id") not in (None, "", did):
            raise OperationalError("workflow_correlation_invalid", 409)
        iid = str(context["incident_id"])
        if body.get("incident_id") not in (None, "", "nuevo", iid):
            raise OperationalError("workflow_incident_mismatch", 409)
        if command["kind"] == "workflow_memory":
            memory = _text(body.get("texto") or body.get("text"), "memory", 2000)
            self._save_meta("memory:" + did, {"text": memory, "incident_id": iid})
            return {"incident_id": iid, "guardado": True}
        roles = document(body.get("papeles") or body.get("roles"), "specialists")
        if set(roles) != SPECIALISTS or any(not roles[key] for key in SPECIALISTS):
            raise OperationalError("specialists_incomplete")
        critic = document(roles["critico"], "critic")
        if critic.get("ok") is not True or critic.get("status") in {
            "failed",
            "timeout",
            "degraded",
        }:
            raise OperationalError("critical_review_failed")
        incident = self._incident(data, iid)
        if (incident["version"] != context["expected_version"]
                or self._changes(data, context)["cambio"] or context["status"] in {"stale", "timeout"}):
            raise OperationalError("workflow_stale", 409)
        if context.get("approval_id"):
            raise OperationalError("workflow_already_decided", 409)
        if body.get("fase") != "rapida" or body.get("agente") != "rapido":
            raise OperationalError("workflow_phase_invalid")
        result = self._propose(
            data,
            incident,
            {
                "command_id": command["command_id"],
                "actions": body.get("actions"),
                "requiere_persona": body.get("requiere_persona", False),
                "reason": body.get("reason") or body.get("porque"),
            },
            "proposal",
            now,
        )
        context["status"] = "pending_human"
        context["approval_id"] = result["approval_id"]
        self._save_meta("launch:" + did, context)
        self._control(
            data,
            now,
            iid,
            "Propuesta de HappyRobot pendiente de aprobación humana en la Sala.",
        )
        return {**result, "estado": "pendiente_persona", "aplicado": False}

    def settle(
        self,
        delivery_id: str,
        lease_token: str,
        status: str,
        *,
        detail: str = "",
        provider_id: str = "",
        retry_after_s: int = 5,
    ) -> bool:
        with self._lock:
            result = super().settle(
                delivery_id,
                lease_token,
                status,
                detail=detail,
                provider_id=provider_id,
                retry_after_s=retry_after_s,
            )
            if result and status == "delivered" and provider_id:
                with self._transaction() as (data, _):
                    delivery = data["deliveries"][delivery_id]
                    if delivery["channel"] == "telegram":
                        recipient = data["actors"][delivery["recipient_id"]]
                        self._save_meta(
                            f"tg-message:{recipient['address']}:{provider_id}",
                            {
                                "incident_id": delivery["incident_id"],
                                "purpose": delivery["purpose"],
                            },
                        )
            return result

    def _maintain(self, data: State, now: float) -> None:
        super()._maintain(data, now)
        rows = cast(list[tuple[str, str]], self._db.execute(
            "SELECT key,value FROM operational_metadata WHERE key LIKE 'launch:%'"
        ).fetchall())
        for key, encoded in rows:
            launch = cast(Document, json.loads(encoded))
            if launch["channel"] != "happyrobot" or launch["status"] not in {"launched", "pending_human"}:
                continue
            approval = data["approvals"].get(str(launch.get("approval_id")))
            if approval and approval["status"] != "pending":
                launch["status"] = "applied" if approval["status"] == "approved" else approval["status"]
                self._save_meta(key, launch)
                self._event(data, now, "workflow." + str(launch["status"]), "system", str(launch["incident_id"]))
                continue
            status = ""
            if launch["status"] == "launched" and cast(float, launch["deadline"]) <= now:
                status = "timeout"
            elif self._changes(data, launch)["cambio"]:
                status = "stale"
            if not status:
                continue
            launch.update(status=status, last_error="workflow_" + status)
            self._save_meta(key, launch)
            approval = data["approvals"].get(str(launch.get("approval_id")))
            if approval and approval["status"] == "pending":
                approval.update({"status": "stale", "version": approval["version"] + 1})
            self._event(data, now, "workflow." + status, "system", str(launch["incident_id"]))
            data["events"][-1]["summary"] = (
                "Workflow " + status + ": se conserva el plan seguro de MANDO; revisar el contexto vigente."
            )

    def state(self) -> Document:
        with self._lock:
            self.reconcile()
            result = super().state()
            rows = cast(
                list[tuple[str]],
                self._db.execute(
                    "SELECT value FROM operational_metadata WHERE key LIKE 'launch:%' ORDER BY rowid DESC LIMIT 100"
                ).fetchall(),
            )
            result["workflows"] = [
                {
                    k: v
                    for k, v in cast(Document, json.loads(row[0])).items()
                    if k
                    in {
                        "delivery_id",
                        "incident_id",
                        "assignment_id",
                        "channel",
                        "status",
                        "last_result",
                        "deadline",
                        "approval_id",
                        "last_error",
                    }
                }
                for row in rows
            ]
            for workflow in cast(list[Document], result["workflows"]):
                if workflow["status"] == "pending_human":
                    approval = next(
                        (
                            a
                            for a in cast(list[Document], result["approvals"])
                            if a["id"] == workflow.get("approval_id")
                        ),
                        {},
                    )
                    workflow["status"] = approval.get("status", "pending_human")
            return result


def channel_status() -> Document:
    real = os.environ.get("MANDO_EXTERNAL_DELIVERY") == "1"
    telegram = bool(
        os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("MANDO_BRIDGE_SECRET")
    )
    provider = bool(abanico.api_key() and abanico.api_base().strip()
                    and os.environ.get("MANDO_PUBLIC_URL", "").strip().startswith("https://"))
    voice = provider and all(
        os.environ.get(key)
        for key in (
            "HR_API_KEY",
            "HR_WORKFLOW_DISPATCH",
            "HR_SECRET",
            "MANDO_PUBLIC_URL",
            "MANDO_ALLOWED_NUMBERS",
        )
    )
    workflow = provider and all(
        os.environ.get(key)
        for key in (
            "HR_API_KEY",
            "HR_WORKFLOW_RAPIDO",
            "HR_SECRET",
            "MANDO_PUBLIC_URL",
        )
    )
    return {
        "mode": "real" if real else "simulation",
        "telegram": {
            "ready": real and telegram,
            "status": "configured" if telegram else "missing",
        },
        "phone": {
            "ready": real and voice,
            "status": "configured" if voice else "missing",
        },
        "happyrobot": {
            "ready": real and workflow,
            "status": "configured" if workflow else "missing",
        },
    }
