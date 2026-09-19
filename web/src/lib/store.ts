import "server-only";
import type { FeedEntry, FeedTone } from "./board-types";
import type {
  Channel,
  Decision,
  Extract,
  HrToMando,
  IncidentRow,
  IncidentStatus,
  PublicReport,
  Reporter,
  TimelineEntry,
} from "./contract";

export type { FeedEntry, FeedTone };

export type Store = {
  ingestReport(report: PublicReport, source: "hr" | "sim"): IncidentRow;
  ingestHrEvent(
    event: HrToMando,
    source: "hr" | "sim",
    extra?: { chat_id?: string },
  ): IncidentRow;
  decide(id: string, decision: Decision): IncidentRow | undefined;
  setStatus(id: string, status: IncidentStatus): IncidentRow | undefined;
  log(id: string, kind: string, text: string, tone: FeedTone): void;
  /** Evento de sistema sin incidente asociado (ej. "el plan ha dejado de valer"). */
  notify(text: string, kind: string, tone: FeedTone, correlationId?: string): void;
  get(id: string): IncidentRow | undefined;
  list(): IncidentRow[];
  feed(): FeedEntry[];
  stats(): { incidents: number; feed: number };
  reset(): void;
};

const FEED_MAX = 250;

function nowIso(): string {
  return new Date().toISOString();
}

function mergeExtract(prev: Extract | undefined, next: Extract | undefined): Extract | undefined {
  if (!next) return prev;
  const merged: Extract = { ...prev };
  for (const [k, v] of Object.entries(next)) {
    if (v !== undefined && v !== null && v !== "") {
      (merged as Record<string, unknown>)[k] = v;
    }
  }
  return merged;
}

function toneForEvent(event: HrToMando["event"]): FeedTone {
  if (event === "needs_human") return "danger";
  if (event === "extract_ready") return "warn";
  if (event === "session_ended") return "info";
  return "ok";
}

function timelineKind(event: HrToMando["event"]): TimelineEntry["kind"] {
  switch (event) {
    case "extract_ready":
      return "hr_extract";
    case "agent_reply":
      return "hr_reply";
    case "needs_human":
      return "hr_needs_human";
    default:
      return "hr_session_ended";
  }
}

function createStore(): Store {
  const incidents = new Map<string, IncidentRow>();
  const feedEntries: FeedEntry[] = [];
  let seq = 0;

  function pushFeed(
    entry: Omit<FeedEntry, "id" | "at"> & { at?: string },
  ): FeedEntry {
    seq += 1;
    const full: FeedEntry = {
      id: `f${seq}`,
      at: entry.at ?? nowIso(),
      kind: entry.kind,
      text: entry.text,
      correlation_id: entry.correlation_id,
      tone: entry.tone,
    };
    feedEntries.unshift(full);
    if (feedEntries.length > FEED_MAX) feedEntries.length = FEED_MAX;
    return full;
  }

  function pushTimeline(id: string, entry: TimelineEntry) {
    const row = incidents.get(id);
    if (!row) return;
    row.timeline.push(entry);
    row.updated_at = entry.at;
  }

  function ensureRow(id: string, source: "hr" | "sim"): IncidentRow {
    const existing = incidents.get(id);
    if (existing) return existing;
    const row: IncidentRow = {
      correlation_id: id,
      status: "nuevo",
      timeline: [],
      source,
      reported_at: nowIso(),
      updated_at: nowIso(),
    };
    incidents.set(id, row);
    return row;
  }

  return {
    ingestReport(report, source) {
      const id = report.correlation_id ?? `sim-${Date.now()}-${seq}`;
      const row = ensureRow(id, source);
      row.channel = report.channel as Channel;
      row.text = report.text;
      row.location_hint = report.location_hint;
      row.reported_at = report.reported_at ?? row.reported_at;
      row.updated_at = nowIso();
      row.source = source;

      const reporter: Reporter = { ...row.reporter, ...report.reporter };
      row.reporter = reporter;

      row.timeline.push({
        at: row.reported_at,
        kind: "report_in",
        text: `Aviso por ${report.channel}${reporter.display_name ? ` de ${reporter.display_name}` : ""}`,
      });

      pushFeed({
        kind: "report_in",
        text: report.text,
        correlation_id: id,
        tone: "info",
        at: row.reported_at,
      });

      return row;
    },

    ingestHrEvent(event, source, extra) {
      const row = ensureRow(event.correlation_id, source);
      if (event.channel) row.channel = event.channel as Channel;
      if (event.hr_run_id) row.hr_run_id = event.hr_run_id;
      if (event.reply_text) row.reply_text = event.reply_text;
      if (extra?.chat_id && row.reporter) row.reporter.chat_id = extra.chat_id;
      if (event.chat_id && row.reporter) row.reporter.chat_id = event.chat_id;

      row.extract = mergeExtract(row.extract, event.extract);
      row.updated_at = nowIso();

      const triage = row.extract?.triage_color;
      const sector = row.extract?.sector;
      const text =
        event.event === "agent_reply" && event.reply_text
          ? `HR responde al ciudadano`
          : event.event === "extract_ready"
            ? `Extraído: ${row.extract?.incident_type ?? "?"}${sector ? ` en ${sector}` : ""}${triage ? ` (${triage})` : ""}`
            : event.event === "needs_human"
              ? "HR pide intervención humana"
              : "Sesión HR cerrada";

      pushTimeline(event.correlation_id, {
        at: row.updated_at,
        kind: timelineKind(event.event),
        text,
      });

      if (event.event === "needs_human") row.status = "escalado";

      pushFeed({
        kind: event.event,
        text,
        correlation_id: event.correlation_id,
        tone: toneForEvent(event.event),
      });

      return row;
    },

    decide(id, decision) {
      const row = incidents.get(id);
      if (!row) return undefined;
      row.decision = decision;
      row.status = "asignado";
      row.updated_at = nowIso();
      pushTimeline(id, {
        at: decision.decided_at,
        kind: "decision",
        text: `Decisión (${decision.decided_by}): ${decision.action}${decision.note ? ` — ${decision.note}` : ""}`,
      });
      pushFeed({
        kind: "decision",
        text: `${decision.action}`,
        correlation_id: id,
        tone: "ok",
      });
      return row;
    },

    setStatus(id, status) {
      const row = incidents.get(id);
      if (!row) return undefined;
      row.status = status;
      row.updated_at = nowIso();
      pushTimeline(id, {
        at: row.updated_at,
        kind: "status",
        text: `Estado: ${status}`,
      });
      return row;
    },

    log(id, kind, text, tone) {
      pushTimeline(id, {
        at: nowIso(),
        kind: kind === "allocation" ? "allocation" : "status",
        text,
      });
      pushFeed({ kind, text, correlation_id: id, tone });
    },

    notify(text, kind, tone, correlationId) {
      pushFeed({ kind, text, tone, correlation_id: correlationId });
    },

    get(id) {
      return incidents.get(id);
    },

    list() {
      return [...incidents.values()];
    },

    feed() {
      return feedEntries;
    },

    stats() {
      return { incidents: incidents.size, feed: feedEntries.length };
    },

    reset() {
      incidents.clear();
      feedEntries.length = 0;
      seq = 0;
    },
  };
}

/**
 * Singleton. En `next dev` (un solo proceso) el estado es coherente.
 * En Vercel cada instancia serverless tiene su propia memoria: para demo
 * multi-instancia hay que enchufar un KV aquí (misma interfaz `Store`).
 */
const globalStore = globalThis as unknown as { __mandoStore?: Store };

export function getStore(): Store {
  if (!globalStore.__mandoStore) globalStore.__mandoStore = createStore();
  return globalStore.__mandoStore;
}
