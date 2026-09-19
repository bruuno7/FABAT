import json
import re

if "apply_event" not in globals():
    from .fa_operaciones import OperationError, apply_event, identifier, run_input


ENTITY = re.compile(r"(?:actor|incident|assignment|question|conversation|reservation|decision|approval)/[A-Za-z0-9][A-Za-z0-9_.~:-]{0,119}\Z")
MAX_ATTEMPTS = 3
MAX_REQUESTS = 110


def finished(state, status):
    return {"status": status, "event_id": state["event_id"], "request": None, "state": None}


def request(state, stage, path, scope, body):
    state["stage"] = stage
    state["requests"] += 1
    if state["requests"] > MAX_REQUESTS:
        return finished(state, "unavailable")
    return {"status": "request", "event_id": state["event_id"], "state": state,
            "request": {"path": path, "scope": scope, "body": body}}


def settle(state, status, reason):
    code = reason.split(":", 1)[0]
    if not re.fullmatch(r"[a-z_]{1,64}", code):
        code = "invalid_operation"
    return request(state, "settle", "/inbox/settle", "commit",
                   {"id": state["event_id"], "status": status, "reason": code})


def plan(state):
    try:
        commit = apply_event(state["event"], state["snapshot"])
    except OperationError as exc:
        reason = str(exc)
        if reason.startswith("snapshot_missing:"):
            entity = reason.split(":", 1)[1]
            if not ENTITY.fullmatch(entity) or entity in state["entities"] or len(state["entities"]) >= 32:
                return settle(state, "rejected", "entity_limit")
            state["entities"].append(entity)
            state["requested_entities"] = [entity]
            return request(state, "snapshot", "/snapshot", "read", {"entities": [entity]})
        return settle(state, "deferred" if reason.startswith("entity_missing:") else "rejected", reason)
    state["attempts"] += 1
    return request(state, "commit", "/commit", "commit", commit)


def advance(event_id, state=None, response=None, status_code=200):
    identifier(event_id)
    if state is None:
        state = {"event_id": event_id, "entities": [], "snapshot": {}, "attempts": 0, "requests": 0}
        return request(state, "event", "/inbox/event", "read", {"id": event_id})
    if not isinstance(state, dict) or state.get("event_id") != event_id:
        raise ValueError("invalid_consumer_state")
    if status_code not in (200, 409):
        return finished(state, "unavailable")
    stage = state["stage"]
    if stage == "event":
        if response is None:
            return finished(state, "missing")
        if not isinstance(response, dict) or not isinstance(response.get("event"), dict) or response["event"].get("event_id") != event_id:
            return finished(state, "unavailable")
        if response.get("status") == "applied":
            return finished(state, "duplicate")
        if response.get("status") == "rejected":
            return finished(state, "rejected")
        if response.get("status") != "pending":
            return finished(state, "unavailable")
        state["event"] = response["event"]
        if state["event"].get("event_type") in ("message.received", "deadline.elapsed", "review.requested"):
            return finished(state, "needs_coordination")
        return plan(state)
    if stage == "snapshot":
        if not isinstance(response, dict) or set(response) != set(state["requested_entities"]):
            return settle(state, "deferred", "incomplete_snapshot")
        state["snapshot"].update(response)
        return plan(state)
    if not isinstance(response, dict):
        return finished(state, "unavailable")
    status = response.get("status")
    if stage == "commit":
        if status == "conflict":
            if state["attempts"] >= MAX_ATTEMPTS:
                return settle(state, "deferred", "conflict")
            state["snapshot"] = {}
            state["requested_entities"] = list(state["entities"])
            return request(state, "snapshot", "/snapshot", "read", {"entities": state["entities"]})
        if status in ("applied", "duplicate", "rejected"):
            return finished(state, status)
        return settle(state, "deferred", "commit_conflict")
    if stage == "settle" and status in ("deferred", "rejected", "duplicate", "missing"):
        return finished(state, status)
    return finished(state, "unavailable")


def consume(event_id, api):
    try:
        output = advance(event_id)
        while output["status"] == "request":
            action = output["request"]
            response = api(action["path"], action["body"])
            output = advance(event_id, output["state"], response)
        return {"event_id": event_id, "status": output["status"]}
    except Exception:
        return {"event_id": event_id, "status": "unavailable"}


def recover(api, limit=8):
    if type(limit) is not int or not 1 <= limit <= 16:
        raise ValueError("invalid_recovery_limit")
    try:
        ids = api("/inbox/pending", {"limit": limit})
        if not isinstance(ids, list) or len(ids) > limit or len(set(ids)) != len(ids):
            raise ValueError("invalid_pending_events")
        for event_id in ids:
            identifier(event_id)
    except Exception:
        return {"status": "unavailable", "processed": 0, "results": []}
    results = [consume(event_id, api) for event_id in ids]
    return {"status": "processed", "processed": len(results), "results": results}


def consumer_input(input_data):
    try:
        event_id = identifier(input_data.get("event_id"))
        state = input_data.get("state_json") or None
        response = input_data.get("response_json")
        state = json.loads(state) if isinstance(state, str) else state
        response = json.loads(response) if isinstance(response, str) and response else response
        code = input_data.get("status_code")
        code = 200 if state is None and code in (None, "") else int(code)
        output = advance(event_id, state, response, code)
        action = output["request"] or {}
        return {"status": output["status"], "event_id": event_id,
                "state_json": json.dumps(output["state"], ensure_ascii=True),
                "path": action.get("path", ""), "scope": action.get("scope", ""),
                "body_json": json.dumps(action.get("body", {}), ensure_ascii=True)}
    except Exception:
        return {"status": "unavailable", "event_id": "", "state_json": "null", "path": "", "scope": "", "body_json": "{}"}


def json_value(value):
    return json.loads(value) if isinstance(value, str) else value


def status_request(event_id, status="unavailable"):
    return {"status": status, "path": "/inbox/status", "body_json": json.dumps({"id": identifier(event_id)})}


def snapshot_input(input_data):
    event_id = identifier(input_data.get("event_id"))
    output = status_request(event_id)
    try:
        if int(input_data.get("status_code", 0)) != 200:
            return output
        status = input_data.get("state_status")
        if status != "pending":
            return status_request(event_id, status if status in ("applied", "rejected", "missing") else "unavailable")
        event = json_value(input_data.get("event_json"))
        if not isinstance(event, dict) or event.get("event_id") != event_id:
            return output
        if event.get("event_type") in ("message.received", "deadline.elapsed", "review.requested"):
            return status_request(event_id, "needs_coordination")
        result = run_input({"event_json": event, "snapshot_json": input_data.get("snapshot_json")})
        if result["status"] == "ready":
            return {"status": "ready", "path": "/commit", "body_json": result["commit_json"]}
        reason = result.get("error", "invalid_input").split(":", 1)[0]
        if not re.fullmatch(r"[a-z_]{1,64}", reason):
            reason = "invalid_operation"
        status = "deferred" if result["status"] == "needs_snapshot" or reason == "entity_missing" else "rejected"
        return {"status": status, "path": "/inbox/settle",
                "body_json": json.dumps({"id": event_id, "status": status, "reason": reason})}
    except (ValueError, TypeError, KeyError, AttributeError):
        return output


def finish_input(input_data):
    event_id = identifier(input_data.get("event_id"))
    output = status_request(event_id)
    try:
        result = json_value(input_data.get("status_json"))
        if int(input_data.get("status_code", 0)) != 200 or result.get("event_id") != event_id:
            return output
        if result.get("status") == "pending" and result.get("event_type") not in ("message.received", "deadline.elapsed", "review.requested"):
            return {"status": "deferred", "path": "/inbox/settle",
                    "body_json": json.dumps({"id": event_id, "status": "deferred", "reason": "conflict"})}
        return status_request(event_id, result.get("status", "unavailable"))
    except (ValueError, TypeError, AttributeError):
        return output


def result_input(input_data):
    event_id = identifier(input_data.get("event_id"))
    status = "unavailable"
    try:
        result = json_value(input_data.get("status_json"))
        code = int(input_data.get("status_code", 0))
        if result.get("event_id", event_id) != event_id:
            return {"event_id": event_id, "status": status}
        if code == 404 and result.get("status") == "missing":
            status = "missing"
        elif code == 200 and result.get("status") in ("applied", "duplicate", "rejected", "deferred", "pending"):
            status = result["status"]
            if status == "pending" and result.get("event_type") in ("message.received", "deadline.elapsed", "review.requested"):
                status = "needs_coordination"
            elif status == "pending" and result.get("next_at"):
                status = "deferred"
    except (ValueError, TypeError, AttributeError):
        pass
    return {"event_id": event_id, "status": status}
