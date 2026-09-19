import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { isHrToMando, isPublicReport } from "./contract.js";
import {
  guessLocationHint,
  telegramUpdateToPublicReport,
} from "./telegram-map.js";
import { loadEnv } from "./hr-client.js";

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
    assert.equal(e.telegramMode, "poll");
    assert.equal(e.port, 9000);
  });
});
