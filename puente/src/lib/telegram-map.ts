import type { PerfilColor, PublicReport } from "./contract.js";

export type TelegramUpdate = {
  update_id: number;
  message?: {
    message_id: number;
    text?: string;
    chat: { id: number; type: string };
    from?: { id: number; first_name?: string; username?: string };
  };
};

const COMMAND_RE = /^\/([a-zA-Z0-9_]+)(?:@\w+)?(?:\s|$)/;

export function parseCommand(text: string): string | null {
  const m = text.trim().match(COMMAND_RE);
  return m ? m[1].toLowerCase() : null;
}

export function telegramUpdateToPublicReport(
  update: TelegramUpdate,
  opts?: { perfil_color?: PerfilColor },
): PublicReport | null {
  const msg = update.message;
  if (!msg?.text?.trim()) return null;

  // Commands are not incident reports
  if (parseCommand(msg.text)) return null;

  const chatId = String(msg.chat.id);
  const fromId = msg.from?.id != null ? String(msg.from.id) : chatId;
  const display =
    msg.from?.first_name ?? msg.from?.username ?? `tg:${fromId}`;

  const report: PublicReport = {
    event: "public_report",
    channel: "telegram",
    reported_at: new Date().toISOString(),
    text: msg.text.trim(),
    reporter: {
      external_id: `tg:${fromId}`,
      display_name: display,
      chat_id: chatId,
      perfil_color: opts?.perfil_color ?? "adulto",
    },
    correlation_id: `tg-${chatId}-${update.update_id}`,
  };

  const hint = guessLocationHint(msg.text);
  if (hint) report.location_hint = hint;
  return report;
}

export function guessLocationHint(text: string): string | undefined {
  const lower = text.toLowerCase();
  const sectors = [
    "escenario",
    "entrada",
    "salida",
    "food",
    "baños",
    "banos",
    "vip",
    "parking",
    "campamento",
  ];
  return sectors.find((s) => lower.includes(s));
}

export const BOT_HELP = [
  "MANDO · Festival Abierto",
  "",
  "Envía un aviso en texto libre, por ejemplo:",
  "«Persona caída cerca del escenario»",
  "«Aglomeración en la entrada VIP»",
  "",
  "Comandos:",
  "/start — presentación",
  "/ayuda — esta ayuda",
  "/ping — comprueba que el bot responde",
].join("\n");
