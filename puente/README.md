# MANDO server — adaptador HappyRobot + puente Telegram

Dueña: **Ana** (`AGENTS.md`). Bruno posee specs en `motor/happyrobot`.

## Qué hace

```
Usuario TG → Bot → POST /telegram/webhook → public_report → HR Incoming Hook
HR agente → POST /hr/events → sendMessage TG
```

También: `POST /hr/events` genérico para webcall y otros canales.

## Arranque local

```bash
cd puente
cp .env.example .env   # rellenar sin commitear
npm install
npm test
npm run dev
```

Polling (sin HTTPS):

```bash
npm run poll
```

Webhook (con túnel CF / similar):

1. Exponer `https://…/telegram/webhook`
2. `setWebhook` con `secret_token` = `TELEGRAM_WEBHOOK_SECRET`
3. Rellenar `HR_HOOK_TG` con URL development del Incoming Hook

## Variables

Ver `.env.example`. Nunca commitear `.env`.

| Var | Uso |
|-----|-----|
| `TELEGRAM_BOT_TOKEN` | BotFather |
| `TELEGRAM_WEBHOOK_SECRET` | Header `X-Telegram-Bot-Api-Secret-Token` |
| `HR_HOOK_TG` | Incoming Hook development `fa-entrada-tg` |
| `HR_HOOK_API_KEY` | Si el hook exige `x-api-key` |
| `HR_SECRET` | Valida callbacks HR → MANDO |
| `HR_API_KEY` | API Editor (crear workflows; opcional en runtime) |
| `HR_WORKFLOW_WEBCALL` | id/slug demo webcall |
| `MANDO_CALLBACK_URL` | URL pública de este server |
| `PORT` | default 8787 |

## Endpoints

| Método | Ruta | Auth |
|--------|------|------|
| GET | `/health` | — |
| POST | `/telegram/webhook` | `X-Telegram-Bot-Api-Secret-Token` si configurado |
| POST | `/hr/events` | `x-hr-secret` si `HR_SECRET` set |
| POST | `/demo/public-report` | solo si `ALLOW_DEMO_INJECT=1` |

## Bloqueado hasta

1. Token BotFather
2. (A) HR Editor key o (B) workflow creado a mano + `HR_HOOK_TG`
3. HTTPS público o decisión de usar `npm run poll`
