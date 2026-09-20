import { timingSafeEqual } from "node:crypto";
import express, { Router, type ErrorRequestHandler } from "express";
import { FETCH_TIMEOUT_MS, type Env } from "../lib/hr-client.js";

const UPDATE_LIMIT = 1024 * 1024;
const ACCEPTANCE_LIMIT = 8192;
const DEFINITIVE_REJECTIONS = new Set([400, 401, 403, 409, 413, 422]);

type Readiness = { ready: boolean; missing: string[]; invalid: string[] };

function operationalUrl(base: string | undefined): string | undefined {
  if (!base || !/^https?:\/\//i.test(base) || /[\s\\]/.test(base)) return;
  try {
    const url = new URL(base);
    const local = ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
    if (url.protocol !== "https:" && !(url.protocol === "http:" && local)) return;
    if (url.username || url.password || url.search || url.hash) return;
    const prefix = url.pathname.replace(/\/+$/, "");
    if (/\/(?:hr\/events|api\/operations\/telegram)$/i.test(prefix)) return;
    url.pathname = `${prefix}/api/operations/telegram`;
    return url.href;
  } catch {
    return;
  }
}

export function operationalReadiness(env: Env): Readiness {
  const missing: string[] = [];
  const invalid: string[] = [];
  if (!env.telegramWebhookSecret) missing.push("TELEGRAM_WEBHOOK_SECRET");
  else if (!/^[A-Za-z0-9_-]{1,256}$/.test(env.telegramWebhookSecret)) {
    invalid.push("TELEGRAM_WEBHOOK_SECRET");
  }
  if (!env.mandoBridgeSecret) missing.push("MANDO_BRIDGE_SECRET");
  else if (!/^[!-~]{1,512}$/.test(env.mandoBridgeSecret)) {
    invalid.push("MANDO_BRIDGE_SECRET");
  }
  if (!env.mandoBackendUrl) missing.push("MANDO_BACKEND_URL");
  else if (!operationalUrl(env.mandoBackendUrl)) invalid.push("MANDO_BACKEND_URL");
  if (env.telegramMode !== "webhook") invalid.push("TELEGRAM_MODE");
  return { ready: missing.length === 0 && invalid.length === 0, missing, invalid };
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function matchesSecret(expected: string, received: string | undefined): boolean {
  if (!received) return false;
  const a = Buffer.from(expected);
  const b = Buffer.from(received);
  return a.length === b.length && timingSafeEqual(a, b);
}

async function readAcceptance(response: Response): Promise<unknown> {
  if (!response.body) throw new Error("missing_acceptance");
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let bytes = 0;
  try {
    for (;;) {
      const chunk = await reader.read();
      if (chunk.done) break;
      bytes += chunk.value.byteLength;
      if (bytes > ACCEPTANCE_LIMIT) throw new Error("acceptance_too_large");
      chunks.push(chunk.value);
    }
    return JSON.parse(Buffer.concat(chunks).toString("utf8")) as unknown;
  } finally {
    void reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

export function operationalTelegramRouter(env: Env): Router {
  const router = Router();
  const readiness = operationalReadiness(env);
  const url = operationalUrl(env.mandoBackendUrl);
  const bridgeSecret = env.mandoBridgeSecret;
  const webhookSecret = env.telegramWebhookSecret;

  router.post("/webhook", (req, res, next) => {
    res.set("Cache-Control", "no-store");
    if (!readiness.ready || !url || !bridgeSecret || !webhookSecret) {
      res.status(503).set("Retry-After", "5").json({ ok: false, error: "bridge_not_configured" });
      return;
    }
    if (!matchesSecret(webhookSecret, req.header("x-telegram-bot-api-secret-token"))) {
      res.status(401).json({ ok: false, error: "invalid_secret" });
      return;
    }
    if (!req.is("application/json")) {
      res.status(415).json({ ok: false, error: "unsupported_media_type" });
      return;
    }
    next();
  }, express.json({ limit: UPDATE_LIMIT, inflate: false }), async (req, res) => {
    const update: unknown = req.body;
    if (!record(update) || !Number.isSafeInteger(update.update_id) || Number(update.update_id) < 0) {
      res.status(400).json({ ok: false, error: "invalid_update" });
      return;
    }
    let body: string;
    try {
      body = JSON.stringify(update);
    } catch {
      res.status(400).json({ ok: false, error: "invalid_update" });
      return;
    }
    if (Buffer.byteLength(body) > UPDATE_LIMIT) {
      res.status(413).json({ ok: false, error: "payload_too_large" });
      return;
    }

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
    try {
      const response = await fetch(url!, {
        method: "POST",
        headers: { "content-type": "application/json", "X-Mando-Bridge-Token": bridgeSecret! },
        body,
        redirect: "manual",
        signal: controller.signal,
      });
      if (DEFINITIVE_REJECTIONS.has(response.status)) {
        void response.body?.cancel().catch(() => {});
        console.warn("[telegram] operational rejection", { update_id: update.update_id, status: response.status });
        res.status(200).json({ ok: false, rejected: true, status: response.status });
        return;
      }
      if (response.status !== 200 && response.status !== 201) {
        void response.body?.cancel().catch(() => {});
        throw new Error("backend_unavailable");
      }
      const accepted = await readAcceptance(response);
      if (!record(accepted) || accepted.ok !== true || typeof accepted.duplicate !== "boolean"
        || !Number.isSafeInteger(accepted.revision) || Number(accepted.revision) < 0) {
        throw new Error("invalid_acceptance");
      }
      res.status(200).json({ ok: true, duplicate: accepted.duplicate, revision: accepted.revision });
    } catch {
      res.status(503).set("Retry-After", "5").json({ ok: false, error: "backend_unavailable" });
    } finally {
      clearTimeout(timer);
      controller.abort();
    }
  });

  const parseError: ErrorRequestHandler = (error: unknown, _req, res, _next) => {
    const status = record(error) && error.status === 413 ? 413
      : record(error) && error.status === 415 ? 415 : 400;
    const code = status === 413 ? "payload_too_large"
      : status === 415 ? "unsupported_media_type" : "invalid_json";
    res.status(status).json({ ok: false, error: code });
  };
  router.use(parseError);
  return router;
}
