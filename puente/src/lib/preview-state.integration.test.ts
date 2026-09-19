import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { it } from "node:test";
import type { CanonicalEvent } from "./event-contract.js";

it("isolated Preview API with real Redis and the Python consumer", {
  skip: process.env.FABAT_RUN_PREVIEW_TESTS !== "1" && "Requires explicit opt-in and a protected isolated Preview",
}, async (t) => {
  const base = new URL(process.env.FABAT_TEST_PREVIEW_URL!);
  assert.equal(base.protocol, "https:");
  assert.ok(base.hostname.endsWith(".vercel.app") && !base.username && !base.password && !base.search && !base.hash && base.pathname === "/");
  const scopes = { ingress: process.env.HR_STATE_INGRESS_SECRET, read: process.env.HR_STATE_READ_SECRET,
    commit: process.env.HR_STATE_COMMIT_SECRET, delivery: process.env.HR_STATE_DELIVERY_SECRET };
  assert.ok(Object.values(scopes).every(Boolean) && process.env.VERCEL_AUTOMATION_BYPASS_SECRET, "Configure private test credentials outside git");
  const prefix = `probe-${randomUUID()}`;
  const id = (suffix: string) => `${prefix}-${suffix}`;
  const post = async (path: string, body: unknown, scope: keyof typeof scopes) => {
    const response = await fetch(new URL(`/hr/state${path}`, base), {
      method: "POST", headers: { "content-type": "application/json", "x-hr-state-secret": scopes[scope]!,
        "x-vercel-protection-bypass": process.env.VERCEL_AUTOMATION_BYPASS_SECRET! },
      body: JSON.stringify(body), redirect: "error", signal: AbortSignal.timeout(15000),
    });
    assert.ok([200, 401, 404, 409].includes(response.status), `Unexpected API status ${response.status} for ${path}`);
    return { code: response.status, data: await response.json() as Record<string, any> };
  };
  const event = (suffix: string, actor = "worker-1", channel = "telegram"): CanonicalEvent => ({
    schema_version: 2, event_id: id(suffix), event_type: "assignment.accepted", actor_id: id(actor),
    channel: channel as "telegram" | "phone", conversation_id: id("conversation"), correlation_id: id("trace"),
    occurred_at: "2026-09-19T20:00:00Z", received_at: "2026-09-19T20:00:01Z",
    incident_id: id("incident"), assignment_id: id(actor === "worker-1" ? "a1" : "a2"), payload: {},
  });
  const python = (name: "apply_event" | "consumer_input", input: unknown) => {
    const source = name === "apply_event"
      ? "import json,sys; from motor.happyrobot.sandbox.fa_operaciones import apply_event; d=json.load(sys.stdin); print(json.dumps(apply_event(d['event'],d['snapshot'])))"
      : "import json,sys; from motor.happyrobot.sandbox.fa_consumidor import consumer_input; print(json.dumps(consumer_input(json.load(sys.stdin))))";
    const child = spawnSync("python3", ["-B", "-c", source], { cwd: fileURLToPath(new URL("../../../", import.meta.url)), input: JSON.stringify(input), encoding: "utf8" });
    assert.equal(child.status, 0, "Python operation failed");
    return JSON.parse(child.stdout) as Record<string, any>;
  };
  const consume = async (eventId: string) => {
    let data: Record<string, unknown> = { event_id: eventId };
    for (let step = 0; step < 110; step++) {
      const output = python("consumer_input", data);
      if (output.status !== "request") return output;
      const result = await post(output.path, JSON.parse(output.body_json), output.scope);
      data = { event_id: eventId, state_json: output.state_json, response_json: result.data, status_code: result.code };
    }
    throw new Error("Consumer exceeded its request limit");
  };
  const docs = {
    [`actor/${id("worker-1")}`]: { roles: ["medico"], preferred_channel: "telegram" },
    [`actor/${id("worker-2")}`]: { roles: ["medico"], preferred_channel: "phone" },
    [`actor/${id("reporter")}`]: { roles: [], permissions: [], preferred_channel: "telegram" },
    [`incident/${id("incident")}`]: { status: "open", reporter_id: id("reporter"), assignment_ids: [id("a1"), id("a2")], empty_lists: [[], {}] },
    [`assignment/${id("a1")}`]: { status: "offered", actor_id: id("worker-1"), incident_id: id("incident"), task_id: id("task"), role: "medico" },
    [`assignment/${id("a2")}`]: { status: "offered", actor_id: id("worker-2"), incident_id: id("incident"), task_id: id("task"), role: "medico" },
  };
  const names = [...Object.keys(docs), `reservation/actor:${id("worker-1")}`, `reservation/actor:${id("worker-2")}`, `reservation/task:${id("task")}`];
  let winner = "";
  let loser = "";
  let deliveryId = "";
  await t.test("separates read and write permissions", async () => {
    assert.equal((await post("/commit", {}, "read")).code, 401);
    assert.equal((await post("/outbox/claim", { id: id("message") }, "commit")).code, 401);
  });
  await t.test("deduplicates ingress and rejects changed reuse of its ID", async () => {
    const seed = { ...event("seed"), event_type: "message.received", payload: { values: [] } };
    assert.equal((await post("/inbox", seed, "ingress")).data.status, "accepted");
    assert.equal((await post("/inbox", seed, "ingress")).data.status, "duplicate");
    assert.equal((await post("/inbox", { ...seed, payload: { changed: true } }, "ingress")).code, 409);
    assert.deepEqual((await post("/inbox/event", { id: id("seed") }, "read")).data.event.payload.values, []);
  });
  await t.test("writes typed empty arrays atomically through the deployed Lua", async () => {
    const snapshot = (await post("/snapshot", { entities: names }, "read")).data;
    const seed = { event_id: id("seed"), expected: Object.fromEntries(Object.entries(snapshot).map(([key, value]) => [key, value.version])),
      writes: Object.entries(docs).map(([entity, value]) => ({ entity, value })), messages: [] };
    assert.equal((await post("/commit", seed, "commit")).data.status, "applied");
    const after = (await post("/snapshot", { entities: names }, "read")).data;
    assert.deepEqual(after[`actor/${id("reporter")}`].value.roles, []);
    assert.deepEqual(after[`incident/${id("incident")}`].value.empty_lists, [[], {}]);
  });
  await t.test("Telegram and phone proposals compete for one task with one winner", async () => {
    const first = event("accept-1");
    const second = event("accept-2", "worker-2", "phone");
    await post("/inbox", first, "ingress");
    await post("/inbox", second, "ingress");
    const snapshot = (await post("/snapshot", { entities: names }, "read")).data;
    const proposals = [first, second].map((e) => python("apply_event", { event: e, snapshot }));
    const results = await Promise.all(proposals.map((proposal) => post("/commit", proposal, "commit")));
    assert.deepEqual(results.map((r) => r.data.status).sort(), ["applied", "conflict"]);
    const winningIndex = results.findIndex((r) => r.data.status === "applied");
    winner = [first, second][winningIndex].event_id;
    loser = [first, second][1 - winningIndex].event_id;
    deliveryId = proposals[winningIndex].messages[0].id;
  });
  await t.test("the consumer reconciles duplicates and quarantines the losing acceptance", async () => {
    assert.equal((await consume(winner)).status, "duplicate");
    assert.equal((await consume(loser)).status, "rejected");
    assert.equal((await post("/inbox/event", { id: loser }, "read")).data.status, "rejected");
  });
  await t.test("delivery uses the configured sink and cannot resend the consumed lease", async () => {
    assert.equal((await post("/outbox/deliver", { id: deliveryId }, "delivery")).data.status, "simulated");
    assert.equal((await post("/outbox/deliver", { id: deliveryId }, "delivery")).data.status, "simulated");
  });
  await t.test("deferred events wait without multiplying attempts on concurrent retries", async () => {
    await post("/inbox", event("deferred"), "ingress");
    const body = { id: id("deferred"), status: "deferred", reason: "conflict" };
    assert.equal((await post("/inbox/settle", body, "commit")).data.status, "deferred");
    assert.equal((await post("/inbox/settle", body, "commit")).data.status, "deferred");
    const record = (await post("/inbox/event", { id: body.id }, "read")).data;
    assert.equal(record.attempts, 1);
    await post("/inbox/settle", { ...body, status: "rejected", reason: "test_complete" }, "commit");
  });
});
