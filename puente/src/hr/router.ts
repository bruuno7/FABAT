import { Router } from "express";
import type { Env } from "../lib/hr-client.js";
import {
  checkSecret,
  forwardToMando,
  forwardMandoPath,
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

  // HappyRobot no alcanza el túnel de MANDO: estas rutas reenvían el cerrojo.
  router.post("/tg/dispatch", (req, res) =>
    proxyMando(env, req, res, "/hr/tg/dispatch"),
  );
  router.post("/tg/staff-response", (req, res) =>
    proxyMando(env, req, res, "/hr/tg/staff-response"),
  );

  // Contiene texto de los avisos de personas: mismo secreto que /events.
  router.get("/incidents", (req, res) => {
    const auth = checkSecret(env, env.hrSecret, req.header("x-hr-secret"));
    if (!auth.ok) {
      res.status(auth.status).json({ error: auth.error });
      return;
    }
    res.json({ incidents: store.list() });
  });

  /**
   * POST /hr/tg-reply
   * Permite a MANDO cerrar el loop con el ciudadano que reportó un incidente.
   * Body: { chat_id: string, text: string, correlation_id?: string }
   * Header: x-hr-secret
   *
   * Ejemplo de uso desde MANDO:
   *   POST /hr/tg-reply
   *   { "chat_id": "-1001234567890", "text": "Hemos enviado un equipo médico. Ref: INC-041.", "correlation_id": "tg-..." }
   */
  router.post("/tg-reply", async (req, res) => {
    const auth = checkSecret(env, env.hrSecret, req.header("x-hr-secret"));
    if (!auth.ok) {
      res.status(auth.status).json({ error: auth.error });
      return;
    }

    const body = req.body as {
      chat_id?: unknown;
      text?: unknown;
      correlation_id?: unknown;
    };

    const rawChatId = body.chat_id;
    const chat_id = rawChatId != null ? String(rawChatId).trim() : "";
    const text = typeof body.text === "string" ? body.text.trim() : "";
    const correlation_id =
      typeof body.correlation_id === "string"
        ? body.correlation_id.trim()
        : undefined;

    if (!chat_id) {
      res.status(400).json({ error: "chat_id requerido (string o número)" });
      return;
    }
    if (!text) {
      res.status(400).json({ error: "text requerido (string)" });
      return;
    }

    const sent = await telegramSendMessage(
      env.telegramBotToken,
      chat_id.trim(),
      text.trim(),
    );

    console.info("[hr] tg-reply", {
      chat_id,
      correlation_id: correlation_id ?? null,
      tg: { ok: sent.ok, skipped: sent.skipped ?? false, status: sent.status },
    });

    res.status(sent.ok || sent.skipped ? 200 : 502).json({
      ok: sent.ok,
      skipped: sent.skipped ?? false,
      status: sent.status,
    });
  });

  return router;
}

async function proxyMando(
  env: Env,
  req: { method: string; header: (name: string) => string | undefined; body: unknown },
  res: {
    status: (code: number) => { json: (body: unknown) => void };
    json: (body: unknown) => void;
  },
  path: string,
): Promise<void> {
  const auth = checkSecret(env, env.hrSecret, req.header("x-hr-secret"));
  if (!auth.ok) {
    res.status(auth.status).json({ error: auth.error });
    return;
  }
  const method = req.method.toUpperCase();
  const result = await forwardMandoPath(env.mandoBackendUrl, env.hrSecret, path, {
    method,
    body: method === "GET" ? undefined : JSON.stringify(req.body ?? {}),
  });
  if (result.skipped) {
    res.status(503).json({
      ok: false,
      dispatched: false,
      reason: "mando_unconfigured",
      outbound: null,
      next_outbound: null,
    });
    return;
  }
  let payload: unknown = { ok: result.ok, body: result.body };
  try {
    payload = JSON.parse(result.body);
  } catch {
    // MANDO a veces responde texto; lo envolvemos para que HR no reciba un string crudo.
  }
  res.status(result.status || (result.ok ? 200 : 502)).json(payload);
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
