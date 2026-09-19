/** In-memory triage board for demo (no persistence across serverless cold starts). */
export type IncidentRow = {
  correlation_id: string;
  channel?: string;
  text?: string;
  extract?: Record<string, unknown>;
  reply_text?: string;
  updated_at: string;
};

export function createIncidentStore() {
  const byId = new Map<string, IncidentRow>();
  return {
    upsert(row: IncidentRow) {
      byId.set(row.correlation_id, row);
    },
    get(id: string) {
      return byId.get(id);
    },
    list() {
      return [...byId.values()].sort((a, b) =>
        b.updated_at.localeCompare(a.updated_at),
      );
    },
  };
}

export type IncidentStore = ReturnType<typeof createIncidentStore>;
