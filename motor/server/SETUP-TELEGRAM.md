# Setup bot Telegram → puente → HappyRobot

HappyRobot = backend de conversación. Este server (local o Vercel) solo es el **puente HTTPS**.

```
Usuario TG → Bot → /telegram/webhook → public_report → HR Incoming Hook (fa-entrada-tg)
HR responde → /hr/events → sendMessage TG
```

## 1. Crear el bot

1. Habla con [@BotFather](https://t.me/BotFather) → `/newbot`
2. Guarda el **token** (nunca en git)
3. Anota el username (`@tu_bot`)

## 2. Variables (local)

```bash
cd motor/server
cp .env.example .env
# edita .env
```

Mínimo para probar solo Telegram (sin HR):

```
TELEGRAM_BOT_TOKEN=123456:ABC…
TELEGRAM_MODE=poll
ALLOW_DEMO_INJECT=1
```

## 3. Probar en local (sin HTTPS)

```bash
npm install
npm test
npm run poll
```

En Telegram: `/start`, `/ping`, luego un aviso tipo «caído en escenario».

Sin `HR_HOOK_TG` el bot confirma y dice que HR aún no está enlazado.

## 4. HTTPS con Vercel (repo ya conectado)

1. En el proyecto Vercel de FABAT, Framework Preset: **Other**
2. Root Directory: dejar raíz del repo (usa `vercel.json`)
3. Añadir Environment Variables (Production + Preview):
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_WEBHOOK_SECRET` (string aleatorio A-Z a-z 0-9 _ -)
   - `HR_HOOK_TG` (cuando exista el Incoming Hook)
   - `HR_HOOK_API_KEY` (si el hook lo pide)
   - `HR_SECRET` (compartido con el webhook saliente de HR)
   - `MANDO_CALLBACK_URL` = `https://<tu-proyecto>.vercel.app`
4. Deploy (cuando aceptes push / merge)
5. Registrar webhook:

```bash
cd motor/server
# .env con token + MANDO_CALLBACK_URL=https://….vercel.app
npm run telegram:set-webhook
```

URL resultante: `https://….vercel.app/telegram/webhook`

## 5. HappyRobot (`fa-entrada-tg`)

Opción **B** (UI): seguir `motor/happyrobot/recipes/fa-entrada-tg.md`  
Opción **A**: API key Editor + crear workflow por API/MCP

Webhook saliente HR → `https://….vercel.app/hr/events` header `x-hr-secret`.

## Qué necesito de ti (para live)

1. Token BotFather (solo en chat / Vercel env / `.env` local — no en commit)
2. ¿Nombre del bot?
3. (A) key Editor HR o (B) creas tú el workflow con la receta
4. URL Vercel del proyecto (`MANDO_CALLBACK_URL`)

**Sin push** hasta que aceptes los cambios locales.
