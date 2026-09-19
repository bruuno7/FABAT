/**
 * Long-poll Telegram getUpdates when no HTTPS webhook is available.
 * Mutually exclusive with setWebhook — delete webhook first if needed.
 */
import { loadEnv, forwardToHappyRobot } from "../lib/hr-client.js";
import {
  telegramUpdateToPublicReport,
  type TelegramUpdate,
} from "../lib/telegram-map.js";

const env = loadEnv();

if (!env.telegramBotToken) {
  console.error("TELEGRAM_BOT_TOKEN required for poll mode");
  process.exit(1);
}

const token = env.telegramBotToken;
let offset = 0;

async function loop() {
  console.info("[poll] starting getUpdates loop");
  for (;;) {
    try {
      const url = new URL(`https://api.telegram.org/bot${token}/getUpdates`);
      url.searchParams.set("timeout", "30");
      url.searchParams.set("offset", String(offset));
      const res = await fetch(url);
      const data = (await res.json()) as {
        ok: boolean;
        result?: TelegramUpdate[];
        description?: string;
      };
      if (!data.ok) {
        console.error("[poll] telegram error", data.description);
        await sleep(2000);
        continue;
      }
      for (const update of data.result ?? []) {
        offset = update.update_id + 1;
        const report = telegramUpdateToPublicReport(update);
        if (!report) continue;
        const fwd = await forwardToHappyRobot(
          env.hrHookTg,
          report,
          env.hrHookApiKey,
        );
        console.info("[poll] forwarded", {
          correlation_id: report.correlation_id,
          text: report.text.slice(0, 80),
          hr_ok: fwd.ok,
          hr_skipped: fwd.skipped ?? false,
        });
      }
    } catch (err) {
      console.error("[poll] exception", err);
      await sleep(2000);
    }
  }
}

function sleep(ms: number) {
  return new Promise((r) => setTimeout(r, ms));
}

void loop();
