import { STATUS_LABEL, type IncidentStatus } from "@/lib/contract";
import { syncPlanFeed } from "@/lib/plan";
import { getStore } from "@/lib/store";

export const dynamic = "force-dynamic";

const STATUSES = Object.keys(STATUS_LABEL) as IncidentStatus[];

/** Cambia el estado operativo (p. ej. marcar `resuelto` libera recursos). */
export async function PATCH(
  request: Request,
  ctx: RouteContext<"/api/incidents/[id]">,
) {
  const { id } = await ctx.params;
  const body = (await request.json().catch(() => ({}))) as {
    status?: string;
  };
  const status = body.status as IncidentStatus | undefined;

  if (!status || !STATUSES.includes(status)) {
    return Response.json(
      { error: `status debe ser uno de: ${STATUSES.join(", ")}` },
      { status: 400 },
    );
  }

  const store = getStore();
  const row = store.setStatus(id, status);
  if (!row) {
    return Response.json({ error: "incidencia no encontrada" }, { status: 404 });
  }

  syncPlanFeed(store);
  return Response.json({ ok: true, incident: row });
}
