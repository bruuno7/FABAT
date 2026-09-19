import "server-only";
import type { PublicReport } from "./contract";
import { loadEnv } from "./env";
import { forwardToHappyRobot, telegramSendMessage, type FetchResult } from "./hr-client";
import { simulateHrLeg } from "./hr-sim";
import { syncPlanFeed } from "./plan";
import { getStore, type Store } from "./store";

export type ProcessResult = {
  correlation_id: string;
  mode: "live" | "simulated";
  /** Resultado del POST al Incoming Hook (solo en modo live). */
  hr: FetchResult | null;
  /** Eventos HR sintetizados localmente (solo en modo simulado). */
  simulated_events: number;
  telegram: FetchResult | null;
};

/**
 * Recorrido completo de un aviso: alta en el tablero -> tramo HR -> (respuesta al
 * ciudadano) -> revaluación del plan.
 *
 * En modo `live` el tramo HR es el workflow real y los eventos llegan después por
 * `POST /api/hr/events`. En modo `simulado` se generan aquí con reglas fijas.
 */
export async function processReport(
  report: PublicReport,
  source: "hr" | "sim" = "hr",
  store: Store = getStore(),
): Promise<ProcessResult> {
  const env = loadEnv();
  const row = store.ingestReport(report, source);
  const id = row.correlation_id;

  let hr: FetchResult | null = null;
  let simulated = 0;

  if (env.hrMode === "live") {
    hr = await forwardToHappyRobot(
      env.hrHookTg,
      { ...report, correlation_id: id },
      env.hrHookApiKey,
    );
  } else {
    for (const event of simulateHrLeg({ ...report, correlation_id: id })) {
      store.ingestHrEvent(event, "sim", {
        chat_id: report.reporter?.chat_id,
      });
      simulated += 1;
    }
  }

  syncPlanFeed(store);

  let telegram: FetchResult | null = null;
  const current = store.get(id);
  const chatId = report.reporter?.chat_id;
  if (current?.reply_text && chatId) {
    telegram = await telegramSendMessage(
      env.telegramBotToken,
      chatId,
      current.reply_text,
    );
  }

  return { correlation_id: id, mode: env.hrMode, hr, simulated_events: simulated, telegram };
}
