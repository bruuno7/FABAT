import { Router } from "express";
import type { Env } from "../lib/hr-client.js";
import type { IncidentStore } from "../hr/store.js";
import { handleTelegramUpdate } from "./handle-update.js";
import type { TelegramUpdate } from "../lib/telegram-map.js";

export function telegramRouter(env: Env, store: IncidentStore): Router {
  const router = Router();

  router.post("/webhook", async (req, res) => {
    if (env.telegramWebhookSecret) {
      const got = req.header("x-telegram-bot-api-secret-token");
      if (got !== env.telegramWebhookSecret) {
        res.status(401).json({ error: "invalid telegram secret" });
        return;
      }
    }

    const update = req.body as TelegramUpdate;
    const result = await handleTelegramUpdate(env, update, store);

    res.status(200).json(result);
  });

  return router;
}
