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
  extract?: {
    incident_type?: string;
    sector?: string;
    severity?: number;
    triage_color?: TriageColor;
    perfil_color?: PerfilColor;
    summary?: string;
  };
  hr_run_id?: string;
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
