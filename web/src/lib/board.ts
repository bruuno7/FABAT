import "server-only";
import { allocate } from "./allocate";
import type { Board, BoardIncident } from "./board-types";
import { needsHumanCard } from "./contract";
import { DECIDED_BY_DEFAULT, proposeSummary, suggestActions } from "./decisions";
import { envSummary, loadEnv } from "./env";
import { lessonsFrom } from "./insights";
import { syncPlanFeed } from "./plan";
import { getStore } from "./store";

/**
 * Vista agregada que consume la UI (un solo fetch).
 * Es determinista: mismas filas -> mismo tablero.
 */
export function buildBoard(): Board {
  const store = getStore();
  syncPlanFeed(store);

  const incidents = store.list();
  const allocation = allocate(incidents);
  const covered = new Set(allocation.assignments.map((a) => a.correlation_id));
  const missingById = new Map(
    allocation.overflow.map((o) => [o.correlation_id, o.missing]),
  );

  const rows: BoardIncident[] = incidents
    .map((row) => {
      const assignment = allocation.assignments.find(
        (a) => a.correlation_id === row.correlation_id,
      );
      const overflow = allocation.overflow.find(
        (o) => o.correlation_id === row.correlation_id,
      );

      return {
        ...row,
        priority: assignment?.priority ?? overflow?.priority ?? 0,
        covered: covered.has(row.correlation_id),
        missing: missingById.get(row.correlation_id) ?? [],
        needs_card: needsHumanCard(row),
        proposal: proposeSummary(row),
        suggested: suggestActions(row),
      };
    })
    .sort((a, b) => {
      const diff = b.priority - a.priority;
      if (diff !== 0) return diff;
      return a.reported_at.localeCompare(b.reported_at);
    });

  return {
    env: envSummary(loadEnv()),
    incidents: rows,
    allocation,
    lessons: lessonsFrom(incidents),
    feed: store.feed(),
    decided_by_default: DECIDED_BY_DEFAULT,
    server_time: new Date().toISOString(),
  };
}
