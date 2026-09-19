import express, { type Express } from "express";
import { loadEnv, type Env } from "./lib/hr-client.js";
import { createIncidentStore } from "./hr/store.js";
import { demoRouter, hrRouter } from "./hr/router.js";
import { telegramRouter } from "./telegram/router.js";

export function createApp(
  env: Env = loadEnv(),
  store = createIncidentStore(),
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
      mando_backend: Boolean(env.mandoBackendUrl),
      mode: env.telegramMode,
    });
  });

  app.use("/telegram", telegramRouter(env, store));
  app.use("/hr", hrRouter(env, store));
  app.use("/demo", demoRouter(env, store));

  return app;
}
