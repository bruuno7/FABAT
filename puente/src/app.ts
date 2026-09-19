import express, { type Express } from "express";
import { loadEnv, type Env } from "./lib/hr-client.js";
import { createIncidentStore, type IncidentStore } from "./hr/store.js";
import { demoRouter, hrRouter } from "./hr/router.js";
import { stateRouter } from "./hr/state-router.js";
import { telegramRouter } from "./telegram/router.js";
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

  app.use(express.json({ limit: "1mb" }));

  app.get(["/", "/health"], (_req, res) => {
    res.json({
      ok: true,
      service: "mando-telegram-bridge",
      telegram_token: Boolean(env.telegramBotToken),
      hr_hook_tg: Boolean(env.hrHookTg),
      hr_hook_tg_response: Boolean(env.hrHookTgResponse),
      staff_pin: Boolean(env.staffPin),
      mando_backend: Boolean(env.mandoBackendUrl),
      mode: env.telegramMode,
    });
  });

  app.use("/telegram", telegramRouter(env, store, staff));
  app.use("/hr/state", stateRouter(env.stateApi));
  app.use("/hr", hrRouter(env, store));
  app.use("/demo", demoRouter(env, store));

  return app;
}
