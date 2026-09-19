# PENDIENTE — lo que queda hasta la entrega (domingo 04:00; el evento cierra a las 05:00)

Cómo arrancar todo: `./mvp.sh` (local, simulado) · `./mvp.sh lan` (móviles de la misma wifi) · `./mvp.sh real` (HappyRobot y Telegram reales, lee `.env`) · `./mvp.sh check` (todos los tests). Pantalla de mando en `/`, app del público en `/asistente`, y `/duelo`, `/memoria`, `/caos`, `/informe`.

## 1. Primera llamada real por HappyRobot  — LO MÁS URGENTE (personas)

1. `cp .env.example .env` y rellenar: `HR_API_KEY` (Settings → API keys; subirle el rol a edición), `HR_SECRET` (inventado), `HR_ENV=development`, `MANDO_ALLOWED_NUMBERS=+34…` (tu móvil), `MANDO_COMMS=happyrobot`, `MANDO_VOICE_MODE=phone`.
2. Copiar del editor de la plataforma la URL del trigger del workflow `mando-despacho-telefono` → `HR_HOOK_DISPATCH`; la del workflow `mando-ingesta-texto` → `HR_HOOK_INTAKE`.
3. `cp motor/server/contacts.example.json motor/server/contacts.local.json` y poner el móvil del punto 1 al recurso que vaya a recibir la llamada.
4. `./mvp.sh real`; en otra terminal `cloudflared tunnel --url http://127.0.0.1:8000`; copiar la URL https a `MANDO_PUBLIC_URL` (y a `MANDO_BACKEND_URL` en Vercel, ver punto 3) y reiniciar.
5. `uv run --project motor/server python -m motor.server doctor` hasta que no diga FALTA.
6. Cargar `demo-gates`, dar a play: suena el móvil → «afirmativo, tres minutos» → la pantalla pone ACEPTA. **Grabarlo.**
7. Si el JSON de vuelta llega roto (comillas en la transcripción), quitar `transcript` del cuerpo del nodo Webhook final del workflow.

## 2. Plataforma HappyRobot (una persona con el editor abierto)

- Publicar en development los borradores `mando-asistente-chat` y `mando-ingesta-voz` v2: antes hay que abrir «View Tool Call Result» en cada una de sus tools (SIN pulsar Generate).
- Email: enviar un correo de prueba a la dirección del trigger de `mando-ingesta-email` para que exponga sus variables; después cablear Extract → Classify → Webhook `public_report` con `channel:"email"`.
- Desactivar «Enhanced security» de la Web call en el entorno que se enseñe, o nadie sin cuenta podrá abrir el enlace.
- Ejecutar una vez los tests adversarios y crear un test a partir de un fallo real (`extract-from-run`); apuntar el % de northstars aprobadas con su N.

## 3. Puerta pública en Vercel (`puente/`)

Vercel no ejecuta un servidor que escucha: `puente/` debe desplegarse como función (rama `codex/vercel-telegram-bridge`, en revisión). En el panel de Vercel: **Root Directory = `puente`**, variables `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, `HR_SECRET`, `HR_HOOK_TG`, `MANDO_BACKEND_URL` (la URL del túnel del punto 1). Después, `setWebhook` hacia `https://fabat.vercel.app/telegram/webhook` (comando exacto en `puente/README.md`).
**Un bot de Telegram solo admite UN consumidor**: mientras el webhook esté activo, arrancar el backend con `TELEGRAM_MODE=send_only`; para volver a local, `deleteWebhook` y `TELEGRAM_MODE=poll`.

## 4. Código (en curso; quien lo coja que avise)

- Conexión completa de la interfaz a HappyRobot (estado por workflow en la pantalla, botones de voz/Telegram/email/SMS desde configuración, entendimiento de texto delegado con caída a local).
- Presentación segura: `./mvp.sh demo` (comprobación previa + qué canales van en real), botón «saltar al momento clave», ensayo automático del guion (`python -m motor.server ensayo`), límites de frecuencia y tokens con URL pública, `motor/server/PRESENTACION-SEGURA.md`.
- `TELEGRAM_MODE=poll|send_only|off` en el backend.
- Gemelo digital visible (`/gemelo`: ahora frente a dentro de 15 min, con el error medido del pronóstico). Solo si sobra tiempo.
- Comprobación VISUAL de todas las pantallas en un navegador y en un móvil real (nadie la ha hecho aún).
- Léxico de Mando: «uno respira bien, el otro está mareado» se lee como parada (falta límite de palabra en el patrón `no respira`).

## 5. Contenido y entrega (personas)

- Validar `motor/protocolos/PROTOCOLOS.md` (hoja de 15 min; hay 7 discrepancias entre fuentes que decidir) — responsable sanitaria del equipo.
- 40 frases reales de avisos escritas por gente ajena para medir el parser, y prueba del agente de voz con ruido de concierto.
- Vídeo de 3 minutos (tiene que entenderse sin sonido): v0 a las 16:00. Quien contesta la llamada, mejor alguien de fuera del equipo.
- Preguntar a la organización: hora de cierre del formulario, duración e idioma del vídeo, formato de la demo en sala.
- A las 22:00: congelar el código y volver a medir (`./mvp.sh cifras`, `python3 -m motor.harness load`, `python3 -m motor.harness day2 --n 400`); actualizar las cifras de `README.md` y `MVP.md` con su N.
- Entrega: hasta el final, SIEMPRE `hackspain submit --draft`.
