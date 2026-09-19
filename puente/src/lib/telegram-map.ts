import type {
  PerfilColor,
  PublicReport,
  StaffResponse,
  StaffRole,
} from "./contract.js";
import { STAFF_ROLES, STAFF_ROLE_LABELS } from "./contract.js";

export const TELEGRAM_ALLOWED_UPDATES = ["message", "callback_query"] as const;

export type TelegramUser = {
  id: number;
  first_name?: string;
  username?: string;
};

export type TelegramChatMessage = {
  message_id: number;
  text?: string;
  chat: { id: number; type: string };
  from?: TelegramUser;
};

export type TelegramCallbackQuery = {
  id: string;
  from: TelegramUser;
  message?: TelegramChatMessage;
  data?: string;
};

export type TelegramUpdate = {
  update_id: number;
  message?: TelegramChatMessage;
  callback_query?: TelegramCallbackQuery;
};

export const STAFF_CALLBACK_KINDS = [
  "acc",
  "dec",
  "eta",
  "loc",
  "apr",
  "vet",
] as const;

export type StaffCallbackKind = (typeof STAFF_CALLBACK_KINDS)[number];

const COMMAND_RE = /^\/([a-zA-Z0-9_]+)(?:@\w+)?(?:\s|$)/;

const STAFF_ROLE_ALIASES: Record<string, StaffRole> = {
  medico: "medico",
  med: "medico",
  staff_entradas: "staff_entradas",
  entradas: "staff_entradas",
  staff: "staff_entradas",
  organizador: "organizador",
  org: "organizador",
  bomberos: "bomberos",
  bombero: "bomberos",
  policia: "policia",
  poli: "policia",
};

export function parseCommand(text: string): string | null {
  const m = text.trim().match(COMMAND_RE);
  return m ? m[1].toLowerCase() : null;
}

export function parseCommandLine(
  text: string,
): { command: string; args: string[] } | null {
  const command = parseCommand(text);
  if (!command) return null;
  const rest = text.trim().replace(COMMAND_RE, "").trim();
  const args = rest.length > 0 ? rest.split(/\s+/) : [];
  return { command, args };
}

export function foldStaffToken(raw: string): string {
  return raw
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .toLowerCase()
    .replace(/-/g, "_");
}

export function parseStaffRole(raw: string): StaffRole | null {
  return STAFF_ROLE_ALIASES[foldStaffToken(raw)] ?? null;
}

export function displayNameFromUser(
  user: TelegramUser | undefined,
  fallbackId: string,
): string {
  return user?.first_name ?? user?.username ?? `tg:${fallbackId}`;
}

export function parseCallbackData(data: string): {
  kind: string;
  assignment_id?: string;
  correlation_id?: string;
} {
  const raw = data.trim();
  if (!raw) return { kind: "unknown" };
  const parts = raw.includes("|") ? raw.split("|") : raw.split(":");
  const kind = (parts[0] ?? "unknown").toLowerCase().slice(0, 16) || "unknown";
  const assignment_id = emptyToUndef(parts[1]);
  const correlation_id = emptyToUndef(parts[2]);
  return { kind, assignment_id, correlation_id };
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
  const display = displayNameFromUser(msg.from, fromId);

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

export function telegramUpdateToStaffResponse(
  update: TelegramUpdate,
  opts?: { role?: StaffRole },
): StaffResponse | null {
  const cq = update.callback_query;
  if (!cq?.data?.trim()) return null;

  const parsed = parseCallbackData(cq.data);
  const chatId = String(cq.message?.chat.id ?? cq.from.id);
  const fromId = String(cq.from.id);
  const display = displayNameFromUser(cq.from, fromId);
  const correlation_id =
    parsed.correlation_id ?? `tg-cb-${chatId}-${update.update_id}`;
  const textParts = [parsed.kind];
  if (parsed.assignment_id) textParts.push(parsed.assignment_id);

  const response: StaffResponse = {
    event: "staff_response",
    channel: "telegram",
    reported_at: new Date().toISOString(),
    kind: parsed.kind,
    callback_data: cq.data,
    callback_query_id: cq.id,
    chat_id: chatId,
    correlation_id,
    text: textParts.join(" "),
    reporter: {
      external_id: `tg:${fromId}`,
      display_name: display,
      chat_id: chatId,
      perfil_color: "personal",
    },
  };
  if (cq.message?.message_id != null) response.message_id = cq.message.message_id;
  if (parsed.assignment_id) response.assignment_id = parsed.assignment_id;
  if (opts?.role) response.reporter.role = opts.role;
  return response;
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

export function staffOccupancyText(
  claims: { role: StaffRole; display_name: string }[],
  mine?: StaffRole,
): string {
  const taken = new Map(claims.map((c) => [c.role, c.display_name]));
  const lines = ["Puestos (simulación):"];
  for (const role of STAFF_ROLES) {
    const holder = taken.get(role);
    const mark = role === mine ? " ← tú" : "";
    lines.push(
      holder
        ? `· ${STAFF_ROLE_LABELS[role]} — ${holder}${mark}`
        : `· ${STAFF_ROLE_LABELS[role]} — libre`,
    );
  }
  return lines.join("\n");
}

export const BOT_HELP = [
  "MANDO · Festival Abierto",
  "Esto es una simulación de hackathon, no un servicio de emergencias.",
  "",
  "Envía un aviso en texto libre, por ejemplo:",
  "«Persona caída cerca del escenario»",
  "«Aglomeración en la entrada VIP»",
  "",
  "Comandos:",
  "/start — presentación",
  "/ayuda — esta ayuda",
  "/ping — comprueba que el bot responde",
  "",
  "Personal del recinto (simulación):",
  "/rol <puesto> [pin] — tomar un puesto",
  "/estado — tu puesto y los ocupados",
  "/baja — dejar el puesto",
  `Puestos: ${STAFF_ROLES.join(", ")}`,
].join("\n");

function emptyToUndef(v: string | undefined): string | undefined {
  if (v == null || v.trim() === "") return undefined;
  return v.trim();
}
