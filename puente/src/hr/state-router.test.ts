import assert from "node:assert/strict";
import http from "node:http";
import type { AddressInfo } from "node:net";
import { describe, it } from "node:test";
import express from "express";
import { stateRouter } from "./state-router.js";
import { RedisStateStore, StateStoreError } from "../lib/redis-state.js";
import type { StateApiConfig } from "../lib/state-env.js";

const settings: StateApiConfig = {
  enabled: true, namespace: "test-router",
  ingressSecret: "ingress-test-only", readSecret: "read-test-only",
  commitSecret: "commit-test-only", deliverySecret: "delivery-test-only",
};

async function server(config: StateApiConfig, store?: RedisStateStore) {
  const app = express();
  app.use(express.json());
  app.use("/hr/state", stateRouter(config, store));
  const listener = http.createServer(app);
  await new Promise<void>((resolve) => listener.listen(0, "127.0.0.1", resolve));
  const base = `http://127.0.0.1:${(listener.address() as AddressInfo).port}/hr/state`;
  return {
    request: (path: string, body: unknown, secret = "") => fetch(base + path, {
      method: "POST", headers: { "content-type": "application/json", "x-hr-state-secret": secret },
      body: JSON.stringify(body),
    }),
    close: () => new Promise<void>((resolve, reject) => listener.close((error) => error ? reject(error) : resolve())),
  };
}

async function deliveryStore(ids: string[]) {
  const settled: string[] = [];
  let pendingCalls = 0;
  const store = {
    async pending(queue: string, limit: number) {
      pendingCalls += 1;
      assert.equal(queue, "outbox");
      return ids.slice(0, limit);
    },
    async claim(id: string) {
      return {
        status: "claimed", lease: "11111111-1111-4111-8111-111111111111",
        message: { id, recipient_id: "worker", incident_id: "incident-1", channel: "telegram", purpose: "status", text: "Estado" },
      };
    },
    async settle(...args: unknown[]) {
      settled.push(String(args[2]));
      return { status: String(args[2]) };
    },
    async snapshot(names: string[]) {
      return Object.fromEntries(names.map((name) => [name, { version: 1, value: name.startsWith("actor/")
        ? { channels: { telegram: { verified: true, chat_id: "123" } } } : { status: "open" } }]));
    },
  };
  return { store: store as unknown as RedisStateStore, settled, pendingCalls: () => pendingCalls };
}

describe("private state API", () => {
  it("is disabled by default and fails closed without credentials", async () => {
    for (const config of [{ enabled: false }, { enabled: true }]) {
      const s = await server(config);
      try {
        assert.equal((await s.request("/snapshot", { entities: ["actor/a"] })).status, 503);
      } finally { await s.close(); }
    }
  });

  it("rejects a reader attempting a write and makes no Redis request", async () => {
    let calls = 0;
    const store = new RedisStateStore(async () => { calls++; return null; }, "test-router");
    const s = await server(settings, store);
    try {
      assert.equal((await s.request("/commit", {}, settings.readSecret)).status, 401);
      assert.equal((await s.request("/outbox/claim", { id: "m1" }, settings.commitSecret)).status, 401);
      assert.equal((await s.request("/inbox", {}, settings.deliverySecret)).status, 401);
      assert.equal((await s.request("/inbox/settle", { id: "e1", status: "rejected", reason: "invalid_operation" }, settings.readSecret)).status, 401);
      assert.equal(calls, 0);
    } finally { await s.close(); }
  });

  it("recovers the outbox in one bounded tick behind the delivery secret", async () => {
    const f = await deliveryStore(["m1", "m2", "m3"]);
    const s = await server(settings, f.store);
    try {
      assert.equal((await s.request("/outbox/recover", {}, settings.commitSecret)).status, 401);
      assert.equal((await s.request("/outbox/recover", {}, settings.ingressSecret)).status, 401);
      const response = await s.request("/outbox/recover", {}, settings.deliverySecret);
      assert.equal(response.status, 200);
      assert.deepEqual(await response.json(), {
        processed: 3,
        results: [
          { id: "m1", status: "simulated" },
          { id: "m2", status: "simulated" },
          { id: "m3", status: "simulated" },
        ],
      });
      const bounded = await s.request("/outbox/recover", { limit: 2 }, settings.deliverySecret);
      assert.equal(bounded.status, 200);
      assert.deepEqual((await bounded.json() as { processed: number }).processed, 2);
    } finally { await s.close(); }
  });

  it("refuses an unbounded recovery tick without touching the queue", async () => {
    const f = await deliveryStore(["m1"]);
    const s = await server(settings, f.store);
    try {
      for (const limit of [0, 17, -1, 1.5, "8", null, []]) {
        assert.equal((await s.request("/outbox/recover", { limit }, settings.deliverySecret)).status, 422);
      }
      assert.equal(f.pendingCalls(), 0);
    } finally { await s.close(); }
  });

  it("validates keys before Redis and serves typed snapshots to readers", async () => {
    let calls = 0;
    const store = new RedisStateStore(async () => { calls++; return [null]; }, "test-router");
    const s = await server(settings, store);
    try {
      assert.equal((await s.request("/snapshot", { entities: ["secret/token"] }, settings.readSecret)).status, 422);
      assert.equal(calls, 0);
      const response = await s.request("/snapshot", { entities: ["actor/a"] }, settings.readSecret);
      assert.equal(response.status, 200);
      assert.deepEqual(await response.json(), { "actor/a": { version: 0, value: null } });
    } finally { await s.close(); }
  });

  it("reports version conflicts and does not leak storage errors or credentials", async () => {
    let fail = false;
    const store = new RedisStateStore(async () => {
      if (fail) throw new StateStoreError("sensitive-details");
      return JSON.stringify({ status: "conflict", entity: "actor/a" });
    }, "test-router");
    const s = await server(settings, store);
    try {
      const commit = { event_id: "e1", expected: { "actor/a": 1 }, writes: [{ entity: "actor/a", value: {} }], messages: [] };
      assert.equal((await s.request("/commit", commit, settings.commitSecret)).status, 409);
      fail = true;
      const response = await s.request("/commit", commit, settings.commitSecret);
      assert.equal(response.status, 503);
      assert.deepEqual(await response.json(), { error: "state_unavailable" });
    } finally { await s.close(); }
  });
});
