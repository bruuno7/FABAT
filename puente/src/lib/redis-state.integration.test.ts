import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { it } from "node:test";
import { RedisStateStore, upstashCommand } from "./redis-state.js";

it("Redis integration: concurrent CAS, replay and delivery leases", {
  skip: process.env.FABAT_RUN_REDIS_TESTS !== "1" && "Requires explicit opt-in and isolated test Redis credentials",
}, async (t) => {
  const url = process.env.FABAT_TEST_REDIS_URL;
  const token = process.env.FABAT_TEST_REDIS_TOKEN;
  assert.ok(url && token, "Configure FABAT_TEST_REDIS_URL and FABAT_TEST_REDIS_TOKEN outside git");
  const namespace = `test-${randomUUID()}`;
  const command = upstashCommand(url, token);
  const keys = new Set<string>();
  const tracked = async (args: (string | number)[]) => {
    if (args[0] === "EVAL") {
      for (const key of args.slice(3, 3 + Number(args[2]))) keys.add(String(key));
    }
    return command(args);
  };
  let now = 1000;
  const store = new RedisStateStore(tracked, namespace, () => now);
  const event = (id: string) => ({
    schema_version: 2, event_id: id, event_type: "assignment.accepted",
    occurred_at: "2026-09-19T14:00:00Z", received_at: "2026-09-19T14:00:01Z",
    channel: "telegram", actor_id: "worker-1", conversation_id: "conversation-1",
    correlation_id: "trace-1", assignment_id: "assignment-1", incident_id: "incident-1", payload: {},
  });
  const proposal = (eventId: string, version: number, messageId: string) => ({
    event_id: eventId,
    expected: { "incident/incident-1": version },
    writes: [{ entity: "incident/incident-1", value: { accepted_by: eventId } }],
    messages: [{ id: messageId, recipient_id: "reporter-1", channel: "telegram",
      incident_id: "incident-1", purpose: "status", text: "Aceptación confirmada (prueba aislada)." }],
  });
  try {
    await t.test("enqueues once and rejects conflicting reuse of an event ID", async () => {
      assert.equal((await store.enqueue(event("event-1"))).status, "accepted");
      assert.equal((await store.enqueue(event("event-1"))).status, "duplicate");
      assert.equal((await store.enqueue({ ...event("event-1"), actor_id: "another" })).status, "event_conflict");
      await store.enqueue(event("event-2"));
    });
    let winner = "";
    let messageId = "";
    await t.test("only one of two competing commits writes state and queues a message", async () => {
      const results = await Promise.all([
        store.commit(proposal("event-1", 0, "message-1")),
        store.commit(proposal("event-2", 0, "message-2")),
      ]);
      assert.deepEqual(results.map((r) => r.status).sort(), ["applied", "conflict"]);
      const index = results.findIndex((r) => r.status === "applied") + 1;
      winner = `event-${index}`;
      messageId = `message-${index}`;
      assert.equal((await store.snapshot(["incident/incident-1"]))["incident/incident-1"].version, 1);
      assert.deepEqual(await store.pending("outbox"), [messageId]);
    });
    await t.test("replaying a committed event cannot queue another notification", async () => {
      assert.equal((await store.commit(proposal(winner, 0, "another-message"))).status, "duplicate");
      assert.deepEqual(await store.pending("outbox"), [messageId]);
    });
    await t.test("one sender obtains the lease and expiry does not blindly resend", async () => {
      const results = await Promise.all([store.claim(messageId), store.claim(messageId)]);
      assert.deepEqual(results.map((r) => r.status).sort(), ["claimed", "sending"]);
      const lease = String(results.find((r) => r.status === "claimed")!.lease);
      now += 60001;
      assert.equal((await store.settle(messageId, lease, "succeeded", "provider-1")).status, "lease_expired");
      assert.equal((await store.claim(messageId)).status, "unknown");
      assert.deepEqual(await store.pending("outbox"), []);
    });
    await t.test("unregistered events cannot commit state", async () => {
      assert.equal((await store.commit(proposal("not-ingested", 1, "message-3"))).status, "event_missing");
      assert.equal((await store.snapshot(["incident/incident-1"]))["incident/incident-1"].version, 1);
    });
    await t.test("Python operations commit to real Redis and share task reservations across channels", async () => {
      const seed: Record<string, Record<string, unknown>> = {
        "actor/worker-1": { roles: ["medico"], preferred_channel: "telegram" },
        "actor/worker-2": { roles: ["medico"], preferred_channel: "phone" },
        "actor/reporter-1": { roles: [], preferred_channel: "telegram" },
        "incident/core-incident": { status: "open", reporter_id: "reporter-1", location: "barra 3", assignment_ids: ["core-a1", "core-a2"] },
        "assignment/core-a1": { status: "offered", actor_id: "worker-1", incident_id: "core-incident", task_id: "core-task", role: "medico" },
        "assignment/core-a2": { status: "offered", actor_id: "worker-2", incident_id: "core-incident", task_id: "core-task", role: "medico" },
      };
      const names = [...Object.keys(seed), "reservation/actor:worker-1", "reservation/actor:worker-2", "reservation/task:core-task"];
      const before = await store.snapshot(names);
      await store.enqueue({ ...event("core-seed"), event_type: "message.received" });
      assert.equal((await store.commit({
        event_id: "core-seed", expected: Object.fromEntries(Object.entries(before).map(([key, doc]) => [key, doc.version])),
        writes: Object.entries(seed).map(([entity, value]) => ({ entity, value })), messages: [],
      })).status, "applied");
      const snapshot = await store.snapshot(names);
      const applyPython = (input: unknown) => {
        const child = spawnSync("python3", ["-c",
          "import json,sys; from motor.happyrobot.sandbox.fa_operaciones import apply_event; d=json.load(sys.stdin); print(json.dumps(apply_event(d['event'], d['snapshot'])))",
        ], { cwd: fileURLToPath(new URL("../../../", import.meta.url)), input: JSON.stringify(input), encoding: "utf8" });
        assert.equal(child.status, 0, child.stderr);
        return JSON.parse(child.stdout);
      };
      const first = { ...event("core-accept-1"), actor_id: "worker-1", incident_id: "core-incident", assignment_id: "core-a1" };
      const second = { ...event("core-accept-2"), actor_id: "worker-2", incident_id: "core-incident", assignment_id: "core-a2", channel: "phone" };
      await store.enqueue(first);
      await store.enqueue(second);
      const outcomes = await Promise.all([
        store.commit(applyPython({ event: first, snapshot })), store.commit(applyPython({ event: second, snapshot })),
      ]);
      assert.deepEqual(outcomes.map((outcome) => outcome.status).sort(), ["applied", "conflict"]);
      const reserved = (await store.snapshot(["reservation/task:core-task"]))["reservation/task:core-task"].value;
      assert.ok(reserved?.assignment_id === "core-a1" || reserved?.assignment_id === "core-a2");
      assert.equal((await store.pending("outbox")).length, 1);
    });
  } finally {
    for (const key of keys) {
      assert.ok(key.startsWith(`fa:v2:{${namespace}}:`));
      await command(["EXPIRE", key, 3600]);
    }
  }
});
