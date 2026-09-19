export type PerfilColor = "menor" | "pmr" | "adulto" | "personal" | "vip";
export type TriageColor =
  | "rojo"
  | "amarillo"
  | "verde"
  | "negro"
  | "desconocido";

export type StaffRole =
  | "medico"
  | "staff_entradas"
  | "organizador"
  | "bomberos"
  | "policia";

export const STAFF_ROLES: readonly StaffRole[] = [
  "medico",
  "staff_entradas",
  "organizador",
  "bomberos",
  "policia",
];

export const STAFF_ROLE_LABELS: Record<StaffRole, string> = {
  medico: "Médico",
  staff_entradas: "Staff entradas",
  organizador: "Organizador",
  bomberos: "Bomberos",
  policia: "Policía",
};

export type PublicReport = {
  event: "public_report";
  channel: "telegram" | "webcall" | "sms" | "voice" | "whatsapp" | "other";
  reported_at: string;
  text: string;
  reporter?: {
    external_id?: string;
    display_name?: string;
    perfil_color?: PerfilColor;
    chat_id?: string;
  };
  location_hint?: string;
  correlation_id?: string;
};

export type StaffResponse = {
  event: "staff_response";
  channel: "telegram";
  reported_at: string;
  kind: string;
  callback_data: string;
  callback_query_id: string;
  chat_id: string;
  message_id?: number;
  assignment_id?: string;
  correlation_id: string;
  text: string;
  reporter: {
    external_id: string;
    display_name: string;
    chat_id: string;
    perfil_color: "personal";
    role?: StaffRole;
  };
};

export type InlineKeyboardButton = {
  text: string;
  callback_data?: string;
};

export type ReplyMarkup = {
  inline_keyboard: InlineKeyboardButton[][];
};

export type TelegramSendEvent = {
  event: "telegram_send";
  chat_id: string;
  text: string;
  reply_markup?: ReplyMarkup;
  correlation_id?: string;
};

export type TelegramEditEvent = {
  event: "telegram_edit";
  chat_id: string;
  message_id: number;
  text: string;
  reply_markup?: ReplyMarkup;
  correlation_id?: string;
};

export type AnswerCallbackEvent = {
  event: "answer_callback";
  callback_query_id: string;
  text?: string;
  show_alert?: boolean;
};

export type TelegramOutbound =
  | TelegramSendEvent
  | TelegramEditEvent
  | AnswerCallbackEvent;

export type HrToMando = {
  event: "extract_ready" | "agent_reply" | "needs_human" | "session_ended";
  correlation_id: string;
  channel?: string;
  chat_id?: string;
  reply_text?: string;
  hr_run_id?: string;
  report?: {
    channel?: string;
    text?: string;
    zone_hint?: string;
    source?: string;
    lang?: string;
  };
  extract?: {
    incident_type?: string;
    sector?: string;
    severity?: number;
    triage_color?: TriageColor;
    perfil_color?: PerfilColor;
    summary?: string;
  };
};

export type MandoPublicReport = {
  schema: "mando.hr.v1";
  type: "public_report";
  message: "public_report";
  final: true;
  event_id: string;
  hr_run_id: string;
  channel: string;
  reply_to: string;
  report: {
    channel: string;
    text: string;
    zone_hint: string;
    source: string;
    lang: string;
  };
  extracted: Record<string, unknown>;
};

export function isPublicReport(body: unknown): body is PublicReport {
  if (!body || typeof body !== "object") return false;
  const b = body as Record<string, unknown>;
  return (
    b.event === "public_report" &&
    typeof b.channel === "string" &&
    typeof b.reported_at === "string" &&
    typeof b.text === "string" &&
    b.text.length > 0
  );
}

export function isHrToMando(body: unknown): body is HrToMando {
  if (!body || typeof body !== "object") return false;
  const b = body as Record<string, unknown>;
  const events = new Set([
    "extract_ready",
    "agent_reply",
    "needs_human",
    "session_ended",
  ]);
  return (
    typeof b.event === "string" &&
    events.has(b.event) &&
    typeof b.correlation_id === "string"
  );
}

export function isStaffResponse(body: unknown): body is StaffResponse {
  if (!body || typeof body !== "object") return false;
  const b = body as Record<string, unknown>;
  return (
    b.event === "staff_response" &&
    b.channel === "telegram" &&
    typeof b.kind === "string" &&
    typeof b.callback_query_id === "string" &&
    typeof b.chat_id === "string" &&
    typeof b.correlation_id === "string"
  );
}

/** Adapta la respuesta de fa-entrada-tg al contrato estable del backend MANDO. */
export function toMandoPublicReport(
  body: HrToMando,
  fallbackText?: string,
): MandoPublicReport | null {
  if (body.event !== "agent_reply") return null;

  const text = (body.report?.text ?? fallbackText ?? "").trim();
  if (!text) return null;

  const channel = body.report?.channel ?? body.channel ?? "telegram";
  const extracted = body.extract ?? {};
  return {
    schema: "mando.hr.v1",
    type: "public_report",
    message: "public_report",
    final: true,
    event_id: `${body.correlation_id}-final`,
    hr_run_id: body.hr_run_id ?? "",
    channel,
    reply_to: body.chat_id ?? "",
    report: {
      channel,
      text,
      zone_hint: body.report?.zone_hint ?? extracted.sector ?? "",
      source: body.report?.source ?? "telegram_bridge",
      lang: body.report?.lang ?? "es",
    },
    extracted: {
      category: extracted.incident_type ?? "otro",
      location: extracted.sector ?? "",
      description: extracted.summary ?? "",
      severity: extracted.severity ?? 1,
      triage_color: extracted.triage_color ?? "desconocido",
      perfil_color: extracted.perfil_color ?? "desconocido",
    },
  };
}

const CALLBACK_DATA_MAX = 64;

export function normalizeReplyMarkup(raw: unknown): ReplyMarkup | undefined {
  if (!raw || typeof raw !== "object") return undefined;
  const keyboard = (raw as { inline_keyboard?: unknown }).inline_keyboard;
  if (!Array.isArray(keyboard)) return undefined;

  const inline_keyboard: InlineKeyboardButton[][] = [];
  for (const row of keyboard) {
    if (!Array.isArray(row)) return undefined;
    const buttons: InlineKeyboardButton[] = [];
    for (const cell of row) {
      if (!cell || typeof cell !== "object") return undefined;
      const text = (cell as { text?: unknown }).text;
      if (typeof text !== "string" || !text.trim()) return undefined;
      const button: InlineKeyboardButton = { text: text.trim() };
      const data = (cell as { callback_data?: unknown }).callback_data;
      if (data != null) {
        if (typeof data !== "string") return undefined;
        const encoded = Buffer.byteLength(data, "utf8");
        if (encoded > CALLBACK_DATA_MAX) return undefined;
        button.callback_data = data;
      }
      buttons.push(button);
    }
    inline_keyboard.push(buttons);
  }
  return { inline_keyboard };
}

export function parseTelegramOutbound(
  body: unknown,
): TelegramOutbound | { error: string } | null {
  if (!body || typeof body !== "object") return null;
  const b = body as Record<string, unknown>;
  if (typeof b.event !== "string") return null;

  if (b.event === "telegram_send") {
    if (typeof b.chat_id !== "string" || !b.chat_id.trim()) {
      return { error: "telegram_send requires chat_id" };
    }
    if (typeof b.text !== "string" || !b.text.trim()) {
      return { error: "telegram_send requires text" };
    }
    const markup = readMarkup(b);
    if ("error" in markup) return markup;
    const event: TelegramSendEvent = {
      event: "telegram_send",
      chat_id: b.chat_id,
      text: b.text,
    };
    if (markup.value) event.reply_markup = markup.value;
    if (typeof b.correlation_id === "string") {
      event.correlation_id = b.correlation_id;
    }
    return event;
  }

  if (b.event === "telegram_edit") {
    if (typeof b.chat_id !== "string" || !b.chat_id.trim()) {
      return { error: "telegram_edit requires chat_id" };
    }
    if (typeof b.message_id !== "number" || !Number.isFinite(b.message_id)) {
      return { error: "telegram_edit requires message_id" };
    }
    if (typeof b.text !== "string" || !b.text.trim()) {
      return { error: "telegram_edit requires text" };
    }
    const markup = readMarkup(b);
    if ("error" in markup) return markup;
    const event: TelegramEditEvent = {
      event: "telegram_edit",
      chat_id: b.chat_id,
      message_id: b.message_id,
      text: b.text,
    };
    if (markup.value) event.reply_markup = markup.value;
    if (typeof b.correlation_id === "string") {
      event.correlation_id = b.correlation_id;
    }
    return event;
  }

  if (b.event === "answer_callback") {
    if (typeof b.callback_query_id !== "string" || !b.callback_query_id.trim()) {
      return { error: "answer_callback requires callback_query_id" };
    }
    const event: AnswerCallbackEvent = {
      event: "answer_callback",
      callback_query_id: b.callback_query_id,
    };
    if (typeof b.text === "string" && b.text.trim()) event.text = b.text.trim();
    if (typeof b.show_alert === "boolean") event.show_alert = b.show_alert;
    return event;
  }

  return null;
}

function readMarkup(
  b: Record<string, unknown>,
): { value?: ReplyMarkup } | { error: string } {
  if (b.reply_markup == null) return {};
  const value = normalizeReplyMarkup(b.reply_markup);
  if (!value) return { error: "invalid reply_markup" };
  return { value };
}
