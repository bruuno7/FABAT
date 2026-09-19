import type { PublicReport } from "./contract.js";

export type Env = {
  port: number;
  telegramBotToken: string | undefined;
  telegramWebhookSecret: string | undefined;
  telegramMode: "webhook" | "poll";
  hrHookTg: string | undefined;
  hrHookApiKey: string | undefined;
  hrSecret: string | undefined;
  mandoCallbackUrl: string;
  allowDemoInject: boolean;
};

export function loadEnv(env: NodeJS.ProcessEnv = process.env): Env {
  const mode = (env.TELEGRAM_MODE ?? "webhook").toLowerCase();
  return {
    port: Number(env.PORT ?? 8787),
    telegramBotToken: emptyToUndef(env.TELEGRAM_BOT_TOKEN),
    telegramWebhookSecret: emptyToUndef(env.TELEGRAM_WEBHOOK_SECRET),
    telegramMode: mode === "poll" ? "poll" : "webhook",
    hrHookTg: emptyToUndef(env.HR_HOOK_TG),
    hrHookApiKey: emptyToUndef(env.HR_HOOK_API_KEY),
    hrSecret: emptyToUndef(env.HR_SECRET),
    mandoCallbackUrl: env.MANDO_CALLBACK_URL ?? "http://127.0.0.1:8787",
    allowDemoInject: env.ALLOW_DEMO_INJECT === "1",
  };
}

function emptyToUndef(v: string | undefined): string | undefined {
  if (v == null || v.trim() === "") return undefined;
  return v.trim();
}

export async function forwardToHappyRobot(
  hookUrl: string | undefined,
  report: PublicReport,
  apiKey?: string,
): Promise<{ ok: boolean; status: number; body: string; skipped?: boolean }> {
  if (!hookUrl) {
    return {
      ok: false,
      status: 0,
      body: "HR_HOOK_TG not configured",
      skipped: true,
    };
  }

  const headers: Record<string, string> = {
    "content-type": "application/json",
  };
  if (apiKey) headers["x-api-key"] = apiKey;

  const res = await fetch(hookUrl, {
    method: "POST",
    headers,
    body: JSON.stringify(report),
  });
  const body = await res.text();
  return { ok: res.ok, status: res.status, body };
}

export async function telegramSendMessage(
  token: string | undefined,
  chatId: string,
  text: string,
): Promise<{ ok: boolean; status: number; body: string; skipped?: boolean }> {
  if (!token) {
    return {
      ok: false,
      status: 0,
      body: "TELEGRAM_BOT_TOKEN not configured",
      skipped: true,
    };
  }

  const url = `https://api.telegram.org/bot${token}/sendMessage`;
  const res = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ chat_id: chatId, text }),
  });
  const body = await res.text();
  return { ok: res.ok, status: res.status, body };
}
