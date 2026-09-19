import { loadEnv } from "@/lib/env";
import { processReport } from "@/lib/pipeline";
import { getStore } from "@/lib/store";
import {
  guessLocationHint,
  telegramUpdateToPublicReport,
  type TelegramUpdate,
} from "@/lib/telegram-map";

export const dynamic = "force-dynamic";

/**
 * Webhook de Telegram (puente gratis paralelo a la web call).
 * En modo simulado el tramo HappyRobot se genera localmente; en modo live se
 * reenvía al Incoming Hook y la respuesta llega por `/api/hr/events`.
 */
export async function POST(request: Request) {
  const env = loadEnv();

  if (env.telegramWebhookSecret) {
    const got = request.headers.get("x-telegram-bot-api-secret-token");
    if (got !== env.telegramWebhookSecret) {
      return Response.json({ error: "invalid telegram secret" }, { status: 401 });
    }
  }

  const update = (await request.json().catch(() => null)) as TelegramUpdate | null;
  if (!update) {
    return Response.json({ ok: true, ignored: true });
  }

  const report = telegramUpdateToPublicReport(update);
  if (!report) {
    return Response.json({ ok: true, ignored: true });
  }

  if (!report.location_hint) {
    const hint = guessLocationHint(report.text);
    if (hint) report.location_hint = hint;
  }

  const result = await processReport(report, "hr", getStore());

  console.info("[telegram] report", {
    correlation_id: result.correlation_id,
    mode: result.mode,
    hr_ok: result.hr?.ok ?? null,
    simulated: result.simulated_events,
  });

  return Response.json({
    ok: true,
    correlation_id: result.correlation_id,
    mode: result.mode,
    simulated_events: result.simulated_events,
  });
}
