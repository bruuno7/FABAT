/**
 * Long-poll Telegram getUpdates when no HTTPS webhook is available.
 * Mutually exclusive with setWebhook — delete webhook first if needed.
 */
import "dotenv/config";
import { loadEnv } from "../lib/hr-client.js";
import { createIncidentStore } from "../hr/store.js";
import { handleTelegramUpdate } from "./handle-update.js";
import {
  TELEGRAM_ALLOWED_UPDATES,
  type TelegramUpdate,
} from "../lib/telegram-map.js";
import { createStaffStore } from "./staff-store.js";

const env = loadEnv();

if (!env.telegramBotToken) {
  console.error("TELEGRAM_BOT_TOKEN required for poll mode");
  process.exit(1);
}

const token = env.telegramBotToken;
const store = createIncidentStore();
const staff = createStaffStore();
let offset = 0;

async function loop() {
  console.info("[poll] starting getUpdates loop");
  for (;;) {
    try {
      const res = await fetch(`https://api.telegram.org/bot${token}/getUpdates`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          timeout: 30,
          offset,
          allowed_updates: [...TELEGRAM_ALLOWED_UPDATES],
        }),
      });
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
        const result = await handleTelegramUpdate(env, update, store, staff);
        if (!result.ignored) {
          console.info("[poll] handled", {
            command: result.command,
            kind: result.kind,
            correlation_id: result.correlation_id,
            hr: result.hr,
          });
        }
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
