/**
 * Tipos compartidos entre server y cliente.
 * Sin `server-only` a propósito: la UI los importa directamente.
 */
import type { Allocation, ResourceKind } from "./allocate";
import type { IncidentRow } from "./contract";
import type { Lesson } from "./insights";

export type FeedTone = "info" | "ok" | "warn" | "danger";

export type FeedEntry = {
  id: string;
  at: string;
  kind: string;
  text: string;
  correlation_id?: string;
  tone: FeedTone;
};

export type BoardIncident = IncidentRow & {
  /** Prioridad de cola calculada por MANDO. */
  priority: number;
  covered: boolean;
  missing: ResourceKind[];
  needs_card: boolean;
  proposal: string;
  suggested: string[];
};

export type BoardEnv = {
  hr_mode: "live" | "simulated";
  hr_hook_tg: boolean;
  hr_secret: boolean;
  telegram_token: boolean;
  telegram_secret: boolean;
  mando_callback_url: string;
};

export type Board = {
  env: BoardEnv;
  incidents: BoardIncident[];
  allocation: Allocation;
  lessons: Lesson[];
  feed: FeedEntry[];
  decided_by_default: string;
  server_time: string;
};

export type InjectResponse = {
  ok: boolean;
  correlation_id: string;
  mode: "live" | "simulated";
  simulated_events: number;
  extract?: BoardIncident["extract"];
  reply_text?: string;
  error?: string;
};
