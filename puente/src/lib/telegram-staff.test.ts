import assert from "node:assert/strict";
import http from "node:http";
import type { AddressInfo } from "node:net";
import { describe, it, mock } from "node:test";
import {
  isStaffResponse,
  normalizeReplyMarkup,
  parseTelegramOutbound,
} from "./contract.js";
import {
  parseCallbackData,
  parseCommandLine,
  parseStaffRole,
  telegramUpdateToStaffResponse,
} from "./telegram-map.js";
import {
  executeTelegramOutbound,
  loadEnv,
  telegramSendMessage,
} from "./hr-client.js";
import { handleTelegramUpdate } from "../telegram/handle-update.js";
import { createIncidentStore } from "../hr/store.js";
import { createStaffStore } from "../telegram/staff-store.js";
import { createApp } from "../app.js";

function mockFetch() {
  const calls: { url: string; body: string }[] = [];
  const realFetch = globalThis.fetch;
  mock.method(
    globalThis,
    "fetch",
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("127.0.0.1") || url.includes("localhost")) {
        return realFetch(input, init);
      }
      calls.push({ url, body: String(init?.body ?? "") });
      return new Response(JSON.stringify({ ok: true }), { status: 200 });
    },
  );
  return calls;
}

describe("staff roles and callback map", () => {
  it("parses role aliases without leaking accents", () => {
    assert.equal(parseStaffRole("Médico"), "medico");
    assert.equal(parseStaffRole("entradas"), "staff_entradas");
    assert.equal(parseStaffRole("policía"), "policia");
    assert.equal(parseStaffRole("jurado"), null);
  });

  it("parses /rol args without treating the PIN as a command", () => {
    const line = parseCommandLine("/rol@MyBot medico 1234");
    assert.deepEqual(line, { command: "rol", args: ["medico", "1234"] });
  });

  it("parses callback_data kind:id and kind|id|corr", () => {
    assert.deepEqual(parseCallbackData("acc:asg-1"), {
      kind: "acc",
      assignment_id: "asg-1",
      correlation_id: undefined,
    });
    assert.deepEqual(parseCallbackData("dec|asg-9|tg-1-2"), {
      kind: "dec",
      assignment_id: "asg-9",
      correlation_id: "tg-1-2",
    });
  });

  it("maps callback_query to staff_response", () => {
    const mapped = telegramUpdateToStaffResponse(
      {
        update_id: 11,
        callback_query: {
          id: "cq-1",
          data: "acc:asg-1",
          from: { id: 77, first_name: "Ana" },
          message: {
            message_id: 88,
            chat: { id: 77, type: "private" },
          },
        },
      },
      { role: "medico" },
    );
    assert.ok(mapped);
    assert.equal(isStaffResponse(mapped), true);
    assert.equal(mapped.event, "staff_response");
    assert.equal(mapped.kind, "acc");
    assert.equal(mapped.assignment_id, "asg-1");
    assert.equal(mapped.chat_id, "77");
    assert.equal(mapped.message_id, 88);
    assert.equal(mapped.reporter.role, "medico");
    assert.equal(mapped.reporter.perfil_color, "personal");
  });
});

describe("staff commands", () => {
  it("claims a role in local without PIN", async () => {
    const calls = mockFetch();
    const env = loadEnv({ TELEGRAM_BOT_TOKEN: "test-token" });
    const staff = createStaffStore();
    const result = await handleTelegramUpdate(
      env,
      {
        update_id: 1,
        message: {
          message_id: 1,
          text: "/rol medico",
          chat: { id: 10, type: "private" },
          from: { id: 10, first_name: "Ana" },
        },
      },
      createIncidentStore(),
      staff,
    );
    assert.equal(result.command, "rol");
    assert.match(result.replies[0] ?? "", /Médico/);
    assert.equal(staff.getByChat("10")?.role, "medico");
    assert.equal(calls.length, 1);
    mock.restoreAll();
  });

  it("rejects an unknown role", async () => {
    mockFetch();
    const env = loadEnv({ TELEGRAM_BOT_TOKEN: "test-token" });
    const result = await handleTelegramUpdate(env, {
      update_id: 1,
      message: {
        message_id: 1,
        text: "/rol jurado",
        chat: { id: 10, type: "private" },
      },
    });
    assert.match(result.replies[0] ?? "", /no existe/);
    mock.restoreAll();
  });

  it("requires a matching PIN when STAFF_PIN is set", async () => {
    mockFetch();
    const env = loadEnv({
      TELEGRAM_BOT_TOKEN: "test-token",
      STAFF_PIN: "9999",
    });
    const staff = createStaffStore();
    const wrong = await handleTelegramUpdate(
      env,
      {
        update_id: 1,
        message: {
          message_id: 1,
          text: "/rol medico 0000",
          chat: { id: 10, type: "private" },
        },
      },
      createIncidentStore(),
      staff,
    );
    assert.match(wrong.replies[0] ?? "", /PIN incorrecto/);
    assert.equal(staff.getByChat("10"), undefined);

    const right = await handleTelegramUpdate(
      env,
      {
        update_id: 2,
        message: {
          message_id: 2,
          text: "/rol medico 9999",
          chat: { id: 10, type: "private" },
          from: { id: 10, first_name: "Ana" },
        },
      },
      createIncidentStore(),
      staff,
    );
    assert.match(right.replies[0] ?? "", /Médico/);
    assert.equal(staff.getByChat("10")?.role, "medico");
    mock.restoreAll();
  });

  it("rejects /rol in production when STAFF_PIN is missing", async () => {
    mockFetch();
    const env = loadEnv({
      TELEGRAM_BOT_TOKEN: "test-token",
      REQUIRE_SECRETS: "1",
    });
    const result = await handleTelegramUpdate(env, {
      update_id: 1,
      message: {
        message_id: 1,
        text: "/rol medico",
        chat: { id: 10, type: "private" },
      },
    });
    assert.match(result.replies[0] ?? "", /PIN de personal no está configurado/);
    mock.restoreAll();
  });

  it("rejects a role already taken by another chat", async () => {
    mockFetch();
    const env = loadEnv({ TELEGRAM_BOT_TOKEN: "test-token" });
    const staff = createStaffStore();
    await handleTelegramUpdate(
      env,
      {
        update_id: 1,
        message: {
          message_id: 1,
          text: "/rol bomberos",
          chat: { id: 1, type: "private" },
          from: { id: 1, first_name: "Luis" },
        },
      },
      createIncidentStore(),
      staff,
    );
    const result = await handleTelegramUpdate(
      env,
      {
        update_id: 2,
        message: {
          message_id: 2,
          text: "/rol bomberos",
          chat: { id: 2, type: "private" },
          from: { id: 2, first_name: "Eva" },
        },
      },
      createIncidentStore(),
      staff,
    );
    assert.match(result.replies[0] ?? "", /ya lo tiene Luis/);
    mock.restoreAll();
  });

  it("/estado and /baja round-trip", async () => {
    mockFetch();
    const env = loadEnv({ TELEGRAM_BOT_TOKEN: "test-token" });
    const staff = createStaffStore();
    await handleTelegramUpdate(
      env,
      {
        update_id: 1,
        message: {
          message_id: 1,
          text: "/rol organizador",
          chat: { id: 3, type: "private" },
          from: { id: 3, first_name: "Nuria" },
        },
      },
      createIncidentStore(),
      staff,
    );
    const estado = await handleTelegramUpdate(
      env,
      {
        update_id: 2,
        message: {
          message_id: 2,
          text: "/estado",
          chat: { id: 3, type: "private" },
        },
      },
      createIncidentStore(),
      staff,
    );
    assert.match(estado.replies[0] ?? "", /Organizador — Nuria/);
    const baja = await handleTelegramUpdate(
      env,
      {
        update_id: 3,
        message: {
          message_id: 3,
          text: "/baja",
          chat: { id: 3, type: "private" },
        },
      },
      createIncidentStore(),
      staff,
    );
    assert.match(baja.replies[0] ?? "", /Dejas el puesto Organizador/);
    assert.equal(staff.getByChat("3"), undefined);
    mock.restoreAll();
  });

  it("persists /rol to MANDO so HR can read chat_id after a cold start", async () => {
    const calls = mockFetch();
    const env = loadEnv({
      TELEGRAM_BOT_TOKEN: "test-token",
      MANDO_BACKEND_URL: "https://mando.invalid",
      HR_SECRET: "s",
    });
    const staff = createStaffStore();
    const result = await handleTelegramUpdate(
      env,
      {
        update_id: 1,
        message: {
          message_id: 1,
          text: "/rol medico",
          chat: { id: 77, type: "private" },
          from: { id: 77, first_name: "Marta" },
        },
      },
      createIncidentStore(),
      staff,
    );
    assert.match(result.replies[0] ?? "", /Puesto Médico tomado/);
    const roster = calls.find((c) => c.url.includes("/hr/tg/roster") && c.body.includes("claim"));
    assert.ok(roster);
    const payload = JSON.parse(roster.body) as {
      action: string;
      role: string;
      chat_id: string;
      alias: string;
    };
    assert.equal(payload.action, "claim");
    assert.equal(payload.role, "medico");
    assert.equal(payload.chat_id, "77");
    assert.equal(payload.alias, "Marta");
    mock.restoreAll();
  });
});

describe("callback_query routing", () => {
  it("answers the callback and skips HR when the response hook is missing", async () => {
    const calls = mockFetch();
    const env = loadEnv({ TELEGRAM_BOT_TOKEN: "test-token" });
    const result = await handleTelegramUpdate(env, {
      update_id: 4,
      callback_query: {
        id: "cq-9",
        data: "acc:asg-1",
        from: { id: 44, first_name: "Ana" },
        message: {
          message_id: 12,
          chat: { id: 44, type: "private" },
        },
      },
    });
    assert.equal(result.kind, "acc");
    assert.equal(result.hr?.skipped, true);
    assert.match(calls[0]?.url ?? "", /answerCallbackQuery/);
    assert.match(calls[1]?.url ?? "", /sendMessage/);
    assert.equal(
      calls.some((c) => c.url.includes("example")),
      false,
    );
    mock.restoreAll();
  });

  it("forwards staff_response to HR_HOOK_TG_RESPONSE, not HR_HOOK_TG", async () => {
    const calls = mockFetch();
    const env = loadEnv({
      TELEGRAM_BOT_TOKEN: "test-token",
      HR_HOOK_TG: "https://example.invalid/entrada",
      HR_HOOK_TG_RESPONSE: "https://example.invalid/respuesta",
    });
    const result = await handleTelegramUpdate(env, {
      update_id: 5,
      callback_query: {
        id: "cq-2",
        data: "vet|asg-8|tg-1-2",
        from: { id: 8, first_name: "Org" },
        message: {
          message_id: 3,
          chat: { id: 8, type: "private" },
        },
      },
    });
    assert.equal(result.kind, "vet");
    assert.equal(result.hr?.skipped, false);
    assert.equal(result.hr?.ok, true);
    const hook = calls.find((c) => c.url.includes("/respuesta"));
    assert.ok(hook);
    const payload = JSON.parse(hook.body) as { event: string; kind: string };
    assert.equal(payload.event, "staff_response");
    assert.equal(payload.kind, "vet");
    assert.equal(
      calls.some((c) => c.url.includes("/entrada")),
      false,
    );
    mock.restoreAll();
  });

  it("still sends public reports to HR_HOOK_TG", async () => {
    const calls = mockFetch();
    const env = loadEnv({
      TELEGRAM_BOT_TOKEN: "test-token",
      HR_HOOK_TG: "https://example.invalid/entrada",
      HR_HOOK_TG_RESPONSE: "https://example.invalid/respuesta",
    });
    await handleTelegramUpdate(env, {
      update_id: 6,
      message: {
        message_id: 1,
        text: "caído en escenario",
        chat: { id: 9, type: "private" },
        from: { id: 9, first_name: "Test" },
      },
    });
    assert.equal(
      calls.some((c) => c.url.includes("/entrada")),
      true,
    );
    assert.equal(
      calls.some((c) => c.url.includes("/respuesta")),
      false,
    );
    mock.restoreAll();
  });
});

describe("telegram outbound events", () => {
  it("normalizes an inline keyboard and rejects oversized callback_data", () => {
    const ok = normalizeReplyMarkup({
      inline_keyboard: [
        [
          { text: "Acepto", callback_data: "acc:asg-1" },
          { text: "No puedo", callback_data: "dec:asg-1" },
        ],
      ],
    });
    assert.equal(ok?.inline_keyboard[0]?.[0]?.callback_data, "acc:asg-1");
    assert.equal(
      normalizeReplyMarkup({
        inline_keyboard: [
          [{ text: "x", callback_data: "k".repeat(65) }],
        ],
      }),
      undefined,
    );
  });

  it("parses telegram_send / telegram_edit / answer_callback", () => {
    const send = parseTelegramOutbound({
      event: "telegram_send",
      chat_id: "1",
      text: "¿Aceptas? (simulación)",
      reply_markup: {
        inline_keyboard: [[{ text: "Acepto", callback_data: "acc:1" }]],
      },
    });
    assert.ok(send && !("error" in send));
    if (send && !("error" in send) && send.event === "telegram_send") {
      assert.equal(send.reply_markup?.inline_keyboard.length, 1);
    }
    const edit = parseTelegramOutbound({
      event: "telegram_edit",
      chat_id: "1",
      message_id: 9,
      text: "Aceptado",
      reply_markup: { inline_keyboard: [] },
    });
    assert.ok(edit && !("error" in edit));
    const ack = parseTelegramOutbound({
      event: "answer_callback",
      callback_query_id: "cq-1",
      text: "Hecho",
    });
    assert.ok(ack && !("error" in ack));
    const bad = parseTelegramOutbound({
      event: "telegram_send",
      text: "hola",
    });
    assert.ok(bad && "error" in bad);
  });

  it("sendMessage includes reply_markup", async () => {
    const calls = mockFetch();
    await telegramSendMessage("tok", "42", "hola", {
      reply_markup: {
        inline_keyboard: [[{ text: "Acepto", callback_data: "acc:1" }]],
      },
    });
    const body = JSON.parse(calls[0]?.body ?? "{}") as {
      reply_markup?: { inline_keyboard: unknown };
    };
    assert.ok(body.reply_markup?.inline_keyboard);
    mock.restoreAll();
  });

  it("executeTelegramOutbound calls editMessageText and answerCallbackQuery", async () => {
    const calls = mockFetch();
    const env = loadEnv({ TELEGRAM_BOT_TOKEN: "tok" });
    await executeTelegramOutbound(env, {
      event: "telegram_edit",
      chat_id: "1",
      message_id: 4,
      text: "En camino",
      reply_markup: { inline_keyboard: [] },
    });
    await executeTelegramOutbound(env, {
      event: "answer_callback",
      callback_query_id: "cq",
      text: "ok",
    });
    assert.match(calls[0]?.url ?? "", /editMessageText/);
    assert.match(calls[1]?.url ?? "", /answerCallbackQuery/);
    mock.restoreAll();
  });
});

describe("HTTP puente", () => {
  it("/health exposes hook and PIN booleans, never the secrets", async () => {
    const env = loadEnv({
      TELEGRAM_BOT_TOKEN: "tok",
      HR_HOOK_TG: "https://example.invalid/entrada",
      HR_HOOK_TG_RESPONSE: "https://example.invalid/respuesta",
      STAFF_PIN: "secret-pin",
    });
    const app = createApp(env);
    const { server, port } = await listen(app);
    try {
      const res = await fetch(`http://127.0.0.1:${port}/health`);
      const body = (await res.json()) as Record<string, unknown>;
      assert.equal(body.ok, true);
      assert.equal(body.hr_hook_tg, true);
      assert.equal(body.hr_hook_tg_response, true);
      assert.equal(body.staff_pin, true);
      assert.equal(body.mando_backend, false);
      assert.equal(JSON.stringify(body).includes("secret-pin"), false);
    } finally {
      await close(server);
    }
  });

  it("POST /hr/events telegram_send forwards the keyboard", async () => {
    const calls = mockFetch();
    const env = loadEnv({
      TELEGRAM_BOT_TOKEN: "tok",
      HR_SECRET: "s3",
      MANDO_BACKEND_URL: "https://mando.example",
    });
    const app = createApp(env);
    const { server, port } = await listen(app);
    try {
      const res = await fetch(`http://127.0.0.1:${port}/hr/events`, {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "x-hr-secret": "s3",
        },
        body: JSON.stringify({
          event: "telegram_send",
          chat_id: "99",
          text: "¿Aceptas? (simulación)",
          reply_markup: {
            inline_keyboard: [
              [{ text: "Acepto", callback_data: "acc:asg-1" }],
            ],
          },
        }),
      });
      assert.equal(res.status, 200);
      const json = (await res.json()) as { ok: boolean };
      assert.equal(json.ok, true);
      assert.match(calls[0]?.url ?? "", /sendMessage/);
      const sent = JSON.parse(calls[0]?.body ?? "{}") as {
        text: string;
        reply_markup: { inline_keyboard: { callback_data: string }[][] };
      };
      assert.equal(sent.reply_markup.inline_keyboard[0]?.[0]?.callback_data, "acc:asg-1");
      assert.equal(
        calls.some((c) => c.url.includes("mando.example")),
        false,
      );
    } finally {
      await close(server);
      mock.restoreAll();
    }
  });

  it("POST /hr/events still accepts agent_reply", async () => {
    const calls = mockFetch();
    const env = loadEnv({
      TELEGRAM_BOT_TOKEN: "tok",
      HR_SECRET: "s3",
      MANDO_BACKEND_URL: "https://mando.example",
    });
    const app = createApp(env);
    const { server, port } = await listen(app);
    try {
      const res = await fetch(`http://127.0.0.1:${port}/hr/events`, {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "x-hr-secret": "s3",
        },
        body: JSON.stringify({
          event: "agent_reply",
          correlation_id: "tg-1-2",
          chat_id: "1",
          reply_text: "Recibido",
          report: { text: "Persona desmayada", channel: "telegram" },
        }),
      });
      assert.equal(res.status, 200);
      const json = (await res.json()) as {
        ok: boolean;
        mando?: { ok: boolean };
      };
      assert.equal(json.ok, true);
      assert.equal(json.mando?.ok, true);
      assert.equal(
        calls.some((c) => c.url.includes("mando.example/hr/events")),
        true,
      );
      assert.match(
        calls.find((c) => c.url.includes("sendMessage"))?.url ?? "",
        /sendMessage/,
      );
    } finally {
      await close(server);
      mock.restoreAll();
    }
  });

  it("POST /hr/tg/dispatch proxies to MANDO and returns outbound", async () => {
    const realFetch = globalThis.fetch;
    const calls: { url: string; body: string }[] = [];
    mock.method(
      globalThis,
      "fetch",
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.includes("127.0.0.1") || url.includes("localhost")) {
          return realFetch(input, init);
        }
        calls.push({ url, body: String(init?.body ?? "") });
        if (url.includes("/hr/tg/dispatch")) {
          return new Response(
            JSON.stringify({
              ok: true,
              dispatched: true,
              assignment_id: "asg-1",
              chat_id: "77",
              outbound: {
                event: "telegram_send",
                chat_id: "77",
                text: "SIMULACIÓN · médico",
              },
            }),
            { status: 200 },
          );
        }
        return new Response(JSON.stringify({ ok: true }), { status: 200 });
      },
    );
    const env = loadEnv({
      HR_SECRET: "s3",
      MANDO_BACKEND_URL: "https://mando.example",
    });
    const app = createApp(env);
    const { server, port } = await listen(app);
    try {
      const res = await fetch(`http://127.0.0.1:${port}/hr/tg/dispatch`, {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "x-hr-secret": "s3",
        },
        body: JSON.stringify({
          texto: "Persona caída",
          tipo: "medica",
          correlation_id: "tg-1",
        }),
      });
      assert.equal(res.status, 200);
      const json = (await res.json()) as {
        dispatched: boolean;
        chat_id: string;
        outbound: { event: string };
      };
      assert.equal(json.dispatched, true);
      assert.equal(json.chat_id, "77");
      assert.equal(json.outbound.event, "telegram_send");
      assert.equal(
        calls.some((c) => c.url.includes("mando.example/hr/tg/dispatch")),
        true,
      );
    } finally {
      await close(server);
      mock.restoreAll();
    }
  });

  it("POST /hr/tg/staff-response proxies acc to MANDO", async () => {
    const realFetch = globalThis.fetch;
    const calls: { url: string; body: string }[] = [];
    mock.method(
      globalThis,
      "fetch",
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.includes("127.0.0.1") || url.includes("localhost")) {
          return realFetch(input, init);
        }
        calls.push({ url, body: String(init?.body ?? "") });
        return new Response(
          JSON.stringify({
            ok: true,
            estado: "accepted",
            outbound: { event: "telegram_send", chat_id: "77", text: "ETA?" },
          }),
          { status: 200 },
        );
      },
    );
    const env = loadEnv({
      HR_SECRET: "s3",
      MANDO_BACKEND_URL: "https://mando.example",
    });
    const app = createApp(env);
    const { server, port } = await listen(app);
    try {
      const res = await fetch(`http://127.0.0.1:${port}/hr/tg/staff-response`, {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "x-hr-secret": "s3",
        },
        body: JSON.stringify({
          kind: "acc",
          assignment_id: "asg-1",
          chat_id: "77",
        }),
      });
      assert.equal(res.status, 200);
      const json = (await res.json()) as { estado: string };
      assert.equal(json.estado, "accepted");
      const forwarded = calls.find((c) =>
        c.url.includes("mando.example/hr/tg/staff-response"),
      );
      assert.ok(forwarded);
      assert.equal(JSON.parse(forwarded.body).kind, "acc");
    } finally {
      await close(server);
      mock.restoreAll();
    }
  });
});

function listen(app: ReturnType<typeof createApp>) {
  return new Promise<{ server: http.Server; port: number }>((resolve) => {
    const server = app.listen(0, "127.0.0.1", () => {
      const addr = server.address() as AddressInfo;
      resolve({ server, port: addr.port });
    });
  });
}

function close(server: http.Server) {
  return new Promise<void>((resolve, reject) => {
    server.close((err) => (err ? reject(err) : resolve()));
  });
}
