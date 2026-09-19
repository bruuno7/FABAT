import { isHrToMando } from "@/lib/contract";
import { loadEnv } from "@/lib/env";
import { telegramSendMessage } from "@/lib/hr-client";
import { syncPlanFeed } from "@/lib/plan";
import { getStore } from "@/lib/store";

export const dynamic = "force-dynamic";

/** Callback de HappyRobot -> MANDO (webhook out del workflow). */
export async function POST(request: Request) {
  const env = loadEnv();

  if (env.hrSecret) {
    const got = request.headers.get("x-hr-secret");
    if (got !== env.hrSecret) {
      return Response.json({ error: "invalid hr secret" }, { status: 401 });
    }
  }

  const body = await request.json().catch(() => null);
  if (!isHrToMando(body)) {
    return Response.json(
      { error: "invalid hr_to_mando payload" },
      { status: 400 },
    );
  }

  const store = getStore();
  const row = store.ingestHrEvent(body, "hr");

  let tg: { ok: boolean; skipped: boolean; status: number } | undefined;
  if (body.reply_text && body.chat_id) {
    const sent = await telegramSendMessage(
      env.telegramBotToken,
      body.chat_id,
      body.reply_text,
    );
    tg = { ok: sent.ok, skipped: sent.skipped ?? false, status: sent.status };
  }

  syncPlanFeed(store);

  console.info("[hr] event", {
    event: body.event,
    correlation_id: body.correlation_id,
    triage: row.extract?.triage_color,
    perfil: row.extract?.perfil_color,
    tg,
  });

  return Response.json({ ok: true, telegram: tg, incident: row });
}
