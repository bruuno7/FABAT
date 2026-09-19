export type PerfilColor = "menor" | "pmr" | "adulto" | "personal" | "vip";
export type TriageColor =
  | "rojo"
  | "amarillo"
  | "verde"
  | "negro"
  | "desconocido";

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
