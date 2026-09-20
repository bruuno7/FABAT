import { Router } from "express";
import {
  checkSecret,
  executeTelegramOutbound,
  forwardMandoBridge,
  telegramSendMessage,
  type Env,
} from "../lib/hr-client.js";
import { isHrToMando, parseTelegramOutbound } from "../lib/contract.js";

/**
 * En modo operativo HappyRobot sigue decidiendo por Telegram (`fa-entrada-tg`,
 * `fa-despacho-tg`, `fa-respuesta-tg`), pero MANDO es la autoridad durable.
 *
 * Este router es la única puerta `/hr/*` viva en modo operativo y sólo acepta:
 *  - `mirror`: espejo de solo lectura (ofertas, aceptación, ETA, hitos, preguntas)
 *    que se reenvía a MANDO para que la interfaz lo pinte.
 *  - `telegram_send` / `telegram_edit` / `answer_callback`: mensajes al bot.
 *  - `agent_reply` con `chat_id` y `reply_text`: respuesta al ciudadano.
 *
 * No crea ofertas, no asigna roles ni reserva capacidad: eso vive en MANDO y en la
 * interfaz queda como override humano.
 */
export function operationalHrRouter(env: Env): Router {
  const router = Router();

  router.post("/events", async (req, res) => {
    res.set("Cache-Control", "no-store");
    const auth = checkSecret(env, env.hrSecret, req.header("x-hr-secret"));
    if (!auth.ok) {
      res.status(auth.status).json({ error: auth.error });
      return;
    }

    const body = req.body as Record<string, unknown> | undefined;
    if (!body || typeof body !== "object" || Array.isArray(body)) {
      res.status(400).json({ ok: false, error: "invalid_body" });
      return;
    }

    const mirror = readMirror(body);
    if (mirror && "error" in mirror) {
      res.status(400).json({ ok: false, error: mirror.error });
      return;
    }

    const parsed = parseTelegramOutbound(body);
    if (parsed && "error" in parsed) {
      res.status(400).json({ ok: false, error: parsed.error });
      return;
    }

    const reply = isHrToMando(body) && body.reply_text && body.chat_id
      ? { chat_id: String(body.chat_id), text: String(body.reply_text) }
      : null;

    if (!mirror && !parsed && !reply) {
      res.status(400).json({ ok: false, error: "nothing_to_apply" });
      return;
    }

    const result: Record<string, unknown> = { ok: true };

    if (mirror) {
      const forwarded = await forwardMandoBridge(
        env.mandoBackendUrl,
        env.mandoBridgeSecret,
        "/api/operations/happyrobot",
        { events: mirror.events },
      );
      result.mirror = {
        ok: forwarded.ok,
        skipped: forwarded.skipped ?? false,
        status: forwarded.status,
      };
      if (!forwarded.ok && !forwarded.skipped) {
        res.status(502).json({ ...result, ok: false });
        return;
      }
    }

    if (parsed) {
      const tg = await executeTelegramOutbound(env, parsed);
      result.telegram = { ok: tg.ok, skipped: tg.skipped ?? false, status: tg.status };
    } else if (reply) {
      const tg = await telegramSendMessage(env.telegramBotToken, reply.chat_id, reply.text);
      result.telegram = { ok: tg.ok, skipped: tg.skipped ?? false, status: tg.status };
    }

    result.revision = 0;
    res.status(200).json(result);
  });

  return router;
}

/** Acepta un espejo explícito (`mirror`) o un único evento `tg_*` como cuerpo. */
function readMirror(
  body: Record<string, unknown>,
): { events: unknown[] } | { error: string } | null {
  const raw = body.mirror;
  if (raw == null) {
    const type = body.type;
    if (typeof type === "string" && type.startsWith("tg_")) return { events: [body] };
    return null;
  }
  if (!Array.isArray(raw) || raw.length === 0 || raw.length > 50) {
    return { error: "invalid mirror" };
  }
  return { events: raw };
}
