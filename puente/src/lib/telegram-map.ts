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
  is_bot?: boolean;
  first_name?: string;
  last_name?: string;
  username?: string;
};

export type TelegramPhoto = {
  file_id: string;
  file_unique_id: string;
  width: number;
  height: number;
  file_size?: number;
};

export type TelegramLocation = {
  latitude: number;
  longitude: number;
  horizontal_accuracy?: number;
};

export type TelegramChatMessage = {
  message_id: number;
  date?: number;
  text?: string;
  caption?: string;
  photo?: TelegramPhoto[];
  location?: TelegramLocation;
  chat: { id: number; type: string };
  from?: TelegramUser;
  reply_to_message?: { message_id: number };
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

const NUMBERED_ZONES: Array<{ re: RegExp; label: (m: RegExpMatchArray) => string }> = [
  // Escenario 1 / stage 2
  { re: /\b(escenario|stage)\s*([1-9][0-9]*|[a-z]\b)/i, label: (m) => `Escenario ${m[2].toUpperCase()}` },
  // Sector A / sector 3
  { re: /\bsector\s*([a-z0-9]+)/i, label: (m) => `Sector ${m[1].toUpperCase()}` },
  // Zona 4 / zone 4
  { re: /\b(zona|zone)\s*([1-9][0-9]*)/i, label: (m) => `Zona ${m[2]}` },
  // Barra 3 / bar 3
  { re: /\b(barra|bar)\s*([1-9][0-9]*)/i, label: (m) => `Barra ${m[2]}` },
  // Puerta / gate 3
  { re: /\b(puerta|gate)\s*([1-9][0-9]*|[a-z]\b)/i, label: (m) => `Puerta ${m[2].toUpperCase()}` },
  // Salida de emergencia / emergency exit
  { re: /\b(salida|exit)\s*(de\s*emergencia|[0-9a-z]+)/i, label: (m) => `Salida ${m[2].replace(/de\s*emergencia/i, "emergencia").trim()}` },
];

export function guessLocationHint(text: string): string | undefined {
  for (const { re, label } of NUMBERED_ZONES) {
    const m = text.match(re);
    if (m) return label(m);
  }
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

/** Returns an urgency emoji based on keywords in the incident text. */
export function guessSeverityEmoji(text: string): string {
  const lower = text.toLowerCase();
  // Critical — immediate life threat
  const critical = [
    'inconsciente', 'no responde', 'sin pulso', 'parada cardiaca', 'cardiac arrest',
    'no respira', 'not breathing', 'aplastamiento', 'derrumbe', 'incendio', 'fuego',
    'fire', 'arma', 'cuchillo', 'disparo', 'ataque', 'attack', 'terrorista',
    'desmay', 'convulsi', 'epilepsi',
  ];
  // High — urgent but stable
  const high = [
    'herido', 'injured', 'sangr', 'fractura', 'caida', 'caído', 'fell', 'fallen',
    'borracho', 'drunk', 'sobredosis', 'overdose', 'aglomeración', 'aglomeracion',
    'stampede', 'empujones', 'pelea', 'fight', 'agresion', 'agresión',
    'perdido', 'lost child', 'niño perdido', 'robo', 'theft', 'pickpocket',
  ];
  if (critical.some((k) => lower.includes(k))) return '🔴';
  if (high.some((k) => lower.includes(k))) return '🟡';
  return '🟢';
}

/**
 * ACK inmediato a cualquier texto. Neutro a propósito: el mismo chat puede estar dando un aviso nuevo,
 * contestando a una pregunta o hablando con el equipo; quien lo sabe es HappyRobot, que responde 3-6 s después.
 */
export function buildAck(
  correlationId: string,
  _locationHint: string | undefined,
  _text: string,
): string {
  const ref = correlationId.slice(-6).toUpperCase();
  return `Recibido (ref ${ref}). Un momento…`;
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
  '🎪 MANDO · Festival Abierto',
  'Sistema de coordinación de emergencias del recinto.',
  '',
  '📢 Si ves una emergencia, escribe un mensaje en texto libre:',
  '  «Persona caída cerca del escenario principal»',
  '  «Aglomeración peligrosa en la entrada VIP»',
  '  «Niño perdido en zona de food court»',
  '',
  'Incluye la zona si la conoces para agilizar la respuesta.',
  '',
  'Comandos disponibles:',
  '/start — bienvenida',
  '/ayuda — esta ayuda',
  '/ping — comprobar conexión',
  '',
  '🔒 Personal acreditado:',
  '/rol <puesto> [pin] — registrar tu puesto',
  '/estado — ver ocupación de puestos',
  '/baja — liberar tu puesto',
  `Puestos: ${STAFF_ROLES.join(', ')}`,
  '',
  '🚨 En caso de emergencia grave llama al 112.',
].join('\n');

function emptyToUndef(v: string | undefined): string | undefined {
  if (v == null || v.trim() === "") return undefined;
  return v.trim();
}
