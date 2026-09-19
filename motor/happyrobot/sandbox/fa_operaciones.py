import copy
import hashlib
import re


class OperationError(ValueError):
    pass


ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.~:-]{0,119}\Z")
IN_PROGRESS = {"accepted", "en_route", "arrived", "located"}


def identifier(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise OperationError("invalid_id")
    return value


def apply_event(event, snapshot):
    if not isinstance(event, dict) or event.get("schema_version") != 2:
        raise OperationError("invalid_event")
    event_id = identifier(event.get("event_id"))
    actor_id = identifier(event.get("actor_id"))
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
        if not isinstance(doc, dict) or type(doc.get("version")) is not int or doc["version"] < 0:
            raise OperationError("invalid_snapshot")
        value = doc.get("value")
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

    def say(recipient, message, incident_id, question_id=None):
        receiver = required("actor/" + identifier(recipient))
        channel = receiver.get("preferred_channel")
        if channel not in ("telegram", "phone", "webcall"):
            raise OperationError("no_verified_reply_channel")
        suffix = hashlib.sha256((event_id + ":" + str(len(messages))).encode()).hexdigest()[:32]
        out = {"id": "delivery-" + suffix, "recipient_id": recipient, "channel": channel,
               "incident_id": incident_id, "purpose": "question" if question_id else "status", "text": message}
        if question_id:
            out["question_id"] = question_id
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
        for key in ("reservation/actor:" + actor_id, "reservation/task:" + identifier(assignment.get("task_id"))):
            reservation = read(key)
            if reservation and reservation.get("assignment_id") == aid:
                put(key, {})

    if kind in ("call.started", "call.ended", "call.failed", "delivery.updated"):
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
            if question.get("kind") != "information":
                raise OperationError("unsupported_question_kind")
            if question.get("status") != "answered":
                if question.get("status") != "pending":
                    raise OperationError("question_not_pending")
                question.update(status="answered", answer=content, answered_by=actor_id)
                put(key, question)
                say(question["requester_id"], "Respuesta del informante: " + content, iid)
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
                actor_key = "reservation/actor:" + actor_id
                task_key = "reservation/task:" + identifier(assignment.get("task_id"))
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
                qid = "availability:" + aid
                identifier(qid)
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
                    if all_assignments and not outstanding:
                        incident.update(status="closed", closed_by=actor_id)
                        put("incident/" + iid, incident)
                        message += " La incidencia queda cerrada. Gracias por avisar."
                say(reporter, message, iid)
        else:
            raise OperationError("unsupported_operation")
    else:
        raise OperationError("unsupported_operation")

    return {"event_id": event_id, "expected": expected,
            "writes": [{"entity": key, "value": value} for key, value in writes.items()], "messages": messages}
