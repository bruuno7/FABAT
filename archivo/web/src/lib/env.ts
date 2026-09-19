import "server-only";

/**
 * Variables de entorno del server (equivalente a `motor/server/src/lib/hr-client.ts#loadEnv`).
 * Sin secretos por defecto: si no hay `HR_HOOK_TG`, la app corre en modo simulado.
 */
export type Env = {
  hrHookTg?: string;
  hrHookApiKey?: string;
  hrSecret?: string;
  hrWorkflowWebcall?: string;
  telegramBotToken?: string;
  telegramWebhookSecret?: string;
  mandoCallbackUrl: string;
  /** `live` = HappyRobot real; `simulated` = extractor determinista local. */
  hrMode: "live" | "simulated";
  /** Habilita las rutas `/api/demo/*` (por defecto sí en modo simulado). */
  allowDemoInject: boolean;
};

function emptyToUndef(v: string | undefined): string | undefined {
  if (v == null || v.trim() === "") return undefined;
  return v.trim();
}

export function loadEnv(env: NodeJS.ProcessEnv = process.env): Env {
  const hrHookTg = emptyToUndef(env.HR_HOOK_TG);
  return {
    hrHookTg,
    hrHookApiKey: emptyToUndef(env.HR_HOOK_API_KEY),
    hrSecret: emptyToUndef(env.HR_SECRET),
    hrWorkflowWebcall: emptyToUndef(env.HR_WORKFLOW_WEBCALL),
    telegramBotToken: emptyToUndef(env.TELEGRAM_BOT_TOKEN),
    telegramWebhookSecret: emptyToUndef(env.TELEGRAM_WEBHOOK_SECRET),
    mandoCallbackUrl: env.MANDO_CALLBACK_URL ?? "http://127.0.0.1:3000",
    hrMode: hrHookTg ? "live" : "simulated",
    allowDemoInject: env.ALLOW_DEMO_INJECT === "1" || !hrHookTg,
  };
}

/** Resumen seguro para exponer en `/api/health` (nunca valores, solo booleanos). */
export function envSummary(env: Env) {
  return {
    hr_mode: env.hrMode,
    hr_hook_tg: Boolean(env.hrHookTg),
    hr_secret: Boolean(env.hrSecret),
    telegram_token: Boolean(env.telegramBotToken),
    telegram_secret: Boolean(env.telegramWebhookSecret),
    mando_callback_url: env.mandoCallbackUrl,
  };
}
