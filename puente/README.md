# MANDO server — adaptador HappyRobot + puente Telegram

Dueña: **Ana** (`AGENTS.md`). Bruno posee specs en `motor/happyrobot`.

## Qué hace

```
Público TG → Bot → POST /telegram/webhook → public_report → HR_HOOK_TG (fa-entrada-tg)
Personal TG → /rol /estado /baja (local) · botones → staff_response → HR_HOOK_TG_RESPONSE
HR agent_reply → POST /hr/events → backend MANDO → sendMessage TG
HR telegram_send / telegram_edit / answer_callback → Bot API
```

También: `POST /hr/events` genérico para webcall y otros canales.

Los puestos de personal viven en memoria del puente (se pierden en un cold start de Vercel). Twin y los workflows de despacho no están en este módulo.

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
2. `setWebhook` con `secret_token` = `TELEGRAM_WEBHOOK_SECRET` (incluye `callback_query`)
3. Rellenar `HR_HOOK_TG` con URL development del Incoming Hook
4. `HR_HOOK_TG_RESPONSE` cuando exista `fa-respuesta-tg`; si falta, los botones no rompen el bot

## Variables

Ver `.env.example`. Nunca commitear `.env`.

| Var | Uso |
|-----|-----|
| `TELEGRAM_BOT_TOKEN` | BotFather |
| `TELEGRAM_WEBHOOK_SECRET` | Header `X-Telegram-Bot-Api-Secret-Token` |
| `HR_HOOK_TG` | Incoming Hook development `fa-entrada-tg` |
| `HR_HOOK_TG_RESPONSE` | Incoming Hook `fa-respuesta-tg` (botones acc/dec/eta/loc/apr/vet) |
| `HR_HOOK_API_KEY` | Si el hook exige `x-api-key` |
| `HR_SECRET` | Valida callbacks HR → puente |
| `STAFF_PIN` | PIN compartido para `/rol`. Obligatorio en producción |
| `HR_API_KEY` | API Editor (crear workflows; opcional en runtime) |
| `HR_WORKFLOW_WEBCALL` | id/slug demo webcall |
| `MANDO_CALLBACK_URL` | URL pública de este server |
| `MANDO_BACKEND_URL` | Backend MANDO público; recibe el aviso estructurado en `/hr/events` |
| `PORT` | default 8787 |

`GET /health` expone booleanos (`hr_hook_tg`, `hr_hook_tg_response`, `staff_pin`, `mando_backend`), nunca los secretos.

## Personal (simulación)

Puestos: `medico`, `staff_entradas`, `organizador`, `bomberos`, `policia`.

| Comando | Efecto |
|---------|--------|
| `/rol medico <PIN>` | Toma el puesto si el PIN coincide y está libre |
| `/estado` | Lista ocupados y libres |
| `/baja` | Suelta el puesto |

Un chat = un puesto. Un puesto = un chat. En local, sin `STAFF_PIN`, `/rol` funciona para poder ensayar. En Vercel, sin PIN no se toma ningún puesto.

`callback_data` de los botones: `kind:assignment_id` o `kind|assignment_id|correlation_id`. Kinds: `acc`, `dec`, `eta`, `loc`, `apr`, `vet`.

## HappyRobot → puente (`POST /hr/events`)

Además de `agent_reply` / `extract_ready` / `needs_human` / `session_ended`:

```json
{
  "event": "telegram_send",
  "chat_id": "123",
  "text": "Persona caída en escenario. ¿Aceptas? (simulación)",
  "reply_markup": {
    "inline_keyboard": [
      [
        { "text": "Acepto", "callback_data": "acc:asg-1" },
        { "text": "No puedo", "callback_data": "dec:asg-1" }
      ]
    ]
  }
}
```

`telegram_edit` (chat_id, message_id, text, reply_markup opcional) y `answer_callback` (callback_query_id, text opcional) usan el mismo endpoint. El puente ya responde al callback al pulsar el botón: `answer_callback` posterior puede fallar y se ignora.

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
4. `HR_HOOK_TG_RESPONSE` y `STAFF_PIN` en Vercel cuando el workflow de respuesta exista
