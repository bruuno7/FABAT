import asyncio
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from dotenv import dotenv_values


async def probe_operations(session, entry, manifest):
    root = Path(__file__).resolve().parents[2]
    values = dotenv_values(root / "puente" / ".env.test")
    base = manifest["preview_url"]
    parsed = urlparse(base)
    if parsed.scheme != "https" or not re.fullmatch(r"fabat-[a-z0-9]+-fabat1\.vercel\.app", parsed.netloc) or parsed.path not in ("", "/") or parsed.query:
        raise ValueError("isolated_preview_required")
    if not manifest["namespace"].startswith("test-") or manifest["environment"] != "development":
        raise ValueError("isolated_environment_required")
    prefix = "native-" + uuid4().hex
    key = lambda name: prefix + "-" + name
    scopes = {name: values["HR_STATE_" + name.upper() + "_SECRET"] for name in ("ingress", "read", "commit", "delivery")}
    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
        async def post(path, body, scope):
            response = await client.post(base + "/hr/state" + path, json=body, headers={
                "x-hr-state-secret": scopes[scope], "x-vercel-protection-bypass": values["VERCEL_AUTOMATION_BYPASS_SECRET"],
            })
            if response.status_code not in (200, 409):
                raise RuntimeError("preview_request_failed")
            return response.json()

        def event(name, actor="worker-1", channel="telegram"):
            return {"schema_version": 2, "event_id": key(name), "event_type": "assignment.accepted", "actor_id": key(actor),
                    "occurred_at": "2026-09-19T20:00:00Z", "received_at": "2026-09-19T20:00:01Z", "channel": channel,
                    "conversation_id": key("conversation"), "correlation_id": key("trace"), "incident_id": key("incident"),
                    "assignment_id": key("a1" if actor == "worker-1" else "a2"), "payload": {}}

        docs = {
            "actor/" + key("worker-1"): {"roles": ["medico"], "preferred_channel": "telegram"},
            "actor/" + key("worker-2"): {"roles": ["medico"], "preferred_channel": "phone"},
            "actor/" + key("reporter"): {"roles": [], "preferred_channel": "telegram"},
            "incident/" + key("incident"): {"status": "open", "reporter_id": key("reporter"), "assignment_ids": [key("a1"), key("a2")]},
            "assignment/" + key("a1"): {"status": "offered", "actor_id": key("worker-1"), "incident_id": key("incident"), "task_id": key("task"), "role": "medico"},
            "assignment/" + key("a2"): {"status": "offered", "actor_id": key("worker-2"), "incident_id": key("incident"), "task_id": key("task"), "role": "medico"},
        }
        seed = {**event("seed"), "event_type": "message.received"}
        await post("/inbox", seed, "ingress")
        saved = await post("/commit", {"event_id": seed["event_id"], "expected": {name: 0 for name in docs},
            "writes": [{"entity": name, "value": value} for name, value in docs.items()], "messages": []}, "commit")
        if saved.get("status") != "applied":
            raise RuntimeError("seed_failed")
        events = [event("accept-1"), event("accept-2", "worker-2", "phone")]
        for item in events:
            await post("/inbox", item, "ingress")

        async def trigger(item):
            result = await session.call_tool("trigger_run", {"workflow_id": entry["id"], "environment": "development",
                "payload": json.dumps({"event_id": item["event_id"]}), "wait": True})
            output = "\n".join(part.text for part in result.content if part.type == "text")
            ids = re.findall(r"(?:run_id|Run ID)\W+([0-9a-f-]{36})", output, re.I)
            print(json.dumps({"event_id": item["event_id"], "run_ids": ids, "tool_error": bool(result.isError)}), flush=True)
            if result.isError:
                safe = output
                for value in values.values():
                    if value:
                        safe = safe.replace(value, "[redacted]")
                safe = re.sub(r"(?i)bearer\s+[^\s\"}]+", "Bearer [redacted]", safe)
                print(json.dumps({"native_error": safe[:2000]}), flush=True)
                raise RuntimeError("native_run_failed")

        await asyncio.gather(*(trigger(item) for item in events))
        records = [await post("/inbox/event", {"id": item["event_id"]}, "read") for item in events]
        states = sorted(record["status"] for record in records)
        if states != ["applied", "rejected"]:
            print(json.dumps({"native_event_states": states}), flush=True)
            raise RuntimeError("native_concurrency_not_verified")
        winner = events[next(index for index, record in enumerate(records) if record["status"] == "applied")]
        before = await post("/snapshot", {"entities": list(docs)}, "read")
        await trigger(winner)
        after = await post("/snapshot", {"entities": list(docs)}, "read")
        if before != after:
            raise RuntimeError("duplicate_changed_state")
        message_id = "delivery-" + hashlib.sha256((winner["event_id"] + ":0").encode()).hexdigest()[:32]
        delivery = await post("/outbox/deliver", {"id": message_id}, "delivery")
        if delivery.get("status") != "simulated":
            raise RuntimeError("sink_delivery_not_verified")
        print(json.dumps({"native_workflow": entry["id"], "concurrent_events": 2, "applied": 1, "rejected": 1,
                          "duplicate_preserved_state": True, "delivery": "simulated", "real_messages": 0, "real_calls": 0}), flush=True)
