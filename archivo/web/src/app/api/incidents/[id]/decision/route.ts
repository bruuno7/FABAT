import { DECIDED_BY_DEFAULT } from "@/lib/decisions";
import { syncPlanFeed } from "@/lib/plan";
import { getStore } from "@/lib/store";

export const dynamic = "force-dynamic";

/**
 * Tarjeta de decisión: el humano confirma la acción propuesta por MANDO.
 * No hay ejecución automática de acciones; queda registrada en el timeline.
 */
export async function POST(
  request: Request,
  ctx: RouteContext<"/api/incidents/[id]/decision">,
) {
  const { id } = await ctx.params;
  const body = (await request.json().catch(() => ({}))) as {
    action?: string;
    note?: string;
    decided_by?: string;
  };

  const action = typeof body.action === "string" ? body.action.trim() : "";
  if (!action) {
    return Response.json({ error: "action es obligatoria" }, { status: 400 });
  }

  const store = getStore();
  const row = store.decide(id, {
    action,
    note: typeof body.note === "string" && body.note.trim() ? body.note.trim() : undefined,
    decided_by:
      typeof body.decided_by === "string" && body.decided_by.trim()
        ? body.decided_by.trim()
        : DECIDED_BY_DEFAULT,
    decided_at: new Date().toISOString(),
  });

  if (!row) {
    return Response.json({ error: "incidencia no encontrada" }, { status: 404 });
  }

  syncPlanFeed(store);
  return Response.json({ ok: true, incident: row });
}
