import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { mapTelegramV2 } from "./telegram-v2.js";
import type { TelegramUpdate } from "./telegram-map.js";

const update = (text: string): TelegramUpdate => ({
  update_id: 42, message: { message_id: 7, date: 1789830000, text,
    chat: { id: 123, type: "private" }, from: { id: 123 } },
});
const now = () => Date.parse("2026-09-19T21:00:00Z");

describe("isolated v2 Telegram normalization", () => {
  it("preserves stable provider IDs, reply references and free text without interpreting it", async () => {
    const input = update("Estamos en la barra 3");
    input.message!.reply_to_message = { message_id: 6 };
    const event = await mapTelegramV2(input, "test-pin", async () => null, now);
    assert.equal(event.event_id, "tg-update-42");
    assert.equal(event.actor_id, "tg-123");
    assert.equal(event.event_type, "message.received");
    assert.equal(event.payload.reply_to_message_id, "6");
    assert.equal(event.payload.text, "Estamos en la barra 3");
    assert.equal(event.source_message_id, "7");
    const retried = await mapTelegramV2(input, "test-pin", async () => null, () => now() + 10000);
    assert.equal(retried.occurred_at, event.occurred_at);
  });

  it("requires a private authenticated sender, not a display name or a forwarded role", async () => {
    for (const mutate of [
      (u: TelegramUpdate) => { u.message!.from!.id = 999; },
      (u: TelegramUpdate) => { u.message!.chat.type = "group"; },
      (u: TelegramUpdate) => { u.message!.from!.is_bot = true; },
      (u: TelegramUpdate) => { u.update_id = 1.5; },
    ]) {
      const input = update("hola");
      mutate(input);
      await assert.rejects(() => mapTelegramV2(input, "test-pin", async () => null, now));
    }
  });

  it("checks role PIN locally and never stores it in events or grants", async () => {
    const event = await mapTelegramV2(update("/rol medico test-pin"), "test-pin", async () => null, now);
    assert.equal(event.event_type, "actor.role_claimed");
    assert.equal(event.payload.role, "medico");
    assert.equal(event.payload.grant_id, "grant:tg-update-42");
    assert.ok(!JSON.stringify(event).includes("test-pin"));
    for (const pin of [undefined, "wrong"]) {
      await assert.rejects(() => mapTelegramV2(update("/rol medico test-pin"), pin, async () => null, now));
    }
  });

  it("rejects malformed role commands instead of sending a PIN to an LLM", async () => {
    for (const text of ["/rol", "/rol medico", "/rol medico test-pin extra", "/rol unknown test-pin"]) {
      await assert.rejects(() => mapTelegramV2(update(text), "test-pin", async () => null, now));
    }
  });

  it("anchors a text reply to the exact delivered question rather than the last incident", async () => {
    const input = update("Sí, está consciente");
    input.message!.reply_to_message = { message_id: 51 };
    const record = { status: "succeeded", provider_message_id: "51", message: { id: "question-message", channel: "telegram",
      recipient_id: "tg-123", incident_id: "incident-2", question_id: "question-2", purpose: "question", text: "¿Está consciente?" } };
    const event = await mapTelegramV2(input, "test-pin", async () => null, now, async () => record);
    assert.equal(event.event_type, "message.received");
    assert.equal(event.incident_id, "incident-2");
    assert.equal(event.question_id, "question-2");
    record.message.recipient_id = "tg-999";
    await assert.rejects(() => mapTelegramV2(input, "test-pin", async () => null, now, async () => record), /unverified_reply_reference/);
  });

  it("binds a callback to the stored delivered message and assignment", async () => {
    const input: TelegramUpdate = { update_id: 43, callback_query: {
      id: "callback-1", from: { id: 123 }, data: "v2|acc|m1",
      message: { message_id: 91, date: 1789830000, chat: { id: 123, type: "private" } },
    } };
    const delivery = { status: "succeeded", provider_message_id: "91", message: {
      id: "m1", channel: "telegram", recipient_id: "tg-123", incident_id: "inc-1", assignment_id: "asg-1", purpose: "offer", text: "Oferta",
    } };
    const event = await mapTelegramV2(input, "test-pin", async () => delivery, now);
    assert.equal(event.event_type, "assignment.accepted");
    assert.equal(event.assignment_id, "asg-1");
    assert.equal(event.incident_id, "inc-1");
    delivery.message.recipient_id = "other";
    await assert.rejects(() => mapTelegramV2(input, "test-pin", async () => delivery, now));
    delivery.message.recipient_id = "tg-123";
    delivery.provider_message_id = "different";
    await assert.rejects(() => mapTelegramV2(input, "test-pin", async () => delivery, now));
  });
});
