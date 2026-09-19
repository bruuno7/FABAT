import type { MandoPublicReport, PublicReport } from "./contract.js";

export type Env = {
  port: number;
  telegramBotToken: string | undefined;
  telegramWebhookSecret: string | undefined;
  telegramMode: "webhook" | "poll";
  hrHookTg: string | undefined;
  hrHookApiKey: string | undefined;
  hrSecret: string | undefined;
  mandoBackendUrl: string | undefined;
  mandoCallbackUrl: string;
  allowDemoInject: boolean;
  /** En despliegue público (Vercel / producción) los secretos son obligatorios: sin ellos se rechaza. */
  requireSecrets: boolean;
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
    mandoBackendUrl: emptyToUndef(env.MANDO_BACKEND_URL),
    mandoCallbackUrl: env.MANDO_CALLBACK_URL ?? "http://127.0.0.1:8787",
    allowDemoInject: env.ALLOW_DEMO_INJECT === "1",
    requireSecrets:
      Boolean(env.VERCEL) ||
      env.NODE_ENV === "production" ||
      env.REQUIRE_SECRETS === "1",
  };
}

/** Ninguna llamada saliente puede dejar colgada la función (Telegram reintenta si no respondemos). */
export const FETCH_TIMEOUT_MS = 5000;

/**
 * Comprueba un secreto compartido. Sin secreto configurado: en local se deja pasar,
 * en despliegue público se rechaza (fallo cerrado).
 */
export function checkSecret(
  env: Env,
  expected: string | undefined,
  got: string | undefined,
): { ok: true } | { ok: false; status: number; error: string } {
  if (!expected) {
    return env.requireSecrets
      ? { ok: false, status: 503, error: "secret not configured" }
      : { ok: true };
  }
  return got === expected
    ? { ok: true }
    : { ok: false, status: 401, error: "invalid secret" };
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
    signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
  });
  const body = await res.text();
  return { ok: res.ok, status: res.status, body };
}

export async function forwardToMando(
  backendUrl: string | undefined,
  secret: string | undefined,
  report: MandoPublicReport,
): Promise<{ ok: boolean; status: number; body: string; skipped?: boolean }> {
  if (!backendUrl) {
    return {
      ok: false,
      status: 0,
      body: "MANDO_BACKEND_URL not configured",
      skipped: true,
    };
  }

  const url = backendUrl.endsWith("/hr/events")
    ? backendUrl
    : `${backendUrl.replace(/\/+$/, "")}/hr/events`;
  const headers: Record<string, string> = {
    "content-type": "application/json",
  };
  if (secret) headers["x-hr-secret"] = secret;

  const res = await fetch(url, {
    method: "POST",
    headers,
    body: JSON.stringify(report),
    signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
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
    signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
  });
  const body = await res.text();
  return { ok: res.ok, status: res.status, body };
}
