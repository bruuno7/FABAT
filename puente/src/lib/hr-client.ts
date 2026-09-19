import { loadStateApiConfig, type StateApiConfig } from "./state-env.js";
import type {
  MandoPublicReport,
  TelegramOutbound,
} from "./contract.js";

export type Env = {
  port: number;
  telegramBotToken: string | undefined;
  telegramWebhookSecret: string | undefined;
  telegramMode: "webhook" | "poll";
  hrHookTg: string | undefined;
  stateApi?: StateApiConfig;
  hrHookTgResponse: string | undefined;
  /** Incoming Hook de `fa-rol-tg`: directorio rol↔chat_id en HappyRobot (Redis). */
  hrHookTgRoster: string | undefined;
  hrHookApiKey: string | undefined;
  hrSecret: string | undefined;
  staffPin: string | undefined;
  mandoBackendUrl: string | undefined;
  mandoOperational: boolean;
  mandoBridgeSecret: string | undefined;
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
    stateApi: loadStateApiConfig(env),
    hrHookTgResponse: emptyToUndef(env.HR_HOOK_TG_RESPONSE),
    hrHookTgRoster: emptyToUndef(env.HR_HOOK_TG_ROSTER),
    hrHookApiKey: emptyToUndef(env.HR_HOOK_API_KEY),
    hrSecret: emptyToUndef(env.HR_SECRET),
    staffPin: emptyToUndef(env.STAFF_PIN),
    mandoBackendUrl: emptyToUndef(env.MANDO_BACKEND_URL),
    mandoOperational: env.MANDO_OPERATIONAL === "1",
    mandoBridgeSecret: emptyToUndef(env.MANDO_BRIDGE_SECRET),
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

export type ForwardResult = {
  ok: boolean;
  status: number;
  body: string;
  skipped?: boolean;
};

export async function forwardToHappyRobot(
  hookUrl: string | undefined,
  payload: unknown,
  apiKey?: string,
  missing = "HR_HOOK_TG not configured",
): Promise<ForwardResult> {
  if (!hookUrl) {
    return {
      ok: false,
      status: 0,
      body: missing,
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
    body: JSON.stringify(payload),
    signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
  });
  const body = await res.text();
  return { ok: res.ok, status: res.status, body };
}

export type TelegramCallResult = ForwardResult;

async function telegramCall(
  token: string | undefined,
  method: string,
  payload: Record<string, unknown>,
): Promise<TelegramCallResult> {
  if (!token) {
    return {
      ok: false,
      status: 0,
      body: "TELEGRAM_BOT_TOKEN not configured",
      skipped: true,
    };
  }

  const url = `https://api.telegram.org/bot${token}/${method}`;
  const res = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
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
  return mandoRequest(backendUrl, secret, "/hr/events", {
    method: "POST",
    body: JSON.stringify(report),
  });
}

function mandoUrl(
  backendUrl: string,
  path: string,
): string {
  const base = backendUrl.replace(/\/+$/, "").replace(/\/hr\/events$/i, "");
  return `${base}${path}`;
}

/** POST/GET autenticado a una ruta de MANDO (`/hr/tg/dispatch`, `/hr/tg/staff-response`, …). */
export async function forwardMandoPath(
  backendUrl: string | undefined,
  secret: string | undefined,
  path: string,
  init: { method: string; body?: string } = { method: "GET" },
): Promise<ForwardResult> {
  return mandoRequest(backendUrl, secret, path, init);
}

async function mandoRequest(
  backendUrl: string | undefined,
  secret: string | undefined,
  path: string,
  init: { method: string; body?: string },
): Promise<ForwardResult> {
  if (!backendUrl) {
    return {
      ok: false,
      status: 0,
      body: "MANDO_BACKEND_URL not configured",
      skipped: true,
    };
  }
  const headers: Record<string, string> = {
    "content-type": "application/json",
  };
  if (secret) {
    headers["x-hr-secret"] = secret;
    headers["x-mando-token"] = secret;
  }
  const res = await fetch(mandoUrl(backendUrl, path), {
    method: init.method,
    headers,
    body: init.body,
    signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
  });
  const body = await res.text();
  return { ok: res.ok, status: res.status, body };
}

export type RosterSeat = {
  rol: string;
  label?: string;
  claimed: boolean;
  chat_id?: string | null;
  alias?: string;
  claimed_at?: string | null;
  busy?: boolean;
};

export type RosterView = {
  ok?: boolean;
  reason?: string;
  seats: RosterSeat[];
  total: number;
  claimed: number;
  disponibles: number;
  previous?: {
    role?: string;
    alias?: string;
    chat_id?: string;
  } | null;
  holder?: { rol?: string; alias?: string; chat_id?: string };
};

function parseRoster(body: string): RosterView | null {
  try {
    const parsed = JSON.parse(body) as Partial<RosterView>;
    let seats: RosterSeat[];
    if (!parsed || !Array.isArray(parsed.seats)) {
      if (!parsed || (typeof parsed.ok !== "boolean" && typeof parsed.reason !== "string")) {
        return null;
      }
      seats = [];
    } else {
      seats = parsed.seats;
    }
    return {
      ok: parsed.ok,
      reason: parsed.reason,
      seats,
      total: Number(parsed.total ?? seats.length),
      claimed: Number(parsed.claimed ?? 0),
      disponibles: Number(parsed.disponibles ?? 0),
      previous: parsed.previous,
      holder: parsed.holder,
    };
  } catch {
    return null;
  }
}

/**
 * Directorio de puestos en HappyRobot (`fa-rol-tg`). El workflow lee/escribe Redis y responde
 * al chat por su cuenta vía `/hr/events`; aquí solo se dispara el hook.
 */
export async function postHappyRobotRoster(
  env: Env,
  payload: { action: "claim" | "release" | "list"; role?: string; chat_id: string; alias?: string },
): Promise<ForwardResult> {
  return forwardToHappyRobot(
    env.hrHookTgRoster,
    payload,
    env.hrHookApiKey,
    "HR_HOOK_TG_ROSTER not configured",
  );
}

export async function fetchMandoRoster(
  backendUrl: string | undefined,
  secret: string | undefined,
): Promise<{ result: ForwardResult; view: RosterView | null }> {
  const result = await mandoRequest(backendUrl, secret, "/hr/tg/roster", {
    method: "GET",
  });
  return { result, view: result.ok ? parseRoster(result.body) : null };
}

export async function postMandoRoster(
  backendUrl: string | undefined,
  secret: string | undefined,
  payload: Record<string, unknown>,
): Promise<{ result: ForwardResult; view: RosterView | null }> {
  const result = await mandoRequest(backendUrl, secret, "/hr/tg/roster", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  return { result, view: parseRoster(result.body) };
}

export async function telegramSendMessage(
  token: string | undefined,
  chatId: string,
  text: string,
  opts?: { reply_markup?: unknown },
): Promise<TelegramCallResult> {
  const payload: Record<string, unknown> = { chat_id: chatId, text };
  if (opts?.reply_markup) payload.reply_markup = opts.reply_markup;
  return telegramCall(token, "sendMessage", payload);
}

export async function telegramEditMessage(
  token: string | undefined,
  chatId: string,
  messageId: number,
  text: string,
  opts?: { reply_markup?: unknown },
): Promise<TelegramCallResult> {
  const payload: Record<string, unknown> = {
    chat_id: chatId,
    message_id: messageId,
    text,
  };
  if (opts?.reply_markup) payload.reply_markup = opts.reply_markup;
  return telegramCall(token, "editMessageText", payload);
}

export async function telegramAnswerCallback(
  token: string | undefined,
  callbackQueryId: string,
  opts?: { text?: string; show_alert?: boolean },
): Promise<TelegramCallResult> {
  const payload: Record<string, unknown> = {
    callback_query_id: callbackQueryId,
  };
  if (opts?.text) payload.text = opts.text;
  if (opts?.show_alert) payload.show_alert = true;
  return telegramCall(token, "answerCallbackQuery", payload);
}

export async function executeTelegramOutbound(
  env: Env,
  event: TelegramOutbound,
): Promise<TelegramCallResult> {
  if (event.event === "telegram_send") {
    return telegramSendMessage(env.telegramBotToken, event.chat_id, event.text, {
      reply_markup: event.reply_markup,
    });
  }
  if (event.event === "telegram_edit") {
    return telegramEditMessage(
      env.telegramBotToken,
      event.chat_id,
      event.message_id,
      event.text,
      { reply_markup: event.reply_markup },
    );
  }
  return telegramAnswerCallback(env.telegramBotToken, event.callback_query_id, {
    text: event.text,
    show_alert: event.show_alert,
  });
}
