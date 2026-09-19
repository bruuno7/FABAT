import type { Env } from "../lib/hr-client.js";
import { forwardToHappyRobot, telegramSendMessage } from "../lib/hr-client.js";
import {
  BOT_HELP,
  parseCommand,
  telegramUpdateToPublicReport,
  type TelegramUpdate,
} from "../lib/telegram-map.js";
import type { IncidentStore } from "../hr/store.js";

export type HandleResult = {
  ok: boolean;
  ignored?: boolean;
  correlation_id?: string;
  command?: string;
  hr?: { ok: boolean; skipped: boolean; status: number };
  replies: string[];
};

/**
 * Core bot logic: commands locally; free text → ACK + HappyRobot Incoming Hook.
 */
export async function handleTelegramUpdate(
  env: Env,
  update: TelegramUpdate,
  store?: IncidentStore,
): Promise<HandleResult> {
  const msg = update.message;
  if (!msg?.text?.trim()) {
    return { ok: true, ignored: true, replies: [] };
  }

  const chatId = String(msg.chat.id);
  const text = msg.text.trim();
  const command = parseCommand(text);

  if (command === "start" || command === "ayuda" || command === "help") {
    const reply = BOT_HELP;
    await telegramSendMessage(env.telegramBotToken, chatId, reply);
    return { ok: true, command, replies: [reply] };
  }

  if (command === "ping") {
    const reply = "pong — puente Telegram activo";
    await telegramSendMessage(env.telegramBotToken, chatId, reply);
    return { ok: true, command, replies: [reply] };
  }

  if (command) {
    const reply = `Comando /${command} no reconocido.\n\n${BOT_HELP}`;
    await telegramSendMessage(env.telegramBotToken, chatId, reply);
    return { ok: true, command, replies: [reply] };
  }

  const report = telegramUpdateToPublicReport(update);
  if (!report) {
    return { ok: true, ignored: true, replies: [] };
  }

  const ack = report.location_hint
    ? `Recibido (sector ~${report.location_hint}). Lo paso a MANDO…`
    : "Recibido. Lo paso a MANDO…";
  await telegramSendMessage(env.telegramBotToken, chatId, ack);

  store?.upsert({
    correlation_id: report.correlation_id!,
    channel: "telegram",
    text: report.text,
    updated_at: new Date().toISOString(),
  });

  const fwd = await forwardToHappyRobot(
    env.hrHookTg,
    report,
    env.hrHookApiKey,
  );

  const replies = [ack];

  // Sin HR configurado: respuesta local para poder probar el bot solo
  if (fwd.skipped) {
    const local =
      "HappyRobot aún no está enlazado (falta HR_HOOK_TG). " +
      "Tu aviso quedó registrado en el puente. Ref: " +
      report.correlation_id;
    await telegramSendMessage(env.telegramBotToken, chatId, local);
    replies.push(local);
  }

  console.info("[telegram] report", {
    correlation_id: report.correlation_id,
    fwd_ok: fwd.ok,
    fwd_skipped: fwd.skipped ?? false,
    fwd_status: fwd.status,
  });

  return {
    ok: true,
    correlation_id: report.correlation_id,
    hr: {
      ok: fwd.ok,
      skipped: fwd.skipped ?? false,
      status: fwd.status,
    },
    replies,
  };
}
