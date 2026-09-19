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
      assert.equal(calls, 0);
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
