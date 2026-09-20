import express, { type Express } from "express";
import { loadEnv, type Env } from "./lib/hr-client.js";
import { createIncidentStore, type IncidentStore } from "./hr/store.js";
import { demoRouter, hrRouter } from "./hr/router.js";
import { stateRouter } from "./hr/state-router.js";
import { telegramRouter } from "./telegram/router.js";
import { operationalReadiness, operationalTelegramRouter } from "./telegram/operational.js";
import {
  createStaffStore,
  type StaffStore,
} from "./telegram/staff-store.js";

export function createApp(
  env: Env = loadEnv(),
  store: IncidentStore = createIncidentStore(),
  staff: StaffStore = createStaffStore(),
): Express {
  const app = express();

  // Vercel rewrite /x → /api may leave the path as /api/x
  app.use((req, _res, next) => {
    if (req.url === "/api") req.url = "/";
    else if (req.url.startsWith("/api?")) req.url = `/${req.url.slice(4)}`;
    else if (req.url.startsWith("/api/")) req.url = req.url.slice(4);
    next();
  });

  if (env.mandoOperational) {
    app.use("/telegram", operationalTelegramRouter(env));
  }

  app.use(express.json({ limit: "1mb" }));

  app.get(["/", "/health"], (_req, res) => {
    const operational = env.mandoOperational ? operationalReadiness(env) : undefined;
    res.status(operational && !operational.ready ? 503 : 200).json({
      ok: operational?.ready ?? true,
      service: "mando-telegram-bridge",
      telegram_token: Boolean(env.telegramBotToken),
      hr_hook_tg: Boolean(env.hrHookTg),
      hr_hook_tg_response: Boolean(env.hrHookTgResponse),
      staff_pin: Boolean(env.staffPin),
      mando_backend: Boolean(env.mandoBackendUrl),
      mode: env.telegramMode,
      operational,
    });
  });

  if (!env.mandoOperational) {
    app.use("/telegram", telegramRouter(env, store, staff));
  }
  app.use("/hr/state", stateRouter(env.stateApi, undefined, {
    mode: env.stateApi?.deliveryMode ?? "sink", telegramToken: env.telegramBotToken,
    allowedTelegramChats: env.stateApi?.allowedTelegramChats ?? [],
  }));
  if (env.mandoOperational) {
    app.use(["/hr", "/demo"], (_req, res) => {
      res.status(409).json({ ok: false, error: "legacy_route_disabled" });
    });
  } else {
    app.use("/hr", hrRouter(env, store));
    app.use("/demo", demoRouter(env, store));
  }

  return app;
}
