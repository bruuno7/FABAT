# Conectar HappyRobot en diez pasos (persona del equipo)

URLs y payloads: [registro de plataforma](../happyrobot/PLATAFORMA_REAL.md),
[contrato y curl completos](WEBHOOKS.md). Configuración no equivale a prueba real.

1. En Settings → API Keys del workspace EU, crear una clave con permisos para lanzar los workflows.
   Mantenerla fuera del repo. No reutilizar la clave como token de webhooks.
2. Abrir los triggers de development y copiar sus URLs. Slugs: teléfono `slug-despacho-telefono`, Web call
   despacho `slug-despacho-webcall`, voz pública `slug-ingesta-voz`, texto `slug-ingesta-texto`, chat `slug-asistente-chat`.
   Los hooks construidos siguen la documentación; confirmar la URL exacta en el editor.
3. Copiar `.env.example` a `.env` local y rellenar la clave, URLs y tokens distintos de operador,
   MCP y callbacks. `HR_ENV=development`. Un enlace explícito prevalece sobre el construido.
   El chat sigue pendiente de publicación/dominio/widget según el registro; no inventar su URL.
4. Arrancar `./mvp.sh real`. Una persona abre, si hace falta, `cloudflared tunnel --url http://127.0.0.1:8000`.
   Copiar la base HTTPS en `MANDO_PUBLIC_URL` y reiniciar. El código no abre túneles.
5. Preparar `contacts.local.json` desde el ejemplo, con móviles consentidos, usando `to_number`.
   Poner esos mismos números E.164 en `MANDO_ALLOWED_NUMBERS`. Nunca emergencias reales.
6. Ejecutar `uv run --project motor/server python -m motor.server doctor`. Resolver cada imprescindible;
   confirmar workflows publicados y librería local de LiveKit. Un 401 sin clave no acredita permisos.
7. Probar ingesta, sin llamada, con variables ya exportadas:
   ```sh
   curl --max-time 10 -X POST "$MANDO_PUBLIC_URL/hr/events" -H "X-Mando-Token: $HR_SECRET" -H 'Content-Type: application/json' \
     -d '{"type":"public_report","event_id":"prueba-manual-1","channel":"email","report":{"text":"Una persona mareada en puerta B"}}'
   ```
   Debe aparecer un aviso. Los curl de parcial/actualización/consulta están en `WEBHOOKS.md` §2.
8. Primera Web call: poner `MANDO_VOICE_MODE=web_call` en `.env` y ejecutar `./mvp.sh real`; abrir una llamada pendiente del panel,
   DESCOLGAR desde HTTPS/localhost, aceptar y decir los minutos. Comprobar callback y sello ACEPTA.
   La llamada usa siete parámetros; la API key nunca llega al navegador.
9. Primer teléfono: poner `MANDO_VOICE_MODE=phone` en `.env` y ejecutar `./mvp.sh real`, móvil consentido en lista blanca.
   Descolgar, aceptar, comprobar provisional y final del run. El curl manual de `WEBHOOKS.md` §1
   lanza una llamada: usar únicamente el móvil autorizado. El `action_id` del callback debe conservar su nonce.
10. Telegram: con webhook del puente Vercel usar `TELEGRAM_MODE=send_only`; sin webhook usar `poll`.
    El puente envía `/hr/events` con `X-Mando-Token`, `type:public_report`, `channel:telegram`,
    `reply_to:<chat_id>`, texto y un `event_id` único por mensaje. El bot responde por `sendMessage`.
    Comprobar aviso → pregunta → respuesta → equipo en camino; `off` apaga el bot por completo.

No hay dirección de email ni número SMS confirmados en el registro: copiar los reales cuando existan.
Las pruebas automáticas usan mocks; audio, publicación y llamadas reales requieren la comprobación humana anterior.
