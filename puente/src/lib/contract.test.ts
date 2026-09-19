import assert from "node:assert/strict";
import { describe, it, mock } from "node:test";
import {
  isHrToMando,
  isPublicReport,
  toMandoPublicReport,
} from "./contract.js";
import {
  guessLocationHint,
  parseCommand,
  telegramUpdateToPublicReport,
} from "./telegram-map.js";
import { forwardToMando, loadEnv } from "./hr-client.js";
import { handleTelegramUpdate } from "../telegram/handle-update.js";
import { createIncidentStore } from "../hr/store.js";

describe("contract guards", () => {
  it("accepts public_report", () => {
    assert.equal(
      isPublicReport({
        event: "public_report",
        channel: "telegram",
        reported_at: "2026-09-19T12:00:00.000Z",
        text: "persona caída en escenario",
      }),
      true,
    );
  });

  it("rejects empty text", () => {
    assert.equal(
      isPublicReport({
        event: "public_report",
        channel: "telegram",
        reported_at: "2026-09-19T12:00:00.000Z",
        text: "",
      }),
      false,
    );
  });

  it("accepts hr_to_mando agent_reply", () => {
    assert.equal(
      isHrToMando({
        event: "agent_reply",
        correlation_id: "tg-1-2",
        chat_id: "1",
        reply_text: "Recibido",
      }),
      true,
    );
  });

  it("adapts an HR reply to the backend public_report contract", () => {
    const report = toMandoPublicReport({
      event: "agent_reply",
      correlation_id: "tg-1-2",
      chat_id: "1",
      hr_run_id: "run-1",
      report: {
        channel: "telegram",
        text: "Persona desmayada en entrada VIP",
        zone_hint: "entrada VIP",
      },
      extract: {
        incident_type: "medica",
        sector: "entrada VIP",
        severity: 3,
        triage_color: "desconocido",
        summary: "Una persona desmayada",
      },
    });

    assert.ok(report);
    assert.equal(report.type, "public_report");
    assert.equal(report.event_id, "tg-1-2-final");
    assert.equal(report.report.text, "Persona desmayada en entrada VIP");
    assert.equal(report.extracted.category, "medica");
    assert.equal(report.extracted.location, "entrada VIP");
  });

  it("does not create backend reports for non-final HR events", () => {
    assert.equal(
      toMandoPublicReport({
        event: "needs_human",
        correlation_id: "tg-1-2",
      }),
      null,
    );
  });
});

describe("telegram map", () => {
  it("maps update to public_report with correlation and perfil default", () => {
    const report = telegramUpdateToPublicReport({
      update_id: 99,
      message: {
        message_id: 1,
        text: "Hay aglomeración en la entrada VIP",
        chat: { id: 555, type: "private" },
        from: { id: 555, first_name: "Luis" },
      },
    });
    assert.ok(report);
    assert.equal(report.event, "public_report");
    assert.equal(report.channel, "telegram");
    assert.equal(report.reporter?.chat_id, "555");
    assert.equal(report.reporter?.perfil_color, "adulto");
    assert.equal(report.correlation_id, "tg-555-99");
    assert.equal(report.location_hint, "entrada");
  });

  it("does not map slash commands as reports", () => {
    assert.equal(
      telegramUpdateToPublicReport({
        update_id: 1,
        message: {
          message_id: 1,
          text: "/start",
          chat: { id: 1, type: "private" },
        },
      }),
      null,
    );
    assert.equal(parseCommand("/start@MyBot"), "start");
    assert.equal(parseCommand("/Ayuda"), "ayuda");
  });

  it("ignores non-text updates", () => {
    assert.equal(
      telegramUpdateToPublicReport({
        update_id: 1,
        message: { message_id: 1, chat: { id: 1, type: "private" } },
      }),
      null,
    );
  });

  it("guessLocationHint finds escenario", () => {
    assert.equal(guessLocationHint("Caído junto al escenario"), "escenario");
  });
});

describe("loadEnv", () => {
  it("treats empty secrets as undefined", () => {
    const e = loadEnv({
      TELEGRAM_BOT_TOKEN: "  ",
      HR_HOOK_TG: "",
      TELEGRAM_MODE: "poll",
      PORT: "9000",
    });
    assert.equal(e.telegramBotToken, undefined);
    assert.equal(e.hrHookTg, undefined);
    assert.equal(e.mandoBackendUrl, undefined);
    assert.equal(e.telegramMode, "poll");
    assert.equal(e.port, 9000);
  });
});

describe("forwardToMando", () => {
  it("posts the public report to the authenticated backend endpoint", async () => {
    let request: { url: string; init?: RequestInit } | undefined;
    mock.method(
      globalThis,
      "fetch",
      async (input: RequestInfo | URL, init?: RequestInit) => {
        request = { url: String(input), init };
        return new Response(JSON.stringify({ ok: true, report_id: "j-001" }), {
          status: 200,
        });
      },
    );

    const report = toMandoPublicReport({
      event: "agent_reply",
      correlation_id: "tg-1-2",
      report: { text: "Persona desmayada", channel: "telegram" },
    });
    assert.ok(report);
    const result = await forwardToMando(
      "https://mando.example",
      "shared-secret",
      report,
    );

    assert.equal(result.ok, true);
    assert.equal(request?.url, "https://mando.example/hr/events");
    assert.equal(
      (request?.init?.headers as Record<string, string>)["x-hr-secret"],
      "shared-secret",
    );
    assert.equal(
      JSON.parse(String(request?.init?.body)).type,
      "public_report",
    );
    mock.restoreAll();
  });
});

describe("handleTelegramUpdate", () => {
  it("answers /ping without calling HR", async () => {
    const fetches: string[] = [];
    mock.method(globalThis, "fetch", async (input: RequestInfo | URL) => {
      fetches.push(String(input));
      return new Response(JSON.stringify({ ok: true }), { status: 200 });
    });

    const env = loadEnv({
      TELEGRAM_BOT_TOKEN: "test-token",
      HR_HOOK_TG: "https://example.invalid/hook",
    });
    const result = await handleTelegramUpdate(
      env,
      {
        update_id: 1,
        message: {
          message_id: 1,
          text: "/ping",
          chat: { id: 42, type: "private" },
        },
      },
      createIncidentStore(),
    );

    assert.equal(result.command, "ping");
    assert.match(result.replies[0] ?? "", /pong/);
    assert.equal(fetches.length, 1);
    assert.match(fetches[0], /sendMessage/);
    mock.restoreAll();
  });

  it("ACKs a report and skips HR when hook missing", async () => {
    const bodies: string[] = [];
    mock.method(globalThis, "fetch", async (_input: RequestInfo | URL, init?: RequestInit) => {
      bodies.push(String(init?.body ?? ""));
      return new Response(JSON.stringify({ ok: true }), { status: 200 });
    });

    const env = loadEnv({ TELEGRAM_BOT_TOKEN: "test-token" });
    const store = createIncidentStore();
    const result = await handleTelegramUpdate(
      env,
      {
        update_id: 7,
        message: {
          message_id: 1,
          text: "persona caída en escenario",
          chat: { id: 9, type: "private" },
          from: { id: 9, first_name: "Test" },
        },
      },
      store,
    );

    assert.equal(result.correlation_id, "tg-9-7");
    assert.equal(result.hr?.skipped, true);
    assert.equal(result.replies.length, 2);
    assert.equal(store.list().length, 1);
    mock.restoreAll();
  });
});

it("checkSecret: en despliegue público sin secreto configurado se rechaza; en local se deja pasar", async () => {
  const { checkSecret } = await import("./hr-client.js");
  const publico = loadEnv({ VERCEL: "1" } as NodeJS.ProcessEnv);
  const local = loadEnv({} as NodeJS.ProcessEnv);
  assert.deepEqual(checkSecret(publico, undefined, undefined), {
    ok: false,
    status: 503,
    error: "secret not configured",
  });
  assert.deepEqual(checkSecret(local, undefined, undefined), { ok: true });
  assert.deepEqual(checkSecret(publico, "s3", "otro"), {
    ok: false,
    status: 401,
    error: "invalid secret",
  });
  assert.deepEqual(checkSecret(publico, "s3", "s3"), { ok: true });
});
