/**
 * Contrato MANDO <-> HappyRobot.
 * Portado desde `motor/server/src/lib/contract.ts` + `motor/happyrobot/webhook_contract.json`.
 * Mantener en sync con el JSON Schema (misma semántica, ampliada con estado operativo).
 */

export type PerfilColor = "menor" | "pmr" | "adulto" | "personal" | "vip";
export type TriageColor =
  | "rojo"
  | "amarillo"
  | "verde"
  | "negro"
  | "desconocido";
export type Channel =
  | "telegram"
  | "webcall"
  | "sms"
  | "voice"
  | "whatsapp"
  | "other";
export type IncidentType =
  | "medica"
  | "aglomeracion"
  | "agresion"
  | "clima"
  | "infra"
  | "otro";
export type IncidentStatus = "nuevo" | "asignado" | "escalado" | "resuelto";

export const PERFIL_LABEL: Record<PerfilColor, string> = {
  menor: "Menor",
  pmr: "PMR",
  adulto: "Adulto",
  personal: "Personal",
  vip: "VIP",
};

export const TRIAGE_LABEL: Record<TriageColor, string> = {
  rojo: "Rojo",
  amarillo: "Amarillo",
  verde: "Verde",
  negro: "Negro",
  desconocido: "Sin triage",
};

export const INCIDENT_TYPE_LABEL: Record<IncidentType, string> = {
  medica: "Médica",
  aglomeracion: "Aglomeración",
  agresion: "Agresión",
  clima: "Clima",
  infra: "Infraestructura",
  otro: "Otro",
};

export const STATUS_LABEL: Record<IncidentStatus, string> = {
  nuevo: "Nuevo",
  asignado: "Asignado",
  escalado: "Escalado",
  resuelto: "Resuelto",
};

export const CHANNEL_LABEL: Record<Channel, string> = {
  telegram: "Telegram",
  webcall: "Web call",
  sms: "SMS",
  voice: "Voz",
  whatsapp: "WhatsApp",
  other: "Otro",
};

export type Reporter = {
  external_id?: string;
  display_name?: string;
  perfil_color?: PerfilColor;
  chat_id?: string;
};

/** Mensaje ciudadano -> MANDO (el que genera el Incoming Hook de HappyRobot). */
export type PublicReport = {
  event: "public_report";
  channel: Channel;
  reported_at: string;
  text: string;
  reporter?: Reporter;
  location_hint?: string;
  correlation_id?: string;
};

/** Extracto determinista producido por el agente HappyRobot (o por el simulador). */
export type Extract = {
  incident_type?: IncidentType;
  sector?: string;
  severity?: number;
  triage_color?: TriageColor;
  perfil_color?: PerfilColor;
  summary?: string;
};

/** HappyRobot -> MANDO. */
export type HrToMando = {
  event: "extract_ready" | "agent_reply" | "needs_human" | "session_ended";
  correlation_id: string;
  channel?: Channel;
  chat_id?: string;
  reply_text?: string;
  extract?: Extract;
  hr_run_id?: string;
};

export type Decision = {
  action: string;
  note?: string;
  decided_by: string;
  decided_at: string;
};

export type TimelineEntry = {
  at: string;
  kind:
    | "report_in"
    | "hr_extract"
    | "hr_reply"
    | "hr_needs_human"
    | "hr_session_ended"
    | "allocation"
    | "decision"
    | "status";
  text: string;
};

/** Fila operativa del tablero. No forma parte del contrato con HR. */
export type IncidentRow = {
  correlation_id: string;
  channel?: Channel;
  text?: string;
  reporter?: Reporter;
  location_hint?: string;
  extract?: Extract;
  reply_text?: string;
  hr_run_id?: string;
  status: IncidentStatus;
  decision?: Decision;
  timeline: TimelineEntry[];
  source: "hr" | "sim";
  reported_at: string;
  updated_at: string;
};

export function clampSeverity(v: unknown): number | undefined {
  if (typeof v !== "number" || Number.isNaN(v)) return undefined;
  return Math.min(5, Math.max(1, Math.round(v)));
}

export function isPerfilColor(v: unknown): v is PerfilColor {
  return (
    typeof v === "string" &&
    ["menor", "pmr", "adulto", "personal", "vip"].includes(v)
  );
}

export function isTriageColor(v: unknown): v is TriageColor {
  return (
    typeof v === "string" &&
    ["rojo", "amarillo", "verde", "negro", "desconocido"].includes(v)
  );
}

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

const HR_EVENTS = new Set([
  "extract_ready",
  "agent_reply",
  "needs_human",
  "session_ended",
]);

export function isHrToMando(body: unknown): body is HrToMando {
  if (!body || typeof body !== "object") return false;
  const b = body as Record<string, unknown>;
  return (
    typeof b.event === "string" &&
    HR_EVENTS.has(b.event) &&
    typeof b.correlation_id === "string"
  );
}

/** ¿Este incidente exige tarjeta de decisión con confirmación humana? */
export function needsHumanCard(row: Pick<IncidentRow, "extract">): boolean {
  const e = row.extract ?? {};
  if (e.triage_color === "rojo" || e.triage_color === "negro") return true;
  if ((e.severity ?? 0) >= 4) return true;
  if (e.incident_type === "agresion") return true;
  return false;
}
