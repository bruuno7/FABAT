import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { RedisStateStore, StateStoreError, upstashCommand } from "./redis-state.js";
import { COMMIT_STATE, ENQUEUE_EVENT } from "./redis-scripts.js";

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
    assert.equal(calls[0][1], ENQUEUE_EVENT);
    assert.equal(calls[0][2], 2);
    assert.equal(calls[0][3], "fa:v2:{test-contract}:inbox:event-1");
    assert.throws(() => new RedisStateStore(async () => null, "../fa:seats"));
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
    assert.equal(calls[0][1], COMMIT_STATE);
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
