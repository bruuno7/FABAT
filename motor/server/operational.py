"""Durable operational authority; adapters supply authenticated identities."""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import math
import re
import secrets
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import ClassVar, cast

from motor.contracts import Channel, Family, Report, Zone
from motor.contracts import Incident as ParsedIncident
from motor.mando.lexicon import spec_for
from motor.mando.parser import HeuristicParser
from motor.mando.priority import compute

from .operational_types import (
    JSON,
    Actor,
    Approval,
    Assignment,
    Document,
    Entity,
    Incident,
    State,
)
from .privacy import scrub

ROLES = frozenset({"medico", "bomberos", "policia", "staff_entradas", "organizador"})
CHANNELS = frozenset({"telegram", "phone", "web"})
AVAILABILITY = frozenset({"available", "unavailable", "unknown"})
ACTIVE = frozenset({"offered", "accepted", "en_route", "arrived", "located"})
GRAVE = frozenset({"evacuate", "stop_show", "request_external"})
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.~:@-]{0,119}\Z")
ROLE_MAP = {
    "medical": "medico", "ambulance": "medico", "security": "policia",
    "tech": "organizador", "logistics": "organizador", "volunteer": "staff_entradas",
}
FIELDS = {
    "register_actor": {"actor_id", "name", "roles", "channel", "address", "zone", "availability"},
    "identify": {"actor_id", "name", "channel", "address", "zone"},
    "report": {"text", "zone"},
    "update": {"incident_id", "text", "zone", "expected_version"},
    "offer": {"incident_id", "actor_id", "role", "task_id", "expected_version", "ttl_seconds"},
    "accept": {"assignment_id", "expected_version"},
    "decline": {"assignment_id", "expected_version", "reason"},
    "eta": {"assignment_id", "expected_version", "eta_min", "destination_confirmed", "destination_zone_id"},
    "arrive": {"assignment_id", "expected_version"},
    "locate": {"assignment_id", "expected_version"},
    "complete": {"assignment_id", "expected_version"},
    "availability": {"actor_id", "availability", "expected_version"},
    "propose": {"incident_id", "expected_version", "actions", "requiere_persona", "reason"},
    "decide": {"approval_id", "expected_version", "approved", "content_hash", "note"},
    "merge": {"incident_id", "target_incident_id", "expected_version"},
    "call_result": {"assignment_id", "expected_version", "result", "metadata"},
}
PERMISSIONS = {
    "operator": set(FIELDS) - {"identify"},
    "system": {"identify", "report", "update", "offer", "availability", "propose", "call_result"},
    "proposal": {"propose"},
    "telegram": {"identify", "report", "update", "accept", "decline", "eta", "arrive", "locate", "complete", "availability"},
    "phone": {"identify", "report", "update", "accept", "decline", "eta", "arrive", "locate", "complete", "availability", "call_result"},
}


class OperationalError(ValueError):
    def __init__(self, code: str, status: int = 422, message: str = "") -> None:
        self.code = code
        self.status = status
        self.message = message or code
        super().__init__(self.message)


def _text(value: object, field: str, maximum: int = 2000, *, empty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > maximum or "\x00" in value:
        raise OperationalError("invalid_" + field, 400)
    if not empty and not value.strip():
        raise OperationalError("invalid_" + field, 400)
    return value.strip()


def _id(value: object, field: str = "id") -> str:
    if not isinstance(value, str) or ID.fullmatch(value) is None:
        raise OperationalError("invalid_" + field, 400)
    return value


def _integer(value: object, field: str, low: int = 1, high: int = 2**53 - 1) -> int:
    if type(value) is not int or not low <= value <= high:
        raise OperationalError("invalid_" + field, 400)
    return value


def _boolean(value: object, field: str) -> bool:
    if type(value) is not bool:
        raise OperationalError("invalid_" + field, 400)
    return value


def _choice(value: object, choices: set[str] | frozenset[str], field: str) -> str:
    result = _text(value, field, 120)
    if result not in choices:
        raise OperationalError("invalid_" + field, 400)
    return result


def _bounded_json(value: object, depth: int = 0) -> int:
    if depth > 6:
        raise OperationalError("input_too_deep", 400)
    if value is None or type(value) is bool:
        return 1
    if type(value) is int:
        _integer(value, "number", -(2**53 - 1))
        return 1
    if isinstance(value, float):
        if not math.isfinite(value):
            raise OperationalError("invalid_number", 400)
        return 1
    if isinstance(value, str):
        _text(value, "text", 4000, empty=True)
        return 1
    if isinstance(value, list):
        items = cast(list[object], value)
        if len(items) > 64:
            raise OperationalError("input_too_large", 400)
        size = 1 + sum(_bounded_json(item, depth + 1) for item in items)
    elif isinstance(value, dict):
        entries = cast(dict[object, object], value)
        if len(entries) > 64:
            raise OperationalError("input_too_large", 400)
        for key in entries:
            _text(key, "key", 120)
        size = 1 + sum(_bounded_json(item, depth + 1) for item in entries.values())
    else:
        raise OperationalError("invalid_json", 400)
    if size > 256:
        raise OperationalError("input_too_large", 400)
    return size


def _encode(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _document(value: object) -> Document:
    return cast(Document, json.loads(_encode(value)))


def _hash(value: object) -> str:
    return hashlib.sha256(_encode(value).encode()).hexdigest()


def _reference(prefix: str, value: str) -> str:
    return prefix + "-" + hashlib.sha256(value.encode()).hexdigest()[:32]


def _public(value: JSON, addresses: list[str], key: str = "") -> JSON:
    if isinstance(value, list):
        return [_public(item, addresses) for item in value]
    if isinstance(value, dict):
        return {k: _public(v, addresses, k) for k, v in value.items()}
    if isinstance(value, str) and key not in {
        "id", "actor_id", "reporter_id", "principal", "assignment_id", "incident_id",
        "task_id", "content_hash", "merged_into",
    }:
        for address in addresses:
            if len(address) >= 4:
                value = value.replace(address, "(contacto oculto)")
        return cast(str, scrub(value))
    return value


def _version(entity: Entity, command: Mapping[str, object]) -> None:
    if entity["version"] != _integer(command.get("expected_version"), "expected_version"):
        raise OperationalError("stale_version", 409)


class OperationalStore:
    command_fields: ClassVar[dict[str, set[str]]] = FIELDS
    command_permissions: ClassVar[dict[str, set[str]]] = PERMISSIONS

    def __init__(self, path: str | Path, festival: Document, *,
                 clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._lock = threading.RLock()
        self._parser = HeuristicParser()
        self._closed = False
        self._zones: dict[str, Zone] = {}
        raw_zones = festival.get("zones")
        if not isinstance(raw_zones, list) or not 1 <= len(raw_zones) <= 256:
            raise OperationalError("invalid_festival", 400)
        zones: list[Document] = []
        for raw in raw_zones:
            if not isinstance(raw, dict):
                raise OperationalError("invalid_zone", 400)
            zid = _id(raw.get("id"), "zone")
            if zid in self._zones:
                raise OperationalError("duplicate_zone", 400)
            name = _text(raw.get("name"), "zone_name", 200)
            kind = _text(raw.get("kind", "general"), "zone_kind", 80)
            self._zones[zid] = Zone(zid, name, kind, 1, 1)
            zones.append({"id": zid, "version": 1, "name": name})
        initial: State = {
            "schema": 1, "revision": 0, "zones": zones, "actors": {}, "incidents": {},
            "assignments": {}, "approvals": {}, "deliveries": {}, "events": [],
            "reservations": {},
        }
        try:
            database = sqlite3.connect(str(path), isolation_level=None, timeout=10, check_same_thread=False)
        except sqlite3.Error as exc:
            raise OperationalError("persistence_unavailable", 503) from exc
        self._db = database
        try:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=FULL")
            self._db.execute("PRAGMA busy_timeout=10000")
            self._db.execute("CREATE TABLE IF NOT EXISTS operational_state (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL)")
            self._db.execute("CREATE TABLE IF NOT EXISTS operational_commands (id TEXT PRIMARY KEY, content_hash TEXT NOT NULL, result TEXT NOT NULL)")
            self._db.execute("INSERT OR IGNORE INTO operational_state VALUES (1, ?)", (_encode(initial),))
            with self._transaction() as (data, _):
                if data["schema"] != 1 or data["zones"] != zones:
                    raise OperationalError("festival_mismatch", 409, "La base pertenece a otro recinto o esquema.")
        except BaseException as exc:
            self._db.close()
            self._closed = True
            if isinstance(exc, sqlite3.Error):
                raise OperationalError("persistence_unavailable", 503) from exc
            raise

    @contextmanager
    def _transaction(self) -> Iterator[tuple[State, float]]:
        with self._lock:
            if self._closed:
                raise OperationalError("store_closed", 503)
            try:
                self._db.execute("BEGIN IMMEDIATE")
                row = cast(tuple[str], self._db.execute("SELECT body FROM operational_state WHERE id=1").fetchone())
                data = cast(State, json.loads(row[0]))
                original = _encode(data)
                yield data, self._clock()
                if _encode(data) != original:
                    data["revision"] += 1
                    self._db.execute("UPDATE operational_state SET body=? WHERE id=1", (_encode(data),))
                self._db.execute("COMMIT")
            except BaseException as exc:
                if self._db.in_transaction:
                    self._db.execute("ROLLBACK")
                if isinstance(exc, sqlite3.Error):
                    raise OperationalError("persistence_unavailable", 503) from exc
                raise

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._db.close()
                self._closed = True

    def execute(self, command: Document, *, principal: str = "operator",
                scope: str = "operator", channel: str = "web") -> Document:
        _bounded_json(command)
        if not isinstance(command, dict) or len(_encode(command)) > 16384:
            raise OperationalError("invalid_command", 400)
        cid = _id(command.get("command_id"), "command_id")
        kind = _choice(command.get("kind"), set(self.command_fields), "kind")
        principal = _id(principal, "principal")
        channel = _choice(channel, CHANNELS, "channel")
        if scope not in self.command_permissions or kind not in self.command_permissions[scope]:
            raise OperationalError("forbidden", 403)
        if set(command) - self.command_fields[kind] - {"command_id", "kind"}:
            raise OperationalError("unknown_fields", 400)
        fingerprint = _hash({"command": command, "principal": principal, "scope": scope, "channel": channel})
        error: OperationalError | None = None
        result: Document = {}
        with self._transaction() as (data, now):
            row = cast(tuple[str, str] | None, self._db.execute(
                "SELECT content_hash,result FROM operational_commands WHERE id=?", (cid,),
            ).fetchone())
            if row:
                if not hmac.compare_digest(row[0], fingerprint):
                    raise OperationalError("command_id_collision", 409)
                result = cast(Document, json.loads(row[1]))
                if result["ok"] is False:
                    raise OperationalError(str(result["error"]), cast(int, result["status"]), str(result["message"]))
                return {**result, "duplicate": True}
            before = copy.deepcopy(data)
            self._db.execute("SAVEPOINT apply_command")
            try:
                result = self._dispatch(data, command, principal, scope, channel, now)
                self._maintain(data, now)
                self._event(data, now, kind, principal, cast(str | None, result.get("incident_id")),
                            cast(str | None, result.get("assignment_id")))
                result.update(ok=True, duplicate=False, revision=data["revision"] + 1)
            except OperationalError as exc:
                self._db.execute("ROLLBACK TO apply_command")
                data.update(before)
                self._failure(data, command, exc, now)
                error = exc
                result = {"ok": False, "error": exc.code, "message": exc.message, "status": exc.status}
            self._db.execute("RELEASE apply_command")
            self._db.execute("INSERT INTO operational_commands VALUES (?,?,?)", (cid, fingerprint, _encode(result)))
        if error:
            raise error
        return result

    def _failure(self, data: State, command: Document, error: OperationalError, now: float) -> None:
        pass

    def state(self) -> Document:
        with self._transaction() as (data, now):
            assignment_order = {
                event["assignment_id"]: index for index, event in enumerate(data["events"])
                if event["kind"] == "assignment.offered" and event["assignment_id"]
            }
            actors = [{k: v for k, v in _document(actor).items() if k != "address"}
                      for actor in data["actors"].values()]
            incidents = [{k: v for k, v in _document(incident).items()
                          if k not in {"updates", "reporter_ids", "tasks"}}
                         for incident in data["incidents"].values()]
            assignments = [{k: v for k, v in _document(assignment).items() if k in {
                "id", "version", "incident_id", "actor_id", "role", "task_id", "zone",
                "status", "eta_min", "expires_at",
            }}
                           for assignment in sorted(data["assignments"].values(),
                                                    key=lambda row: assignment_order.get(row["id"], -1))]
            for assignment_view in assignments:
                communication = data["assignments"][str(assignment_view["id"])]["communication"]
                assignment_view["communication"] = {
                    k: v for k, v in communication.items() if k in {"result", "occurred_at"}
                }
            deliveries = [
                {k: v for k, v in _document(delivery).items() if k in {
                    "id", "version", "channel", "purpose", "status", "attempts",
                    "incident_id", "assignment_id", "last_error",
                }} for delivery in data["deliveries"].values()
            ]
            snapshot = _document({
                "revision": data["revision"], "mode": "operational", "server_time": now,
                "zones": data["zones"], "actors": actors, "incidents": incidents,
                "assignments": assignments, "approvals": list(data["approvals"].values()),
                "deliveries": deliveries, "events": data["events"][-500:],
            })
            return cast(Document, _public(snapshot, [a["address"] for a in data["actors"].values()]))

    def recipient(self, actor_id: str) -> Document:
        with self._transaction() as (data, _):
            return _document(self._actor(data, _id(actor_id, "actor_id")))

    @staticmethod
    def _actor(data: State, aid: str) -> Actor:
        if aid not in data["actors"]:
            raise OperationalError("actor_missing")
        return data["actors"][aid]

    @staticmethod
    def _incident(data: State, iid: str) -> Incident:
        if iid not in data["incidents"]:
            raise OperationalError("incident_missing")
        incident = data["incidents"][iid]
        if incident["status"] in {"closed", "merged"}:
            raise OperationalError("incident_closed", 409)
        return incident

    def _zone(self, value: object) -> str | None:
        if value is None:
            return None
        zone = _id(value, "zone")
        if zone not in self._zones:
            raise OperationalError("unknown_zone")
        return zone

    @staticmethod
    def _event(data: State, now: float, kind: str, principal: str,
               incident_id: str | None = None, assignment_id: str | None = None) -> None:
        data["events"].append({
            "id": "event-" + secrets.token_hex(12), "version": 1, "occurred_at": now,
            "kind": kind, "principal": principal, "incident_id": incident_id,
            "assignment_id": assignment_id, "summary": kind,
        })

    def _say(self, data: State, now: float, recipient: str, purpose: str, text: str,
             incident_id: str, assignment: Assignment | None = None,
             payload: Document | None = None) -> None:
        actor = data["actors"].get(recipient)
        if actor is None or not actor["address"]:
            return
        did = "delivery-" + secrets.token_hex(12)
        body = dict(payload or {})
        if assignment:
            body.update(assignment_id=assignment["id"], expected_version=assignment["version"],
                        destination_zone_id=assignment["zone"])
        data["deliveries"][did] = {
            "id": did, "version": 1, "channel": actor["channel"], "recipient_id": recipient,
            "purpose": purpose, "text": text, "incident_id": incident_id,
            "assignment_id": assignment["id"] if assignment else None, "status": "pending",
            "attempts": 0, "payload": body, "last_error": "", "private_detail": "",
            "provider_id": "", "lease_token": "", "lease_until": 0, "worker": "",
            "next_attempt_at": now,
        }

    def claim(self, worker: str, *, limit: int = 20, lease_seconds: int = 30) -> list[Document]:
        worker = _id(worker, "worker")
        _integer(limit, "limit", 1, 100)
        _integer(lease_seconds, "lease_seconds", 1, 300)
        claimed: list[Document] = []
        with self._transaction() as (data, now):
            self._maintain(data, now)
            for delivery in data["deliveries"].values():
                if len(claimed) >= limit or delivery["status"] not in {"pending", "retry"}:
                    continue
                if delivery["next_attempt_at"] > now:
                    continue
                if delivery["channel"] == "phone" and any(
                    other["channel"] == "phone" and other["status"] == "uncertain"
                    and other["recipient_id"] == delivery["recipient_id"]
                    and other["incident_id"] == delivery["incident_id"]
                    for other in data["deliveries"].values()
                ):
                    delivery.update({"status": "failed", "last_error": "prior_call_uncertain",
                                     "version": delivery["version"] + 1})
                    continue
                delivery.update({"status": "leased", "attempts": delivery["attempts"] + 1,
                                 "lease_token": secrets.token_hex(24), "lease_until": now + lease_seconds,
                                 "worker": worker, "version": delivery["version"] + 1})
                claimed.append({k: v for k, v in _document(delivery).items() if k in {
                    "id", "lease_token", "channel", "recipient_id", "purpose", "text",
                    "incident_id", "assignment_id", "attempts", "payload",
                }})
        return claimed

    def settle(self, delivery_id: str, lease_token: str, status: str, *,
               detail: str = "", provider_id: str = "", retry_after_s: int = 5) -> bool:
        _id(delivery_id, "delivery_id")
        if not isinstance(lease_token, str) or re.fullmatch(r"[a-f0-9]{48}", lease_token) is None:
            return False
        _choice(status, {"delivered", "retry", "failed", "uncertain"}, "delivery_status")
        detail = _text(detail, "detail", 2000, empty=True)
        provider_id = _text(provider_id, "provider_id", 200, empty=True)
        _integer(retry_after_s, "retry_after_s", 1, 3600)
        with self._transaction() as (data, now):
            delivery = data["deliveries"].get(delivery_id)
            if (delivery is None or delivery["status"] != "leased"
                    or delivery["lease_until"] <= now
                    or not hmac.compare_digest(delivery["lease_token"], lease_token)):
                return False
            delivery.update({"status": status, "version": delivery["version"] + 1,
                             "lease_token": "", "lease_until": 0, "provider_id": provider_id,
                             "private_detail": detail, "last_error": "" if status == "delivered" else status,
                             "next_attempt_at": now + retry_after_s})
            return True

    def reconcile(self) -> Document:
        with self._transaction() as (data, now):
            before = _encode(data)
            self._maintain(data, now)
            return {"ok": True, "revision": data["revision"] + int(before != _encode(data))}

    def _dispatch(self, data: State, command: Document, principal: str,
                  scope: str, channel: str, now: float) -> Document:
        kind = str(command["kind"])
        if scope in {"telegram", "phone"} and channel != scope:
            raise OperationalError("channel_mismatch", 403)
        if kind in {"register_actor", "identify"}:
            return self._register(data, command, principal, scope)
        if kind == "report":
            return self._report(data, command, principal, scope, channel, now)
        if kind == "availability":
            aid = _id(command.get("actor_id", principal), "actor_id")
            if scope not in {"operator", "system"} and aid != principal:
                raise OperationalError("actor_forbidden", 403)
            actor = self._actor(data, aid)
            _version(actor, command)
            available = _choice(command.get("availability"), AVAILABILITY, "availability")
            actor.update({"availability": available, "version": actor["version"] + 1})
            if available != "available":
                for assignment in list(data["assignments"].values()):
                    if assignment["actor_id"] == aid and assignment["status"] == "offered":
                        self._release(data, assignment, "cancelled", now, "actor_unavailable")
            return {"actor_id": aid}
        if kind == "decide":
            return self._decide(data, command, principal, now)
        if kind in {"accept", "decline", "eta", "arrive", "locate", "complete", "call_result"}:
            return self._transition(data, command, principal, scope, now)
        iid = _id(command.get("incident_id"), "incident_id")
        incident = self._incident(data, iid)
        _version(incident, command)
        if kind == "update":
            if scope not in {"operator", "system"} and principal not in incident["reporter_ids"]:
                raise OperationalError("incident_forbidden", 403)
            text = _text(command.get("text"), "text")
            zone = self._zone(command.get("zone", incident["zone"]))
            parsed_zone, priority, needs, life = self._parse(text, zone)
            zone = parsed_zone or zone
            if zone != incident["zone"]:
                active = [a for a in data["assignments"].values()
                          if a["incident_id"] == iid and a["status"] in ACTIVE]
                if any(a["status"] != "offered" for a in active):
                    raise OperationalError("destination_in_use", 409, "No se cambia el destino de un equipo activo.")
                for assignment in active:
                    self._release(data, assignment, "cancelled", now, "destination_changed")
            incident.update({"text": text, "zone": zone, "priority": max(priority, incident["priority"]),
                             "life_threat": life or incident["life_threat"], "updated_at": now,
                             "version": incident["version"] + 1})
            for role, count in needs.items():
                incident["needs"][role] = max(incident["needs"].get(role, 0), count)
            self._tasks(incident)
            incident["updates"].append({"principal": principal, "channel": channel, "text": text, "occurred_at": now})
            for assignment in data["assignments"].values():
                if assignment["incident_id"] == iid and assignment["status"] in ACTIVE:
                    self._say(data, now, assignment["actor_id"], "update", text, iid)
            return {"incident_id": iid}
        if kind == "offer":
            assignment = self._offer(
                data, incident, _id(command.get("actor_id"), "actor_id"),
                _choice(command.get("role"), ROLES, "role"), now,
                task_id=_id(command["task_id"], "task_id") if "task_id" in command else None,
                ttl=_integer(command.get("ttl_seconds", 120), "ttl_seconds", 1, 900),
            )
            return {"incident_id": iid, "assignment_id": assignment["id"]}
        if kind == "propose":
            return self._propose(data, incident, command, scope, now)
        if kind == "merge":
            target = self._incident(data, _id(command.get("target_incident_id"), "target_incident_id"))
            if target is incident or target["zone"] != incident["zone"]:
                raise OperationalError("unsafe_merge", 409, "La fusión requiere dos avisos de la misma zona.")
            if any(a["incident_id"] in {iid, target["id"]} and a["status"] in ACTIVE | {"completed"}
                   for a in data["assignments"].values()):
                raise OperationalError("unsafe_merge", 409, "No se fusionan reservas o asistencias ya iniciadas.")
            target["reporter_ids"] = sorted(set(target["reporter_ids"] + incident["reporter_ids"]))
            target["updates"].extend(incident["updates"])
            target["priority"] = max(target["priority"], incident["priority"])
            target["life_threat"] = target["life_threat"] or incident["life_threat"]
            for role, count in incident["needs"].items():
                target["needs"][role] = max(target["needs"].get(role, 0), count)
            self._tasks(target)
            target.update({"version": target["version"] + 1, "updated_at": now})
            incident.update({"status": "merged", "merged_into": target["id"], "why_waiting": "",
                             "version": incident["version"] + 1, "updated_at": now})
            return {"incident_id": iid, "target_incident_id": target["id"]}
        raise OperationalError("unsupported_command", 400)

    def _register(self, data: State, command: Document, principal: str, scope: str) -> Document:
        identify = command["kind"] == "identify"
        aid = _id(command.get("actor_id", principal), "actor_id")
        if identify and aid != principal:
            raise OperationalError("identity_forbidden", 403)
        channel = _choice(command.get("channel"), CHANNELS, "channel")
        if identify and scope in {"telegram", "phone"} and channel != scope:
            raise OperationalError("channel_mismatch", 403)
        address = _text(command.get("address") or (aid if channel == "web" else None), "address", 300)
        name = _text(command.get("name", aid), "name", 120)
        zone = self._zone(command.get("zone"))
        previous = data["actors"].get(aid)
        if any(a["id"] != aid and a["channel"] == channel and a["address"] == address
               for a in data["actors"].values()):
            raise OperationalError("address_already_registered", 409)
        if identify:
            if previous:
                if previous["address"] != address or previous["channel"] != channel:
                    raise OperationalError("identity_changed", 409)
                return {"actor_id": aid}
            roles: list[str] = []
            availability = "unknown"
        else:
            raw_roles = command.get("roles")
            if not isinstance(raw_roles, list) or not 1 <= len(raw_roles) <= len(ROLES):
                raise OperationalError("invalid_roles", 400)
            roles = sorted({_choice(role, ROLES, "role") for role in raw_roles})
            availability = _choice(command.get("availability"), AVAILABILITY, "availability")
            if "actor:" + aid in data["reservations"]:
                raise OperationalError("actor_busy", 409)
        data["actors"][aid] = {
            "id": aid, "version": previous["version"] + 1 if previous else 1,
            "name": name, "roles": roles, "channel": channel, "address": address,
            "zone": zone, "availability": availability,
        }
        return {"actor_id": aid}

    def _parse(self, text: str, zone: str | None) -> tuple[str | None, float, dict[str, int], bool]:
        parsed = cast(Mapping[str, object], self._parser.parse(
            Report("operational", 0, Channel.WHATSAPP, text, zone_hint=zone), self._zones,
        ))
        zone = self._zone(parsed["zone"])
        life = _boolean(parsed["life_threat"], "life_threat")
        raw_needs = dict(cast(dict[str, int], parsed["needs"]))
        secondary = cast(list[str], parsed["secondary"])
        for incident_type in secondary:
            for resource, number in spec_for(incident_type).needs.items():
                raw_needs[resource] = max(raw_needs.get(resource, 0), number)
        needs: dict[str, int] = {}
        for resource, number in raw_needs.items():
            role = ROLE_MAP[resource]
            needs[role] = max(needs.get(role, 0), min(8, number))
        if parsed["type"] == "fire" or "fire" in secondary:
            needs["bomberos"] = 1
        if life:
            needs["medico"] = max(1, needs.get("medico", 0))
        model = ParsedIncident(
            "operational", cast(Family, parsed["family"]), str(parsed["type"]), zone,
            cast(int, parsed["severity"]), 0, confidence=cast(float, parsed["confidence"]),
        )
        priority, _ = compute(model, self._zones.get(zone or ""), 0, life_threat=life,
                              minors=cast(bool, parsed["minors"]))
        return zone, priority, needs, life

    def _report(self, data: State, command: Document, principal: str, scope: str,
                channel: str, now: float) -> Document:
        if scope in {"telegram", "phone"}:
            self._actor(data, principal)
        text = _text(command.get("text"), "text")
        zone, priority, needs, life = self._parse(text, self._zone(command.get("zone")))
        if not needs:
            needs["organizador"] = 1
        iid = _reference("incident", str(command["command_id"]))
        incident: Incident = {
            "id": iid, "version": 1, "text": text, "zone": zone, "priority": priority,
            "status": "open", "needs": needs, "tasks": {}, "why_waiting": "",
            "created_at": now, "updated_at": now, "reporter_id": principal,
            "reporter_ids": [principal], "life_threat": life, "merged_into": None,
            "updates": [{"principal": principal, "channel": channel, "text": text, "occurred_at": now}],
        }
        self._tasks(incident)
        data["incidents"][iid] = incident
        self._say(data, now, principal, "status", "Aviso registrado. Coordinación pendiente.", iid)
        if zone is None:
            self._say(data, now, principal, "question", "¿En qué zona estás? Necesitamos la ubicación para enviar ayuda.", iid)
        return {"incident_id": iid}

    @staticmethod
    def _tasks(incident: Incident) -> None:
        for role, count in incident["needs"].items():
            for index in range(count):
                task_id = _reference("task", f"{incident['id']}:{role}:{index}")
                incident["tasks"][task_id] = role

    @staticmethod
    def _covered(data: State, task_id: str) -> bool:
        return any(a["task_id"] == task_id and a["status"] in ACTIVE | {"completed"}
                   for a in data["assignments"].values())

    def _offer(self, data: State, incident: Incident, actor_id: str, role: str,
               now: float, *, task_id: str | None = None, ttl: int = 120) -> Assignment:
        if incident["zone"] is None:
            raise OperationalError("location_required")
        actor = self._actor(data, actor_id)
        if role not in actor["roles"] or role not in incident["needs"]:
            raise OperationalError("capacity_mismatch")
        if actor["availability"] != "available" or not actor["address"]:
            raise OperationalError("actor_unavailable", 409)
        if "actor:" + actor_id in data["reservations"]:
            raise OperationalError("actor_busy", 409)
        if task_id is None:
            task_id = next((tid for tid, needed in incident["tasks"].items()
                            if needed == role and not self._covered(data, tid)), None)
        if task_id is None:
            raise OperationalError("task_covered", 409)
        if incident["tasks"].get(task_id) != role:
            raise OperationalError("task_capacity_mismatch")
        if self._covered(data, task_id):
            raise OperationalError("task_covered", 409)
        if any(a["incident_id"] == incident["id"] and a["actor_id"] == actor_id
               and a["status"] in {"declined", "expired"} for a in data["assignments"].values()):
            raise OperationalError("actor_requires_followup", 409)
        aid = "assignment-" + secrets.token_hex(12)
        assignment: Assignment = {
            "id": aid, "version": 1, "incident_id": incident["id"], "actor_id": actor_id,
            "role": role, "task_id": task_id, "zone": incident["zone"], "status": "offered",
            "eta_min": None, "expires_at": now + ttl, "reason": "", "communication": {},
        }
        data["assignments"][aid] = assignment
        data["reservations"]["actor:" + actor_id] = aid
        data["reservations"]["task:" + task_id] = aid
        actor["version"] += 1
        incident.update({"version": incident["version"] + 1, "updated_at": now})
        self._say(data, now, actor_id, "offer",
                  f"¿Puedes atender el aviso en {assignment['zone']}? {incident['text']}",
                  incident["id"], assignment)
        self._event(data, now, "assignment.offered", "system", incident["id"], aid)
        return assignment

    @staticmethod
    def _cancel_deliveries(data: State, assignment_id: str) -> None:
        for delivery in data["deliveries"].values():
            if delivery["assignment_id"] == assignment_id and delivery["status"] in {"pending", "retry", "leased"}:
                delivery.update({"status": "cancelled", "lease_token": "", "lease_until": 0,
                                 "version": delivery["version"] + 1})

    def _release(self, data: State, assignment: Assignment, status: str,
                 now: float, reason: str) -> None:
        assignment.update({"status": status, "reason": reason, "version": assignment["version"] + 1})
        for key in ("actor:" + assignment["actor_id"], "task:" + assignment["task_id"]):
            if data["reservations"].get(key) == assignment["id"]:
                del data["reservations"][key]
        actor = data["actors"][assignment["actor_id"]]
        actor["version"] += 1
        incident = data["incidents"][assignment["incident_id"]]
        incident.update({"version": incident["version"] + 1, "updated_at": now})
        self._cancel_deliveries(data, assignment["id"])
        self._event(data, now, "assignment." + status, "system", incident["id"], assignment["id"])

    def _transition(self, data: State, command: Document, principal: str,
                    scope: str, now: float) -> Document:
        aid = _id(command.get("assignment_id"), "assignment_id")
        assignment = data["assignments"].get(aid)
        if assignment is None:
            raise OperationalError("assignment_missing")
        if scope not in {"operator", "system"} and assignment["actor_id"] != principal:
            raise OperationalError("assignment_forbidden", 403)
        _version(assignment, command)
        incident = self._incident(data, assignment["incident_id"])
        actor = self._actor(data, assignment["actor_id"])
        if assignment["role"] not in actor["roles"]:
            raise OperationalError("capacity_mismatch", 403)
        kind = str(command["kind"])
        status = assignment["status"]
        if kind == "call_result":
            if status not in ACTIVE or (status == "offered" and assignment["expires_at"] <= now):
                raise OperationalError("stale_assignment", 409)
            result = _choice(command.get("result"), {
                "accept", "reject", "unclear", "unknown", "no_answer", "timeout", "provider_failed",
            }, "result")
            metadata = command.get("metadata", {})
            if not isinstance(metadata, dict):
                raise OperationalError("invalid_metadata", 400)
            assignment["communication"] = {"result": result, "metadata": metadata, "occurred_at": now}
            assignment["version"] += 1
            self._cancel_deliveries(data, aid)
            return {"incident_id": incident["id"], "assignment_id": aid}
        allowed = {
            "accept": {"offered"}, "decline": {"offered", "accepted", "en_route"},
            "eta": {"accepted", "en_route"}, "arrive": {"accepted", "en_route"},
            "locate": {"arrived"}, "complete": {"located"},
        }
        if status not in allowed[kind]:
            raise OperationalError("invalid_transition", 409)
        if status == "offered" and assignment["expires_at"] <= now:
            raise OperationalError("offer_expired", 409)
        if any(data["reservations"].get(key) != aid for key in
               ("actor:" + actor["id"], "task:" + assignment["task_id"])):
            raise OperationalError("reservation_lost", 409)
        if kind == "decline":
            reason = _text(command.get("reason"), "reason", 500)
            self._release(data, assignment, "declined", now, reason)
            actor.update({"availability": "unknown", "version": actor["version"] + 1})
            self._say(data, now, actor["id"], "question", "¿Cuándo podrás volver a atender avisos?", incident["id"])
        elif kind == "complete":
            self._release(data, assignment, "completed", now, "")
            for sibling in list(data["assignments"].values()):
                if sibling["task_id"] == assignment["task_id"] and sibling["status"] == "offered":
                    self._release(data, sibling, "cancelled", now, "task_completed")
        else:
            target = {"accept": "accepted", "eta": "en_route", "arrive": "arrived", "locate": "located"}[kind]
            if kind == "accept" and actor["availability"] != "available":
                raise OperationalError("actor_unavailable", 409)
            if kind == "eta":
                eta = _integer(command.get("eta_min"), "eta_min", 0, 240)
                if command.get("destination_confirmed") is not True:
                    raise OperationalError("destination_unconfirmed")
                if self._zone(command.get("destination_zone_id")) != assignment["zone"]:
                    raise OperationalError("destination_mismatch")
                assignment["eta_min"] = eta
            assignment.update({"status": target, "version": assignment["version"] + 1})
            incident.update({"version": incident["version"] + 1, "updated_at": now})
            self._cancel_deliveries(data, aid)
            if kind in {"arrive", "locate"}:
                actor.update({"zone": assignment["zone"], "version": actor["version"] + 1})
        for reporter in incident["reporter_ids"]:
            self._say(data, now, reporter, "status", {
                "accept": "El equipo ha aceptado el aviso. ETA pendiente de confirmar.",
                "decline": "El equipo no puede atender ahora. Buscamos una alternativa.",
                "eta": f"El equipo estima {assignment['eta_min']} minutos hasta la zona confirmada.",
                "arrive": "El equipo ha llegado a la zona.",
                "locate": "El equipo ha localizado la incidencia.",
                "complete": "El equipo ha completado su tarea.",
            }[kind], incident["id"])
        return {"incident_id": incident["id"], "assignment_id": aid}

    def _validate_actions(self, data: State, incident: Incident, value: JSON) -> list[Document]:
        if not isinstance(value, list) or not 1 <= len(value) <= 16:
            raise OperationalError("invalid_actions", 400)
        actions: list[Document] = []
        for action in value:
            if not isinstance(action, dict):
                raise OperationalError("invalid_action", 400)
            kind = _choice(action.get("kind"), {"offer", "notify"} | GRAVE, "action_kind")
            allowed = {"kind", "actor_id", "role", "zone", "text"}
            if set(action) - allowed:
                raise OperationalError("unknown_action_fields", 400)
            normalized: Document = {"kind": kind}
            if "zone" in action:
                normalized["zone"] = self._zone(action["zone"])
                if normalized["zone"] is None:
                    raise OperationalError("invalid_zone", 400)
            if "text" in action:
                normalized["text"] = _text(action["text"], "text")
            if "actor_id" in action:
                actor = self._actor(data, _id(action["actor_id"], "actor_id"))
                if not actor["address"]:
                    raise OperationalError("recipient_unavailable")
                normalized["actor_id"] = actor["id"]
            if "role" in action:
                normalized["role"] = _choice(action["role"], ROLES, "role")
            if kind == "offer":
                actor_id = _id(normalized.get("actor_id"), "actor_id")
                role = _choice(normalized.get("role"), ROLES, "role")
                if role not in self._actor(data, actor_id)["roles"] or role not in incident["needs"]:
                    raise OperationalError("capacity_mismatch")
                if "zone" in normalized and normalized["zone"] != incident["zone"]:
                    raise OperationalError("destination_mismatch")
            else:
                if "role" in action:
                    raise OperationalError("unexpected_role", 400)
                if kind in GRAVE and "text" not in normalized:
                    normalized["text"] = {
                        "evacuate": "Coordinar evacuación de la zona.",
                        "stop_show": "Coordinar la parada del espectáculo.",
                        "request_external": "Coordinar la solicitud de asistencia externa.",
                    }[kind]
                _text(normalized.get("text"), "text")
                if kind == "notify" and "actor_id" not in normalized:
                    raise OperationalError("recipient_required")
                if kind in GRAVE and "actor_id" in normalized:
                    coordinator = self._actor(data, str(normalized["actor_id"]))
                    if "organizador" not in coordinator["roles"]:
                        raise OperationalError("coordinator_required", 403)
                    if coordinator["availability"] != "available":
                        raise OperationalError("coordinator_unavailable", 409)
            actions.append(normalized)
        return actions

    def _apply_actions(self, data: State, incident: Incident, actions: list[Document], now: float) -> None:
        for action in actions:
            kind = str(action["kind"])
            if kind == "offer":
                self._offer(data, incident, str(action["actor_id"]), str(action["role"]), now)
            elif kind == "notify":
                self._say(data, now, str(action["actor_id"]), "notify", str(action["text"]), incident["id"])
            else:
                recipients = [str(action["actor_id"])] if action.get("actor_id") else [
                    a["id"] for a in data["actors"].values() if "organizador" in a["roles"]
                    and a["address"] and a["availability"] == "available"
                ]
                if not recipients:
                    raise OperationalError("coordinator_unavailable")
                for recipient in recipients:
                    self._say(data, now, recipient, kind, str(action["text"]), incident["id"],
                              payload={"kind": kind, "zone": action.get("zone", incident["zone"]),
                                       "human_approved": True})
                self._event(data, now, "approved." + kind, "operator", incident["id"])

    def _propose(self, data: State, incident: Incident, command: Document,
                 scope: str, now: float) -> Document:
        actions = self._validate_actions(data, incident, command.get("actions"))
        requires_person = _boolean(command.get("requiere_persona"), "requiere_persona")
        reason = _text(command.get("reason"), "reason", 1000)
        trial = copy.deepcopy(data)
        self._apply_actions(trial, trial["incidents"][incident["id"]], actions, now)
        if requires_person or scope == "proposal" or any(a["kind"] in GRAVE for a in actions):
            approval_id = _reference("approval", str(command["command_id"]))
            approval: Approval = {
                "id": approval_id, "version": 1, "incident_id": incident["id"],
                "incident_version": incident["version"], "status": "pending", "actions": actions,
                "content_hash": "", "expires_at": now + 300, "reason": reason,
                "requires_person": requires_person, "decided_by": "", "note": "",
            }
            approval["content_hash"] = self._approval_hash(approval)
            data["approvals"][approval_id] = approval
            return {"incident_id": incident["id"], "approval_id": approval_id}
        self._apply_actions(data, incident, actions, now)
        return {"incident_id": incident["id"]}

    @staticmethod
    def _approval_hash(approval: Approval) -> str:
        return _hash({key: value for key, value in _document(approval).items() if key in {
            "incident_id", "incident_version", "actions", "expires_at", "reason", "requires_person",
        }})

    def _decide(self, data: State, command: Document, principal: str, now: float) -> Document:
        approval_id = _id(command.get("approval_id"), "approval_id")
        approval = data["approvals"].get(approval_id)
        if approval is None:
            raise OperationalError("approval_missing")
        _version(approval, command)
        approved = _boolean(command.get("approved"), "approved")
        content_hash = _text(command.get("content_hash"), "content_hash", 64)
        if re.fullmatch(r"[a-f0-9]{64}", content_hash) is None:
            raise OperationalError("approval_content_changed", 409)
        note = _text(command.get("note", ""), "note", 1000, empty=True)
        if approval["status"] != "pending" or approval["expires_at"] <= now:
            raise OperationalError("approval_expired_or_decided", 409)
        if (not hmac.compare_digest(content_hash, approval["content_hash"])
                or not hmac.compare_digest(content_hash, self._approval_hash(approval))):
            raise OperationalError("approval_content_changed", 409)
        incident = self._incident(data, approval["incident_id"])
        if incident["version"] != approval["incident_version"]:
            raise OperationalError("approval_stale", 409)
        if approved:
            actions = self._validate_actions(data, incident, cast(JSON, approval["actions"]))
            trial = copy.deepcopy(data)
            self._apply_actions(trial, trial["incidents"][incident["id"]], actions, now)
            self._apply_actions(data, incident, actions, now)
        approval.update({"status": "approved" if approved else "rejected", "decided_by": principal,
                         "note": note, "version": approval["version"] + 1})
        return {"incident_id": incident["id"], "approval_id": approval_id}

    def _maintain(self, data: State, now: float) -> None:
        for delivery in data["deliveries"].values():
            if delivery["status"] == "leased" and delivery["lease_until"] <= now:
                delivery.update({
                    "status": "uncertain" if delivery["channel"] in {"phone", "happyrobot"} else "retry",
                    "lease_token": "", "lease_until": 0, "last_error": "lease_expired",
                    "version": delivery["version"] + 1,
                })
        for assignment in list(data["assignments"].values()):
            if assignment["status"] == "offered" and assignment["expires_at"] <= now:
                self._release(data, assignment, "expired", now, "offer_timeout")
                actor = data["actors"][assignment["actor_id"]]
                actor.update({"availability": "unknown", "version": actor["version"] + 1})
                self._say(data, now, actor["id"], "question",
                          "La oferta ha caducado. Confirma tu disponibilidad.", assignment["incident_id"])
        self._replan(data, now)
        for approval in data["approvals"].values():
            if approval["status"] != "pending":
                continue
            incident = data["incidents"][approval["incident_id"]]
            status = ("expired" if approval["expires_at"] <= now else
                      "stale" if incident["version"] != approval["incident_version"]
                      or incident["status"] in {"closed", "merged"} else "pending")
            if status != "pending":
                approval.update({"status": status, "version": approval["version"] + 1})
                self._event(data, now, "approval." + status, "system", incident["id"])

    def _replan(self, data: State, now: float) -> None:
        ordered = sorted(data["incidents"].values(), key=lambda i: (-i["priority"], i["created_at"], i["id"]))
        for incident in ordered:
            if incident["status"] in {"closed", "merged"}:
                continue
            waiting: list[str] = []
            if incident["zone"] is None:
                waiting.append("location_required: esperando ubicación del informante")
            else:
                for task_id, role in incident["tasks"].items():
                    if self._covered(data, task_id):
                        continue
                    eligible = [
                        actor for actor in data["actors"].values()
                        if role in actor["roles"] and actor["availability"] == "available" and actor["address"]
                        and not any(a["actor_id"] == actor["id"] and a["incident_id"] == incident["id"]
                                    and a["status"] in {"declined", "expired"} for a in data["assignments"].values())
                    ]
                    eligible.sort(key=lambda a: (a["zone"] != incident["zone"], a["id"]))
                    free = next((a for a in eligible if "actor:" + a["id"] not in data["reservations"]), None)
                    if free is None:
                        candidates = []
                        for actor in eligible:
                            aid = data["reservations"].get("actor:" + actor["id"])
                            current = data["assignments"].get(aid or "")
                            if (current and current["status"] == "offered"
                                    and data["incidents"][current["incident_id"]]["priority"] < incident["priority"]):
                                candidates.append(current)
                        if candidates:
                            victim = min(candidates, key=lambda a: data["incidents"][a["incident_id"]]["priority"])
                            self._release(data, victim, "cancelled", now, "higher_priority")
                            free = data["actors"][victim["actor_id"]]
                            self._say(data, now, free["id"], "cancelled", "Oferta sustituida por una urgencia mayor.", victim["incident_id"])
                    if free:
                        self._offer(data, incident, free["id"], role, now, task_id=task_id)
                    else:
                        waiting.append(f"no_available_{role}: sin recurso autorizado disponible; requiere coordinación")
            assignments = [a for a in data["assignments"].values() if a["incident_id"] == incident["id"]]
            complete = {a["task_id"] for a in assignments if a["status"] == "completed"}
            status = "waiting" if waiting else "open"
            if incident["tasks"] and set(incident["tasks"]) <= complete:
                status = "closed"
                for sibling in assignments:
                    if sibling["status"] == "offered":
                        self._release(data, sibling, "cancelled", now, "incident_completed")
                for reporter in incident["reporter_ids"]:
                    self._say(data, now, reporter, "closed", "Todas las tareas han finalizado. Incidencia cerrada.", incident["id"])
            elif any(a["status"] in {"arrived", "located"} for a in assignments):
                status = "in_progress"
            elif any(a["status"] in {"accepted", "en_route"} for a in assignments):
                status = "assigned"
            elif any(a["status"] == "offered" for a in assignments) and not waiting:
                status = "offered"
            why = "; ".join(waiting)
            if status != incident["status"] or why != incident["why_waiting"]:
                incident.update({"status": status, "why_waiting": why,
                                 "version": incident["version"] + 1, "updated_at": now})
