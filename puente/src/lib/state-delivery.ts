import { object, parseId, parseMessage, type PendingMessage } from "./event-contract.js";
import type { RedisStateStore } from "./redis-state.js";

export type DeliveryStore = Pick<RedisStateStore, "claim" | "snapshot" | "settle" | "pending">;
export type DeliveryConfig = {
  mode: "sink" | "live";
  telegramToken?: string;
  allowedTelegramChats?: string[];
};
export type DeliveryResult = { id: string; status: string };

async function destination(store: DeliveryStore, message: PendingMessage): Promise<string> {
  const actorKey = `actor/${message.recipient_id}`;
  const incidentKey = message.incident_id ? `incident/${message.incident_id}` : null;
  const keys = [actorKey];
  if (incidentKey) keys.push(incidentKey);
  if (message.assignment_id) keys.push(`assignment/${message.assignment_id}`);
  if (message.question_id) keys.push(`question/${message.question_id}`);
  const snapshot = await store.snapshot(keys);
  const actor = object(snapshot[actorKey]?.value);
  const incident = incidentKey ? object(snapshot[incidentKey]?.value) : {};
  if (message.purpose === "offer") {
    const assignment = object(snapshot[`assignment/${message.assignment_id}`]?.value);
    if (incident.status === "closed" || assignment.status !== "offered" || assignment.actor_id !== message.recipient_id || assignment.incident_id !== message.incident_id) {
      throw new Error("stale_offer");
    }
  }
  if (message.question_id) {
    const question = object(snapshot[`question/${message.question_id}`]?.value);
    if (question.status !== "pending" || question.recipient_id !== message.recipient_id || question.incident_id !== message.incident_id) {
      throw new Error("stale_question");
    }
  }
  const channel = object(object(actor.channels)[message.channel]);
  if (channel.verified !== true || typeof channel.chat_id !== "string" || !/^[1-9][0-9]{0,15}$/.test(channel.chat_id)) {
    throw new Error("unverified_destination");
  }
  return channel.chat_id;
}

export async function deliver(
  store: DeliveryStore, id: string, config: DeliveryConfig = { mode: "sink" }, fetcher: typeof fetch = fetch,
): Promise<DeliveryResult> {
  parseId(id);
  let lease: string;
  let message: PendingMessage;
  try {
    const claimed = await store.claim(id);
    if (claimed.status !== "claimed") {
      const safe = ["sending", "succeeded", "failed", "unknown", "simulated", "missing", "deferred"];
      return { id, status: safe.includes(claimed.status) ? claimed.status : "unavailable" };
    }
    lease = String(claimed.lease);
    message = parseMessage(claimed.message);
    if (message.id !== id) return { id, status: "unavailable" };
  } catch {
    return { id, status: "unavailable" };
  }
  const settle = async (status: "succeeded" | "failed" | "unknown" | "simulated" | "retry", providerId = "", retryAfterMs = 5000): Promise<DeliveryResult> => {
    try {
      const result = await store.settle(id, lease, status, providerId, retryAfterMs);
      if (status === "retry" && ["pending", "failed"].includes(result.status)) return { id, status: result.status === "pending" ? "deferred" : "failed" };
      return { id, status: result.status === status ? status : "unknown" };
    } catch {
      return { id, status: "unknown" };
    }
  };
  if (config.mode === "sink") return settle("simulated");
  let chatId: string;
  let body: Record<string, unknown>;
  try {
    if (config.mode !== "live" || message.channel !== "telegram" || !config.telegramToken) return settle("failed");
    chatId = await destination(store, message);
    if (!config.allowedTelegramChats?.includes(chatId)) return settle("failed");
    body = { chat_id: chatId, text: message.text };
    if (message.purpose === "offer") {
      if (`v2|acc|${id}`.length > 64) return settle("failed");
      body.reply_markup = { inline_keyboard: [[
        { text: "Acepto", callback_data: `v2|acc|${id}` },
        { text: "No puedo", callback_data: `v2|dec|${id}` },
      ]] };
    }
  } catch {
    return settle("failed");
  }
  try {
    const response = await fetcher(`https://api.telegram.org/bot${config.telegramToken}/sendMessage`, {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
      redirect: "error", signal: AbortSignal.timeout(5000),
    });
    if (response.status >= 500) return settle("unknown");
    const data = object(await response.json());
    if (data.ok === false) {
      if (data.error_code === 429) {
        const seconds = object(data.parameters).retry_after;
        if (Number.isInteger(seconds) && (seconds as number) >= 1 && (seconds as number) <= 300) {
          return settle("retry", "", (seconds as number) * 1000);
        }
      }
      return settle("failed");
    }
    if (!response.ok || data.ok !== true) return settle("unknown");
    const providerId = object(data.result).message_id;
    if (!Number.isSafeInteger(providerId) || (providerId as number) < 1) return settle("unknown");
    return settle("succeeded", String(providerId));
  } catch {
    return settle("unknown");
  }
}

export async function recoverDeliveries(
  store: DeliveryStore, config: DeliveryConfig = { mode: "sink" }, limit = 8, fetcher: typeof fetch = fetch,
): Promise<{ processed: number; results: DeliveryResult[] }> {
  if (!Number.isInteger(limit) || limit < 1 || limit > 16) throw new Error("invalid_recovery_limit");
  const ids = await store.pending("outbox", limit);
  if (ids.length > limit) throw new Error("invalid_pending_messages");
  const results: DeliveryResult[] = [];
  for (const id of ids) results.push(await deliver(store, id, config, fetcher));
  return { processed: results.length, results };
}
