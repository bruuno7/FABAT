import { createHash, timingSafeEqual } from "node:crypto";
import { ContractError, object, parseEvent, parseId, parseMessage, type CanonicalEvent, type JsonObject } from "./event-contract.js";
import { parseCommandLine, parseStaffRole, type TelegramUpdate } from "./telegram-map.js";

export async function mapTelegramV2(
  update: TelegramUpdate, staffPin: string | undefined,
  lookupDelivery: (id: string) => Promise<Record<string, unknown> | null>, clock = Date.now,
  lookupReply?: (providerId: string) => Promise<Record<string, unknown> | null>,
): Promise<CanonicalEvent> {
  if (!Number.isSafeInteger(update.update_id) || update.update_id < 0 || Boolean(update.message) === Boolean(update.callback_query)) {
    throw new ContractError("invalid_telegram_update");
  }
  const callback = update.callback_query;
  const message = callback?.message ?? update.message;
  const user = callback?.from ?? message?.from;
  if (!message || !user || user.is_bot || !Number.isSafeInteger(user.id) || user.id <= 0 ||
      message.chat.type !== "private" || message.chat.id !== user.id ||
      !Number.isSafeInteger(message.message_id) || message.message_id <= 0) {
    throw new ContractError("unverified_telegram_identity");
  }
  const eventId = `tg-update-${update.update_id}`;
  const actorId = `tg-${user.id}`;
  const received = new Date(clock()).toISOString();
  let payload: JsonObject;
  const base = {
    schema_version: 2, event_id: eventId, event_type: "message.received",
    occurred_at: received, received_at: received, channel: "telegram", actor_id: actorId,
    conversation_id: actorId, correlation_id: eventId, source_message_id: String(message.message_id),
  };
  if (callback) {
    if (typeof callback.data !== "string" || callback.data.length > 64) throw new ContractError("invalid_callback");
    const [version, kind, deliveryId, extra] = callback.data.split("|");
    if (version !== "v2" || !["acc", "dec"].includes(kind) || extra !== undefined) throw new ContractError("invalid_callback");
    const delivery = await lookupDelivery(parseId(deliveryId));
    if (!delivery || delivery.status !== "succeeded" || delivery.provider_message_id !== String(message.message_id)) {
      throw new ContractError("unverified_callback");
    }
    const sent = parseMessage(delivery.message);
    if (sent.id !== deliveryId || sent.channel !== "telegram" || sent.recipient_id !== actorId || sent.purpose !== "offer" || !sent.assignment_id) {
      throw new ContractError("callback_for_other_actor");
    }
    return parseEvent({ ...base, event_type: kind === "acc" ? "assignment.accepted" : "assignment.declined",
      incident_id: sent.incident_id, assignment_id: sent.assignment_id,
      payload: { timestamp_source: "received", delivery_id: deliveryId,
        callback_query_id: parseId(callback.id), ...(kind === "dec" ? { reason: "Rechazo explícito por botón" } : {}) } });
  }
  if (typeof message.text !== "string" || !message.text.trim() || message.text.length > 2000 ||
      !Number.isSafeInteger(message.date) || message.date! < 1) throw new ContractError("invalid_telegram_message");
  base.occurred_at = new Date(message.date! * 1000).toISOString();
  const text = message.text.trim();
  const command = parseCommandLine(text);
  if (command?.command === "rol") {
    const [rawRole, pin] = command.args;
    const role = rawRole && parseStaffRole(rawRole);
    if (command.args.length !== 2 || !role || !staffPin || !pin) throw new ContractError("role_authentication_required");
    const digest = (value: string) => createHash("sha256").update(value).digest();
    if (!timingSafeEqual(digest(staffPin), digest(pin))) throw new ContractError("role_authentication_required");
    return parseEvent({ ...base, event_type: "actor.role_claimed", payload: { role, grant_id: `grant:${eventId}` } });
  }
  if (command?.command === "baja") {
    if (command.args.length) throw new ContractError("invalid_role_command");
    return parseEvent({ ...base, event_type: "actor.role_released", payload: {} });
  }
  payload = { text };
  const references: Partial<Pick<CanonicalEvent, "incident_id" | "assignment_id" | "question_id">> = {};
  if (message.reply_to_message) {
    const reply = object(message.reply_to_message);
    if (!Number.isSafeInteger(reply.message_id) || (reply.message_id as number) <= 0) throw new ContractError("invalid_reply_reference");
    const providerId = String(reply.message_id);
    payload.reply_to_message_id = providerId;
    const receipt = lookupReply ? await lookupReply(providerId) : null;
    if (receipt) {
      const sent = parseMessage(receipt.message);
      if (receipt.status !== "succeeded" || receipt.provider_message_id !== providerId || sent.recipient_id !== actorId || sent.channel !== "telegram") {
        throw new ContractError("unverified_reply_reference");
      }
      for (const key of ["incident_id", "assignment_id", "question_id"] as const) if (sent[key]) references[key] = sent[key];
    }
  }
  return parseEvent({ ...base, ...references, payload });
}
