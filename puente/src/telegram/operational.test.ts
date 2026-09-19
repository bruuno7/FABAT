import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import type { AddressInfo } from "node:net";
import { afterEach, describe, it, mock, type TestContext } from "node:test";
import { createApp } from "../app.js";
import { createIncidentStore } from "../hr/store.js";
import { FETCH_TIMEOUT_MS, loadEnv, type Env } from "../lib/hr-client.js";
import { handleTelegramUpdate } from "./handle-update.js";
import { operationalReadiness } from "./operational.js";
import { createStaffStore } from "./staff-store.js";

const request = globalThis.fetch;
const settings = {
  MANDO_OPERATIONAL: "1",
  MANDO_BACKEND_URL: "https://mando.invalid/festival/",
  MANDO_BRIDGE_SECRET: "bridge-test-only",
  TELEGRAM_WEBHOOK_SECRET: "telegram-test-only",
  TELEGRAM_MODE: "webhook",
  TELEGRAM_BOT_TOKEN: "bot-test-only",
  HR_HOOK_TG: "https://hr.invalid/intake",
  HR_HOOK_TG_RESPONSE: "https://hr.invalid/response",
  HR_HOOK_TG_ROSTER: "https://hr.invalid/roster",
  HR_SECRET: "hr-test-only",
  ALLOW_DEMO_INJECT: "1",
};
const update = {
  update_id: 123,
  message: {
    message_id: 42,
    date: 1789840000,
    from: { id: 777, first_name: "Prueba" },
    chat: { id: -100123, type: "supergroup" },
    caption: "Caída en escenario 2",
    caption_entities: [{ type: "bold", offset: 0, length: 5 }],
    photo: [{ file_id: "test-photo", file_unique_id: "test-id", width: 640, height: 480 }],
    location: { latitude: 40.4, longitude: -3.7, horizontal_accuracy: 4 },
    reply_to_message: {
      message_id: 41,
      from: { id: 888, is_bot: true },
      chat: { id: -100123, type: "supergroup" },
      text: "¿Dónde estás?",
    },
    message_thread_id: 19,
  },
};
const callback = {
  update_id: 124,
  callback_query: {
    id: "callback-test",
    from: { id: 999, first_name: "Personal" },
    data: "accept|asg-test|3",
    chat_instance: "chat-instance-test",
    message: { ...update.message, from: { id: 888, is_bot: true } },
  },
};

function acceptance(duplicate = false): Response {
  return Response.json({ ok: true, duplicate, revision: 7 });
}

function deferred() {
  let resolve = () => {};
  const promise = new Promise<void>((done) => { resolve = done; });
  return { promise, resolve };
}

function transport(reply: (init?: RequestInit) => Response | Promise<Response> = () => acceptance()) {
  const calls: { url: string; init?: RequestInit }[] = [];
  mock.method(globalThis, "fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(input), init });
    return reply(init);
  });
  return calls;
}

async function server(t: TestContext, env: Env = loadEnv(settings)) {
  const store = createIncidentStore();
  const staff = createStaffStore();
  const listener = createApp(env, store, staff).listen(0, "127.0.0.1");
  await new Promise<void>((resolve) => listener.once("listening", resolve));
  t.after(() => new Promise<void>((resolve, reject) => {
    listener.close((error) => error ? reject(error) : resolve());
    listener.closeAllConnections();
  }));
  const base = `http://127.0.0.1:${(listener.address() as AddressInfo).port}`;
  return {
    store,
    staff,
    get: (path: string) => request(base + path),
    post: (body: unknown = update, path = "/telegram/webhook", headers: Record<string, string> = {}) =>
      request(base + path, {
        method: "POST",
        headers: { "content-type": "application/json", "x-telegram-bot-api-secret-token": settings.TELEGRAM_WEBHOOK_SECRET, ...headers },
        body: JSON.stringify(body),
      }),
    raw: (body: string, headers: Record<string, string> = {}) => request(base + "/telegram/webhook", {
      method: "POST",
      headers: { "content-type": "application/json", "x-telegram-bot-api-secret-token": settings.TELEGRAM_WEBHOOK_SECRET, ...headers },
      body,
    }),
  };
}

afterEach(() => mock.restoreAll());

describe("operational Telegram ingress", () => {
  it("forwards original identities, photo, caption, location and reply context with only bridge auth", async (t) => {
    const calls = transport();
    const s = await server(t);
    const response = await s.post(update, "/api/telegram/webhook");
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), { ok: true, duplicate: false, revision: 7 });
    assert.equal(calls.length, 1);
    assert.equal(calls[0].url, "https://mando.invalid/festival/api/operations/telegram");
    assert.deepEqual(JSON.parse(String(calls[0].init?.body)), update);
    assert.deepEqual(calls[0].init?.headers, {
      "content-type": "application/json",
      "X-Mando-Bridge-Token": settings.MANDO_BRIDGE_SECRET,
    });
    assert.equal(calls[0].init?.redirect, "manual");
    assert.ok(calls[0].init?.signal instanceof AbortSignal);
    assert.deepEqual(s.store.list(), []);
    assert.deepEqual(s.staff.list(), []);
  });

  it("forwards every duplicate callback with its sender; backend owns deduplication", async (t) => {
    let attempts = 0;
    const calls = transport(() => acceptance(attempts++ > 0));
    const s = await server(t);
    for (let i = 0; i < 10; i++) {
      const response = await s.post(callback);
      assert.equal(response.status, 200);
      assert.deepEqual(await response.json(), { ok: true, duplicate: i > 0, revision: 7 });
    }
    assert.equal(calls.length, 10);
    for (const call of calls) assert.deepEqual(JSON.parse(String(call.init?.body)), callback);
  });

  it("does not derive sender identity from group chat or reply author when from is absent", async (t) => {
    const calls = transport(() => Response.json({ ok: false }, { status: 422 }));
    mock.method(console, "warn", () => {});
    const s = await server(t);
    const missingSender = { update_id: 125, message: { message_id: 1, chat: { id: -100123 }, text: "test" } };
    assert.deepEqual(await (await s.post(missingSender)).json(), { ok: false, rejected: true, status: 422 });
    assert.deepEqual(JSON.parse(String(calls[0].init?.body)), missingSender);
  });

  it("waits for durable response body before ACK; headers alone are insufficient", async (t) => {
    const backendReached = deferred();
    const durableCommit = deferred();
    transport(() => {
      backendReached.resolve();
      return new Response(new ReadableStream<Uint8Array>({
        async start(controller) {
          await durableCommit.promise;
          controller.enqueue(new TextEncoder().encode(JSON.stringify({ ok: true, duplicate: false, revision: 8 })));
          controller.close();
        },
      }), { status: 200 });
    });
    const s = await server(t);
    let replied = false;
    const pending = s.post().then((response) => { replied = true; return response; });
    await backendReached.promise;
    await new Promise<void>((resolve) => setImmediate(resolve));
    assert.equal(replied, false);
    durableCommit.resolve();
    assert.deepEqual(await (await pending).json(), { ok: true, duplicate: false, revision: 8 });
  });

  it("never uses legacy intake, role, response, dispatch hooks, local stores or Telegram sends", async (t) => {
    const calls = transport();
    const s = await server(t);
    for (const text of ["/start", "/ping", "/rol medico test-pin", "/estado", "/baja", "Persona caída", "/fin"]) {
      assert.equal((await s.post({ ...update, message: { ...update.message, text } })).status, 200);
    }
    assert.equal((await s.post(callback)).status, 200);
    assert.equal(calls.length, 8);
    assert.ok(calls.every((call) => call.url === "https://mando.invalid/festival/api/operations/telegram"));
    assert.deepEqual(s.store.list(), []);
    assert.deepEqual(s.staff.list(), []);
    for (const path of ["/hr/events", "/hr/tg/dispatch", "/hr/tg/staff-response", "/hr/tg-reply", "/demo/public-report"]) {
      assert.equal((await s.post({ event: "telegram_send", chat_id: "1", text: "test" }, path)).status, 409);
    }
    assert.equal(calls.length, 8);
    assert.equal((await s.post({}, "/hr/state/inbox")).status, 503);
    await assert.rejects(() => handleTelegramUpdate(loadEnv(settings), callback), /authenticated webhook/);
    assert.equal(calls.length, 8);
  });

  it("refuses to start the poller before making a provider request", () => {
    const result = spawnSync(process.execPath, ["--import", "tsx", "src/telegram/poll.ts"], {
      cwd: process.cwd(),
      env: { PATH: process.env.PATH, MANDO_OPERATIONAL: "1", TELEGRAM_BOT_TOKEN: "test-only" },
      encoding: "utf8",
      timeout: 10000,
    });
    assert.equal(result.status, 1);
    assert.match(result.stderr, /polling is disabled/);
    assert.doesNotMatch(result.stdout, /getUpdates/);
  });

  it("preserves legacy webhook and health behavior unless the flag equals 1", async (t) => {
    for (const flag of [undefined, "0", "true"]) {
      const calls = transport();
      const s = await server(t, loadEnv({ ...settings, MANDO_OPERATIONAL: flag }));
      const response = await s.post({ update_id: 1, message: { message_id: 1, chat: { id: 12, type: "private" }, text: "/ping" } });
      assert.equal(response.status, 200);
      assert.match(await response.text(), /pong/);
      assert.equal(calls.length, 1);
      assert.match(calls[0].url, /api\.telegram\.org.*sendMessage/);
      const health = await s.get("/health");
      assert.equal(health.status, 200);
      assert.equal("operational" in await health.json(), false);
      mock.restoreAll();
    }
  });
});

describe("operational downstream failures", () => {
  it("records bounded terminal 400/401/403/409/422 rejections without exposing backend text", async (t) => {
    const logs = mock.method(console, "warn", () => {});
    const s = await server(t);
    for (const status of [400, 401, 403, 409, 422]) {
      const calls = transport(() => new Response("sensitive-provider-token".repeat(100000), { status }));
      const response = await s.post();
      assert.equal(response.status, 200);
      assert.deepEqual(await response.json(), { ok: false, rejected: true, status });
      assert.equal(calls.length, 1);
      assert.deepEqual(logs.mock.calls.at(-1)?.arguments, ["[telegram] operational rejection", { update_id: 123, status }]);
    }
  });

  it("returns retryable 503 for transient errors, redirects and unknown HTTP failures", async (t) => {
    const s = await server(t);
    for (const status of [202, 204, 301, 302, 307, 308, 404, 408, 425, 429, 500, 502, 503, 504]) {
      const calls = transport(() => new Response(null, { status, headers: { location: "https://other.invalid/secret" } }));
      const response = await s.post();
      assert.equal(response.status, 503, `backend ${status}`);
      assert.equal(response.headers.get("retry-after"), "5");
      assert.deepEqual(await response.json(), { ok: false, error: "backend_unavailable" });
      assert.equal(calls.length, 1);
    }
  });

  it("returns 503 for network errors and allows the same update to retry", async (t) => {
    let fail = true;
    const calls = transport(() => {
      if (fail) throw new Error("private URL and token must not escape");
      return acceptance(true);
    });
    const s = await server(t);
    const failed = await s.post();
    assert.equal(failed.status, 503);
    assert.deepEqual(await failed.json(), { ok: false, error: "backend_unavailable" });
    fail = false;
    assert.deepEqual(await (await s.post()).json(), { ok: true, duplicate: true, revision: 7 });
    assert.equal(calls.length, 2);
    assert.equal(calls[0].init?.body, calls[1].init?.body);
  });

  it("aborts the transport at the bounded timeout and does not acknowledge", async (t) => {
    const backendReached = deferred();
    transport((init) => new Promise<Response>((_resolve, reject) => {
      assert.ok(init?.signal);
      init.signal.addEventListener("abort", () => reject(new Error("aborted")), { once: true });
      backendReached.resolve();
    }));
    const s = await server(t);
    // El reloj simulado solo controla el deadline del puente.
    t.mock.timers.enable({ apis: ["setTimeout"] });
    const pending = s.post();
    await backendReached.promise;
    t.mock.timers.tick(FETCH_TIMEOUT_MS);
    const response = await pending;
    assert.equal(response.status, 503);
    assert.deepEqual(await response.json(), { ok: false, error: "backend_unavailable" });
  });

  it("requires complete valid durable acceptance and strips non-contract response fields", async (t) => {
    const s = await server(t);
    for (const body of ["not JSON", "{}", '{"ok":false}', '{"ok":true}', '{"ok":true,"duplicate":false}', '{"ok":true,"duplicate":false,"revision":-1}', '{"ok":true,"duplicate":false,"revision":"7"}', '{"ok":true,"duplicate":false,"revision":1.5}', "x".repeat(8193)]) {
      transport(() => new Response(body, { status: 200 }));
      const response = await s.post();
      assert.equal(response.status, 503);
      assert.deepEqual(await response.json(), { ok: false, error: "backend_unavailable" });
    }
    transport(() => Response.json({ ok: true, duplicate: false, revision: 0, token: "hidden" }, { status: 201 }));
    const response = await s.post();
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), { ok: true, duplicate: false, revision: 0 });
  });

  it("keeps the timeout active while the backend acceptance body is incomplete", async (t) => {
    const bodyStarted = deferred();
    transport((init) => new Response(new ReadableStream<Uint8Array>({
      start(controller) {
        assert.ok(init?.signal);
        controller.enqueue(new TextEncoder().encode('{"ok":true,'));
        init.signal.addEventListener("abort", () => controller.error(new Error("aborted")), { once: true });
        bodyStarted.resolve();
      },
    })));
    const s = await server(t);
    t.mock.timers.enable({ apis: ["setTimeout"] });
    const pending = s.post();
    await bodyStarted.promise;
    t.mock.timers.tick(FETCH_TIMEOUT_MS);
    const response = await pending;
    assert.equal(response.status, 503);
    assert.deepEqual(await response.json(), { ok: false, error: "backend_unavailable" });
  });
});

describe("operational ingress configuration and bounds", () => {
  it("requires both independent secrets and backend configuration even in local mode", async (t) => {
    const calls = transport();
    for (const field of ["TELEGRAM_WEBHOOK_SECRET", "MANDO_BRIDGE_SECRET", "MANDO_BACKEND_URL"]) {
      const s = await server(t, loadEnv({ ...settings, [field]: "", REQUIRE_SECRETS: "0" }));
      const response = await s.post();
      assert.equal(response.status, 503);
      assert.deepEqual(await response.json(), { ok: false, error: "bridge_not_configured" });
      const health = await s.get("/health");
      assert.equal(health.status, 503);
      assert.deepEqual((await health.json()).operational, { ready: false, missing: [field], invalid: [] });
    }
    assert.equal(calls.length, 0);
  });

  it("rejects missing/wrong Telegram authentication before parsing a large or malformed body", async (t) => {
    const calls = transport();
    const s = await server(t);
    for (const secret of ["", "wrong", settings.MANDO_BRIDGE_SECRET, settings.HR_SECRET]) {
      const response = await s.raw("{".repeat(1024 * 1024 + 1), { "x-telegram-bot-api-secret-token": secret });
      assert.equal(response.status, 401);
      assert.deepEqual(await response.json(), { ok: false, error: "invalid_secret" });
    }
    assert.equal(calls.length, 0);
  });

  it("rejects invalid URL, header configuration and poll mode without leaking values", async (t) => {
    const calls = transport();
    const cases = [
      { MANDO_BACKEND_URL: "ftp://mando.invalid" },
      { MANDO_BACKEND_URL: "http://mando.invalid" },
      { MANDO_BACKEND_URL: "https://user:private@mando.invalid" },
      { MANDO_BACKEND_URL: "https://mando.invalid/?token=private" },
      { MANDO_BACKEND_URL: "https://mando.invalid/#private" },
      { MANDO_BACKEND_URL: "https://mando.invalid/hr/events/" },
      { MANDO_BACKEND_URL: "https://mando.invalid/api/operations/telegram" },
      { MANDO_BACKEND_URL: "//mando.invalid" },
      { MANDO_BACKEND_URL: "https:\\\\mando.invalid" },
      { MANDO_BACKEND_URL: "https://mando.invalid/\nprivate" },
      { MANDO_BRIDGE_SECRET: "private\r\ninjected-header:test" },
      { MANDO_BRIDGE_SECRET: "x".repeat(513) },
      { TELEGRAM_WEBHOOK_SECRET: "private invalid" },
      { TELEGRAM_MODE: "poll" },
    ];
    for (const values of cases) {
      const s = await server(t, loadEnv({ ...settings, ...values }));
      assert.equal((await s.post()).status, 503);
      const health = await s.get("/health");
      assert.equal(health.status, 503);
      const body = await health.text();
      assert.doesNotMatch(body, /private|bridge-test-only|telegram-test-only/);
      assert.deepEqual(JSON.parse(body).operational.invalid, Object.keys(values));
    }
    assert.equal(calls.length, 0);
  });

  it("constructs an exact endpoint for root, base paths and local development HTTP", async (t) => {
    for (const [base, expected] of [
      ["https://mando.invalid///", "https://mando.invalid/api/operations/telegram"],
      ["https://mando.invalid/prefix///", "https://mando.invalid/prefix/api/operations/telegram"],
      ["http://127.0.0.1:8000", "http://127.0.0.1:8000/api/operations/telegram"],
      ["http://[::1]:8000/", "http://[::1]:8000/api/operations/telegram"],
    ]) {
      const calls = transport();
      const s = await server(t, loadEnv({ ...settings, MANDO_BACKEND_URL: base, TELEGRAM_BOT_TOKEN: "" }));
      assert.equal((await s.post()).status, 200);
      assert.equal(calls[0].url, expected);
      const health = await s.get("/health");
      assert.equal(health.status, 200);
      assert.deepEqual((await health.json()).operational, { ready: true, missing: [], invalid: [] });
    }
    assert.equal(operationalReadiness(loadEnv(settings)).ready, true);
  });

  it("rejects malformed, oversized, unsupported or invalid updates without forwarding", async (t) => {
    const calls = transport();
    const s = await server(t);
    for (const body of [null, [], {}, { update_id: "1" }, { update_id: -1 }, { update_id: 1.5 }, { update_id: Number.MAX_SAFE_INTEGER + 1 }]) {
      assert.equal((await s.post(body)).status, 400);
    }
    const invalid = await s.raw('{"secret":"test-private"');
    assert.equal(invalid.status, 400);
    assert.deepEqual(await invalid.json(), { ok: false, error: "invalid_json" });
    const deep = await s.raw(`{"update_id":1,"context":${"[".repeat(20000)}0${"]".repeat(20000)}}`);
    assert.equal(deep.status, 400);
    assert.deepEqual(await deep.json(), { ok: false, error: "invalid_update" });
    const large = await s.post({ update_id: 1, message: { text: "é".repeat(1024 * 1024) } });
    assert.equal(large.status, 413);
    assert.deepEqual(await large.json(), { ok: false, error: "payload_too_large" });
    assert.equal((await s.raw("text", { "content-type": "text/plain" })).status, 415);
    assert.equal((await s.raw("{}", { "content-encoding": "gzip" })).status, 415);
    assert.equal(calls.length, 0);
  });
});
