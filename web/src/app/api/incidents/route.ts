import { loadEnv } from "@/lib/env";
import { resetPlanSignature, syncPlanFeed } from "@/lib/plan";
import { getStore } from "@/lib/store";

export const dynamic = "force-dynamic";

/** Lista cruda de incidencias (sin agregados del tablero). */
export async function GET() {
  const store = getStore();
  return Response.json({ ok: true, incidents: store.list() });
}

/** Vacía el tablero para empezar una demo limpia. */
export async function DELETE() {
  const env = loadEnv();
  if (!env.allowDemoInject) {
    return Response.json(
      { error: "demo deshabilitada (ALLOW_DEMO_INJECT!=1 y modo live)" },
      { status: 403 },
    );
  }
  const store = getStore();
  store.reset();
  resetPlanSignature();
  syncPlanFeed(store, true);
  return Response.json({ ok: true, reset: true });
}
