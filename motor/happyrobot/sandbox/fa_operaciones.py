import copy
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone


class OperationError(ValueError):
    pass


ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.~:-]{0,119}\Z")
IN_PROGRESS = {"accepted", "en_route", "arrived", "located"}
ROLES = {"medico", "bomberos", "policia", "staff_entradas", "organizador"}


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError()
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError):
        raise OperationError("invalid_timestamp") from None


def available(actor, now):
    if actor.get("availability", "available") == "available":
        return True
    return bool(actor.get("available_after") and timestamp(actor["available_after"]) <= now)


def identifier(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise OperationError("invalid_id")
    return value


def reference(prefix, value):
    identifier(value)
    joined = prefix + ":" + value
    return joined if len(joined) <= 120 else prefix + ":" + hashlib.sha256(value.encode()).hexdigest()[:32]


def apply_event(event, snapshot):
    if not isinstance(event, dict) or event.get("schema_version") != 2:
        raise OperationError("invalid_event")
    event_id = identifier(event.get("event_id"))
    actor_id = identifier(event.get("actor_id"))
    now = timestamp(event.get("received_at"))
    kind = event.get("event_type")
    payload = event.get("payload")
    if not isinstance(payload, dict):
        raise OperationError("invalid_payload")
    expected, writes, messages = {}, {}, []
    values = {}

    def read(entity):
        if entity not in snapshot:
            raise OperationError("snapshot_missing:" + entity)
        doc = snapshot[entity]
        if not isinstance(doc, dict) or type(doc.get("version")) is not int or not 0 <= doc["version"] < 2**53 - 1:
            raise OperationError("invalid_snapshot")
        value = doc.get("value")
        if (value is None) != (doc["version"] == 0):
            raise OperationError("invalid_snapshot")
        if value is not None and not isinstance(value, dict):
            raise OperationError("invalid_snapshot")
        expected[entity] = doc["version"]
        if entity not in values:
            values[entity] = copy.deepcopy(value)
        return values[entity]

    def required(entity):
        result = read(entity)
        if result is None:
            raise OperationError("entity_missing:" + entity)
        return result

    def put(entity, value):
        if entity not in expected:
            read(entity)
        writes[entity] = copy.deepcopy(value)
        values[entity] = copy.deepcopy(value)

    def text(field="text"):
        result = payload.get(field)
        if not isinstance(result, str) or not result.strip() or len(result) > 2000:
            raise OperationError("invalid_text")
        return result.strip()

    actor = required("actor/" + actor_id)

    def say(recipient, message, incident_id, question_id=None, assignment_id=None):
        receiver = required("actor/" + identifier(recipient))
        channel = receiver.get("preferred_channel")
        if channel not in ("telegram", "phone", "webcall"):
            raise OperationError("no_verified_reply_channel")
        suffix = hashlib.sha256((event_id + ":" + str(len(messages))).encode()).hexdigest()[:32]
        out = {"id": "delivery-" + suffix, "recipient_id": recipient, "channel": channel,
               "incident_id": incident_id, "purpose": "question" if question_id else "status", "text": message}
        if question_id:
            out["question_id"] = question_id
        if assignment_id:
            out.update(purpose="offer", assignment_id=assignment_id)
        messages.append(out)

    def assignment_for_caller(incident_id):
        aid = identifier(event.get("assignment_id"))
        assignment = required("assignment/" + aid)
        if assignment.get("actor_id") != actor_id:
            raise OperationError("assignment_for_other_actor")
        if assignment.get("incident_id") != incident_id:
            raise OperationError("assignment_for_other_incident")
        if assignment.get("role") not in actor.get("roles", []):
            raise OperationError("role_not_authorized")
        return aid, assignment

    def release(aid, assignment):
        for key in ("reservation/" + reference("actor", assignment.get("actor_id")), "reservation/" + reference("task", assignment.get("task_id"))):
            reservation = read(key)
            if reservation and reservation.get("assignment_id") == aid:
                put(key, {})

    def coordinator():
        if "coordinate" not in actor.get("permissions", []):
            raise OperationError("coordinator_required")

    def open_incident():
        iid = identifier(event.get("incident_id"))
        incident = required("incident/" + iid)
        if incident.get("status") == "closed":
            raise OperationError("incident_closed")
        return iid, incident

    def assignments(incident):
        ids = incident.get("assignment_ids", [])
        if not isinstance(ids, list) or len(ids) > 16:
            raise OperationError("assignment_batch_limit")
        return [(identifier(aid), required("assignment/" + identifier(aid))) for aid in ids]

    def change_availability(minutes):
        if minutes is not None and (type(minutes) is not int or not 0 <= minutes <= 240):
            raise OperationError("invalid_availability")
        actor["availability"] = "unknown" if minutes is None else "available" if minutes == 0 else "unavailable"
        actor["available_after"] = (now + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z") if minutes is not None else None
        put("actor/" + actor_id, actor)

    if kind == "incident.reported":
        iid = identifier(event.get("incident_id"))
        key = "incident/" + iid
        if read(key) is not None:
            raise OperationError("incident_exists")
        conversation_key = "conversation/" + identifier(event.get("conversation_id"))
        conversation = read(conversation_key) or {"actor_id": actor_id, "incident_ids": []}
        if conversation.get("actor_id") != actor_id:
            raise OperationError("conversation_for_other_actor")
        if len(conversation.get("incident_ids", [])) >= 16:
            raise OperationError("conversation_incident_limit")
        conversation.setdefault("incident_ids", []).append(iid)
        put(conversation_key, conversation)
        put(key, {"status": "open", "reporter_id": actor_id, "text": text(),
                  "location": text("location") if payload.get("location") else None,
                  "assignment_ids": [], "tasks": {}, "conversation_id": event["conversation_id"], "created_at": event["received_at"]})
        say(actor_id, "He registrado tu aviso. La coordinación del equipo está pendiente.", iid)
    elif kind == "assignment.offered":
        coordinator()
        iid, incident = open_incident()
        aid = identifier(event.get("assignment_id"))
        key = "assignment/" + aid
        if read(key) is not None:
            raise OperationError("assignment_exists")
        recipient = identifier(payload.get("recipient_id"))
        receiver = required("actor/" + recipient)
        role = payload.get("role")
        if role not in ROLES or role not in receiver.get("roles", []):
            raise OperationError("capacity_mismatch")
        task_id = identifier(payload.get("task_id"))
        tasks = incident.setdefault("tasks", {})
        if task_id in tasks and tasks[task_id].get("role") != role:
            raise OperationError("task_capacity_mismatch")
        for _, previous in assignments(incident):
            if previous.get("task_id") == task_id and previous.get("role") != role:
                raise OperationError("task_capacity_mismatch")
        if not available(receiver, now):
            raise OperationError("actor_unavailable")
        actor_key = "reservation/" + reference("actor", recipient)
        if (read(actor_key) or {}).get("assignment_id"):
            raise OperationError("actor_busy")
        if (read("reservation/" + reference("task", task_id)) or {}).get("assignment_id"):
            raise OperationError("task_covered")
        if len(incident["assignment_ids"]) >= 16:
            raise OperationError("assignment_batch_limit")
        tasks[task_id] = {"role": role}
        incident["assignment_ids"].append(aid)
        put("incident/" + iid, incident)
        put(key, {"status": "offered", "actor_id": recipient, "incident_id": iid,
                  "task_id": task_id, "role": role, "created_at": event["received_at"]})
        put(actor_key, {"assignment_id": aid})
        say(recipient, "¿Puedes atender el aviso en " + str(incident.get("location") or "zona pendiente de confirmar") + "? " + str(incident.get("text") or ""), iid, assignment_id=aid)
    elif kind in ("actor.role_claimed", "actor.role_released"):
        busy = read("reservation/" + reference("actor", actor_id)) or {}
        if busy.get("assignment_id"):
            raise OperationError("actor_busy")
        if kind == "actor.role_claimed":
            role = payload.get("role")
            if role not in ROLES:
                raise OperationError("invalid_role")
            grant_key = "approval/" + identifier(payload.get("grant_id"))
            grant = required(grant_key)
            if (grant.get("kind") != "role_claim" or grant.get("status") != "approved" or
                    grant.get("actor_id") != actor_id or grant.get("role") != role or timestamp(grant.get("expires_at")) <= now):
                raise OperationError("invalid_role_grant")
            role_key = "reservation/role:" + role
            holder = read(role_key) or {}
            if holder.get("actor_id") not in (None, actor_id):
                raise OperationError("role_taken")
            put(role_key, {"actor_id": actor_id})
            grant.update(status="consumed", consumed_by=event_id)
            put(grant_key, grant)
            new_roles = [role]
        else:
            new_roles = []
        for previous in actor.get("roles", []):
            if previous in new_roles:
                continue
            role_key = "reservation/role:" + identifier(previous)
            if (read(role_key) or {}).get("actor_id") == actor_id:
                put(role_key, {})
        actor["roles"] = new_roles
        put("actor/" + actor_id, actor)
    elif kind == "actor.availability_updated":
        if not actor.get("roles"):
            raise OperationError("role_not_authorized")
        change_availability(payload.get("available_in_min"))
    elif kind in ("incident.updated", "incident.close_requested"):
        iid, incident = open_incident()
        reporter = identifier(incident.get("reporter_id"))
        if actor_id != reporter and "coordinate" not in actor.get("permissions", []):
            raise OperationError("incident_for_other_actor")
        if kind == "incident.close_requested":
            qid = identifier(event.get("question_id"))
            key = "question/" + qid
            if read(key) is not None:
                raise OperationError("question_exists")
            put(key, {"incident_id": iid, "recipient_id": reporter, "requester_id": actor_id,
                      "status": "pending", "kind": "closure", "text": "¿Confirmas que el aviso está resuelto y puede cerrarse?"})
            say(reporter, "¿Confirmas que el aviso está resuelto y puede cerrarse?", iid, qid)
        else:
            content = text()
            if payload.get("location"):
                incident["location"] = text("location")
            incident.setdefault("updates", []).append({"event_id": event_id, "actor_id": actor_id, "text": content})
            put("incident/" + iid, incident)
            for _, assignment in assignments(incident):
                if assignment.get("status") in IN_PROGRESS or assignment.get("status") == "offered":
                    say(assignment["actor_id"], "Información del aviso: " + content, iid)
    elif kind in ("call.started", "call.ended", "call.failed", "delivery.updated"):
        if kind.startswith("call."):
            identifier(event.get("call_id"))
    elif kind in ("question.created", "question.answered"):
        iid = identifier(event.get("incident_id"))
        incident = required("incident/" + iid)
        if incident.get("status") == "closed":
            raise OperationError("incident_closed")
        qid = identifier(event.get("question_id"))
        key = "question/" + qid
        question = read(key)
        content = text()
        if kind == "question.created":
            aid, assignment = assignment_for_caller(iid)
            if assignment.get("status") not in IN_PROGRESS:
                raise OperationError("assignment_not_accepted")
            if question is not None:
                raise OperationError("question_exists")
            recipient = identifier(incident.get("reporter_id"))
            put(key, {"incident_id": iid, "assignment_id": aid, "requester_id": actor_id,
                      "recipient_id": recipient, "status": "pending", "kind": "information", "text": content})
            say(recipient, "El equipo pregunta: " + content, iid, qid)
        else:
            if not question or question.get("incident_id") != iid:
                raise OperationError("question_missing")
            if question.get("recipient_id") != actor_id:
                raise OperationError("question_for_other_actor")
            if question.get("status") != "answered":
                if question.get("status") != "pending":
                    raise OperationError("question_not_pending")
                question_kind = question.get("kind")
                pending = False
                if question_kind == "information":
                    say(question["requester_id"], "Respuesta del informante: " + content, iid)
                elif question_kind == "availability":
                    if not actor.get("roles"):
                        raise OperationError("role_not_authorized")
                    minutes = payload.get("available_in_min")
                    change_availability(minutes)
                    pending = minutes is None
                    reply = "Anoto que todavía no sabes cuándo podrás atender el aviso. Cuando lo sepas, responde aquí." if pending else f"Disponibilidad anotada: en {minutes} minutos."
                    say(actor_id, reply, iid, qid if pending else None)
                elif question_kind == "closure":
                    if actor_id != incident.get("reporter_id") or type(payload.get("confirmed")) is not bool:
                        raise OperationError("explicit_closure_confirmation_required")
                    if payload["confirmed"]:
                        incident.update(status="closed", closed_by=actor_id)
                        put("incident/" + iid, incident)
                        for aid, assignment in assignments(incident):
                            if assignment.get("status") in IN_PROGRESS or assignment.get("status") == "offered":
                                assignment["status"] = "cancelled"
                                put("assignment/" + aid, assignment)
                                release(aid, assignment)
                                say(assignment["actor_id"], "El informante confirma que el aviso está resuelto. Incidencia cerrada.", iid)
                    say(actor_id, "Incidencia cerrada. Gracias por avisar." if payload["confirmed"] else "El aviso sigue abierto. Informo a coordinación.", iid)
                else:
                    raise OperationError("unsupported_question_kind")
                question.update(status="pending" if pending else "answered", answer=content, answered_by=actor_id)
                put(key, question)
    elif isinstance(kind, str) and kind.startswith("assignment."):
        iid = identifier(event.get("incident_id"))
        incident = required("incident/" + iid)
        if incident.get("status") == "closed":
            raise OperationError("incident_closed")
        aid, assignment = assignment_for_caller(iid)
        status = assignment.get("status")
        reporter = identifier(incident.get("reporter_id"))
        if kind == "assignment.accepted":
            if status != "accepted":
                if status != "offered":
                    raise OperationError("invalid_transition")
                if not available(actor, now):
                    raise OperationError("actor_unavailable")
                actor_key = "reservation/" + reference("actor", actor_id)
                task_key = "reservation/" + reference("task", assignment.get("task_id"))
                actor_reservation, task_reservation = read(actor_key), read(task_key)
                if actor_reservation and actor_reservation.get("assignment_id") not in (None, aid):
                    raise OperationError("actor_busy")
                if task_reservation and task_reservation.get("assignment_id") not in (None, aid):
                    raise OperationError("task_covered")
                put(actor_key, {"assignment_id": aid})
                put(task_key, {"assignment_id": aid})
                assignment["status"] = "accepted"
                put("assignment/" + aid, assignment)
                say(reporter, "El equipo ha aceptado tu aviso. El tiempo de llegada está pendiente de confirmar.", iid)
        elif kind == "assignment.declined":
            if status != "declined":
                if status not in ("offered", "accepted", "en_route"):
                    raise OperationError("invalid_transition")
                assignment.update(status="declined", reason=text("reason"))
                put("assignment/" + aid, assignment)
                release(aid, assignment)
                change_availability(None)
                incident["needs_replan"] = True
                put("incident/" + iid, incident)
                qid = reference("availability", aid)
                key = "question/" + qid
                if read(key) is not None:
                    raise OperationError("question_exists")
                put(key, {"incident_id": iid, "assignment_id": aid, "recipient_id": actor_id,
                          "status": "pending", "kind": "availability", "text": "¿Cuándo podrás atender el aviso?"})
                say(actor_id, "¿Cuándo podrás atender el aviso? Si no lo sabes todavía, indícalo.", iid, qid)
                say(reporter, "El equipo no puede intervenir ahora. La coordinación queda pendiente de reasignación.", iid)
        elif kind == "assignment.eta_updated":
            if status not in IN_PROGRESS:
                raise OperationError("assignment_not_accepted")
            eta = payload.get("eta_min")
            if type(eta) is not int or not 0 <= eta <= 240:
                raise OperationError("invalid_eta")
            if assignment.get("eta_min") != eta:
                assignment["eta_min"] = eta
                put("assignment/" + aid, assignment)
                say(reporter, f"El equipo estima su llegada en {eta} minutos.", iid)
        elif kind in ("assignment.arrived", "assignment.located", "assignment.completed"):
            target = kind.split(".")[1]
            allowed = {"arrived": {"accepted", "en_route"}, "located": {"arrived"}, "completed": {"located"}}
            if status != target:
                if status not in allowed[target]:
                    raise OperationError("invalid_transition")
                assignment["status"] = target
                put("assignment/" + aid, assignment)
                message = {"arrived": "El equipo ha llegado a la zona indicada.",
                           "located": "El equipo ha localizado la incidencia.",
                           "completed": "El equipo ha finalizado su asistencia."}[target]
                if target == "completed":
                    release(aid, assignment)
                    all_assignments = [required("assignment/" + identifier(other)) for other in incident.get("assignment_ids", [])]
                    complete_tasks = {a.get("task_id") for a in all_assignments if a.get("status") == "completed" and a.get("task_id")}
                    outstanding = [a for a in all_assignments if a.get("status") not in ("completed", "cancelled") and a.get("task_id") not in complete_tasks]
                    unfulfilled_tasks = set(incident.get("tasks", {})) - complete_tasks
                    if all_assignments and not outstanding and not unfulfilled_tasks:
                        incident.update(status="closed", closed_by=actor_id)
                        put("incident/" + iid, incident)
                        message += " La incidencia queda cerrada. Gracias por avisar."
                say(reporter, message, iid)
        else:
            raise OperationError("unsupported_operation")
    else:
        raise OperationError("unsupported_operation")

    def link_actor(recipient, field, value, remove=False):
        key = "actor/" + identifier(recipient)
        person = required(key)
        items = person.get(field, [])
        if not isinstance(items, list):
            raise OperationError("invalid_actor_context")
        updated = [item for item in items if item != value]
        if not remove:
            updated.append(value)
        if len(updated) > 16:
            raise OperationError("actor_context_limit")
        if updated != items:
            person[field] = updated
            put(key, person)

    if kind == "incident.reported":
        link_actor(actor_id, "incident_ids", event["incident_id"])
    if kind == "assignment.offered":
        link_actor(payload["recipient_id"], "incident_ids", event["incident_id"])
    for key, value in list(writes.items()):
        if key.startswith("question/"):
            qid = key.split("/", 1)[1]
            link_actor(value["recipient_id"], "pending_question_ids", qid, value.get("status") != "pending")
            incident_key = "incident/" + identifier(value["incident_id"])
            incident_value = required(incident_key)
            questions = incident_value.get("question_ids", [])
            if not isinstance(questions, list):
                raise OperationError("invalid_question_index")
            pending = [item for item in questions if item != qid]
            if value.get("status") == "pending":
                pending.append(qid)
            if len(pending) > 16:
                raise OperationError("question_limit")
            if pending != questions:
                incident_value["question_ids"] = pending
                put(incident_key, incident_value)
    for key, value in list(writes.items()):
        if key.startswith("incident/") and value.get("status") == "closed":
            iid = key.split("/", 1)[1]
            closed = required(key)
            people = {closed["reporter_id"]} | {item["actor_id"] for _, item in assignments(closed)}
            for person in sorted(people):
                link_actor(person, "incident_ids", iid, True)
            for qid in closed.get("question_ids", []):
                question = required("question/" + identifier(qid))
                if question.get("status") == "pending":
                    question["status"] = "cancelled"
                    put("question/" + qid, question)
                    link_actor(question["recipient_id"], "pending_question_ids", qid, True)
            closed["question_ids"] = []
            put(key, closed)
            if closed.get("conversation_id"):
                conversation_key = "conversation/" + identifier(closed["conversation_id"])
                conversation = required(conversation_key)
                if conversation.get("actor_id") != closed["reporter_id"]:
                    raise OperationError("conversation_for_other_actor")
                conversation["incident_ids"] = [item for item in conversation.get("incident_ids", []) if item != iid]
                put(conversation_key, conversation)

    return {"event_id": event_id, "expected": expected,
            "writes": [{"entity": key, "value": value} for key, value in writes.items()], "messages": messages}


def run_input(input_data):
    try:
        if not isinstance(input_data, dict):
            raise OperationError("invalid_input")
        event = input_data.get("event_json")
        snapshot = input_data.get("snapshot_json")
        event = json.loads(event) if isinstance(event, str) else event
        snapshot = json.loads(snapshot) if isinstance(snapshot, str) else snapshot
        if not isinstance(event, dict) or not isinstance(snapshot, dict):
            raise OperationError("invalid_input")
        commit = apply_event(event, snapshot)
        return {"status": "ready", "commit_json": json.dumps(commit, ensure_ascii=True),
                "required_entities_json": "[]", "error": ""}
    except OperationError as exc:
        error = str(exc)
        missing = error.startswith("snapshot_missing:")
        return {"status": "needs_snapshot" if missing else "rejected", "commit_json": "",
                "required_entities_json": json.dumps([error.split(":", 1)[1]]) if missing else "[]",
                "error": "snapshot_missing" if missing else error}
    except (ValueError, TypeError, KeyError, AttributeError):
        return {"status": "rejected", "commit_json": "", "required_entities_json": "[]", "error": "invalid_input"}
