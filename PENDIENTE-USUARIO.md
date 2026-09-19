# PENDIENTE DEL USUARIO — bot Telegram

Para probar **solo el bot** en local (ya listo en working tree, sin push):

1. Token BotFather → `motor/server/.env` como `TELEGRAM_BOT_TOKEN`
2. `cd motor/server && npm install && npm run poll`
3. En Telegram: `/start`, `/ping`, aviso libre

Para **HTTPS con Vercel** (repo ya conectado):

1. Preset **Other**, vars de entorno en el dashboard (ver `motor/server/SETUP-TELEGRAM.md`)
2. Aceptar push/deploy de estos cambios
3. `MANDO_CALLBACK_URL=https://….vercel.app` + `npm run telegram:set-webhook`

Para enlazar **HappyRobot**:

- (A) API key Editor, o (B) crear `fa-entrada-tg` con la receta UI
- Pegar URL Incoming Hook en `HR_HOOK_TG`
