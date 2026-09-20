import { Router } from "express";
import { checkSecret, forwardToHappyRobot, type Env } from "../lib/hr-client.js";
import { ContractError } from "../lib/event-contract.js";
import { RedisStateStore, upstashCommand } from "../lib/redis-state.js";
import { mapTelegramV2 } from "../lib/telegram-v2.js";
import type { IncidentStore } from "../hr/store.js";
import { handleTelegramUpdate } from "./handle-update.js";
import type { TelegramUpdate } from "../lib/telegram-map.js";
import type { StaffStore } from "./staff-store.js";

export function telegramRouter(
  env: Env,
  store: IncidentStore,
  staff: StaffStore,
  injected?: RedisStateStore,
): Router {
  const router = Router();
  const config = env.stateApi;
  let state = injected;
  if (!state && config?.enabled && config.url && config.token && config.namespace) {
    try { state = new RedisStateStore(upstashCommand(config.url, config.token), config.namespace); }
    catch { state = undefined; }
  }

  router.post("/webhook", async (req, res) => {
    const auth = checkSecret(
      env,
      env.telegramWebhookSecret,
      req.header("x-telegram-bot-api-secret-token"),
    );
    if (!auth.ok) {
      res.status(auth.status).json({ error: auth.error });
      return;
    }

    const update = req.body as TelegramUpdate;
    const sender = update?.callback_query?.from?.id ?? update?.message?.from?.id;
    const markedV2 = typeof update?.callback_query?.data === "string" && update.callback_query.data.startsWith("v2|");
    const selected = config?.telegramMode === "isolated" && config.telegramUsers?.includes(String(sender));
    if (selected || markedV2) {
      if (!selected || !config?.enabled || !state || !env.telegramWebhookSecret || !/^(test|dev)-/.test(config.namespace ?? "")) {
        res.status(503).json({ error: "state_unavailable" });
        return;
      }
      try {
        const event = await mapTelegramV2(update, env.staffPin, (id) => state!.message(id), Date.now,
          (providerId) => state!.messageForReply(`tg-${sender}`, providerId));
        const result = await state.ingestTelegram(event, String(sender));
        if (!["accepted", "duplicate"].includes(result.status)) {
          res.status(409).json({ error: "state_conflict" });
          return;
        }
        if (config.coordinatorHook) {
          try { await forwardToHappyRobot(config.coordinatorHook, { event_id: event.event_id }, env.hrHookApiKey); }
          catch {}
        }
        res.status(200).json({ ok: true, route: "v2", status: result.status, event_id: event.event_id });
      } catch (error) {
        res.status(error instanceof ContractError ? 422 : 503).json({ error: error instanceof ContractError ? "invalid_update" : "state_unavailable" });
      }
      return;
    }
    // Un fallo aguas abajo no debe provocar reintentos de Telegram: siempre 200.
    let result: unknown;
    try {
      result = await handleTelegramUpdate(env, update, store, staff);
    } catch (err) {
      console.error("[telegram] update failed", (err as Error).name);
      result = { ok: false };
    }

    res.status(200).json(result);
  });

  return router;
}
