import { Router } from "express";
import type { Env } from "../lib/hr-client.js";
import {
  checkSecret,
  forwardToMando,
  telegramSendMessage,
  forwardToHappyRobot,
  executeTelegramOutbound,
} from "../lib/hr-client.js";
import {
  isHrToMando,
  isPublicReport,
  parseTelegramOutbound,
  toMandoPublicReport,
} from "../lib/contract.js";
import type { IncidentStore } from "./store.js";

export function hrRouter(env: Env, store: IncidentStore): Router {
  const router = Router();

  router.post("/events", async (req, res) => {
    const auth = checkSecret(env, env.hrSecret, req.header("x-hr-secret"));
    if (!auth.ok) {
      res.status(auth.status).json({ error: auth.error });
      return;
    }

    const body = req.body;
    const outbound = parseTelegramOutbound(body);
    if (outbound && "error" in outbound) {
      res.status(400).json({ error: outbound.error });
      return;
    }
    if (outbound) {
      const tg = await executeTelegramOutbound(env, outbound);
      console.info("[hr] telegram_outbound", {
        event: outbound.event,
        tg: { ok: tg.ok, skipped: tg.skipped ?? false, status: tg.status },
      });
      res.status(200).json({
        ok: true,
        telegram: { ok: tg.ok, skipped: tg.skipped, status: tg.status },
      });
      return;
    }

    if (!isHrToMando(body)) {
      res.status(400).json({ error: "invalid hr_to_mando payload" });
      return;
    }

    const prev = store.get(body.correlation_id);
    store.upsert({
      correlation_id: body.correlation_id,
      channel: body.channel ?? prev?.channel,
      text: body.report?.text ?? prev?.text,
      extract:
        (body.extract as Record<string, unknown> | undefined) ?? prev?.extract,
      reply_text: body.reply_text ?? prev?.reply_text,
      updated_at: new Date().toISOString(),
    });

    const report = toMandoPublicReport(body, prev?.text);
    let mando:
      | { ok: boolean; skipped?: boolean; status: number; body: string }
      | undefined;
    if (report) {
      try {
        mando = await forwardToMando(
          env.mandoBackendUrl,
          env.hrSecret,
          report,
        );
      } catch (error) {
        mando = {
          ok: false,
          status: 0,
          body: error instanceof Error ? error.message : "MANDO request failed",
        };
      }
    }

    let backendReply: string | undefined;
    if (mando?.ok) {
      try {
        const parsed = JSON.parse(mando.body) as { say_text?: unknown };
        if (typeof parsed.say_text === "string" && parsed.say_text.trim()) {
          backendReply = parsed.say_text.trim();
        }
      } catch {
        // El backend puede responder sin JSON; la respuesta de HR sigue siendo válida.
      }
    }

    const replyText = body.reply_text?.trim() || backendReply;
    let tg: { ok: boolean; skipped?: boolean; status: number } | undefined;
    if (replyText && body.chat_id) {
      const sent = await telegramSendMessage(
        env.telegramBotToken,
        body.chat_id,
        replyText,
      );
      tg = { ok: sent.ok, skipped: sent.skipped, status: sent.status };
    }

    console.info("[hr] event", {
      event: body.event,
      correlation_id: body.correlation_id,
      triage: body.extract?.triage_color,
      perfil: body.extract?.perfil_color,
      mando: mando
        ? { ok: mando.ok, skipped: mando.skipped ?? false, status: mando.status }
        : undefined,
      tg,
    });

    res.status(200).json({
      ok: true,
      telegram: tg,
      mando: mando
        ? { ok: mando.ok, skipped: mando.skipped ?? false, status: mando.status }
        : undefined,
    });
  });

  // Contiene texto de los avisos de personas: mismo secreto que /events.
  router.get("/incidents", (req, res) => {
    const auth = checkSecret(env, env.hrSecret, req.header("x-hr-secret"));
    if (!auth.ok) {
      res.status(auth.status).json({ error: auth.error });
      return;
    }
    res.json({ incidents: store.list() });
  });

  return router;
}

export function demoRouter(env: Env, store: IncidentStore): Router {
  const router = Router();

  router.post("/public-report", async (req, res) => {
    if (!env.allowDemoInject) {
      res.status(403).json({ error: "ALLOW_DEMO_INJECT!=1" });
      return;
    }
    if (!isPublicReport(req.body)) {
      res.status(400).json({ error: "invalid public_report" });
      return;
    }
    const report = req.body;
    store.upsert({
      correlation_id: report.correlation_id ?? `demo-${Date.now()}`,
      channel: report.channel,
      text: report.text,
      updated_at: new Date().toISOString(),
    });
    const fwd = await forwardToHappyRobot(
      env.hrHookTg,
      report,
      env.hrHookApiKey,
    );
    res.json({ ok: true, hr: fwd });
  });

  return router;
}
