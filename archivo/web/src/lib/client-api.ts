import type { Board, InjectResponse } from "./board-types";
import type { PerfilColor } from "./contract";

export async function fetchBoard(): Promise<Board> {
  const res = await fetch("/api/board", { cache: "no-store" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()) as Board;
}

export type InjectInput = {
  text: string;
  perfil_color?: PerfilColor;
  channel?: "telegram" | "webcall" | "sms" | "voice" | "whatsapp" | "other";
  display_name?: string;
  location_hint?: string;
  correlation_id?: string;
};

export async function injectReport(
  input: InjectInput,
): Promise<InjectResponse> {
  const res = await fetch("/api/demo/public-report", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(input),
  });
  const data = (await res.json()) as InjectResponse;
  if (!res.ok) throw new Error(data.error ?? `HTTP ${res.status}`);
  return data;
}

export async function decideIncident(
  id: string,
  action: string,
  note?: string,
): Promise<void> {
  const res = await fetch(`/api/incidents/${encodeURIComponent(id)}/decision`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ action, note }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.error ?? `HTTP ${res.status}`);
  }
}

export async function setIncidentStatus(
  id: string,
  status: string,
): Promise<void> {
  const res = await fetch(`/api/incidents/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ status }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.error ?? `HTTP ${res.status}`);
  }
}

export async function resetBoard(): Promise<void> {
  const res = await fetch("/api/incidents", { method: "DELETE" });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.error ?? `HTTP ${res.status}`);
  }
}
