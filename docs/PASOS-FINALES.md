# Pasos finales para terminar (cualquiera del equipo) — sáb 19-sep, 19:35

Todo el código está en `main` (PR #17) y en verde: servidor 584/584, núcleo 95/95, puente 40/40.
Demo pública: **https://mando-fabat.onrender.com** (Render, plan gratuito, rama `ana`). Hoy funciona en **simulado**.
Las claves las ha pasado Ana por WhatsApp. **Nunca** en el repo ni en el chat del agente.

## 1. Conectar la demo pública a HappyRobot (5 min) — cualquiera con acceso a Render
Render → servicio **mando-fabat** → **Environment** → **Edit**.
1. En el desplegable junto a «+ Add variable» → **Import from .env** → pega el bloque de claves que pasó Ana → **Add variables**.
2. Corrige estas tres (no son secretas):
   - `MANDO_PUBLIC_URL` = `https://mando-fabat.onrender.com`
   - `TELEGRAM_MODE` = `off` (el bot lo lleva Bruno en Vercel)
   - **Borra** la fila `TELEGRAM_BOT_TOKEN` (si se queda, compite con el bot de Bruno)
3. **Pulsa «Save, rebuild, and deploy»** (sin esto no se guarda nada).
4. Espera a que ponga **Live** (2–4 min) y comprueba en el navegador `https://mando-fabat.onrender.com/api/state` (debe abrir un JSON).
Operador de la Sala: al pedir el token, usa el `MANDO_OPERATOR_TOKEN` del bloque de claves (se entra por `/acceso`).

## 2. Que los avisos de Telegram lleguen a nuestros agentes (15 min) — Bruno
En HappyRobot, en su `fa-entrada-tg` (fork → editar → publicar en development):
- Añadir un nodo **Call Workflow** hacia **`prueba-ana-rapido`** con estos parámetros:
  `texto` (texto del aviso) · `canal` = `telegram` · `zona_sugerida` (si la hay) · `idioma` · `remitente` (alias, nunca chat_id) ·
  `correlation_id` (id del mensaje) · `entrada_json` (todo lo anterior en JSON) ·
  `callback_url` = `https://mando-fabat.onrender.com` · `callback_token` = el `HR_SECRET` del bloque de claves.
- En Vercel: `MANDO_BACKEND_URL` = `https://mando-fabat.onrender.com` → Redeploy.
- Contrato del espejo (asignaciones del staff hacia la Sala): `motor/server/ESPEJO-TELEGRAM.md`.

## 3. Prueba de punta a punta (10 min) — cualquiera
1. Abre `https://mando-fabat.onrender.com/` (la primera visita tarda ~50 s: el plan gratuito se duerme).
2. Manda un aviso al bot de Telegram (o desde `/asistente`): «Hay una pelea en la puerta B, dos personas en el suelo».
3. En ~40 s debe aparecer en la Sala un incidente con la decisión del equipo de agentes (pestaña «Equipo de agentes»).
4. En HappyRobot, pestaña **Runs** de `prueba-ana-rapido`: se ve la ejecución. **Graba las dos pantallas para el vídeo.**
5. Rompe el plan desde `/jurado` y veta algo grave en la Sala.
Si algo falla: la demo local con `./mvp.sh` en simulado siempre funciona.

## 4. Teléfono (opcional, 10 min) — quien tenga el móvil
- Añadir en Render `MANDO_ALLOWED_NUMBERS=+34XXXXXXXXX` (móvil de alguien que acepte la llamada) y `MANDO_VOICE_MODE=phone`.
- Si la llamada a un móvil español da «SIP 403» (número de EE. UU.), volver a `MANDO_VOICE_MODE=web_call`.

## 5. Vídeo de 3 min en inglés (lo más importante) — Talía y Firdaous
Guion segundo a segundo en `docs/VIDEO-3MIN.md`. Planos: Sala (`./mvp.sh` o Render), pestaña Runs de HappyRobot, un móvil
mandando el aviso, el veto, y `python3 -m motor.evals aprende --demo` (aprendizaje día 1 → día 2). Se entiende SIN sonido.

## 6. Entrega antes de las 11:00
Vídeo + URL de la demo (`https://mando-fabat.onrender.com` y `docs/TRY-IT.md`) + repo `github.com/bruuno7/FABAT`.
Pitch de 5 min si somos finalistas: `docs/PITCH-5MIN.md`.

## 7. Después del hackathon: regenerar TODAS las claves
Han pasado por chats: API key de HappyRobot (`prueba-ana-backend`), clave de OpenRouter, token del bot de Telegram,
authtoken de ngrok, `HR_SECRET`, `MANDO_OPERATOR_TOKEN`, `MANDO_MCP_TOKEN`.
