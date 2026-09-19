import { buildBoard } from "@/lib/board";

export const dynamic = "force-dynamic";

/** Tablero completo: incidencias priorizadas + recursos + lecciones + feed. */
export async function GET() {
  return Response.json({ ok: true, ...buildBoard() });
}
