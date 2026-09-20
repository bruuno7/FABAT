import assert from "node:assert/strict";
import http from "node:http";
import type { AddressInfo } from "node:net";
import { describe, it } from "node:test";
import express from "express";
import { telegramRouter } from "./router.js";
import { createStaffStore } from "./staff-store.js";
import { createIncidentStore } from "../hr/store.js";
import { loadEnv } from "../lib/hr-client.js";
import { RedisStateStore, StateStoreError } from "../lib/redis-state.js";

async function fixture(options: { namespace?: string; enabled?: boolean; fail?: boolean } = {}) {
  const env = loadEnv({ TELEGRAM_WEBHOOK_SECRET: "test-webhook", STAFF_PIN: "test-pin", HR_STATE_API_ENABLED: "1",
    HR_STATE_TELEGRAM_MODE: options.enabled === false ? "off" : "isolated", HR_STATE_TELEGRAM_USERS: "123",
    HR_STATE_NAMESPACE: options.namespace ?? "test-router" });
  const calls: unknown[][] = [];
  const store = new RedisStateStore(async (args) => {
    calls.push(args);
    if (options.fail) throw new StateStoreError("private details");
    return JSON.stringify({ status: "accepted" });
  }, env.stateApi!.namespace!);
  const app = express();
  app.use(express.json());
  app.use("/telegram", telegramRouter(env, createIncidentStore(), createStaffStore(), store));
  const listener = http.createServer(app);
  await new Promise<void>((resolve) => listener.listen(0, "127.0.0.1", resolve));
  return {
    calls,
    send: (body: unknown, secret = "test-webhook") => fetch(`http://127.0.0.1:${(listener.address() as AddressInfo).port}/telegram/webhook`, {
      method: "POST", headers: { "content-type": "application/json", "x-telegram-bot-api-secret-token": secret }, body: JSON.stringify(body),
    }),
    close: () => new Promise<void>((resolve) => listener.close(() => resolve())),
  };
}

const update = (id = 123, text = "Un aviso") => ({ update_id: 42,
  message: { message_id: 7, date: 1789830000, text, from: { id }, chat: { id, type: "private" } } });

describe("isolated v2 Telegram route", () => {
  it("acknowledges the provider only after durable ingestion, without sending or dispatching", async () => {
    const f = await fixture();
    try {
      const response = await f.send(update());
      assert.equal(response.status, 200);
      assert.deepEqual(await response.json(), { ok: true, route: "v2", status: "accepted", event_id: "tg-update-42" });
      assert.equal(f.calls.length, 1);
      assert.equal(f.calls[0][0], "EVAL");
    } finally { await f.close(); }
  });

  it("returns a retriable failure rather than losing an event when storage fails", async () => {
    const f = await fixture({ fail: true });
    try {
      const response = await f.send(update());
      assert.equal(response.status, 503);
      assert.deepEqual(await response.json(), { error: "state_unavailable" });
    } finally { await f.close(); }
  });

  it("does not enable the isolated route in a live namespace", async () => {
    const f = await fixture({ namespace: "live-unsupported" });
    try {
      assert.equal((await f.send(update())).status, 503);
      assert.equal(f.calls.length, 0);
    } finally { await f.close(); }
  });

  it("keeps unselected users and the disabled route on v1", async () => {
    for (const options of [{ enabled: false }, {}]) {
      const f = await fixture(options);
      try {
        const response = await f.send(update(options.enabled === false ? 123 : 999, "/ping"));
        assert.equal(response.status, 200);
        assert.equal((await response.json() as { command: string }).command, "ping");
        assert.equal(f.calls.length, 0);
      } finally { await f.close(); }
    }
  });

  it("requires webhook authentication before any persistence and never saves a bad PIN", async () => {
    const f = await fixture();
    try {
      assert.equal((await f.send(update(), "wrong")).status, 401);
      const response = await f.send(update(123, "/rol medico wrong-pin"));
      assert.equal(response.status, 422);
      assert.equal(f.calls.length, 0);
    } finally { await f.close(); }
  });
});
