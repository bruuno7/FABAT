import "server-only";
import type { PublicReport } from "./contract";

export type FetchResult = {
  ok: boolean;
  status: number;
  body: string;
  skipped?: boolean;
};

/**
 * POST del `public_report` al Incoming Hook de `fa-entrada-tg` (o `fa-webcall`).
 * Portado de `motor/server/src/lib/hr-client.ts`.
 */
export async function forwardToHappyRobot(
  hookUrl: string | undefined,
  report: PublicReport,
  apiKey?: string,
): Promise<FetchResult> {
  if (!hookUrl) {
    return {
      ok: false,
      status: 0,
      body: "HR_HOOK_TG not configured",
      skipped: true,
    };
  }

  const headers: Record<string, string> = {
    "content-type": "application/json",
  };
  if (apiKey) headers["x-api-key"] = apiKey;

  try {
    const res = await fetch(hookUrl, {
      method: "POST",
      headers,
      body: JSON.stringify(report),
    });
    const body = await res.text();
    return { ok: res.ok, status: res.status, body };
  } catch (err) {
    return {
      ok: false,
      status: 0,
      body: `HR hook error: ${(err as Error).message}`,
    };
  }
}

/** Respuesta al ciudadano por Telegram. Portado de `motor/server/src/lib/hr-client.ts`. */
export async function telegramSendMessage(
  token: string | undefined,
  chatId: string,
  text: string,
): Promise<FetchResult> {
  if (!token) {
    return {
      ok: false,
      status: 0,
      body: "TELEGRAM_BOT_TOKEN not configured",
      skipped: true,
    };
  }

  try {
    const res = await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ chat_id: chatId, text }),
    });
    const body = await res.text();
    return { ok: res.ok, status: res.status, body };
  } catch (err) {
    return {
      ok: false,
      status: 0,
      body: `Telegram error: ${(err as Error).message}`,
    };
  }
}
