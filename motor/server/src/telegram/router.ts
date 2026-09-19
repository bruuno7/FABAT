import { Router } from "express";
import type { Env } from "../lib/hr-client.js";
import { forwardToHappyRobot } from "../lib/hr-client.js";
import {
  guessLocationHint,
  telegramUpdateToPublicReport,
  type TelegramUpdate,
} from "../lib/telegram-map.js";

export function telegramRouter(env: Env): Router {
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
    const report = telegramUpdateToPublicReport(update);
    if (!report) {
      res.status(200).json({ ok: true, ignored: true });
      return;
    }

    if (!report.location_hint) {
      const hint = guessLocationHint(report.text);
      if (hint) report.location_hint = hint;
    }

    // ACK rápido a Telegram; forward en background-ish (await corto)
    const fwd = await forwardToHappyRobot(
      env.hrHookTg,
      report,
      env.hrHookApiKey,
    );

    console.info("[telegram] report", {
      correlation_id: report.correlation_id,
      fwd_ok: fwd.ok,
      fwd_skipped: fwd.skipped ?? false,
      fwd_status: fwd.status,
    });

    res.status(200).json({
      ok: true,
      correlation_id: report.correlation_id,
      hr: { ok: fwd.ok, skipped: fwd.skipped ?? false, status: fwd.status },
    });
  });

  return router;
}
