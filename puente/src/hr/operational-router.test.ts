import assert from "node:assert/strict";
import type { AddressInfo } from "node:net";
import { afterEach, describe, it, mock, type TestContext } from "node:test";
import { createApp } from "../app.js";
import { createIncidentStore } from "./store.js";
import { loadEnv, type Env } from "../lib/hr-client.js";
import { createStaffStore } from "../telegram/staff-store.js";

const request = globalThis.fetch;
const settings = {
  MANDO_OPERATIONAL: "1",
  MANDO_BACKEND_URL: "https://mando.invalid/festival/",
  MANDO_BRIDGE_SECRET: "bridge-test-only",
  TELEGRAM_WEBHOOK_SECRET: "telegram-test-only",
  TELEGRAM_MODE: "webhook",
  TELEGRAM_BOT_TOKEN: "bot-test-only",
  HR_SECRET: "hr-test-only",
};

function transport(reply: () => Response | Promise<Response> = () => Response.json({ ok: true })) {
  const calls: { url: string; init?: RequestInit }[] = [];
  mock.method(globalThis, "fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(input), init });
    return reply();
  });
  return calls;
}

async function server(t: TestContext, env: Env = loadEnv(settings)) {
  const listener = createApp(env, createIncidentStore(), createStaffStore()).listen(0, "127.0.0.1");
  await new Promise<void>((resolve) => listener.once("listening", resolve));
  t.after(() => new Promise<void>((resolve, reject) => {
    listener.close((error) => error ? reject(error) : resolve());
    listener.closeAllConnections();
  }));
  const base = `http://127.0.0.1:${(listener.address() as AddressInfo).port}`;
  return {
    post: (body: unknown, headers: Record<string, string> = { "x-hr-secret": settings.HR_SECRET }) =>
      request(`${base}/hr/events`, {
        method: "POST",
        headers: { "content-type": "application/json", ...headers },
        body: JSON.stringify(body),
      }),
  };
}

afterEach(() => mock.restoreAll());

describe("operational HappyRobot router", () => {
  it("mirrors HappyRobot decisions to MANDO with the bridge token", async (t) => {
    const calls = transport();
    const s = await server(t);
    const response = await s.post({
      event: "telegram_send",
      chat_id: "123",
      text: "¿Puedes acudir?",
      mirror: [
        {
          type: "tg_incident",
          id: "tg-123-1",
          texto: "Persona caída",
          tipo: "medica",
          zona: "front_pit",
          gravedad: "emergencia",
        },
        { type: "tg_assignment", incident_id: "tg-123-1", rol: "medico", estado: "pending", alias: "Marta", intento: 1 },
      ],
    });
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), {
      ok: true,
      mirror: { ok: true, skipped: false, status: 200 },
      telegram: { ok: true, skipped: false, status: 200 },
      revision: 0,
    });
    const mirror = calls.find((call) => call.url.endsWith("/api/operations/happyrobot"));
    assert.ok(mirror);
    assert.equal(mirror!.init?.headers && (mirror!.init!.headers as Record<string, string>)["X-Mando-Bridge-Token"], "bridge-test-only");
    const payload = JSON.parse(String(mirror!.init?.body));
    assert.equal(payload.events.length, 2);
    assert.equal(payload.events[0].type, "tg_incident");
    const tg = calls.find((call) => call.url.includes("api.telegram.org"));
    assert.ok(tg);
    assert.match(tg!.url, /sendMessage$/);
  });

  it("sends the citizen reply carried by agent_reply", async (t) => {
    const calls = transport();
    const s = await server(t);
    const response = await s.post({
      event: "agent_reply",
      correlation_id: "tg-123-1",
      chat_id: "123",
      reply_text: "Aviso registrado.",
      report: { channel: "telegram", text: "Persona caída", zone_hint: "front_pit", source: "telegram_bridge", lang: "es" },
    });
    assert.equal(response.status, 200);
    const tg = calls.find((call) => call.url.includes("api.telegram.org"));
    assert.ok(tg);
    assert.match(tg!.url, /sendMessage$/);
    assert.equal(JSON.parse(String(tg!.init?.body)).chat_id, "123");
  });

  it("rejects without the shared secret and never invents work", async (t) => {
    const calls = transport();
    const s = await server(t);
    assert.equal((await s.post({ mirror: [{ type: "tg_staff", disponibles: 1, total: 2 }] }, {})).status, 401);
    assert.equal((await s.post({})).status, 400);
    assert.equal((await s.post({ mirror: [] })).status, 400);
    assert.equal((await s.post({ mirror: [{ type: "tg_staff" }] })).status, 200);
    assert.equal(calls.filter((call) => call.url.includes("api.telegram.org")).length, 0);
  });

  it("surfaces MANDO mirror failures instead of pretending success", async (t) => {
    transport(() => new Response("nope", { status: 500 }));
    const s = await server(t);
    const response = await s.post({ type: "tg_staff", disponibles: 1, total: 2 });
    assert.equal(response.status, 502);
    assert.deepEqual(await response.json(), {
      ok: false,
      mirror: { ok: false, skipped: false, status: 500 },
    });
  });
});
