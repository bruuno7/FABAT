# Setup bot Telegram → puente → HappyRobot

Esta guía corresponde al modo legado. Para `MANDO_OPERATIONAL=1`, seguir
[ingreso operativo duradero](README.md#ingreso-operativo-duradero-opt-in):
webhook único hacia MANDO, sin hooks Telegram de HappyRobot ni polling.

HappyRobot = backend de conversación. Este server (local o Vercel) solo es el **puente HTTPS**.

```
Público TG → /telegram/webhook → public_report → HR_HOOK_TG (fa-entrada-tg)
Personal TG → /rol (local) · botones → staff_response → HR_HOOK_TG_RESPONSE
HR → /hr/events → telegram_send / telegram_edit / agent_reply
```

## 1. Crear el bot

1. Habla con [@BotFather](https://t.me/BotFather) → `/newbot`
2. Guarda el **token** (nunca en git)
3. Anota el username (`@tu_bot`)

## 2. Variables (local)

```bash
cd puente
cp .env.example .env
# edita .env
```

Mínimo para probar solo Telegram (sin HR):

```
TELEGRAM_BOT_TOKEN=123456:ABC…
TELEGRAM_MODE=poll
ALLOW_DEMO_INJECT=1
STAFF_PIN=         # opcional en local; /rol funciona sin PIN
```

## 3. Probar en local (sin HTTPS)

```bash
npm install
npm test
npm run poll
```

En Telegram: `/start`, `/ping`, un aviso tipo «caído en escenario», luego `/rol medico` y `/estado`.

Sin `HR_HOOK_TG` el bot confirma y dice que HR aún no está enlazado.
Sin `HR_HOOK_TG_RESPONSE` un botón se acusa igual y avisa de que falta el hook.

## 4. HTTPS con Vercel (repo ya conectado)

1. En el proyecto Vercel de FABAT, Framework Preset: **Other**
2. Root Directory: dejar raíz del repo (usa `vercel.json`)
3. Añadir Environment Variables (Production + Preview):
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_WEBHOOK_SECRET` (string aleatorio A-Z a-z 0-9 _ -)
   - `HR_HOOK_TG` (cuando exista el Incoming Hook)
   - `HR_HOOK_TG_RESPONSE` (cuando exista `fa-respuesta-tg`; si falta, se omite)
   - `STAFF_PIN` (obligatorio para `/rol` en producción)
   - `HR_HOOK_API_KEY` (si el hook lo pide)
   - `HR_SECRET` (compartido con el webhook saliente de HR)
   - `MANDO_CALLBACK_URL` = `https://<tu-proyecto>.vercel.app`
4. Deploy (cuando aceptes push / merge)
5. Registrar webhook (incluye `callback_query`):

```bash
cd puente
# .env con token + MANDO_CALLBACK_URL=https://….vercel.app
npm run telegram:set-webhook
```

URL resultante: `https://….vercel.app/telegram/webhook`

Comprobar `GET /health`: `hr_hook_tg_response` y `staff_pin` deben ser `true` cuando esas vars estén en Vercel. Nunca pegues el PIN ni URLs privadas del hook en un PR.

## 5. HappyRobot (`fa-entrada-tg`)

Opción **B** (UI): seguir `motor/happyrobot/recipes/fa-entrada-tg.md`  
Opción **A**: API key Editor + crear workflow por API/MCP

Webhook saliente HR → `https://….vercel.app/hr/events` header `x-hr-secret`.

Para despachar al personal, `fa-despacho-tg` POST `/hr/tg/dispatch` (este puente reenvía a MANDO)
y luego `telegram_send` con `inline_keyboard`. Las pulsaciones vuelven como `staff_response` a
`HR_HOOK_TG_RESPONSE` (`kind` = acc|dec|eta|loc|apr|vet) → `fa-respuesta-tg`.

## Qué necesito de ti (para live)

1. Token BotFather (solo en chat / Vercel env / `.env` local — no en commit)
2. ¿Nombre del bot?
3. (A) key Editor HR o (B) creas tú el workflow con la receta
4. URL Vercel del proyecto (`MANDO_CALLBACK_URL`)
5. Un `STAFF_PIN` inventado para los 5 chats de personal (solo en Vercel / `.env`)
