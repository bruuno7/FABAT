import { isPerfilColor, isPublicReport, type PublicReport } from "@/lib/contract";
import { loadEnv } from "@/lib/env";
import { processReport } from "@/lib/pipeline";
import { getStore } from "@/lib/store";

export const dynamic = "force-dynamic";

type InjectBody = {
  text?: string;
  perfil_color?: string;
  channel?: string;
  display_name?: string;
  location_hint?: string;
  correlation_id?: string;
};

const CHANNELS = ["telegram", "webcall", "sms", "voice", "whatsapp", "other"];

/**
 * Inyecta un aviso como si viniera del ciudadano (simulador y web call).
 * Si el body ya es un `public_report` completo, se respeta tal cual.
 */
export async function POST(request: Request) {
  const env = loadEnv();
  if (!env.allowDemoInject) {
    return Response.json(
      { error: "demo deshabilitada (ALLOW_DEMO_INJECT!=1 y modo live)" },
      { status: 403 },
    );
  }

  const body = (await request.json().catch(() => null)) as
    | (InjectBody & { event?: string })
    | null;
  if (!body) {
    return Response.json({ error: "body JSON requerido" }, { status: 400 });
  }

  const report = isPublicReport(body)
    ? (body as PublicReport)
    : buildReport(body);

  if (!report) {
    return Response.json(
      { error: "text es obligatorio (o un public_report válido)" },
      { status: 400 },
    );
  }

  const store = getStore();
  const result = await processReport(report, "sim", store);
  const row = store.get(result.correlation_id);

  return Response.json({
    ok: true,
    correlation_id: result.correlation_id,
    mode: result.mode,
    simulated_events: result.simulated_events,
    extract: row?.extract,
    reply_text: row?.reply_text,
    incident: row,
  });
}

function buildReport(body: InjectBody): PublicReport | null {
  const text = typeof body.text === "string" ? body.text.trim() : "";
  if (!text) return null;

  const channel =
    typeof body.channel === "string" && CHANNELS.includes(body.channel)
      ? (body.channel as PublicReport["channel"])
      : "webcall";

  return {
    event: "public_report",
    channel,
    reported_at: new Date().toISOString(),
    text,
    reporter: {
      external_id: `sim:${body.display_name ?? "asistente"}`,
      display_name: body.display_name ?? "Asistente",
      perfil_color: isPerfilColor(body.perfil_color)
        ? body.perfil_color
        : "adulto",
      chat_id: "sim-chat",
    },
    location_hint: body.location_hint,
    correlation_id:
      body.correlation_id ?? `sim-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
  };
}
