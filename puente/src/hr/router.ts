import { Router } from "express";
import type { Env } from "../lib/hr-client.js";
import { telegramSendMessage } from "../lib/hr-client.js";
import { isHrToMando, isPublicReport } from "../lib/contract.js";
import { forwardToHappyRobot } from "../lib/hr-client.js";

/** In-memory triage board for demo (no persistence). */
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

export function hrRouter(env: Env, store: IncidentStore): Router {
  const router = Router();

  router.post("/events", async (req, res) => {
    if (env.hrSecret) {
      const got = req.header("x-hr-secret");
      if (got !== env.hrSecret) {
        res.status(401).json({ error: "invalid hr secret" });
        return;
      }
    }

    const body = req.body;
    if (!isHrToMando(body)) {
      res.status(400).json({ error: "invalid hr_to_mando payload" });
      return;
    }

    const prev = store.get(body.correlation_id);
    store.upsert({
      correlation_id: body.correlation_id,
      channel: body.channel ?? prev?.channel,
      text: prev?.text,
      extract: (body.extract as Record<string, unknown> | undefined) ?? prev?.extract,
      reply_text: body.reply_text ?? prev?.reply_text,
      updated_at: new Date().toISOString(),
    });

    let tg: { ok: boolean; skipped?: boolean; status: number } | undefined;
    if (body.reply_text && body.chat_id) {
      const sent = await telegramSendMessage(
        env.telegramBotToken,
        body.chat_id,
        body.reply_text,
      );
      tg = { ok: sent.ok, skipped: sent.skipped, status: sent.status };
    }

    console.info("[hr] event", {
      event: body.event,
      correlation_id: body.correlation_id,
      triage: body.extract?.triage_color,
      perfil: body.extract?.perfil_color,
      tg,
    });

    res.status(200).json({ ok: true, telegram: tg });
  });

  router.get("/incidents", (_req, res) => {
    res.json({ incidents: store.list() });
  });

  return router;
}

export function demoRouter(env: Env, store: IncidentStore): Router {
  const router = Router();

  router.post("/public-report", async (req, res) => {
    if (!env.allowDemoInject) {
      res.status(403).json({ error: "ALLOW_DEMO_INJECT!=1" });
      return;
    }
    if (!isPublicReport(req.body)) {
      res.status(400).json({ error: "invalid public_report" });
      return;
    }
    const report = req.body;
    store.upsert({
      correlation_id: report.correlation_id ?? `demo-${Date.now()}`,
      channel: report.channel,
      text: report.text,
      updated_at: new Date().toISOString(),
    });
    const fwd = await forwardToHappyRobot(
      env.hrHookTg,
      report,
      env.hrHookApiKey,
    );
    res.json({ ok: true, hr: fwd });
  });

  return router;
}
