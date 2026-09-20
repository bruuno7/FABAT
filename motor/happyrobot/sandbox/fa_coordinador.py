import copy
import hashlib
import json

if "apply_event" not in globals():
    from .fa_operaciones import OperationError, ROLES, apply_event, identifier, reference


INTENTS = {"report", "update", "accept", "decline", "eta", "arrived", "located", "completed", "availability", "question", "answer", "request_close", "chat", "clarify"}
SERVICE_ACTOR = "service-coordinator"


def derived_id(event_id, kind, index=0):
    return kind + "-" + hashlib.sha256((identifier(event_id) + ":" + kind + ":" + str(index)).encode()).hexdigest()[:32]


def document(snapshot, key, optional=False):
    if key not in snapshot:
        raise OperationError("snapshot_missing:" + key)
    doc = snapshot[key]
    if not isinstance(doc, dict) or type(doc.get("version")) is not int or not 0 <= doc["version"] < 2**53 - 1:
        raise OperationError("invalid_snapshot")
    value = doc.get("value")
    if (value is None) != (doc["version"] == 0) or value is not None and not isinstance(value, dict):
        raise OperationError("invalid_snapshot")
    if value is None and not optional:
        raise OperationError("entity_missing:" + key)
    return value


def public_context(event, snapshot):
    actor_id = identifier(event.get("actor_id"))
    actor = document(snapshot, "actor/" + actor_id)
    incidents, assignments, questions, staff = [], [], [], []
    mine = set(actor.get("incident_ids", []))
    conversation = document(snapshot, "conversation/" + identifier(event.get("conversation_id")), True)
    if conversation and conversation.get("actor_id") != actor_id:
        raise OperationError("conversation_for_other_actor")
    mine.update((conversation or {}).get("incident_ids", []))
    if event.get("incident_id"):
        candidate = document(snapshot, "incident/" + identifier(event["incident_id"]))
        if candidate.get("reporter_id") == actor_id:
            mine.add(event["incident_id"])
    for key, doc in snapshot.items():
        value = document(snapshot, key, True)
        if not value:
            continue
        if key.startswith("assignment/") and value.get("actor_id") == actor_id:
            mine.add(value.get("incident_id"))
            assignments.append({"id": key.split("/", 1)[1], **{field: value.get(field) for field in ("incident_id", "role", "status", "eta_min", "task_id")}})
        if key.startswith("question/") and value.get("recipient_id") == actor_id and value.get("status") == "pending":
            questions.append({"id": key.split("/", 1)[1], **{field: value.get(field) for field in ("incident_id", "assignment_id", "kind", "text")}})
    for iid in sorted(value for value in mine if isinstance(value, str)):
        value = document(snapshot, "incident/" + identifier(iid), True)
        if value and value.get("status") != "closed":
            incidents.append({"id": iid, **{field: value.get(field) for field in ("status", "text", "location", "tasks")}})
    for role in ("medico", "bomberos", "policia", "staff_entradas", "organizador"):
        seat = document(snapshot, "reservation/role:" + role, True)
        if not seat or not seat.get("actor_id"):
            continue
        worker_id = identifier(seat["actor_id"])
        worker = document(snapshot, "actor/" + worker_id)
        busy = document(snapshot, "reservation/" + reference("actor", worker_id), True) or {}
        staff.append({"id": worker_id, "role": role, "availability": worker.get("availability", "available"),
                      "available_after": worker.get("available_after"), "busy": bool(busy.get("assignment_id"))})
    history = [{"role": turn.get("role"), "text": str(turn.get("text", ""))[:2000]} for turn in (conversation or {}).get("turns", [])[-12:] if isinstance(turn, dict)]
    return {"actor_id": actor_id, "roles": actor.get("roles", []), "text": event.get("payload", {}).get("text", ""),
            "incidents": incidents, "assignments": assignments, "questions": questions, "staff": staff, "history": history}


def coordinate(event, snapshot, proposal):
    if not isinstance(event, dict) or event.get("event_type") != "message.received":
        raise OperationError("message_required")
    if not isinstance(proposal, dict) or proposal.get("intent") not in INTENTS:
        raise OperationError("invalid_intent")
    event_id = identifier(event.get("event_id"))
    context = public_context(event, snapshot)
    actor_id = context["actor_id"]
    actor = document(snapshot, "actor/" + actor_id)
    decision_key = "decision/" + derived_id(event_id, "decision")
    if document(snapshot, decision_key, True) is not None:
        raise OperationError("decision_exists")
    work = copy.deepcopy(snapshot)
    expected = {key: doc["version"] for key, doc in snapshot.items()}
    writes, messages, operations = {}, [], []

    def apply(kind, payload, *, actor=actor_id, **references):
        child = {**event, "event_id": derived_id(event_id, "operation", len(operations)), "event_type": kind,
                 "actor_id": actor, "causation_id": event_id, "payload": payload}
        for name in ("incident_id", "assignment_id", "question_id"):
            child.pop(name, None)
        child.update(references)
        commit = apply_event(child, work)
        for key in commit["expected"]:
            document(snapshot, key, True)
            expected[key] = snapshot[key]["version"]
        for item in commit["writes"]:
            key = item["entity"]
            writes[key] = item["value"]
            work[key] = {"version": max(1, snapshot[key]["version"]), "value": copy.deepcopy(item["value"])}
        messages.extend(commit["messages"])
        operations.append({"event_type": kind, **references})

    def reply(message):
        if not isinstance(message, str) or not message.strip() or len(message) > 1000:
            raise OperationError("invalid_reply")
        channel = actor.get("preferred_channel")
        if channel not in ("telegram", "phone", "webcall"):
            raise OperationError("no_verified_reply_channel")
        messages.append({"id": derived_id(event_id, "reply"), "recipient_id": actor_id, "channel": channel,
                         "purpose": "conversation", "text": message.strip()})

    def choose(field, choices):
        anchored = event.get(field)
        wanted = anchored or proposal.get(field)
        available = [item["id"] for item in choices]
        if wanted:
            if wanted not in available:
                raise OperationError("reference_for_other_actor")
            if len(available) > 1 and not anchored and wanted not in event.get("payload", {}).get("text", ""):
                raise OperationError("ambiguous_reference")
            return wanted
        if len(available) != 1:
            raise OperationError("ambiguous_reference")
        return available[0]

    intent = proposal["intent"]
    text = event.get("payload", {}).get("text")
    if not isinstance(text, str) or not text.strip() or len(text) > 2000:
        raise OperationError("invalid_text")
    try:
        if intent in ("chat", "clarify"):
            reply(proposal.get("reply") or "¿Puedes concretar qué necesitas y a qué aviso te refieres?")
        elif intent == "report":
            iid = derived_id(event_id, "incident")
            payload = {"text": text}
            location = proposal.get("location")
            if isinstance(location, str) and location.strip():
                payload["location"] = location[:200]
            apply("incident.reported", payload, incident_id=iid)
            offers = proposal.get("offers", [])
            if not isinstance(offers, list) or len(offers) > 5:
                raise OperationError("invalid_offers")
            required_roles = proposal.get("required_roles", [offer.get("role") for offer in offers if isinstance(offer, dict)])
            if not isinstance(required_roles, list) or len(required_roles) > 5 or any(role not in ROLES for role in required_roles):
                raise OperationError("invalid_required_capacities")
            planned = copy.deepcopy(work["incident/" + iid]["value"])
            planned["tasks"] = {derived_id(event_id, "task-" + role): {"role": role} for role in required_roles}
            writes["incident/" + iid] = planned
            work["incident/" + iid]["value"] = copy.deepcopy(planned)
            seen = set()
            for index, offer in enumerate(offers):
                if not isinstance(offer, dict):
                    raise OperationError("invalid_offer")
                recipient, role = offer.get("recipient_id"), offer.get("role")
                if recipient in seen or not any(member["id"] == recipient and member["role"] == role for member in context["staff"]):
                    raise OperationError("capacity_mismatch")
                seen.add(recipient)
                if role not in required_roles and role != "organizador":
                    raise OperationError("capacity_mismatch")
                apply("assignment.offered", {"recipient_id": recipient, "role": role, "task_id": derived_id(event_id, "task-" + role)},
                      actor=SERVICE_ACTOR, incident_id=iid, assignment_id=derived_id(event_id, "assignment", index))
        elif intent == "answer":
            qid = choose("question_id", context["questions"])
            question = next(item for item in context["questions"] if item["id"] == qid)
            payload = {"text": text}
            if question["kind"] == "availability":
                payload["available_in_min"] = proposal.get("minutes")
            if question["kind"] == "closure":
                if type(proposal.get("confirmed")) is not bool:
                    raise OperationError("ambiguous_reference")
                payload["confirmed"] = proposal["confirmed"]
            apply("question.answered", payload, incident_id=question["incident_id"], question_id=qid)
        elif intent == "availability":
            apply("actor.availability_updated", {"available_in_min": proposal.get("minutes")})
        elif intent in ("update", "request_close"):
            iid = choose("incident_id", context["incidents"])
            if intent == "request_close":
                apply("incident.close_requested", {}, incident_id=iid, question_id=derived_id(event_id, "question"))
            else:
                payload = {"text": text}
                if isinstance(proposal.get("location"), str) and proposal["location"].strip():
                    payload["location"] = proposal["location"][:200]
                apply("incident.updated", payload, incident_id=iid)
        else:
            candidates = [item for item in context["assignments"] if item["status"] in ("offered", "accepted", "en_route", "arrived", "located")]
            aid = choose("assignment_id", candidates)
            assignment = next(item for item in candidates if item["id"] == aid)
            refs = {"incident_id": assignment["incident_id"], "assignment_id": aid}
            if intent == "question":
                apply("question.created", {"text": text}, **refs, question_id=derived_id(event_id, "question"))
            else:
                kinds = {"accept": "accepted", "decline": "declined", "eta": "eta_updated", "arrived": "arrived", "located": "located", "completed": "completed"}
                payload = {"reason": text} if intent == "decline" else {"eta_min": proposal.get("minutes")} if intent == "eta" else {}
                apply("assignment." + kinds[intent], payload, **refs)
    except OperationError as exc:
        if str(exc) not in ("ambiguous_reference", "reference_for_other_actor"):
            raise
        if operations:
            raise
        intent = "clarify"
        reply("No puedo asociar esa respuesta con seguridad. Indica a qué aviso, asignación o pregunta te refieres.")
    conversation_key = "conversation/" + identifier(event["conversation_id"])
    conversation = copy.deepcopy(document(work, conversation_key, True) or {"actor_id": actor_id, "incident_ids": []})
    turns = conversation.get("turns", [])
    if not isinstance(turns, list):
        raise OperationError("invalid_conversation")
    turns = turns + [{"role": "user", "text": text, "event_id": event_id}]
    turns += [{"role": "assistant", "text": message["text"], "event_id": event_id, "delivery": "queued"}
              for message in messages if message["recipient_id"] == actor_id]
    conversation["turns"] = turns[-12:]
    writes[conversation_key] = conversation
    reason = proposal.get("reason", "")
    if not isinstance(reason, str):
        raise OperationError("invalid_reason")
    writes[decision_key] = {"source_event_id": event_id, "status": "applied", "intent": intent,
                            "reason": reason[:500], "operations": operations, "based_on": expected}
    if len(expected) > 32 or len(writes) > 32 or len(messages) > 16:
        raise OperationError("plan_limit")
    return {"event_id": event_id, "expected": expected, "writes": [{"entity": key, "value": value} for key, value in writes.items()], "messages": messages}


def required_entities(event, proposal):
    event_id = identifier(event.get("event_id"))
    keys = ["decision/" + derived_id(event_id, "decision")]
    if proposal.get("intent") == "report":
        keys.append("incident/" + derived_id(event_id, "incident"))
        offers = proposal.get("offers", [])
        if not isinstance(offers, list) or len(offers) > 5:
            raise OperationError("invalid_offers")
        for index, offer in enumerate(offers):
            if not isinstance(offer, dict) or offer.get("role") not in ROLES:
                raise OperationError("invalid_offers")
            keys.extend(["assignment/" + derived_id(event_id, "assignment", index),
                         "reservation/" + reference("task", derived_id(event_id, "task-" + offer["role"]))])
    if proposal.get("intent") in ("question", "request_close"):
        keys.append("question/" + derived_id(event_id, "question"))
    return keys


def context_input(input_data):
    try:
        parse = lambda value: json.loads(value) if isinstance(value, str) else value
        event = parse(input_data.get("event_json"))
        if input_data.get("state_status") != "pending" or int(input_data.get("status_code", 0)) != 200:
            return {"status": "skip", "context_json": "{}"}
        if event.get("event_type") != "message.received":
            return {"status": "structured", "context_json": "{}"}
        context = public_context(event, parse(input_data.get("snapshot_json")))
        return {"status": "ready", "context_json": json.dumps(context, ensure_ascii=True)}
    except (OperationError, ValueError, TypeError, AttributeError, KeyError):
        return {"status": "unavailable", "context_json": "{}"}


def request_input(input_data):
    try:
        parse = lambda value: json.loads(value) if isinstance(value, str) else value
        event = parse(input_data.get("event_json"))
        proposal = parse(input_data.get("proposal_json"))
        keys = required_entities(event, proposal)
        return {"status": "ready", "body_json": json.dumps({"id": identifier(event["event_id"]), "extra_entities_json": json.dumps(keys)})}
    except (OperationError, ValueError, TypeError, AttributeError, KeyError):
        return {"status": "rejected", "body_json": json.dumps({"id": input_data.get("event_id"), "extra_entities_json": "[]"})}


def coordinator_rpc_input(input_data):
    event_id = identifier(input_data.get("event_id"))
    output = {"status": "unavailable", "path": "/inbox/status", "body_json": json.dumps({"id": event_id})}
    try:
        if input_data.get("state_status") != "pending" or int(input_data.get("status_code", 0)) != 200:
            return output
        event = input_data.get("event_json")
        event = json.loads(event) if isinstance(event, str) else event
        if not isinstance(event, dict) or event.get("event_id") != event_id:
            return output
        result = coordinator_input(input_data)
        if result["status"] == "ready":
            return {"status": "ready", "path": "/commit", "body_json": result["commit_json"]}
        return {"status": result["status"], "path": "/inbox/settle",
                "body_json": json.dumps({"id": event_id, "status": "deferred", "reason": result["error"] or "invalid_proposal"})}
    except (OperationError, ValueError, TypeError, AttributeError, KeyError):
        return output


def coordinator_input(input_data):
    try:
        parse = lambda value: json.loads(value) if isinstance(value, str) else value
        event, snapshot, proposal = [parse(input_data.get(name)) for name in ("event_json", "snapshot_json", "proposal_json")]
        commit = coordinate(event, snapshot, proposal)
        return {"status": "ready", "commit_json": json.dumps(commit, ensure_ascii=True), "error": "", "required_entities_json": "[]"}
    except OperationError as exc:
        reason = str(exc)
        missing = reason.startswith("snapshot_missing:")
        return {"status": "needs_snapshot" if missing else "rejected", "commit_json": "", "error": reason.split(":", 1)[0],
                "required_entities_json": json.dumps([reason.split(":", 1)[1]]) if missing else "[]"}
    except (ValueError, TypeError, KeyError, AttributeError):
        return {"status": "rejected", "commit_json": "", "error": "invalid_input", "required_entities_json": "[]"}
