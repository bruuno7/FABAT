# motor/server — backend: herramientas del equipo, barandillas, Sala y APIs

La interfaz de supervisión es `/` (Sala: `static/sala*`). Público `/asistente`, jurado `/jurado`. Pantallas viejas → `archivo/motor/server/static/` (las rutas redirigen a `/`).

La pestaña **Equipo → Probar HappyRobot** permite lanzar `prueba-ana-rapido` y seguir
su decisión y la revisión. Configuración de agentes, Telegram y teléfono:
[Integración de Ana](../../docs/INTEGRACION-ANA.md).

Carpeta privada. Nada de aquí se sube a ningún sitio. El servidor escucha en `127.0.0.1`; con `--lan`, en la red
local (para los móviles del jurado). Nunca se abre a internet desde aquí.

## Arrancar

Para la entrega: `./mvp.sh demo` hace diagnóstico previo sin red y arranca `demo-1` pausado, con canales rotulados.
Ver [PRESENTACION-SEGURA.md](PRESENTACION-SEGURA.md) para el recorrido de 15 minutos y planes B.
`uv run --project motor/server python -m motor.server ensayo --case demo-1` comprueba siete hitos sin pantalla ni plataforma.

```sh
# desde la raíz del proyecto
uv run --project motor/server python -m motor.server --case demo-1 --speed 1          # o: motor/server/run.sh --case demo-1
uv run --project motor/server python -m motor.server --case demo-gates --speed 4 --lan --play
UV_CACHE_DIR=/private/tmp/codex-uv-cache uv run --project motor/server python -m unittest discover -s motor/server -p "test_*.py" -t .
```

`--case`: `demo-N` (línea N de `cases/data/demo.jsonl`), `demo-gates` (`world/demo_case.json`) o un id de
`demo.jsonl`/`heldout.jsonl`. `--speed`: minutos simulados por segundo real. `--comms sim|happyrobot`.
`--playbook auto|learned|seed|none` (auto = `harness/out/playbook.learned.json` si existe). `--play` arranca con el
reloj en marcha (por defecto arranca en pausa: espacio para empezar). `--port 8000`.

Páginas: `/` mando (`/?escena=1` o tecla E = MODO ESCENA) · `/duelo` pantalla partida lista fija contra Mando ·
`/asistente` conversación web · `/memoria` observaciones y propuestas · `/jurado` móvil del jurado · `/llamada/<id>` quien hace de jefe de equipo contesta la llamada web · `/caos` consola del
adversario · `/informe` informe posterior · `/curva` curva de aprendizaje · `/qr?path=/jurado` SVG con el QR de una ruta local.

Teclado en `/`: espacio = pausa · flechas = velocidad (×1/×4/×16) · A / V = aprobar / vetar la primera pendiente ·
E = modo escena · S = +1 min · R = reiniciar escena · K = momento clave simulado (minuto 7, pausado) · Q = QR del jurado a pantalla completa.

**Quién puede qué.** Avisar y golpear (3 por `client_id`, además de 3 globales por partida) puede cualquiera de la red local. Aprobar, mover el reloj,
cambiar de caso, la consola de Caos, tomar una llamada y bloquear un test solo se aceptan desde esta máquina o con la
cabecera `X-Mando-Operator` = `MANDO_OPERATOR_TOKEN`. El enlace secreto de una llamada web y su token no salen nunca en
`/api/state`: el enlace solo lo ve el puesto de control (`/api/webcalls`) y el token solo va a la página que descuelga.
Con `MANDO_PUBLIC_URL`, también en localhost se exige token para mando y operaciones: entrar por `/acceso`
(cookie HttpOnly) o usar `X-Mando-Operator`. `/mcp` siempre exige su propio token. Avisos públicos limitados
por IP de conexión, 400 caracteres y 8192 bytes de cuerpo; no se confía en `client_id` ni cabeceras reenviadas.

## Endpoints

| Método | Ruta | Qué |
|---|---|---|
| GET | `/api/state` | instantánea completa (lo mismo que cada evento del SSE) |
| GET | `/api/stream` | SSE, evento `state` en cada tick o cambio (`?limit=N` corta tras N eventos: pruebas) |
| GET | `/api/cases`, `/api/festival` | casos de demo · zonas, aristas, incidentes típicos y golpes del jurado |
| POST | `/api/session` | `{case_id | case:{...}, seed?, speed?, comms?: sim|happyrobot, playbook?, autoplay?}` |
| POST | `/api/control` | `{cmd: play|pause|toggle|step|speed|reset|key_moment, value?, n?}` |
| POST | `/api/report` | `{channel, text, zone?, preset?}` aviso del jurado → `world.inject`. Devuelve `report_id` |
| POST | `/api/workflows/rapido` | Operador: `{request_id, text, zone?}` → aviso + dos ticks simulados → workflow rápido, si abre un incidente pendiente. Reintentos con el mismo `request_id` no repiten efectos. |
| GET | `/api/report/{id}` | qué ha hecho Mando con ese aviso (lo ve el jurado en su móvil) |
| POST | `/api/strike` | `{preset}` o `{effect:{...}}` validado y acotado, `client_id?`, `origin: jury|chaos` |
| GET | `/api/chaos/suggest` | `Chaos.suggest(world, agent)` normalizado: label, why, damage, effect |
| POST | `/api/approve` | `{action_id, ok: true|false, note?}`; cadenas y números se rechazan con 422 |
| GET | `/api/informe`, `/api/curve` | datos del informe posterior · `curve.json`/`summary.json` del banco |
| GET | `/api/duel/state`, `/api/duel/stream` · POST `/api/duel/session`, `/api/duel/control` | pantalla partida: mismo caso, semilla y golpes en los dos lados (los avisos y golpes del jurado entran en ambos) |
| GET | `/api/jury?client_id=…` | `left` personal, `global_left`, `budget` y marcador |
| GET | `/api/strike/{n}` | golpe público con `id`, `broken[]`, `new_plans[]`, `locked_test`, `outcome` |
| POST | `/api/chat` | conversación real con `motor.intake.IntakeSession`; contrato abajo |
| GET | `/api/chat/{session_id}/events` | SSE de preguntas al informante y cambios de estado |
| GET | `/api/memoria` | observaciones, propuestas y comparación antes/después con N e intervalos |
| POST | `/api/memoria/decide` | operador: `{id, approve: true|false, by?}` → API de tuning, efectivo en la siguiente sesión |
| GET | `/api/regression` · POST `/api/regression/lock {author}`, `/api/regression/run {n}` | «el test con tu nombre»: guarda caso + entradas en `regression_live/` y lo re-ejecuta, determinista, a ×16 |
| GET | `/api/webcalls` (operador) · GET `/api/webcall/{id}` · POST `/api/webcall/{id}/answer` | llamada web: pendientes con su enlace · datos para quien contesta · DESCOLGAR (aquí se pide el token) |
| POST | `/api/call/{action_id}/token {takeover}` · `/api/call/{action_id}/signal {text}` (operador) | ESCUCHAR o TOMAR una llamada viva · cambio de orden a mano dentro de la llamada |
| POST | `/hr/events` | webhooks de HappyRobot: `progress`, `*_result`, `public_report`, `tg_*` (contrato `mando.hr.v1`) |
| GET/POST | `/hr/tg/roster` | directorio privado rol↔chat_id (exige `HR_SECRET`; no sale por `/api/state`) |
| POST | `/hr/tg/dispatch` | elige puesto reclamado, espeja `tg_*`, devuelve `telegram_send` |
| POST | `/hr/tg/staff-response` | `acc`/`dec`/`eta`/`loc`/`apr`/`vet`; primer acc gana; reasigna |
| POST | `/hr/identify`, `/hr/approval_check`, `/hr/webcall/next` | consultas síncronas del contrato |

Los `/hr/*` exigen la cabecera `X-Mando-Token` igual a `HR_SECRET`. Sin secreto configurado responden 503.

Un aviso del jurado que se reconoce (uno de los 8 típicos, o texto libre con palabras clave) crea un incidente
VERDADERO en el mundo: quien avisa es la verdad del caso y Mando solo ve el texto. Si no se reconoce entra solo el
aviso y Mando tendrá que preguntar.

## Variables de entorno (nunca en el código ni en ficheros versionables)

| Variable | Para qué |
|---|---|
| `HR_HOOK_DISPATCH`, `HR_HOOK_ASK` (= `HR_HOOK_CLARIFY`), `HR_HOOK_NOTIFY`, `HR_HOOK_EXTERNAL`, `HR_HOOK_FOLLOWUP` | URL del «Incoming hook» de cada workflow |
| `HR_SECRET` (= `MANDO_HR_TOKEN`) | secreto compartido de los webhooks entrantes (`X-Mando-Token`) |
| `HR_API_BASE` | API de la plataforma. Clúster EU: `https://platform.eu.happyrobot.ai/api/v2` |
| `HR_API_KEY` | Bearer de la API (`/workflows/{id}/runs`, `/voice/tokens/`, `/signals`, `/runs/{id}/sessions`, `/sessions/{id}/stream`) y cabecera `x-api-key` del hook con Enhanced Security (`HR_HOOK_ENHANCED=0` para no mandarla) |
| `HR_LAUNCH_MODE` (`hook`) | `hook` = POST a `/hooks/{slug}` (no se usa su respuesta: no está documentada) · `runs` = `POST {HR_API_BASE}/workflows/{id}/runs`, que devuelve `run_id` |
| `HR_WORKFLOW_DISPATCH`, `_ASK`, `_NOTIFY`, `_EXTERNAL`, `_FOLLOWUP`, `HR_WORKFLOW_WEBCALL` | id o slug de cada workflow (modo `runs` y llamada web) · `HR_ENV` (`development`) |
| `HR_PLATFORM_BASE` | `https://platform.eu.happyrobot.ai`; hooks y deployments incluyen entorno salvo production. URLs explícitas prevalecen; confirmar hooks en el editor. |
| `MANDO_VOICE_MODE` (`web_call`) | `web_call` = la voz va por llamada web (sin números +34) · `phone` = teléfono por hook/runs |
| `HR_DISCLAIMER_S` (4) | segundos del aviso legal UE al descolgar: se restan, no son latencia del agente |
| `MANDO_OPERATOR_TOKEN` | permite operar (aprobar, reloj, tomar llamadas) desde otra máquina de la red |
| `MANDO_DB` | una sola SQLite (historial + ledger + episodios de agentes). Por defecto `motor/server/data/mando.db`; `off` apaga el historial (el reloj sigue). `MANDO_LEDGER_PATH` es un alias si `MANDO_DB` no está |
| `MANDO_DB` | ruta de SQLite del historial (por defecto `motor/server/data/mando.db`); `off` lo desactiva |
| `MANDO_TG_ROSTER` | SQLite privado rol↔chat_id de Telegram (por defecto `motor/server/data/tg_roster.db`); `off` o `MANDO_DB=off` = memoria |
| `MANDO_CALLBACK_URL` | URL a la que HappyRobot devuelve los webhooks (por defecto `http://127.0.0.1:<puerto>`). El túnel, si hace falta, lo abre una persona, no este código |
| `MANDO_ALLOWED_NUMBERS` | lista blanca OBLIGATORIA de teléfonos (E.164, comas) |
| `MANDO_CONTACTS` | ruta alternativa a `contacts.local.json` |
| `HR_FALLBACK_S` (12), `HR_TIMEOUT_S` (5), `HR_RETRIES` (1) | segundos reales sin resultado antes de caer a simulación (máx. 75) · timeout (máx. 10) y reintentos del POST (máx. 3) |
| `HR_SLOW_ON_CALL` (1) | con una llamada real en curso el reloj baja a 1 min simulado cada 5 s |
| `MANDO_PUBLIC_URL` | URL base de callbacks y QR; prevalece sobre `MANDO_CALLBACK_URL` |
| `MANDO_ASK_WAIT_S` (45) | plazo real para que conteste una persona; al vencer se sigue con lo conocido |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_API_BASE`, `TELEGRAM_BOT_USERNAME` | bot y API; sin token permanece apagado |
| `TELEGRAM_MODE` (`poll`) | `poll`: getUpdates; `send_only`: webhook del puente entra por /hr/events, respuestas por sendMessage; `off`: desactivado. Ambos caminos comparten recogida por chat. |
| `TELEGRAM_POLL_TIMEOUT_S` (25), `TELEGRAM_RATE_MAX` (6), `TELEGRAM_RATE_WINDOW_S` (60), `TELEGRAM_MAX_CHARS` (400) | sondeo, frecuencia y tamaño |
| `MANDO_MCP_TOKEN` | Bearer de `/mcp` |
| `HR_HOOK_INTAKE`, `HR_INTAKE_TIMEOUT_S` (6), `HR_CHAT_TOKEN` | extracción delegada opcional, plazo y token público limitado a avisos/consultas |
| `HR_HOOK_DISPATCH_<ENV>` | hook de despacho específico del entorno |
| `HR_WEBCALL_PUBLIC_URL`, `HR_INTAKE_EMAIL`, `HR_SMS_NUMBER` | enlaces de entrada públicos; los teléfonos se ocultan en estado/SSE/logs |

Modo híbrido: solo los recursos de `contacts.local.json` (copiar de `contacts.example.json`; NO se versiona, está
en `.gitignore`) salen por HappyRobot; el resto lo contesta `SimComms`. Nunca se marca un número de emergencias
(lista `NEVER_DIAL`). Un `REQUEST_EXTERNAL` sin aprobación humana registrada no sale (segundo cerrojo) y, además,
el bucle del servidor bloquea cualquier acción `ALWAYS_APPROVE` o cierre de zona que llegue sin aprobar.
Los clones de Mando que hace Caos para mirar hacia delante reciben comunicaciones simuladas: nunca llaman a nadie.

Probar sin la plataforma:

```sh
uv run --project motor/server python -m motor.server.mock_happyrobot --port 8765 --delay 4 &
cp motor/server/contacts.example.json motor/server/contacts.local.json
HR_SECRET=cambia-esto HR_HOOK_DISPATCH=http://127.0.0.1:8765/hook/dispatch HR_HOOK_ASK=http://127.0.0.1:8765/hook/ask \
  uv run --project motor/server python -m motor.server --case demo-1 --comms happyrobot
```

El mock imita las mismas rutas que usa el adaptador: `/hooks/{slug}`, `/api/v2/workflows/{id}/runs`, `/api/v2/voice/tokens/`,
`/api/v2/signals`, `/api/v2/runs/{id}/sessions`, `/api/v2/sessions/{id}/stream` y `/messages`. Para probar la llamada web
entera sin plataforma: `HR_API_BASE=http://127.0.0.1:8765/api/v2 HR_API_KEY=mock HR_WORKFLOW_WEBCALL=fa-webcall`; la página
`/llamada/<id>` detecta `mock://` y contesta con botones ACEPTO / NO PUEDO en vez de con audio.
La latencia por turno que devuelve el mock es inventada (`mock: true`): no es cifra para el pitch.

**Llamada web de verdad, dos requisitos que no están en esta carpeta:** (1) dejar `livekit-client.umd.min.js` en
`static/vendor/` (no se carga de ningún CDN; la carpeta está en `.gitignore`); (2) el micrófono del navegador exige HTTPS o
`localhost`: desde un móvil por `http://<ip-local>` NO funciona. Eso lo resuelve una persona (certificado local o su propio
túnel) y entonces se pone `MANDO_PUBLIC_URL`; este código no abre túneles. En la plataforma, los parámetros del trigger Web
Call tienen que coincidir con las claves de `dispatch_request` que se mandan en `data`, o `/voice/tokens/` devuelve 400.
Cuando se rompe un supuesto con alguien AL TELÉFONO por ese incidente, el servidor publica un Signal a `session.<id>`
con la orden nueva; si no se conoce la sesión o Signals falla, queda dicho en el registro y está el botón TOMAR LA LLAMADA.

## Guion de 3 minutos (según `consejo/directora-demo.md`; la demo son tres gestos, no ocho paneles)

Los tres gestos que se tienen que entender SIN SONIDO a cinco metros: **una mano de fuera rompe el plan desde un móvil ·
el plan se tacha en rojo y nace otro · suena una llamada y alguien dice «no»**. Las cartelas de día (DÍA 1 · NOCHE ·
DÍA 2 · DÍA 3) son montaje, no tiempo simulado. Todo en `/?escena=1` (tecla E) salvo el arranque.

Preparación: `--case demo-1 --speed 1 --lan --comms happyrobot` con `MANDO_VOICE_MODE=web_call`; `/duelo` cargado en otra
pestaña con `demo-gates`; el móvil de quien hace de jefa de equipo, con permisos de micrófono ya dados; el móvil de la
mano de fuera en `/jurado`. Las cifras que salgan en pantalla son las de ESA ejecución: se rotula lo que dé, con su N.

| Tiempo | Pantalla | Qué se hace | Qué se ve |
|---|---|---|---|
| 0:00–0:06 | cartela | — | «21:07 primera llamada · 22:12 fin del concierto. 65 minutos. La información existía.» |
| 0:06–0:24 | `/duelo` a ×16 | Espacio | MISMO caso, semilla y golpes. Izquierda, LISTA FIJA: una puerta pasa a rojo y parpadea; marcador con críticos fallidos, pico de densidad y minutos > 5/m². Derecha, MANDO: desvío ensayado, todo por debajo |
| 0:24–0:30 | cartela | — | MANDO · «Sabe cuándo su plan ha dejado de valer» |
| 0:33–0:52 | `/?escena=1`, DÍA 1 (`demo-2`) | Mando pide algo grave; una persona pulsa V (VETAR) | TARJETA DE DECISIÓN: a quién va (cargo y suplente), los dos futuros ENSAYADOS lado a lado, reloj de ventana. Sello del veto y lección candidata en `/informe` |
| 0:55–1:10 | `/curva` | — | NOCHE: curva train/heldout con N e intervalo frente a la lista fija. Solo si el dato aguanta (D7) |
| 1:13–1:20 | `/?escena=1`, DÍA 2 (`demo-1`) | Espacio | Cuatro avisos se funden en un frente de prioridad 10; médico y ambulancia salen sin pedir permiso. Tablero FRENTES: cinco o más a la vez |
| 1:20–1:35 | igual | La jefa de equipo abre su enlace (QR del panel LLAMADAS) y pulsa DESCOLGAR | Tira inferior: «LLAMADA WEB · HappyRobot», transcripción en grande, sello **ACEPTA · 3 min** (o **RECHAZA** y Mando reasigna a la vista). En PLAN, los supuestos con tic verde y la línea del ENSAYO |
| 1:35–1:42 | igual | La mano de fuera, en «Rompe el plan», gasta un golpe (●●○) | Banda morada «GOLPE DEL JURADO» → plano grande 3 s: **SUPUESTO ROTO** · plan tachado · PLAN NUEVO con su porqué. Entra un IMPREVISTO resaltado en FRENTES y los demás se reordenan |
| 1:42–1:52 | igual | (automático) | La llamada sigue viva: «CAMBIO DE ORDEN EN LA LLAMADA: …» (Signals). Si Signals no funciona en EU: botón **TOMAR LA LLAMADA** y la operadora da la orden de viva voz |
| 1:52–2:05 | igual | A (APROBAR) en la tarjeta «pedir ambulancia externa» | «0 decisiones graves sin una persona» y latencia de decisión humana con su N |
| 2:08–2:40 | `/?escena=1`, DÍA 3 | Alguien de fuera elige un caso heldout (selector de caso o `POST /api/session`); ×16; tres golpes | Marcador **JURADO 0 — 0 MANDO**. Si un golpe provoca un fallo crítico: barra «BLOQUEAR COMO TEST Nº N · autor: <nombre>» → RE-EJECUTAR A ×16 → PASA / NO PASA, a la vista |
| 2:40–3:00 | captura de la plataforma y cartela | — | El run con su transcripción; RD 393/2007; QR |

Plan B en directo: si la llamada no entra, el mundo ya modela `no_answer` y Mando reasigna; si la plataforma encola sin
error, a los `HR_FALLBACK_S` segundos la llamada cae a simulación y queda escrito en el registro; si se cae el servidor,
REINICIAR con el mismo caso y semilla reproduce la partida (por eso se puede auditar).

## Qué hay en la carpeta

`app.py` (sesión, reloj, API, webhooks) · `comms_happyrobot.py` (`HappyRobotComms`) · `mock_happyrobot.py` ·
`views.py` (frentes, tarjeta de decisión, ensayo, nombres legibles, incidentes reservados, marcador) ·
`regression_live.py` y `regression_live/` (tests bloqueados en directo) ·
`fallback_agent.py` (relleno, solo si `motor.mando` no se puede importar) · `test_server.py` · `static/`
(`index.html`, `app.js`, `style.css`, `plano.js`, `duelo.html`, `llamada.*`, `jurado.*`, `caos.html`, `informe.html`, `curva.html`, `pages.css`) ·
`contacts.example.json` · `run.sh` · `pyproject.toml`.

Lo que la pantalla lee de Mando, tolerante a su ausencia: `snapshot()["fronts"]` (`incident, status, team[{resource,
eta}], eta, why_waiting`; si falta se deriva de los incidentes), `Action.params["decision_card"]` (`addressee, deputy,
if_approved, if_vetoed, window_min, asked_at, escalate_at, escalated_at`), la línea del ensayo (entrada de log `plan`
con `data.rehearsal`), `incident["reserved"]` (se enmascara EN EL SERVIDOR: ni texto ni zona llegan al navegador) y
`Mando(twin=lambda: world.twin())` cuando `World.twin` existe. En `/duelo`, lo grave de Mando lo aprueba un operador
simulado a los 2 min (va rotulado en el estado): ahí no hay persona delante.

Campos propios en dict libres: `Action.params["reason"]` (lo escribe Mando) se usa como texto del paso;
los `poll()` reales llevan `data.real = true`, `eta_min`, `detail`, `reason_code`, `channel`.


## Contrato de conversación y endurecimiento (19-sep)

`POST /api/chat` acepta `{text, session_id?, channel?, lang?: "es"|"en", zone_hint?, pulsera?, source?, preset?, client_id?}`.
Cada conversación tiene una `IntakeSession` propia, con id único; se reinicia al cambiar la partida. Se ha integrado contra
la API real de [motor/intake](../intake/README.md). Sus informes parciales y actualizaciones entran por `submit_report`,
enlazados por raíz. Si el paquete falta o falla, el aviso entra igualmente y la respuesta lleva `degraded: true`.

Además de `say`, `reports`, `report_id`, `done`, `why_next` y `session_id`, devuelve:

- `quick_replies`: `['Sí', 'No', 'No lo sé']` para un booleano, opciones del slot para un enum, o `[]`.
- `state.slots`: `[{id, label, value, confidence}]`, con etiquetas del idioma de la persona.
- `instruction`: `{id, title, steps: [...], metronome: bool}` o `null`. Los pasos provienen de la instrucción del motor;
  el metrónomo se activa por el id de RCP, sin inferirlo de una mención condicional en el texto.
- Con `lang: "en"`, conversación, opciones, instrucciones y notificaciones se emiten en inglés. El estado general de
  la sala (`/api/state`: planes, explicaciones y megafonía de Mando) conserva su idioma original.

Las preguntas `purpose: sitrep`, con recurso o dirigidas a un recurso/responsable, no llegan al informante.
En web/chat/Telegram, un ASK espera una respuesta real hasta `MANDO_ASK_WAIT_S`; tampoco lo expira el HOLD por minutos
simulados acelerados. Al vencer se registra `no_answer` y Mando sigue con lo conocido, sin una falsa respuesta simulada.

Los efectos admitidos por `/api/strike` son `resource_offline`, `resource_online`, `resource_no_answer`, `resource_rejects`,
`zone_state`, `zone_inflow`, `zone_flag`, `weather`, `comms_down`, `transport_cut` e `incident`. Se validan campos, ids,
booleanos, valores finitos y límites antes de inyectar o gastar presupuesto (detalle en `validation.py`). Los golpes
llevan `strike.id`; `broken[]` y `new_plans[]` son consecuencias posteriores en una ventana de 6 minutos, cortada por el
golpe siguiente: `attribution: "temporal"`, no una demostración causal. `locked_test` vincula el test guardado.
El `client_id` lo facilita el navegador: sirve para repartir el presupuesto de demo, no acredita identidad.

`/duelo` usa `BaselineReroute` por defecto. Los GET ignoran `baseline` y nunca cambian la comparación.
Solo `POST /api/duel/session {baseline: "reroute"|"fixed"}` (operador) selecciona la variante. Cada lado expone `kind`, `agent`,
`peak_zone`, `peak_zone_name`, `reroutes`, `score` y `n: 1`: los rótulos deben usar esas cifras de simulación, sin presuponer
qué puerta se satura ni quién gana. En el duelo, lo grave se autoaprueba tras 2 minutos simulados; no es decisión humana.

`GET /api/memoria` lee `memory.day1.json`, `params.proposed.json` y `harness/out/latest/day2.json` (alternativa:
`harness/out/day2.json`). Conserva N, intervalos, conjunto, huella y veredicto por métrica. Aprobar/rechazar llama a
`motor.mando.tuning.Proposals.approve/reject` y `write_approved` cuando están disponibles. Escribe únicamente
`motor/server/params.approved.local.json` y `memoria.decisions.local.json`; la siguiente sesión Mando carga esos parámetros.
El fichero canónico de Mando no se modifica, ni se recalcula el informe histórico al aprobar. Sin API disponible,
`applied_to_mando: false` deja explícito que solo se ha registrado la decisión.

H1–H8 están cubiertos por `test_hardening.py`: error de motor visible en `engine_error` sin matar el hilo; privacidad
provisional antes del primer tick, también en log, llamadas e informe; booleanos estrictos; validación antes de idempotencia;
finalización protegida por cerrojo; correlación por ids emitidos de esta sesión; actualización SSE estando en pausa;
y clon de Caos con `rehearsal.twin` enlazado a su propio mundo. Un fallo de mundo pausa la simulación y conserva vivo el hilo;
un fallo de agente queda registrado y el mundo continúa. Un reinicio de sesión limpia el error.

Pendiente de integración manual: frontend en edición por otro proceso, móvil real, audio/Telegram/HappyRobot reales y
rótulos basados en los nuevos campos. No se han abierto túneles ni publicado ficheros. Ver [PENDIENTE.md](PENDIENTE.md).

## Demo pública: límites y seguimiento

Sin operador, `/api/strike` acepta únicamente presets y su presupuesto de tres golpes; `close_gate`
permite elegir `gate_a`, `gate_b` o `gate_c`. Otros efectos o modificaciones exigen operador, igual que
`GET /api/chaos/suggest`. `/caos` conserva su uso con la cookie de `/acceso` o en local.
El modo local simulado mantiene sus permisos y controles habituales.

Los avisos públicos de `/api/report` y `/api/chat` devuelven referencias aleatorias en `report_id` y
`reports`. Solo esas referencias permiten consultar o contestar en `/api/report/{ref}`; caducan al
reiniciar la sesión. `report_refs` relaciona las referencias de esa respuesta con los ids internos
para seguir el mismo incidente en la pantalla; conocer un id interno no concede acceso. El operador
y las integraciones conservan los ids internos. Las sesiones `tg-` no se leen ni continúan desde la web.

La cuota usa `CF-Connecting-IP` (preferente) o la primera IP de `X-Forwarded-For` solo si está configurada
`MANDO_PUBLIC_URL` o el peer es loopback; en otro caso, o con una cabecera inválida, usa la IP directa.
Estas cabeceras nunca conceden acceso de operador. Las llamadas web esperan 75 s al descuelgue y
45 s al resultado; el descuelgue concurrente se rechaza. Telegram procesa hasta ocho actualizaciones
en paralelo y mantiene como máximo 32 trabajos entre activos y pendientes.


## Personal de campo y varios operadores

Tres perspectivas: público en `/asistente`, equipos en `/personal` y coordinación compartida en `/centro`.
El modo inicial y las teclas de `/` se conservan. Desde **Enlaces del personal** en el centro se eligen
unidad del recinto y cargo; se generan enlace firmado y QR. El HMAC usa `MANDO_STAFF_SECRET` si está
configurado o un secreto aleatorio del servidor por escena. Caduca al finalizar/reiniciar la escena.
El token está en el fragmento del enlace, después en sessionStorage y cabecera `X-Mando-Unit`;
no concede permisos de operador y nunca lleva teléfonos.

`/personal` enseña solo las órdenes vigentes de la unidad, aceptar/rechazar con motivo y botones de estado,
texto libre o nuevo aviso. `GET /api/personal/me`, `POST /api/personal/status`,
`POST /api/personal/order/{id}` exigen ese token. `POST /api/personal/links` y `/api/personal/qr`
exigen operador. `GET /api/personal/catalog` contiene únicamente nombres/ids y cargos.
Los partes usan `Report` RADIO/VOICE, `source=unit_id`, y metadatos del servidor `staff_unit`,
`staff_status`, `source_label`: no se cambia `motor/contracts.py` ni `INTERFACES.md`.
Partes operativos no abren incidentes artificiales: se enlazan al asignado y sus efectos entran en
Observation y el tratamiento sitrep existente. `new_notice` usa la ingesta/fusión normal.
La ruta bloqueada marca zona y recurso: al siguiente tick Mando rompe el supuesto y replantea si
existía un plan dependiente. Cada parte conserva su Report y su línea explicada en el log.

Operadores: `MANDO_OPERATORS="Marta:sanitario:<token-1>,Luis:seguridad:<token-2>"` (también admite punto
 y coma o saltos de línea). Nombres/papeles no vacíos y tokens distintos; configuración inválida impide
arrancar. `MANDO_OPERATOR_TOKEN` continúa como `operador-1`. `/acceso` emite la cookie HttpOnly existente;
`X-Mando-Operator` sirve para API. Sin tokens en localhost, el centro permite seleccionar nombre/papel.
La identidad de una decisión viene de la credencial; el campo `by` del cliente no la suplanta.

El centro muestra presencia (heartbeat 10 s, caducidad 35 s), incidente abierto, **Lo llevo yo**, soltar,
filtro **Los míos**, papel sugerido y fuentes fusionadas. Las notas admiten `@sanitario`, `@seguridad`, etc.
Presencia, propietarios, notas y acciones llegan por el SSE existente. Asumir no impide actuar a otros.
Aprobar/vetar/corregir/tomar una llamada se reservan bajo el cerrojo de la escena: un segundo intento
recibe 409 con persona, papel y tiempo transcurrido. Una toma fallida libera la reserva para reintentar.
`MANDO_TWO_PERSON=1` exige dos identidades distintas para evacuar, parar y solicitar ayuda externa;
el primer voto muestra **1 de 2** y no ejecuta nada. El veto sigue siendo inmediato. Las firmas no se
mezclan entre propuesta original y corrección. Una propuesta retirada ya no se puede refrendar.
`/informe` incluye identidad, hora, acciones y latencia por operador (segundos hasta su voto; N visible).

HappyRobot: `staff_status` requiere `HR_SECRET` **y** `unit_token`; `external_notice` requiere `HR_SECRET`.
Ambos rechazan el token público del widget. Contrato exacto y seis casos en
[PERSONAL-CAMPO.md](../happyrobot/PERSONAL-CAMPO.md). El mock incorpora `/mock/staff-status` y
`/mock/external-notice`. Entrada manual externa: centro → Aviso de 112 / servicios externos.
No se ha montado ni probado este workflow en la plataforma real.

Conversaciones web: identificadores aleatorios de 192 bits emitidos por servidor, almacenamiento por
pestaña (sessionStorage), **Otro aviso** crea conversación nueva y SSE específico de esa conversación.
Duplicar pestaña descarta la conversación heredada (Web Locks); una recarga conserva la propia.
En HTTP LAN sin Web Locks, toda navegación nueva inicia una conversación nueva. El identificador interno
de IntakeSession es distinto del acceso secreto web: nunca se publica este último en el estado compartido.
Los cambios de pantalla del chat se agrupan hasta 100 ms; no se retrasa la entrada del Report en el mundo.
La clasificación de privacidad se reutiliza mientras no cambia el aviso y la limpieza recorre el JSON
una sola vez. Cuota predeterminada: 300 mutaciones/minuto/IP para soportar usuarios tras la wifi compartida;
`MANDO_PUBLIC_RATE_MAX` sigue permitiendo reducirla y conserva 429, límite de cuerpo y cuota de páginas.
Prueba local N=50 sesiones × 4 turnos: tick máximo 0,0801 s en la primera medición integrada (antes 9,3730 s).
Es una medición local de esta ejecución, no garantía de producción; la suite imprime el máximo en cada pasada.

Pruebas: `test_personal.py`, `test_multi.py`, `test_team_services.py`, `test_chat_tabs.py`; incluyen carrera 200/409,
doble firma, presencia/SSE, credenciales, bloqueo de ruta y carga de chat. Todo se verifica sin plataforma.
