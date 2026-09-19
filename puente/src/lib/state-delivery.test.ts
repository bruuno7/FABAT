import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { deliver, recoverDeliveries, type DeliveryStore } from "./state-delivery.js";
import type { JsonObject, PendingMessage } from "./event-contract.js";

function fixture() {
  const message: PendingMessage = { id: "m1", recipient_id: "worker", incident_id: "incident-1", channel: "telegram", purpose: "status", text: "Estado confirmado" };
  const docs: Record<string, JsonObject> = {
    "actor/worker": { channels: { telegram: { verified: true, chat_id: "123" } } },
    "incident/incident-1": { status: "open" },
    "assignment/a1": { actor_id: "worker", incident_id: "incident-1", status: "offered" },
    "question/q1": { recipient_id: "worker", incident_id: "incident-1", status: "pending" },
  };
  const settled: unknown[][] = [];
  let claimed = false;
  const store: DeliveryStore = {
    async claim() {
      if (claimed) return { status: "sending" };
      claimed = true;
      return { status: "claimed", lease: "11111111-1111-4111-8111-111111111111", message };
    },
    async settle(...args) { settled.push(args); return { status: args[2] === "retry" ? "pending" : args[2] }; },
    async snapshot(names) { return Object.fromEntries(names.map((name) => [name, { version: docs[name] ? 1 : 0, value: docs[name] ?? null }])); },
    async pending() { return ["m1"]; },
  };
  const config = { mode: "live" as const, telegramToken: "test-token", allowedTelegramChats: ["123"] };
  return { store, message, docs, settled, config };
}

describe("durable v2 communications", () => {
  it("is a simulation by default and never contacts any provider", async () => {
    const f = fixture();
    const result = await deliver(f.store, "m1", { mode: "sink" }, async () => { throw new Error("must not send"); });
    assert.equal(result.status, "simulated");
    assert.equal(f.settled[0][2], "simulated");
  });

  it("requires an allowlisted verified destination, never a destination from the request", async () => {
    const f = fixture();
    f.config.allowedTelegramChats = [];
    let requests = 0;
    const result = await deliver(f.store, "m1", f.config, async () => { requests++; return new Response(); });
    assert.equal(result.status, "failed");
    assert.equal(requests, 0);
  });

  it("checks Telegram's body instead of treating HTTP 200 as delivered", async () => {
    const f = fixture();
    const result = await deliver(f.store, "m1", f.config, async () => new Response(JSON.stringify({ ok: false, description: "private details" })));
    assert.equal(result.status, "failed");
    assert.equal(f.settled[0][2], "failed");
    assert.ok(!JSON.stringify(result).includes("private details"));
  });

  it("records provider message identity only after confirmed delivery", async () => {
    const f = fixture();
    const result = await deliver(f.store, "m1", f.config, async (_url, init) => {
      assert.equal(init?.redirect, "error");
      assert.deepEqual(JSON.parse(String(init?.body)), { chat_id: "123", text: "Estado confirmado" });
      return new Response(JSON.stringify({ ok: true, result: { message_id: 42 } }));
    });
    assert.equal(result.status, "succeeded");
    assert.equal(f.settled[0][3], "42");
  });

  it("does not blindly repeat a send after an ambiguous timeout", async () => {
    const f = fixture();
    let requests = 0;
    const fetcher: typeof fetch = async () => { requests++; throw new Error("token must stay private"); };
    assert.equal((await deliver(f.store, "m1", f.config, fetcher)).status, "unknown");
    assert.equal((await deliver(f.store, "m1", f.config, fetcher)).status, "sending");
    assert.equal(requests, 1);
  });

  it("does not send an offer cancelled after it was queued", async () => {
    const f = fixture();
    f.message.purpose = "offer";
    f.message.assignment_id = "a1";
    f.docs["assignment/a1"].status = "cancelled";
    let requests = 0;
    assert.equal((await deliver(f.store, "m1", f.config, async () => { requests++; return new Response(); })).status, "failed");
    assert.equal(requests, 0);
  });

  it("binds question deliveries to their real recipient and incident", async () => {
    const f = fixture();
    f.message.purpose = "question";
    f.message.question_id = "q1";
    f.docs["question/q1"].recipient_id = "other";
    assert.equal((await deliver(f.store, "m1", f.config, async () => { throw new Error("must not send"); })).status, "failed");
  });

  it("does not interpret non-JSON success or upstream 5xx as confirmed failure", async () => {
    for (const response of [new Response("bad gateway", { status: 502 }), new Response("not-json")]) {
      const f = fixture();
      assert.equal((await deliver(f.store, "m1", f.config, async () => response)).status, "unknown");
    }
  });

  it("reschedules an explicit provider rejection rather than retrying an ambiguous delivery", async () => {
    const f = fixture();
    const result = await deliver(f.store, "m1", f.config, async () => new Response(JSON.stringify({
      ok: false, error_code: 429, parameters: { retry_after: 12 },
    }), { status: 429 }));
    assert.equal(result.status, "deferred");
    assert.equal(f.settled[0][2], "retry");
    assert.equal(f.settled[0][4], 12000);
  });

  it("recovers a bounded batch without repeating leases or leaking errors", async () => {
    const f = fixture();
    const result = await recoverDeliveries(f.store, { mode: "sink" }, 1);
    assert.equal(result.processed, 1);
    assert.equal(result.results[0].status, "simulated");
    await assert.rejects(() => recoverDeliveries(f.store, { mode: "sink" }, 99));
  });
});
