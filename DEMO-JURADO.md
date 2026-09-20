# Demo rápida: Telegram → Sala → llamada

La demo reutiliza el backend y la interfaz ResQval. Añade una guía en `/jurado`, cuatro personajes y una base SQLite independiente. No modifica el despliegue habitual ni su bot.

## Ensayar ahora, sin proveedores

Desde la raíz del repositorio, con Python ≥3.12 y `uv`:

```sh
uv sync --project motor/server --frozen
uv run --project motor/server python -m motor.server.demo_jurado --data "$HOME/resqval-jurado-local"
```

Abre `http://127.0.0.1:8000/jurado`. El token **solo para este ensayo local** es `jurado-local`, salvo que hayas configurado `MANDO_OPERATOR_TOKEN`.

1. Entra; abre **Sala completa** en otra pestaña.
2. En la guía, despliega **Alternativa desde la web** y registra el incidente.
3. Selecciona **Médico**: Aceptar → Confirmar ETA → Llegada → Localización → Finalización.
4. Observa cómo se actualiza la Sala. Seguridad y Accesos muestran sus propias tareas cuando el incidente necesita esos roles.
5. El Organizador abre la Sala, propone una acción grave desde el detalle del incidente y revisa la aprobación pendiente.

Estos botones registran hitos manuales. Cambiar de personaje es una vista de ensayo del operador, no autenticación independiente ni permisos restringidos por rol.

Se conservan los datos al reiniciar. Para repetir, termina las llamadas si las hubiera y usa **Sala → Mantenimiento → Reiniciar incidencias**. Para otro festival vacío, elige otro directorio. Nunca se borra una base desde el lanzador.

## Telegram y llamadas reales: un servicio Railway de demo

Este recorrido reducido usa **Telegram directamente con MANDO** y **HappyRobot para voz**. No depende del workflow rápido ni del despacho conversacional de Telegram: el planificador operativo asigna el médico. No necesita otro Vercel.

### 1. Servicio separado

En el mismo proyecto Railway, crea **otro servicio desde este repositorio** con la revisión que incluya esta demo. Conserva el servicio habitual. Usa el Dockerfile existente y un volumen **nuevo** montado en `/data`.

Configura este comando de inicio:

```sh
uv run --project motor/server python -m motor.server.demo_jurado --data /data/jurado --connected --host 0.0.0.0
```

El lanzador lee `PORT` automáticamente (8000 por defecto). Genera un dominio HTTPS para este servicio y úsalo como `MANDO_PUBLIC_URL`. Una sola réplica. Para presentar, abre `https://<dominio-demo>/jurado`.

### 2. Variables privadas

Copia desde la configuración privada del servicio actual los valores de HappyRobot y los móviles consentidos. **No copies su base de datos ni su token de bot.** Crea un bot dedicado en [BotFather](https://t.me/BotFather) con `/newbot`; comparte su enlace con el equipo.

```text
MANDO_OPERATOR_TOKEN=<nuevo token privado para entrar en esta demo>
MANDO_PUBLIC_URL=https://<dominio-demo>
TELEGRAM_BOT_TOKEN=<token del NUEVO bot de demo>
TELEGRAM_WEBHOOK_SECRET=<nuevo secreto aleatorio>
HR_API_KEY=<clave HappyRobot EU existente>
HR_API_BASE=https://platform.eu.happyrobot.ai/api/v2
HR_ENV=production
HR_WORKFLOW_DISPATCH=<workflow telefónico compatible publicado>
HR_SECRET=<secreto privado de firma de callbacks>
MANDO_ALLOWED_NUMBERS=+34XXXXXXXXX,+34YYYYYYYYY
```

Genera los secretos nuevos con tu gestor de contraseñas o `openssl rand -hex 32`. No los guardes en Git ni los muestres al proyectar. El lanzador exige estos valores antes de activar entregas externas, prepara los perfiles inicialmente por canal Web y no carga `.env` automáticamente.

El workflow telefónico debe admitir `callback_url`, `callback_token`, `assignment_id`, `expected_assignment_version`, `destination_zone_id`, `correlation_id` y `sequence`, y devolver aceptación/ETA al callback de esta demo. El identificador usado en la prueba histórica fue `01a0b84b-b7cc-7e30-83a4-1bd5c7169215`; confirma su versión publicada antes de reutilizarlo.

### 3. Conectar el bot dedicado

Con `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET` y `MANDO_PUBLIC_URL` disponibles en una terminal privada, registra el webhook **del bot de demo**:

```sh
curl --fail-with-body -sS -X POST \
  "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
  --data-urlencode "url=${MANDO_PUBLIC_URL%/}/telegram/webhook" \
  --data-urlencode "secret_token=${TELEGRAM_WEBHOOK_SECRET}" \
  --data-urlencode 'allowed_updates=["message","callback_query"]' \
  --data-urlencode 'drop_pending_updates=false'

curl --fail-with-body -sS \
  "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getWebhookInfo"
```

Debe devolver `ok: true`, la URL de la demo y, después de un mensaje, no acumular errores de entrega. **No cambies el webhook del bot habitual.** Referencia oficial: [Telegram Bot API · setWebhook](https://core.telegram.org/bots/api#setwebhook).

### 4. Preparar los personajes y presentar

En `/jurado`, entra con el token privado:

- **Organizador:** proyecta la Sala completa.
- **Médico:** guarda en la guía su móvil autorizado. Hazlo antes de crear el incidente.
- **Asistente al festival:** otra persona abre el bot nuevo, pulsa Iniciar y escribe: «SIMULACRO: una persona inconsciente, no respira, en puerta B».
- **Seguridad y Accesos:** preparados por Web. Sus tareas se pueden representar en la guía. Para probar respuestas de un trabajador por Telegram, regístralo en Personal con identificador `tg:<su from.id>`, contacto igual a ese ID numérico y rol correspondiente; debe haber iniciado conversación con el bot. Marca no disponible el personaje Web equivalente si quieres que se oferte al trabajador Telegram.

El médico responde a la llamada: **«Confirmo puerta B, acepto, llego en tres minutos»**. Espera a que aparezcan aceptación y ETA. Después representa llegada, localización y finalización por separado. En el modo conectado, la guía no ofrece aceptar manualmente una oferta telefónica pendiente.

Si no llama: comprueba que el médico está por canal Voz y sin asignación activa, que su número está en la lista y revisa **Comunicaciones / Entregas**. Una entrega fallida o incierta requiere revisión; no genera rellamadas automáticas. No reinicies incidencias durante una llamada.

## Qué demuestra cada modo

| Ensayo local | Demo conectada |
|---|---|
| Incidentes, roles, reservas y estados reales en SQLite aislada | Lo mismo, con transporte externo habilitado |
| Hitos introducidos manualmente por el operador | Aceptación/ETA desde los callbacks de una llamada, si se reciben |
| No envía Telegram ni llama | Requiere bot, HTTPS, workflow publicado y móviles consentidos |

La configuración no demuestra una llamada atendida. Antes de presentar el modo conectado, realiza un mensaje y una llamada de prueba y comprueba su resultado en la Sala. Si falta acceso, usa el ensayo local identificándolo como simulación.

No usar con víctimas reales ni teléfonos de emergencias. El incidente es ficticio; los participantes del equipo reciben los mensajes y llamadas de prueba.
