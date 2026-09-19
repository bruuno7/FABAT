import express from "express";
import { loadEnv } from "./lib/hr-client.js";
import { createIncidentStore, demoRouter, hrRouter } from "./hr/router.js";
import { telegramRouter } from "./telegram/router.js";

const env = loadEnv();
const store = createIncidentStore();
const app = express();

app.use(express.json({ limit: "1mb" }));

app.get("/health", (_req, res) => {
  res.json({
    ok: true,
    service: "mando-server",
    telegram_token: Boolean(env.telegramBotToken),
    hr_hook_tg: Boolean(env.hrHookTg),
    mode: env.telegramMode,
  });
});

app.use("/telegram", telegramRouter(env));
app.use("/hr", hrRouter(env, store));
app.use("/demo", demoRouter(env, store));

app.listen(env.port, () => {
  console.info(
    `[mando] listening :${env.port} callback=${env.mandoCallbackUrl}`,
  );
});
