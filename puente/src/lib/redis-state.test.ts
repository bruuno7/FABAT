import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { RedisStateStore, StateStoreError, upstashCommand } from "./redis-state.js";
import { COMMIT_STATE, ENQUEUE_EVENT, withTestExpiry } from "./redis-scripts.js";

const event = {
  schema_version: 2, event_id: "event-1", event_type: "message.received",
  occurred_at: "2026-09-19T14:00:00Z", received_at: "2026-09-19T14:00:01Z",
  channel: "telegram", actor_id: "actor-1", conversation_id: "conversation-1",
  correlation_id: "trace-1", payload: { text: "En la barra 3" },
};

describe("state transport boundaries", () => {
  it("uses fixed scripts and environment-isolated keys", async () => {
    const calls: unknown[][] = [];
    const store = new RedisStateStore(async (args) => {
      calls.push(args);
      return JSON.stringify({ status: "accepted" });
    }, "test-contract");
    await store.enqueue(event);
    assert.equal(calls[0][0], "EVAL");
    assert.equal(calls[0][1], withTestExpiry(ENQUEUE_EVENT));
    assert.equal(calls[0][2], 2);
    assert.equal(calls[0][3], "fa:v2:{test-contract}:inbox:event-1");
    assert.throws(() => new RedisStateStore(async () => null, "../fa:seats"));
  });

  it("expires only isolated test namespaces, never live or development state", async () => {
    for (const namespace of ["test-expiry", "dev-preserve", "live-preserve"]) {
      const calls: unknown[][] = [];
      const store = new RedisStateStore(async (args) => { calls.push(args); return JSON.stringify({ status: "accepted" }); }, namespace);
      await store.enqueue(event);
      assert.equal(calls[0][1], namespace.startsWith("test-") ? withTestExpiry(ENQUEUE_EVENT) : ENQUEUE_EVENT);
      assert.equal(String(calls[0][1]).includes("redis.call('EXPIRE'"), namespace.startsWith("test-"));
    }
  });

  it("compares the same event independently of retry receipt timestamp and object key order", async () => {
    const calls: unknown[][] = [];
    const store = new RedisStateStore(async (args) => {
      calls.push(args);
      return JSON.stringify({ status: "accepted" });
    }, "test-contract");
    await store.enqueue(event);
    await store.enqueue({ ...event, received_at: "2026-09-19T14:00:02Z", payload: { text: "En la barra 3" } });
    assert.equal(calls[0][6], calls[1][6]);
  });

  it("builds one atomic state/event/outbox commit, not a pipeline", async () => {
    const calls: unknown[][] = [];
    const store = new RedisStateStore(async (args) => {
      calls.push(args);
      return JSON.stringify({ status: "applied", versions: { "incident/inc-1": 2 } });
    }, "test-contract", () => 1000);
    await store.commit({
      event_id: "event-1", expected: { "incident/inc-1": 1 },
      writes: [{ entity: "incident/inc-1", value: { status: "open" } }],
      messages: [{ id: "message-1", recipient_id: "actor-1", channel: "telegram", incident_id: "inc-1", purpose: "status", text: "Recibido" }],
    });
    assert.equal(calls.length, 1);
    assert.equal(calls[0][1], withTestExpiry(COMMIT_STATE));
    const keys = calls[0].slice(3, 9);
    assert.deepEqual(keys, [
      "fa:v2:{test-contract}:inbox:event-1", "fa:v2:{test-contract}:inbox-pending",
      "fa:v2:{test-contract}:outbox-pending", "fa:v2:{test-contract}:events",
      "fa:v2:{test-contract}:incident/inc-1", "fa:v2:{test-contract}:outbox:message-1",
    ]);
    const payload = JSON.parse(String(calls[0][9]));
    assert.equal(payload.reads[0].index, 5);
    assert.equal(payload.messages[0].index, 6);
  });

  it("reports missing versions and corrupt stored values without guessing a snapshot", async () => {
    const store = new RedisStateStore(async () => [null, '{"version":3,"value":{"status":"open"}}'], "test-contract");
    assert.deepEqual(await store.snapshot(["actor/actor-1", "incident/inc-1"]), {
      "actor/actor-1": { version: 0, value: null },
      "incident/inc-1": { version: 3, value: { status: "open" } },
    });
    const corrupt = new RedisStateStore(async () => ["not-json"], "test-contract");
    await assert.rejects(() => corrupt.snapshot(["actor/actor-1"]), StateStoreError);
  });

  it("uses one-time lease tokens, server clock and bounded lease duration", async () => {
    const calls: unknown[][] = [];
    const store = new RedisStateStore(async (args) => {
      calls.push(args);
      return JSON.stringify({ status: "claimed" });
    }, "test-contract", () => 1000);
    await store.claim("message-1");
    await store.claim("message-1");
    assert.notEqual(calls[0][6], calls[1][6]);
    assert.equal(calls[0][5], 1000);
    assert.equal(calls[0][7], 60000);
    await assert.rejects(() => store.settle("message-1", "bad", "succeeded", "1"));
  });

  it("validates every operation before calling Redis", async () => {
    let calls = 0;
    const store = new RedisStateStore(async () => { calls++; return null; }, "test-contract");
    await assert.rejects(() => store.snapshot(["secret/token"]));
    await assert.rejects(() => store.commit({ event_id: "x", expected: {}, writes: [{ entity: "actor/a", value: {} }], messages: [] }));
    await assert.rejects(() => store.pending("outbox", 10000));
    assert.equal(calls, 0);
  });

  it("preserves empty arrays in stored documents instead of Lua cjson turning them into objects", async () => {
    let payload: { writes: { value_json: string }[] } = { writes: [] };
    const store = new RedisStateStore(async (args) => {
      payload = JSON.parse(String(args[args.length - 2]));
      return JSON.stringify({ status: "applied" });
    }, "test-contract");
    await store.commit({ event_id: "e1", expected: { "incident/i1": 0 },
      writes: [{ entity: "incident/i1", value: { assignment_ids: [], tasks: {} } }], messages: [] });
    assert.equal(payload.writes[0].value_json, '{"assignment_ids":[],"tasks":{}}');
    const reader = new RedisStateStore(async () => JSON.stringify({
      status: "pending", event: { ...event, payload: { values: {} } },
      event_json: JSON.stringify({ ...event, payload: { values: [] } }),
    }), "test-contract");
    assert.deepEqual((await reader.event("event-1"))?.event, { ...event, payload: { values: [] } });
  });

  it("atomically registers verified Telegram identity and a bounded role grant with ingress", async () => {
    const calls: unknown[][] = [];
    const store = new RedisStateStore(async (args) => {
      calls.push(args);
      return JSON.stringify({ status: "accepted" });
    }, "test-contract", () => 1000);
    const claimed = { ...event, event_id: "tg-update-42", channel: "telegram", actor_id: "tg-123",
      conversation_id: "tg-123", event_type: "actor.role_claimed", payload: { role: "medico", grant_id: "grant:tg-update-42" } };
    await store.ingestTelegram(claimed, "123");
    assert.equal(calls.length, 1);
    assert.equal(calls[0][0], "EVAL");
    assert.equal(calls[0][2], 4);
    assert.deepEqual(calls[0].slice(3, 7), ["fa:v2:{test-contract}:inbox:tg-update-42", "fa:v2:{test-contract}:inbox-pending",
      "fa:v2:{test-contract}:actor/tg-123", "fa:v2:{test-contract}:approval/grant:tg-update-42"]);
    const actor = JSON.parse(String(calls[0][10]));
    assert.deepEqual(actor.roles, []);
    assert.deepEqual(actor.permissions, []);
    assert.equal(actor.channels.telegram.chat_id, "123");
    const grant = JSON.parse(String(calls[0][11]));
    assert.equal(grant.actor_id, "tg-123");
    assert.equal(grant.expires_at, new Date(301000).toISOString());
    await assert.rejects(() => store.ingestTelegram({ ...claimed, actor_id: "coordinator" }, "123"));
    await assert.rejects(() => store.ingestTelegram({ ...claimed, payload: { role: "admin", grant_id: "grant:tg-update-42" } }, "123"));
    assert.equal(calls.length, 1);
  });

  it("deduplicates Telegram callbacks whose provider has no timestamp", async () => {
    const calls: unknown[][] = [];
    const store = new RedisStateStore(async (args) => { calls.push(args); return JSON.stringify({ status: "accepted" }); }, "test-contract");
    const callback = { ...event, payload: { timestamp_source: "received", callback_query_id: "c1" } };
    await store.enqueue(callback);
    await store.enqueue({ ...callback, occurred_at: "2026-09-19T14:00:10Z", received_at: "2026-09-19T14:00:10Z" });
    assert.equal(calls[0][6], calls[1][6]);
  });

  it("quarantines invalid events and schedules bounded retries with server time", async () => {
    const calls: unknown[][] = [];
    const store = new RedisStateStore(async (args) => {
      calls.push(args);
      return JSON.stringify({ status: "deferred" });
    }, "test-contract", () => 1000);
    await store.settleEvent("event-1", "deferred", "conflict");
    assert.equal(calls[0][0], "EVAL");
    assert.equal(calls[0][3], "fa:v2:{test-contract}:inbox:event-1");
    assert.deepEqual(calls[0].slice(-3), ["deferred", "conflict", 1000]);
    await assert.rejects(() => store.settleEvent("event-1", "rejected", "sensitive error contents"));
    assert.equal(calls.length, 1);
  });

  it("binds successful Telegram receipts to the recipient and updates the index in the settlement script", async () => {
    const calls: (string | number)[][] = [];
    const message = { id: "m1", recipient_id: "tg-123", channel: "telegram", purpose: "conversation", text: "Hola" };
    const store = new RedisStateStore(async (args) => {
      calls.push(args);
      if (args[0] === "GET") return JSON.stringify({ status: "sending", message });
      return JSON.stringify({ status: "succeeded" });
    }, "test-receipt");
    await store.settle("m1", "11111111-1111-4111-8111-111111111111", "succeeded", "51");
    assert.equal(calls[1][2], 3);
    assert.match(String(calls[1][5]), /^fa:v2:\{test-receipt\}:receipt:[a-f0-9]{64}$/);
    const reads: (string | number)[][] = [];
    const reader = new RedisStateStore(async (args) => { reads.push(args); return null; }, "test-receipt");
    await reader.messageForReply("tg-123", "51");
    await reader.messageForReply("tg-999", "51");
    assert.equal(reads[0][1], calls[1][5]);
    assert.notEqual(reads[0][1], reads[1][1]);
  });

  it("rejects untrusted URLs and never includes secrets or provider errors in thrown errors", async () => {
    assert.throws(() => upstashCommand("http://example.invalid", "token"), StateStoreError);
    assert.throws(() => upstashCommand("https://upstash.io.evil.invalid", "token"), StateStoreError);
    assert.throws(() => upstashCommand("https://user:password@db.upstash.io", "token"), StateStoreError);
    const command = upstashCommand("https://test.upstash.io", "sensitive-test-value", async () => {
      throw new Error("sensitive-test-value");
    });
    await assert.rejects(() => command(["MGET", "x"]), (error: Error) => error.message === "redis_unavailable");
    const apiError = upstashCommand("https://test.upstash.io", "token", async () => new Response(JSON.stringify({ error: "private-details" })));
    await assert.rejects(() => apiError(["MGET", "x"]), (error: Error) => error.message === "redis_unavailable");
  });
});
