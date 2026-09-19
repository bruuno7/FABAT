# MANDO server — adaptador HappyRobot + puente Telegram

Dueña: **Ana** (`AGENTS.md`). Bruno posee specs en `motor/happyrobot`.

## Qué hace

```
Público TG → Bot → POST /telegram/webhook → public_report → HR_HOOK_TG (fa-entrada-tg)
Personal TG → /rol /estado /baja → HR_HOOK_TG_ROSTER (fa-rol-tg) · botones → staff_response → HR_HOOK_TG_RESPONSE
HR agent_reply → POST /hr/events → sendMessage TG (y espejo a MANDO si MANDO_BACKEND_URL)
HR telegram_send / telegram_edit / answer_callback → Bot API
```

También: `POST /hr/events` genérico para webcall y otros canales.

El directorio rol↔chat_id, los incidentes y el cerrojo «primer acepta gana» viven en **HappyRobot**
(workflows `fa-rol-tg`, `fa-despacho-tg`, `fa-respuesta-tg` sobre Redis). El puente solo transporta.
`/rol`, `/baja` y `/estado` disparan `HR_HOOK_TG_ROSTER`; `fa-rol-tg` contesta al chat con la ocupación
real. Sin ese hook, el mapa es solo memoria local (se pierde en un cold start de Vercel) y, si además hay
`MANDO_BACKEND_URL`, se espeja en MANDO (`POST /hr/tg/roster`, ruta heredada).

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
4. `HR_HOOK_TG_RESPONSE` = Incoming Hook development de `fa-respuesta-tg`
5. `HR_HOOK_TG_ROSTER` = Incoming Hook development de `fa-rol-tg` (directorio de puestos)
6. `HR_SECRET` con el MISMO valor que la variable `HR_SECRET` de `fa-entrada-tg`, `fa-despacho-tg`,
   `fa-respuesta-tg` y `fa-rol-tg` en la plataforma; si no coincide, HappyRobot recibe `invalid secret`

## Variables

Ver `.env.example`. Nunca commitear `.env`.

| Var | Uso |
|-----|-----|
| `TELEGRAM_BOT_TOKEN` | BotFather |
| `TELEGRAM_WEBHOOK_SECRET` | Header `X-Telegram-Bot-Api-Secret-Token` |
| `HR_HOOK_TG` | Incoming Hook development `fa-entrada-tg` |
| `HR_HOOK_TG_RESPONSE` | Incoming Hook `fa-respuesta-tg` (botones acc/dec/eta/loc/apr/vet) |
| `HR_HOOK_TG_ROSTER` | Incoming Hook `fa-rol-tg` (`/rol`, `/baja`, `/estado`; el directorio vive en Redis vía HappyRobot) |
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

Un chat = un puesto. Un puesto = un chat. Con `HR_HOOK_TG_ROSTER`, el mapa se guarda en Redis
desde `fa-rol-tg`; ese workflow contesta `/rol`, `/estado` y `/baja` por `/hr/events`. Sin el hook,
el puente usa el directorio legado de MANDO (`/hr/tg/roster`) o memoria local. En local, sin
`STAFF_PIN`, `/rol` funciona para poder ensayar. En Vercel, sin PIN no se toma ningún puesto.

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
| POST | `/hr/tg/dispatch` | proxy a MANDO (`telegram_send` listo); `x-hr-secret` |
| POST | `/hr/tg/staff-response` | proxy a MANDO (`acc`/`dec`/`eta`/`loc`); `x-hr-secret` |
| POST | `/demo/public-report` | solo si `ALLOW_DEMO_INJECT=1` |

## Base multicanal v2 (en desarrollo, desactivada)

La API técnica `/hr/state/*` es independiente de los hooks actuales: **no migra Telegram ni llamadas**.
`HR_STATE_API_ENABLED=0` es el valor por defecto; no habilitarla en producción antes de completar
la migración y las pruebas contra Redis. Los workflows LIVE siguen usando v1.

El contrato está en `motor/happyrobot/event_contract.json`. Los eventos identifican persona,
conversación, incidente, asignación y pregunta por separado. La API no elige recursos ni interpreta
mensajes: recibe propuestas de HappyRobot y realiza commits con versiones esperadas.

Variables: `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN`, `HR_STATE_NAMESPACE`
(`test-...`, `dev-...` o `live-...`) y cuatro secretos distintos, privados, en
`x-hr-state-secret`. No reutilizar el token público del bot ni incluir credenciales en prompts.

| POST relativo a `/hr/state` | Secreto | Efecto |
|---|---|---|
| `/inbox` | `HR_STATE_INGRESS_SECRET` | Acepta evento de un adaptador autenticado; deduplica por ID y contenido |
| `/inbox/event`, `/inbox/pending`, `/snapshot` | `HR_STATE_READ_SECRET` | Lectura privada y versionada |
| `/commit` | `HR_STATE_COMMIT_SECRET` | CAS de entidades + evento aplicado + mensajes pendientes; conflicto devuelve 409 |
| `/outbox/pending`, `/outbox/claim`, `/outbox/settle` | `HR_STATE_DELIVERY_SECRET` | Reserva temporal de envío y confirmación del resultado |

Los scripts Lua son fijos y solo escriben bajo `fa:v2:{namespace}:...`; no se admiten comandos
Redis ni URLs de destinatarios arbitrarios. Un lease vencido pasa a entrega `unknown`, no a reenvío
automático: un timeout puede haber ocurrido después de entregar el mensaje. Todavía falta conectar
los consumidores, la recuperación programada, los adaptadores de identidad y todas las operaciones.

Pruebas sin red externa:

```bash
npm run typecheck
npm test
npm run build
```

Desde la raíz, `python3 -m unittest motor.happyrobot.sandbox.test_operaciones motor.happyrobot.sandbox.test_operation_artifact`
comprueba el núcleo puro: creación/actualización de avisos, ofertas por capacidad, permisos de rol,
aceptación, rechazo, disponibilidad, ETA, hitos, cierre y preguntas. No crea ni publica workflows.
Los eventos aún no implementados (por ejemplo revisión y aprobación de decisiones) fallan explícitamente;
no se convierten en incidentes nuevos. La asignación de un rol requiere un permiso previo de un
adaptador autenticado, vinculado a esa persona y con caducidad; el PIN no viaja en el evento.

`build_nodes.py fa_operaciones TRIGGER_PID=<UUID-persistente>` exporta el archivo Python completo
más su entrada `run_input`, sin recortarlo ni reescribirlo. Si falta una entidad en el snapshot,
la salida pide su lectura (`needs_snapshot`), no supone que está libre o vacía. Si la entrada es
inválida, no genera ningún commit. El consumidor con reintentos acotados todavía debe conectarse.

La prueba real de CAS es opt-in. Configura de forma privada `FABAT_TEST_REDIS_URL` y
`FABAT_TEST_REDIS_TOKEN` de una base de pruebas y ejecuta desde `puente/`:

```bash
FABAT_RUN_REDIS_TESTS=1 node --import tsx --test src/lib/redis-state.integration.test.ts
```

Cada ejecución crea un namespace `test-<uuid>`, no envía mensajes ni llama a HappyRobot y aplica
caducidad solo a las claves creadas por esa prueba. Sin opt-in la prueba aparece como omitida;
los mocks de transporte no acreditan atomicidad real. No habilitar v2 basándose solo en ellos.

## Bloqueado hasta

1. Token BotFather
2. (A) HR Editor key o (B) workflow creado a mano + `HR_HOOK_TG`
3. HTTPS público o decisión de usar `npm run poll`
4. `HR_HOOK_TG_RESPONSE` y `STAFF_PIN` en Vercel cuando el workflow de respuesta exista
