/**
 * Registra (o borra) el webhook de Telegram contra la URL pública (Vercel).
 *
 * Uso:
 *   TELEGRAM_BOT_TOKEN=… MANDO_CALLBACK_URL=https://xxx.vercel.app \
 *     npx tsx scripts/telegram-set-webhook.ts
 *
 *   … npx tsx scripts/telegram-set-webhook.ts --delete
 */
import "dotenv/config";
import { loadEnv } from "../src/lib/hr-client.js";

const env = loadEnv();
const del = process.argv.includes("--delete");

if (!env.telegramBotToken) {
  console.error("Falta TELEGRAM_BOT_TOKEN");
  process.exit(1);
}

const base = env.mandoCallbackUrl.replace(/\/$/, "");
const webhookUrl = `${base}/telegram/webhook`;
const api = `https://api.telegram.org/bot${env.telegramBotToken}`;

async function main() {
  if (del) {
    const res = await fetch(`${api}/setWebhook`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ url: "" }),
    });
    console.log(await res.json());
    return;
  }

  const body: Record<string, unknown> = {
    url: webhookUrl,
    allowed_updates: ["message"],
    drop_pending_updates: true,
  };
  if (env.telegramWebhookSecret) {
    body.secret_token = env.telegramWebhookSecret;
  }

  const res = await fetch(`${api}/setWebhook`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const json = await res.json();
  console.log(json);

  const info = await fetch(`${api}/getWebhookInfo`);
  console.log("webhookInfo:", await info.json());
}

void main();
