import { Router } from "express";
import { checkSecret, type Env } from "../lib/hr-client.js";
import type { IncidentStore } from "../hr/store.js";
import { handleTelegramUpdate } from "./handle-update.js";
import type { TelegramUpdate } from "../lib/telegram-map.js";

export function telegramRouter(env: Env, store: IncidentStore): Router {
  const router = Router();

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
    // Un fallo aguas abajo no debe provocar reintentos de Telegram: siempre 200.
    let result: unknown;
    try {
      result = await handleTelegramUpdate(env, update, store);
    } catch (err) {
      console.error("[telegram] update failed", (err as Error).name);
      result = { ok: false };
    }

    res.status(200).json(result);
  });

  return router;
}
