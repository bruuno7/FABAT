# MANDO — guía de uso

> **Nota (diseño 19-sep).** Este texto describe sobre todo el **plan B de reglas** (`motor/mando`: prioridad, gemelo, supuestos) y pantallas que ya no son la demo (`/centro`, `/clasico`, `/duelo`, `/memoria`…). El diseño actual: un **equipo de agentes en HappyRobot** decide; este repo es mundo, herramientas, barandillas y **Sala** (`/`). Público: `/asistente`. Jurado: `/jurado`. Ver `README.md`, `docs/PLAN-GIRO.md` y `motor/happyrobot/cerebro/HERRAMIENTAS.md`.

Guía para quien no conoce el producto: compañera nueva, mentor, o alguien con un portátil que quiere levantarlo y tocarlo. No hace falta saber programar más allá de pegar comandos.

**Esto es una simulación de un festival ficticio** (Festival Abierto). No es un servicio de emergencias. Si hay una emergencia de verdad, llama al 112.

Comprobado contra un servidor real en local (`TELEGRAM_MODE=off`, `MANDO_DB=off`, casos `demo-1` y `demo-gates`). Si algo no se pudo probar o no existe, está en [§6](#6-limitaciones-y-cosas-a-medias), no se vende como si funcionara.

---

> **Para entender cómo decide:** [`COMO-DECIDE.md`](COMO-DECIDE.md) (fórmulas y umbrales reales) y la pantalla `/porque` (las seis preguntas del reto, en vivo). **Qué cubre del reto y cómo demostrarlo en 30 segundos:** [`COBERTURA-RETO.md`](COBERTURA-RETO.md).

## 0. En un minuto

**MANDO** coordina muchos incidentes a la vez en un macroconcierto simulado: recibe avisos, decide qué va primero, manda al equipo más rápido, escribe de qué depende el plan y lo tira cuando eso deja de ser cierto. Lo grave no lo ejecuta solo: te lo pone delante y espera tu sí o tu no.

### El problema

En un recinto lleno llegan a la vez mareos, embudos, una pelea, una parada, una puerta atascada. Si tratas cada aviso como un mundo aparte, mandas dos equipos al mismo sitio, dejas lo grave sin gente y no te enteras de que el pasillo que usabas ya no se puede cruzar.

### Las tres piezas

| Pieza | Qué hace | Qué no hace |
|---|---|---|
| **HappyRobot** | Habla y entiende. Convierte voz o texto en un aviso estructurado. Llama (o abre una llamada web) al jefe de equipo y recoge ACEPTA / NO PUEDO. | No decide prioridad, no reparte recursos, no tira planes. |
| **MANDO** | Decide con **reglas** (no con un modelo de lenguaje). Ensayo previo en un **gemelo** del recinto: copia del estado de ahora, **sin** el guion futuro. Escribe supuestos («esta ambulancia acepta en 3 min»). | No marca el 112. No evacúa ni para el concierto sin una persona. |
| **Una persona** | Manda en lo grave: evacuar, parar el concierto, pedir ayuda externa, cerrar una zona. Ve dos futuros y aprueba o veta. | No tiene que aprobar un despacho médico de riesgo vital: eso sale solo. |

### Qué es real y qué es simulado

| Real (si lo configuras) | Simulado siempre |
|---|---|
| Llamadas / llamadas web de HappyRobot a **móviles de una lista blanca** | El recinto, la gente, los equipos, el tiempo |
| Bot de Telegram, webhooks de ida y vuelta | Sensores de aforo y meteorología |
| Avisos desde `/asistente` (navegador de verdad) | La voz del equipo cuando arrancas en modo `sim` |
| Tu clic de aprobar / vetar | — |

Un **tick** es un minuto del recinto. A velocidad 1, un segundo real ≈ un minuto simulado.

**SSE** (Server-Sent Events): el servidor empuja una foto nueva del estado a la pantalla cuando algo cambia. No recargas. Si se corta, ves «Reconectando…».

**Webhook**: HappyRobot (u otro puente) hace POST a `/hr/events` para avisarnos. Sin secreto configurado, esa puerta está cerrada.

### Flujo (dibujo)

```
  público / staff                 HappyRobot                 MANDO                    persona
  -------------                   ----------                 -----                    -------
  escribe o habla  ----------->  entiende el aviso
                                 (si está configurado)
                                        |
                                        v
                                 POST /hr/events  ------>  triaje · fusión
                                 o /api/chat /report        prioridad (0–10 + porqué)
                                                            ensayo 12–15 min en el gemelo
                                                            plan con SUPUESTOS
                                                            despacho / desvío / pregunta
                                        ^                          |
                                        |                          |
                                 llama al equipo  <-----  orden
                                 ACEPTA / RECHAZA / silencio
                                        |                          |
                                        v                          v
                                 resultado ---------------->  si se rompe un supuesto:
                                                              SUPUESTO ROTO → plan nuevo
                                                              si es grave → TARJETA
                                                                                   |
                                                                                   v
                                                                            APROBAR o VETAR
                                                                            (o se escala al suplente)
```

El recinto vive en un simulador. Puedes romperlo a mano (imprevistos) y ver si el plan aguanta.

---

## 1. Levantarlo

### Requisitos

- **Python 3.12 o más nuevo** (comprobado con 3.14).
- **`uv`** (el arranque del servidor lo usa). En macOS: `brew install uv`.
- Un navegador.
- Opcional: Docker, túnel (`cloudflared`), cuenta de HappyRobot, bot de Telegram. Sin eso, el MVP corre **entero en local y simulado**.

Núcleo del motor (simulador, casos, planificador): biblioteca estándar de Python. El servidor añade FastAPI, uvicorn, httpx, segno, mcp.

Trabaja **siempre desde la raíz del repositorio**.

### Instalación desde cero

```bash
# 1. Python 3.12+ y uv
python3 --version
uv --version

# 2. (opcional) variables locales; vacío = todo simulado
cp .env.example .env

# 3. Primera vez: el script genera casos grandes si faltan
#    (train.jsonl 3000 + heldout.jsonl 1000, semilla 1). Puede tardar.
./mvp.sh
```

Abre:

- Sala de control: `http://127.0.0.1:8000/`
- App de quien avisa: `http://127.0.0.1:8000/asistente`

Para parar: **Ctrl+C** en esa terminal.

### Todas las formas de arrancar

#### `./mvp.sh` (modos)

`mvp.sh` lee `.env` si existe. Puerto por defecto `MANDO_PORT` (8000). Caso por defecto `MANDO_CASE` (demo-1). Velocidad `MANDO_SPEED` (1).

| Comando | Qué hace | Cuándo usarlo |
|---|---|---|
| `./mvp.sh` o `./mvp.sh local` | Servidor simulado en `127.0.0.1`. Imprime las dos URLs y entra. Reloj **en pausa** salvo que pases `--play` por el comando directo. | Día a día en tu máquina. |
| `./mvp.sh lan` | Igual, pero escucha en `0.0.0.0` (misma wifi). | Móviles en la sala. |
| `./mvp.sh real` | Pasa `doctor` (sigue aunque falle). Arranca `--comms happyrobot --lan`. Avisa si falta `MANDO_ALLOWED_NUMBERS`. | Cuando ya rellenaste `.env` y quieres voz / Telegram de verdad. |
| `./mvp.sh demo` | `python -m motor.server demo`: doctor **sin red**, caso pausado, playbook de partida, canales rotulados. | Presentar. Plan B local si falta plataforma. |
| `./mvp.sh check` | Tests del núcleo + tests del servidor + `cases check-world` + `doctor`. | Antes de fiarte de un cambio. |
| `./mvp.sh cifras` | `python3 -m motor.harness headline`. Recalcula el titular del banco (con N). | Medir; no es la demo. |
| `./mvp.sh loquesea` | Imprime la ayuda y sale 1. | Recordar modos. |

La primera ejecución de `local`/`lan`/`real`/`check` puede generar `motor/cases/data/train.jsonl` y `heldout.jsonl` si no están.

#### Comando directo (todas las opciones reales)

Servidor normal:

```bash
uv run --project motor/server python -m motor.server \
  --case demo-1 \
  --speed 1 \
  --port 8000 \
  --comms sim \
  --playbook auto
```

| Opción | Valores | Por defecto | Qué hace |
|---|---|---|---|
| `--case` | `demo-1`…`demo-12`, `demo-gates`, o un id de `demo.jsonl` / `heldout.jsonl` | `demo-1` | Qué historia carga. |
| `--seed` | entero | la del caso | Reproduce la aleatoriedad. |
| `--speed` | float | `1.0` | Minutos del recinto por segundo real. |
| `--comms` | `sim` \| `happyrobot` | `sim` | Voz simulada o plataforma. |
| `--playbook` | `auto` \| `learned` \| `seed` \| `none` | `auto` | Manual de lecciones. `auto` = el aprendido del banco si existe. |
| `--port` | entero | `8000` | Puerto HTTP. |
| `--lan` | flag | off | Escucha en `0.0.0.0`. Nunca abre internet por sí mismo. |
| `--play` | flag | off | Reloj en marcha al arrancar. |

Presentación (`demo`): **solo** `--case`, `--port`, `--lan`. Siempre pausa inicial, playbook `seed`, parámetros locales desactivados. Si `MANDO_COMMS=happyrobot` **y** no faltan imprescindibles de voz, usa HappyRobot; si no, cae a `sim` y lo dice.

```bash
TELEGRAM_MODE=off MANDO_DB=off uv run --project motor/server python -m motor.server demo --case demo-1 --port 8000
```

Otros subcomandos:

```bash
uv run --project motor/server python -m motor.server doctor          # diagnóstico (puede sondear red)
uv run --project motor/server python -m motor.server doctor --sin-red
uv run --project motor/server python -m motor.server doctor --json /tmp/doctor.json
uv run --project motor/server python -m motor.server ensayo --case demo-1   # 7 hitos sin pantalla
```

Al arrancar imprime:

- `Pantalla de mando: http://127.0.0.1:<puerto>/`
- Con `--lan`: `Página del jurado: http://<ip-lan>:<puerto>/jurado` (QR en `/qr`)
- Bot de Telegram: arrancando (long polling) o apagado (falta token / `TELEGRAM_MODE=off`)

El modo `demo` imprime además `HAPPYROBOT` / `TELEGRAM` / `VOICE` en mayúsculas y recuerda Espacio / R / K.

#### Docker

Hay `Dockerfile` (Python 3.13-slim + `uv`, genera heldout al construir, `EXPOSE 8000`, arranca `--lan`). Variables de la imagen: `MANDO_CASE`, `MANDO_SPEED`, `MANDO_PORT`, `MANDO_COMMS`.

```bash
docker build -t mando .
docker run --rm -p 8000:8000 -e MANDO_CASE=demo-1 mando
```

**No se pudo verificar aquí:** el demonio de Docker no estaba en marcha (`Cannot connect to the Docker daemon`). El fichero existe; el contenedor no se construyó ni se ejecutó en esta máquina.

### Casos de demostración

`GET /api/cases` devolvió **13** casos:

| Alias | Título (qué enseña) | Min |
|---|---|---|
| `demo-gates` | Puerta B atascada: comparación de decisiones. Título de sesión a menudo **vacío**; el recinto sí carga. Previsiones del gemelo visibles al avanzar. | 90 |
| `demo-1` | Parada cardiaca con la ambulancia atrapada. Momento clave (K) del producto. Fusión, supuestos, escalada. | 60 |
| `demo-2` | Densidad crítica en el foso y una valla que cede. | 60 |
| `demo-3` | Calor: agua agotada, golpes de calor, puesto saturado. | 75 |
| `demo-4` | Aviso en inglés sin ubicación y un equipo que dice que no. | 60 |
| `demo-5` | Objeto sin dueño: Mando no decide, escala. | 60 |
| `demo-6` | Apagón en restauración, cae el cashless, se calienta la cola. | 70 |
| `demo-7` | Salida del día 3: metro cortado, un mayor desorientado y fin de turno. | 70 |
| `demo-8` | Tormenta con estructuras: parar es decisión humana. | 60 |
| `demo-9` | Tormenta a la salida, agresión a un auxiliar y metro cortado. | 70 |
| `demo-10` | Quien avisa es el público (la app). | 45 |
| `demo-11` | Seis frentes a la vez. | 60 |
| `demo-12` | Seis frentes y el imprevisto de quien avisa. | 60 |

Cargar otro caso en caliente:

```bash
curl -sS -X POST http://127.0.0.1:8000/api/session \
  -H 'Content-Type: application/json' \
  -d '{"case_id":"demo-gates"}'
```

### Variables de entorno

Copia `.env.example` → `.env`. Nunca subas secretos. Agrupadas. «Vacío» = no la pongas o déjala en blanco.

#### Arranque

| Variable | Por defecto | Qué hace | Cuándo tocarla |
|---|---|---|---|
| `MANDO_PORT` | `8000` | Puerto HTTP. | Puerto ocupado. |
| `MANDO_CASE` | `demo-1` | Caso de `mvp.sh` local/lan/real. | Elegir historia. |
| `MANDO_SPEED` | `1` | Minutos simulados por segundo. | Acelerar. |
| `MANDO_DEMO_CASE` | `demo-1` | Caso de `./mvp.sh demo` **y** de la tecla K. | Presentar otra historia. **Ojo:** K ignora el caso actual. |
| `MANDO_COMMS` | `sim` | `sim` o `happyrobot`. El modo `demo` puede forzar `sim` si faltan claves. | Voz real. |
| `MANDO_PUBLIC_URL` | vacío | URL https pública (túnel). Obligatorio para que HappyRobot nos llame. Con esto, **también en localhost** hace falta token de operador. | Túnel / demo remota. |

#### Operadores y seguridad

| Variable | Por defecto | Qué hace | Cuándo tocarla |
|---|---|---|---|
| `MANDO_OPERATOR_TOKEN` | vacío | Token único (legado). Cabecera `X-Mando-Operator` o cookie vía `/acceso`. | URL pública. |
| `MANDO_OPERATORS` | vacío | Varios operadores `nombre:rol:token` separados por coma o salto. | Varias personas. En local sin esto, el servidor te trata como `operador-1`. |
| `MANDO_TWO_PERSON` | off (`1` activa) | Lo grave pide **2 firmas**. | Cuatro ojos. |
| `MANDO_MCP_TOKEN` | vacío | Protege `/mcp`. Sin él: **503**. | Herramientas MCP. |
| `MANDO_CORS_ORIGINS` | vacío (sin CORS) | Orígenes permitidos, coma, `https://host` sin ruta. Cookie SameSite=strict: una UI externa usa la cabecera, no la cookie. | Front en otro origen. |
| `MANDO_PUBLIC_RATE_MAX` | `300` | Mutaciones por IP y ventana. Los GET de página tienen el doble. | Abuso. |
| `MANDO_PUBLIC_RATE_WINDOW_S` | `60` | Ventana del cupo. | Idem. |
| `MANDO_ASK_WAIT_S` | `45` | Espera de una pregunta al informante (HappyRobot). | Ajustar voz. |

En local, sin URL pública y sin `MANDO_OPERATORS`, localhost **no** pide login para mandar. Con `MANDO_PUBLIC_URL`, entra por `/acceso` o manda `X-Mando-Operator`.

#### HappyRobot

| Variable | Por defecto | Qué hace | Cuándo tocarla |
|---|---|---|---|
| `HR_API_BASE` | clúster EU `/api/v2` | API de la plataforma. | Casi nunca. |
| `HR_PLATFORM_BASE` | plataforma EU | Editor. | Casi nunca. |
| `HR_ENV` | `development` | Elige hooks `_DEVELOPMENT` si existen. | Producción. |
| `HR_API_KEY` | vacío | Bearer. **Nunca en el repo.** | Llamadas reales. |
| `HR_SECRET` (alias `MANDO_HR_TOKEN`) | vacío | Secreto de webhooks entrantes (`X-Mando-Token`). Sin él, `/hr/events` → **503**. | Callbacks. |
| `HR_LAUNCH_MODE` | `hook` | `hook` (URL) o `runs` (API + slug). | Cómo lanzas workflows. |
| `HR_WORKFLOW_*` / `HR_HOOK_*` | vacío | Slug o URL de cada oficio. Nombres genéricos: despacho, webcall, voz, texto, chat, sanitario, seguridad, técnico, logística, director, externos, difusión, relevo, personal, sms, avisos externos, email. | Tras publicar en la plataforma. **No copies slugs de otro entorno.** |
| `HR_INTAKE_TIMEOUT_S` | `6` | Tope de la ingesta de texto. | Red lenta. |
| `HR_TIMEOUT_S` | `5` | Tope de un hook. | Idem. |
| `HR_RETRIES` | `1` | Reintentos. | Idem. |
| `HR_FALLBACK_S` | `12` | Segundos hasta caer a simulado. | Demo con red mala. |
| `HR_HOOK_ENHANCED` | `1` | Manda `x-api-key` al hook. `0` la quita. | Si el hook no la quiere. |
| `HR_SLOW_ON_CALL` | `1` | Reloj más lento mientras hay llamada real. `0` lo apaga. | Presentación. |
| `MANDO_VOICE_MODE` | código: `web_call` (`.env.example` sugiere `phone`) | `web_call` = no marca teléfono. `phone` = salida Telnyx a lista blanca. | Primera llamada. |
| `MANDO_ALLOWED_NUMBERS` | vacío | E.164 separados por comas. **Sin lista no se llama a nadie.** | Teléfono real. |
| `MANDO_CONTACTS` | `contacts.local.json` | Contactos locales (no versionados). | Mapeo recurso → número. |
| `HR_CHAT_PUBLIC_URL` / `HR_WEBCALL_PUBLIC_URL` | vacío | Enlaces públicos de chat y web call. No se inventan. | Botones de `/asistente`. |
| `HR_INTAKE_EMAIL` / `HR_SMS_NUMBER` | vacío | Muestran email/SMS en la app. SMS debe ser E.164. | Canales de texto. |
| `HR_CHAT_TOKEN` | vacío | Token del widget; **no** vale como secreto de webhook (403). | Chat embebido. |

Números de emergencias reales están en una lista **NEVER_DIAL** (112, 061, 091, 911, 999, …). El doctor avisa si aparecen en contactos. El botón «112» **no marca**.

#### Telegram

| Variable | Por defecto | Qué hace | Cuándo tocarla |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | vacío | Token de BotFather. Sin él el bot no arranca. | Canal público. |
| `TELEGRAM_BOT_USERNAME` | vacío | Usuario para el enlace / QR. | Mostrar el botón. |
| `TELEGRAM_MODE` | `poll` en el ejemplo; el bot **no** arranca si vale `off` | `poll` = este proceso pregunta a Telegram (un consumidor). `send_only` = otro proceso (puente) recibe el webhook; aquí solo se envía. `off` = apagado. | Un bot = un solo consumidor. |
| `TELEGRAM_API_BASE` | `https://api.telegram.org` | API. | Tests. |
| `TELEGRAM_POLL_TIMEOUT_S` | `25` | Long poll. | Red. |
| `TELEGRAM_RATE_MAX` / `TELEGRAM_RATE_WINDOW_S` | `6` / `60` | Cupo de envíos. | Evitar flood. |
| `TELEGRAM_MAX_CHARS` | `400` | Tope de un mensaje. | Igual que avisos web. |
| `MANDO_TRUST_TG_APPROVAL` | off | Si `1`, el espejo Telegram puede registrar una decisión. | Solo con puente de confianza. |

#### Base de datos

| Variable | Por defecto | Qué hace | Cuándo tocarla |
|---|---|---|---|
| `MANDO_DB` | `motor/server/data/mando.db` | SQLite del historial (mismo estado público ya enmascarado). `off` desactiva `/historial` (**503**). | Demo sin disco, o ruta propia. |

#### Banco de pruebas (no hace falta para la pantalla)

`MOTOR_HARNESS_OUT`, `MOTOR_HARNESS_DATA`, `MOTOR_HARNESS_RUNS`, `MOTOR_HARNESS_REG`, `MOTOR_HARNESS_FROZEN`: carpetas del banco. Déjalas.

### Abrirlo a móviles de la misma wifi

```bash
./mvp.sh lan
# o:  uv run --project motor/server python -m motor.server --case demo-1 --port 8000 --lan
```

1. El portátil y el móvil en la **misma** wifi (no red de invitados aislada).
2. En el portátil abre `/qr?path=/asistente`. Es un SVG. La cabecera `X-Jurado-Url` trae `http://<tu-ip>:<puerto>/asistente`.
3. En `/clasico`, tecla **Q** o botón «QR JURADO» pone ese QR a pantalla completa. En la Sala (`/`) **no hay tecla Q**.
4. `/jurado` redirige a `/asistente`.

### Abrirlo con un túnel

El código **no** abre túneles. En otra terminal:

```bash
cloudflared tunnel --url http://127.0.0.1:8000
```

Copia la URL `https://…` a `MANDO_PUBLIC_URL`, pon `MANDO_OPERATOR_TOKEN` (o `MANDO_OPERATORS`), **reinicia** el servidor. Entra a la Sala por `/acceso`. HappyRobot debe poder alcanzar `{MANDO_PUBLIC_URL}/hr/events`.

### Pararlo y reiniciarlo

- **Parar:** Ctrl+C en la terminal del servidor.
- **Reiniciar el proceso:** el mismo comando.
- **Reiniciar la escena** (mismo proceso, minuto 0): tecla **R** o `POST /api/control` con `{"cmd":"reset"}`.
- **Cambiar de caso:** `POST /api/session` o el desplegable de `/clasico`.
- **Puerto ocupado:** `lsof -iTCP:8000 -sTCP:LISTEN` y otro `--port`, o mata el proceso anterior.

### Problemas típicos

| Síntoma | Qué suele ser | Qué hacer |
|---|---|---|
| `Falta uv: brew install uv` | No está `uv` en el PATH. | Instálalo; cierra y abre la terminal. |
| Puerto en uso / `address already in use` | Otro MANDO (u otra app) en ese puerto. | Cambia `MANDO_PORT` / `--port`. |
| Pantalla en blanco | JS no carga, o el API no responde. | Abre la consola del navegador; `curl -sS http://127.0.0.1:PUERTO/api/version` debe dar `{"version":"0.1.0"}`. |
| «Reconectando…» / «↻ Reconectando…» | Se cortó el SSE (`/api/stream`). La UI **conserva** selección y último estado. | Mira si el proceso sigue vivo; recarga si no vuelve. |
| `Historial desactivado con MANDO_DB=off` | Lo apagaste a propósito (esta guía lo hizo en la demo). | Quita `MANDO_DB=off` y reinicia. |
| `/hr/events` → 503 | Falta `HR_SECRET`. | No es un fallo del recinto; falta secreto. |
| `/canal/sms` → 404 | `HR_SMS_NUMBER` vacío o no es E.164. | Los botones email/SMS de `/asistente` están **ocultos** hasta configurar. |
| Voz «simulada» en el banner | `MANDO_COMMS=sim` o faltan clave / contactos. | Normal en local. |
| K te cambia el caso a `demo-1` | K carga `MANDO_DEMO_CASE`, no el caso actual. | Pon `MANDO_DEMO_CASE` o no pulses K en `demo-gates`. |
| `/porque` 404 | El enlace existe en `/clasico`; la ruta **no**. | Usa esta guía. |

---

## 2. Lado del PÚBLICO (quien avisa)

Tres pestañas en `/asistente`: **Avisar**, **El festival ahora**, **Poner a prueba**. Hay idioma (ES/EN) y tema claro/oscuro.

Varias personas a la vez: cada móvil es un chat (`session_id`) y sus avisos (`j-…`). Todos ven el mismo recinto. Cada cual sigue **su** aviso.

### Página del asistente (`/asistente`)

**Qué hace la persona**

1. Entra (opcional: nombre). Elige zona en el plano o escribe.
2. Cuenta **qué pasa y dónde** en el recuadro, o usa un atajo de incidente.
3. Responde las preguntas (botones Sí / No / No lo sé cuando salen).
4. Lee la instrucción de seguridad si sale («Qué hacer ahora»).
5. Pestaña «El festival ahora»: plano y densidad **simulada**.
6. Pestaña «Poner a prueba»: hasta **3 imprevistos** por persona y **3 globales** por partida.

**Qué le contesta el sistema**

- Acuse («Anotado…», «Ya he pasado el aviso al centro de control»).
- **Una** pregunta por turno, si falta un dato crítico.
- Instrucción de una lista cerrada (RCP, calor, quédate con el menor…).
- Si el texto no es un aviso («hola», «no lo sé» suelto): puede cerrar con *«Solo atiendo avisos de emergencia del recinto.»* sin contar pregunta.

**Por qué pregunta.** Para no mandar un equipo a «pista» sin saber si la persona responde, o si hay que hacer RCP. Tope declarado: **5** (`max_questions`). En un mareo real el hilo cerró a las **3** y dejó de preguntar.

**Qué ve después sobre SU aviso.** El hilo sigue en «Avisar». En control, `GET /api/report/{id}` (ejemplo tras un chat de parada):

- `incident`, `label`, `priority`, `priority_why`
- `status` / `status_text`
- `doing` (qué orden hay)
- `call.state` (`acepta`, etc.)
- `safety` (la instrucción que le dieron)

**Varios usuarios.** Cada uno tiene su conversación. El triaje puede **fusionar** dos textos del mismo sitio en un solo incidente (lo ves en control, no como dos fichas gemelas).

### Página del jurado (`/jurado`)

El servidor entrega HTML y **el JavaScript redirige a `/asistente`**. No hay una UI distinta. Los imprevistos están en la pestaña «Poner a prueba» de esa misma app.

### Bot de Telegram

**No se pudo hablar con un bot en esta verificación** (`TELEGRAM_MODE=off`, sin token). Lo que sigue es lo que el código hace **si** arrancas con token y `TELEGRAM_MODE=poll` (y nadie más está haciendo poll del mismo bot).

Comandos: `/start` · `/zona <nombre>` · `/pulsera <código>` · `/golpe` · `/estado`. Admite ubicación compartida (zona más cercana de un plano **ficticio**; no es GPS de verdad).

Al escribir qué + dónde:

1. Acuse: *«Recibido. Lo paso al centro de control.»*
2. Una instrucción de la lista cerrada (o la genérica de «sitio seguro»).
3. Pregunta de aclaración si MANDO emite un ASK a ese chat.
4. Cierre según estado: *«Equipo en camino.»* / *«El equipo ya está en el sitio.»* / *«Resuelto.»*

`/start` avisa que es **simulación** y que una emergencia real es el 112.

En control el origen se guarda como alias `telegram:<n>`, **nunca** el nombre de Telegram. Si el incidente es reservado, las respuestas son neutras.

Un bot = **un** consumidor. Si el puente (webhook) ya recibe updates, aquí `TELEGRAM_MODE=send_only` o `off`. Dos pollers a la vez se pisan.

### Llamada web (voz)

Botón **«Prefiero hablar»** en `/asistente` (si hay `HR_WEBCALL_PUBLIC_URL`). El personal descolgó en `/llamada/{id}`: **DESCOLGAR**, luego **ACEPTO** / **NO PUEDO** si es mock, o **COLGAR** si es LiveKit.

Con `--comms sim`, `GET /api/webcalls` devolvió **lista vacía**. No hay página de llamada que abrir. La «llamada» al equipo es simulada (véase §4).

### Email / SMS

Los botones están en el HTML **ocultos** (`hidden`) hasta que existan `HR_INTAKE_EMAIL` y `HR_SMS_NUMBER`. `GET /canal/sms` sin número válido → **404** `SMS sin configurar`. **No hay canal de email/SMS usable en un arranque vacío.**

### Pulsera (opcional)

En Telegram: `/pulsera FA-1001`. Por API:

```bash
curl -sS http://127.0.0.1:8000/api/pulsera/FA-1001
```

Perfil de demo: `raises_priority: false`, `demo: true`, *«La pulsera no da ubicación.»* Código inventado `00000` → 404 `Pulsera desconocida`.

---

## 3. Lado del CONTROL (quien responde del evento)

Pantalla principal: **`/`** (igual que `/sala`). Título: «MANDO · Sala de control». Cinta: *Simulación · recinto ficticio*.

La pantalla se actualiza sola por SSE (`GET /api/stream`).

### Recorrido de la Sala (`/`), zona por zona

**Barra izquierda**

- Marca MANDO y aforo del recinto simulado.
- Estado del evento.
- Filtros: **Todos los sectores** · **Solo graves** · **Sin recursos** · **Por sector activo**.
- Botón **112 EMERGENCIAS** — texto *«No marca ningún número»*. Abre el cajón «Pedir ayuda externa».
- Punto «Agente HR».
- Enlaces: `/centro`, `/clasico`, `/informe`. Tema claro/oscuro.

**Cabecera**

- Reloj del recinto, ACTIVOS, CRÍTICOS (Vital o Emergencia), LIBRES (equipos).
- Buscar por zona, tipo o ID.
- **Mesa de inyección** (imprevistos).
- Botón de operador.

**Banda del plan** (entre cabecera y plano)

- *«El plan sigue en pie»* o **«EL PLAN HA DEJADO DE VALER»** si un plan vivo acaba de romperse (supuesto `holds: false` en los últimos 8 minutos simulados). Debajo, el supuesto y el plan nuevo.

**Plano**

- Zonas coloreadas por densidad estimada (leyenda: <2 / 2–5 / >5 / >6,5).
- Botones **Trayectos**, **velocidad ▶ 1x/4x/16x**, **Densidad**.
- Clic en zona o en un punto de incidente abre la ficha.

**Leyenda de gravedad** (píldoras; el `?` abre la regla):

| Tramo | Regla (la pantalla **no** recalcula la prioridad; solo agrupa) |
|---|---|
| Vital | prioridad ≥ 9 **o** `life_threat` |
| Emergencia | ≥ 7 |
| Urgente | ≥ 5 |
| Leve | < 5 |
| Sin clasificar | aún no hay número |

**Cola** (tabla): GRAVEDAD, ID/TIPO, SECTOR, HORA, ESTADO, RECURSOS MANDO, AGENTE HR. Clic en una fila → ficha.

**Columna derecha:** recursos por oficio, barras de abiertos por gravedad, chat HR.

**«Reconectando…»** abajo si cae el SSE.

### Cómo leer cola, gravedad, plano, recursos

- La cola está ordenada por lo que el motor publica (prioridad). Pasa el ratón por la píldora: sale el **porqué** (`prioridad 9,2 = gravedad 9 × plazo …`).
- El plano **no es GPS**. Posición por zona del simulador.
- Recursos: libre / de camino / ocupado / fuera. Un despacho elige «el más rápido libre» y lo dice en el log.

### La banda «EL PLAN HA DEJADO DE VALER»

Significa: un supuesto escrito (`S-…`) pasó a `holds: false`. Ejemplo vivo: *«Seguridad 4 (pista) acepta en 3 min»* → el plan se tira y nace otro *«Porque: se rompió el supuesto …»*. No es decoración: es el titular del producto.

### Cómo abrir la ficha de un incidente

Clic en la fila, en el punto del plano, o **Enter** sobre la primera tarjeta de decisión (salta a ese incidente). **Esc** cierra cajones. La ficha trae: prioridad y porqué, fuentes fusionadas, plan y supuestos, tarjeta de decisión, llamadas, ensayo «¿y si…?», bloque Telegram si hay espejo.

### Cómo decidir

**Tarjeta de decisión** (en la ficha; teclas **A** / **V** sobre la **primera** pendiente):

- Quién decide (`role`) y **suplente** (`deputy`).
- Minutos de ventana (`remaining_min`). Si se pasa el primer plazo: **ESCALADO AL SUPLENTE** (`escalated: true`) y la tarjeta **sigue** `awaiting_approval`.
- **Dos futuros**, si el motor los publicó: **SI APRUEBAS** / **SI VETAS**, a menudo con personas/m² de pico y minutos por encima de 4/m², ensayados 12–15 min en el gemelo (`rehearsed: true`). Si no hay cifras, la ficha dice que **no se inventan**.
- Nota opcional (200 caracteres en Sala; 400 en Centro).
- Botones **APROBAR (A)** y **VETAR (V)**. Lo grave (evacuar, parar, pedir externa, cerrar zona) pide **segundo clic**: el botón pasa a *«CONFIRMAR: ES UNA ACCIÓN GRAVE»* (8 s).

**Qué pasa**

| Acción | Efecto comprobado |
|---|---|
| Aprobar | `POST /api/approve` `{action_id, ok: true}` → `ok: true`. La orden sigue. |
| Volver a aprobar | **409** `ya lo decidió operador-1 hace 0 s`. |
| Vetar | `ok: false` → la acción queda `status: "rejected"`. El `why` ya decía la alternativa (*«Si dices no: restringir la zona…»*). Log: `operador-1: veta`. |
| Nadie decide | La ventana corre. A mitad (p. ej. 2 min de 3) `escalated: true` hacia el suplente. **No** se ejecuta sola una evacuación. |

Lo que **siempre** espera persona (contrato): evacuar, parar el concierto, pedir ayuda externa. Cerrar una zona también. Un despacho de parada **no**.

### Mesa de inyección

Botón **Mesa de inyección**. Presupuesto de golpes (3 luces). Presets:

| Clave | Etiqueta |
|---|---|
| `block_ambulance` | Bloquear la ambulancia |
| `close_gate` | Cerrar una puerta |
| `no_answer` | Un equipo deja de contestar |
| `food_blackout` | Apagón en restauración |
| `storm` | Tormenta |
| `voice_down` | Cortar el canal de voz |

Los golpes **entran en el recinto simulado**. Nada sale a la calle. Origen `chaos` desde esta mesa; origen `jury` desde `/asistente`.

### Botón 112

Abre el parte de ayuda externa. **Nunca marca un número real.** Una petición `request_external` sigue siendo una tarjeta para una persona.

### Varias personas operando

- En local sin tokens: todos sois `operador-1`. Una decisión duplicada → 409.
- Con `MANDO_OPERATORS`: cada cual entra por `/acceso` o manda su cabecera. El Centro (`/centro`) muestra presencia, **Lo llevo yo**, notas.
- `MANDO_TWO_PERSON=1`: lo grave pide 2 firmas (no se activó en esta verificación).

### Teclas en la Sala (`/`)

| Tecla | Efecto |
|---|---|
| Espacio | Play / pausa |
| S | +1 minuto |
| R | Reiniciar escena |
| K | Momento clave (**carga `MANDO_DEMO_CASE`**, por defecto demo-1, ~minuto 7, pausado) |
| A / V | Aprobar / vetar la **primera** pendiente (abre ficha y decide) |
| Enter | Ir al incidente de la primera pendiente |
| Flechas | Velocidad 1 ↔ 4 ↔ 16 |
| E | Modo escena (más grande) |
| Esc | Cerrar cajones |

No hay Q aquí.

---

### Otras pantallas (más breve)

**`/centro`** — Centro de control con cuenta atrás de previsiones. Filtros Todos / Críticos / Atención / Previstos. El bloque ◷ muestra `PREVISTO` *«En N min»*, o `EVITADO` / `CUMPLIDO` / `NO_CUMPLIDO`. Pie: `N previstos · evitados* · cumplidos…` (*asociación temporal al plan*). Teclas: Espacio, S, K, R, A/V, E (pantalla grande). Panel de equipo: identidad, **Lo llevo yo**, enlaces de personal + QR, aviso 112 **registrado** (no marcado). Banner propio de reconexión.

**`/clasico`** — Vista técnica oscura (la antigua principal). Embudo de avisos, frentes, supuestos, llamadas, tarjeta. Teclas extra: **Q** (QR), **M** (sonido), desplegable de caso y de `sim` / `happyrobot`. Enlaza `/porque` → **404** (la ruta no existe).

**`/duelo`** — Misma semilla, mismos imprevistos: izquierda lista fija, derecha MANDO. Play / ×1 ×4 ×16 / reiniciar. Espacio = play/pausa. N = 1 caso por lado.

**`/memoria`** — Observaciones del día 1 (con su N), propuestas **Aprobar / Rechazar**, tabla antes/después con intervalo. MANDO no cambia parámetros solo.

**`/informe`** — Informe de **esta** ejecución (N=1). Críticos, supuestos rotos, llamadas fallidas→recuperadas, decisiones, golpes. Las medias van en `/curva` y en el banco.

**`/historial`** — Con `MANDO_DB=off`: **503**. Con base activa: escenas, incidentes, decisiones, export JSON/CSV. Exige operador si hay URL pública.

**`/curva`** — Gráfica del banco (`motor/harness/out/curve.json`) si existe (`available: true` en esta máquina). Si no hay fichero, la página lo dice.

**`/caos`** — Consola del adversario. Pide sugerencias a `GET /api/chaos/suggest` (ata el supuesto que más daño hace) y **EJECUTAR GOLPE**.

También: `/personal` (órdenes de una unidad; enlace firmado desde el Centro), `/simulacro` (batería exprés de ataques), `/acceso` (login de operador).

---

## 4. Probar cada función, una a una

Arranque recomendado para copiar y pegar (otro puerto si 8000 está pillado):

```bash
TELEGRAM_MODE=off MANDO_DB=off uv run --project motor/server python -m motor.server demo --case demo-1 --port 8000
```

En otro terminal, `HOST=http://127.0.0.1:8000`. **R** o `reset` entre pruebas sucias.

---

### Aviso por la app web

**Qué hace.** Convierte un texto del público en un aviso (`j-…`) y, si se entiende, en un incidente (`M-…`).

**Cómo actúa por dentro.** `/api/chat` usa el motor de recogida (protocolos, máximo 5 preguntas). El texto pasa al triaje. Canal `web` / `chat`.

**Cómo probarla.** Abre `/asistente`, elige zona, escribe: `Persona inconsciente en el foso, no responde`. O:

```bash
curl -sS -X POST $HOST/api/chat -H 'Content-Type: application/json' \
  -d '{"text":"Persona inconsciente en el foso, no responde","zone_hint":"front_pit","lang":"es"}'
```

**Qué deberías ver.** `report_id` (`j-001`…), acuse, a menudo instrucción. En `/`, una fila nueva.

**Si no sale.** El texto vago (*«pasa algo raro»* sin sitio) puede responder *«Cuéntame qué pasa y dónde.»* sin abrir incidente.

---

### Aviso por `POST /api/report`

**Qué hace.** Inyecta un aviso como el de la app, sin chat.

**Cómo actúa por dentro.** Mismo triaje. `channel` típicos: `web`, `whatsapp` (contrato del público; Telegram también usa esa vía).

**Cómo probarla.**

```bash
curl -sS -X POST $HOST/api/report -H 'Content-Type: application/json' \
  -d '{"channel":"web","text":"Hay alguien tirado en el foso que no se mueve","zone":"front_pit"}'
```

**Qué deberías ver.** `report_id`. Luego `curl $HOST/api/report/j-00X` con estado y prioridad.

**Si no sale.** Cuerpo > 8192 bytes o texto > 400 caracteres → rechazo. Cupo por IP.

---

### Aviso por Telegram (bot)

**Qué hace.** Mismo camino de aviso; responde en el chat.

**Cómo actúa por dentro.** El bot hace long-poll, crea el aviso, manda acuse + instrucción de lista cerrada.

**Cómo probarla.** Solo con token y `TELEGRAM_MODE=poll`. `/start` y un texto con zona.

**Qué deberías ver.** Acuse *«Recibido. Lo paso al centro de control.»* y el aviso en la Sala.

**Si no sale.** Sin token, `telegram: apagado`. Dos procesos en `poll` se pisan. **No verificado en vivo en esta guía.**

---

### Aviso por llamada web / email / SMS

**Qué hace.** Entrada de voz o texto por HappyRobot hacia `/hr/events`.

**Cómo actúa por dentro.** Webhook `public_report` + `X-Mando-Token`.

**Cómo probarla.** Sin `HR_SECRET`, el POST a `/hr/events` da **503**. Email/SMS: botones ocultos, `/canal/sms` **404**. `GET /api/webcalls` en `sim` → `[]`.

**Qué deberías ver.** Con plataforma: aviso en la cola y, si hay web call de despacho, `/llamada/{id}`.

**Si no sale.** Es el caso normal en local vacío. No lo documentes como canal vivo hasta `doctor` en verde y un callback visto.

---

### Preguntas del asistente y límite

**Qué hace.** Pregunta lo mínimo (¿responde? ¿dónde?) y corta.

**Cómo actúa por dentro.** Tope `max_questions = 5`, una pregunta por turno. Fuera de tema: cierra. «No lo sé» repetido puede cerrar antes de 5.

**Cómo probarla.**

```bash
curl -sS -X POST $HOST/api/chat -H 'Content-Type: application/json' \
  -d '{"text":"Hay una persona mareada en puerta B, está sentada en el suelo","zone_hint":"gate_b"}'
```

Sigue con el `session_id` que te devuelve y `{"text":"No lo sé","session_id":"…"}`.

**Qué deberías ver.** Primera: *«¿Está despierta y te responde?»*, `questions_asked: 1`, `max_questions: 5`, instrucción `heat`. En esta máquina el hilo **cerró en 3** (`done: true`) y dejó de preguntar. Un *«pasa algo raro»* suelto **no** incrementó el contador y acabó en *«Solo atiendo avisos de emergencia…»*.

**Si no sale.** No esperes siempre 5 preguntas: el tope es techo, no cuota.

---

### Instrucción de RCP inmediata

**Qué hace.** Si no responde y no respira, despacha ya y lee RCP solo con las manos.

**Cómo actúa por dentro.** Protocolo `cpr_hands_only` (8 pasos, metrónomo). `questions_asked` puede quedar en **0**: no retrasa la RCP preguntando el color de la camiseta.

**Cómo probarla.** Texto tipo *«en el foso no respira, no responde»* (con zona).

**Qué deberías ver.** `instruction.id = cpr_hands_only`, pasos (altavoz, boca arriba, talón de la mano, 5 cm, etc.), `done: true`, aviso en control. Fuente del protocolo en el JSON (`source`).

**Si no sale.** Si dices solo «mareo», sale el protocolo de calor, no RCP.

---

### Fusión de avisos duplicados

**Qué hace.** Dos relatos del mismo sitio → un incidente, no dos equipos.

**Cómo actúa por dentro.** Ventana **15 min** (`MERGE_WINDOW`). Acción `kind: merge`, p. ej. *«Aviso j-002 es el mismo incidente M-001 (2 avisos, confianza 67 %): no se manda otro equipo»*.

**Cómo probarla.** Tras reset, dos chats/reportes: *«Persona inconsciente en el foso, no responde»* y *«Hay alguien tirado en el foso que no se mueve»*. Avanza 1 min (**S**).

**Qué deberías ver.** Un `M-001` con `reports: ["j-001","j-002"]`. `GET /api/informe` → `metrics.merges` ≥ 1.

**Si no sale.** Si pasan >15 min simulados o la zona no cuadra, abre otro incidente.

---

### Contradicción y desmentido

**Qué hace.** Un aviso dice pelea y otro dice que no pasa nada: baja confianza y pregunta.

**Cómo actúa por dentro.** Nota en el incidente: *«un aviso del público dice que no pasa nada»*. Log: versiones contradictorias; puede **sustituir el plan**. ASK al informante.

**Cómo probarla.** Reset. Reporta una pelea en puerta A; luego *«En puerta A no pasa nada, era una broma»*. Step.

**Qué deberías ver.** `notes` con el desmentido, confianza más baja, pregunta en el log.

**Si no sale.** El segundo texto tiene que anclar la misma zona.

---

### Prioridad con número y porqué

**Qué hace.** Ordena la cola con un número 0–10 y una frase.

**Cómo actúa por dentro.**

`prioridad = min(10, gravedad × plazo × densidad × vulnerable × tendencia × confianza) + ajuste`

Suelo: riesgo vital **nunca baja de 9,0**. Plazo: más urgente si quedan pocos de 30 min. Densidad cuenta más en aglomeraciones.

**Cómo probarla.** Tras un aviso de inconsciente, `curl -sS $HOST/api/state | …` mira `incidents[].priority` y `explain`, o la ficha.

**Qué deberías ver.** Frase tipo *«prioridad 9,2 = gravedad 9 × plazo 7 min (×1,06) × densidad 4,2/m² …»*.

**Si no sale.** Sin triaje aún: «sin clasificar», sin número.

---

### Asignación de recursos

**Qué hace.** Elige el equipo libre más rápido de ese oficio.

**Cómo actúa por dentro.** Despacho `kind: dispatch`. El `why` nombra al elegido y al siguiente. En riesgo vital puede **retirar** un equipo de otro frente y decirlo en `why_waiting`.

**Cómo probarla.** Aviso médico + **S** varias veces. Mira cola (columna recursos) y `resources[]` (`busy` + `task`).

**Qué deberías ver.** *«Equipo médico 1 … el más rápido … 4 min (siguiente: Equipo médico 3)»*.

**Si no sale.** Si todos están ocupados, el frente queda «sin asignar» y explica la espera.

---

### Llamada con ACEPTA

**Qué hace.** El equipo dice que va y da un ETA.

**Cómo actúa por dentro.** En `sim`, `SimComms` tarda **1–3 min** simulados. Aceptar es lo más frecuente (`p_reject=0.04`, `p_no_answer=0.03`). Texto típico: *«Recibido, vamos para allá. Unos N min.»* `result: "accept"`, `real: false`.

**Cómo probarla.** `demo-1`, play o varios **S**. `GET /api/state` → `calls.calls`.

**Qué deberías ver.** `stage: llamando`, `result: accept`, `eta_min`, `comms_mode: sim`. Banner «voz simulada».

**Si no sale.** En `t=0` pausado no hay llamadas todavía.

---

### Llamada con RECHAZA y reasignación

**Qué hace.** Si no puede ir, se libera y se busca el siguiente.

**Cómo actúa por dentro.** `result: reject` o el caso fuerza `resource_rejects`. Log: *«está con otro incidente»* / se busca el siguiente.

**Cómo probarla.** `demo-4` (un equipo dice que no) o golpe `no_answer`. Avanza minutos.

**Qué deberías ver.** Recurso libre otra vez y un segundo despacho.

**Si no sale.** Con la semilla de `demo-1` a veces verás más «no contesta» que «rechaza»; el plan B es el mismo.

---

### Sin respuesta y plan B

**Qué hace.** Nadie coge; no deja el recurso bloqueado.

**Cómo actúa por dentro.** `result: no_answer` → `RECALL` (*«no contesta: se le libera»*). **SUPUESTO ROTO** si el plan decía «acepta en 3 min». Plan nuevo. Notify al coordinador.

**Cómo probarla.** `demo-1` + **K** (minuto 7) + **S**. O mesa: «Un equipo deja de contestar».

**Qué deberías ver.** Log `SUPUESTO ROTO en P-002: «Seguridad 4 (pista) acepta en 3 min»`. Plan `P-003 SUSTITUYE a P-002`. `calls_failed` y `calls_recovered` en el informe.

**Si no sale.** K te puede **cambiar el caso** a demo-1; es normal.

---

### Supuestos escritos de un plan

**Qué hace.** Cada plan lista de qué depende, en castellano.

**Cómo actúa por dentro.** Objetos `assumptions[]`: `text`, `holds`, `broken_at`, `id` (`S-0001`…). Ejemplos: *«Ambulancia interna acepta en 3 min»*, *«camino despejado por backstage (menos de 1,5/m²)»*, *«reevaluar en 5 min: la ocupación baja»*.

**Cómo probarla.** Ficha → caja PLAN, o `plans` en `/api/state` tras unos **S**.

**Qué deberías ver.** Lista con ✓ / ROTO.

**Si no sale.** A `t=0` aún no hay plan.

---

### SUPUESTO ROTO y plan nuevo

**Qué hace.** Si un supuesto falla, tira el plan y escribe otro con el porqué.

**Cómo actúa por dentro.** `invalidated_by: "S-0003"`. `why` del nuevo: *«se rompió el supuesto …»*. Banda **EL PLAN HA DEJADO DE VALER**.

**Cómo probarla.** `demo-1`, K, luego **S** al minuto 8.

**Qué deberías ver.** `holds: false`, `broken_at: 7` (u 4). Plan siguiente con el mismo incidente.

**Si no sale.** Sin avanzar el reloj no se rompe nada.

---

### Ensayo «¿y si…?»

**Qué hace.** Copia el recinto **ahora** (sin futuro del guion), simula 12–15 min con y sin una acción. No mueve el recinto de verdad.

**Cómo actúa por dentro.** `POST /api/whatif`. Veredicto: `mejor` / `igual` / `peor`. `note`: *«Ensayo en el gemelo: estado de ahora, sin futuro. No cambia nada en el recinto.»* Umbrales: 4 / 5 / 6,5 personas/m².

**Cómo probarla.** En la ficha: Desviar público → destino → **ENSAYAR**. O:

```bash
curl -sS -X POST $HOST/api/whatif -H 'Content-Type: application/json' \
  -d '{"kind":"reroute","zone":"gate_b","to":"gate_a","fraction":0.5,"minutes":15}'
```

**ORDENAR ESTA ALTERNATIVA** → `POST /api/whatif/order` (corrección de operador).

**Qué deberías ver.** `ok: true`, series `mando` vs `alternative`, `verdict` (en un ensayo a t=0 sobre puertas vacías salió `igual`).

**Si no sale.** Zona desconocida → 400.

---

### Previsiones del gemelo (PREVISTO → EVITADO / CUMPLIDO)

**Qué hace.** Publica *«si nadie actúa, esta métrica cruza el umbral en N min»*. Luego marca si ocurrió, no ocurrió, o se evitó.

**Cómo actúa por dentro.** El gemelo mira densidad (4 y 5 /m²), agua, equipos libres, rutas de ambulancia. Estados: `PREVISTO`, `CUMPLIDO`, `NO_CUMPLIDO`, `EVITADO`, `NO_VERIFICABLE`. EVITADO = umbral no visto en la ventana **y** hay intervención asociada (asociación **temporal**, no prueba causal). Centro: cuenta atrás *«En N min»*.

**Cómo probarla.** Carga `demo-gates`, muchos **S** (p. ej. hasta t≈20–32). Abre `/centro`, filtro **Previstos**.

**Qué deberías ver.** En vivo: `PREVISTO`, `CUMPLIDO`, `NO_CUMPLIDO` (p. ej. densidad puerta A). El UI sabe pintar **EVITADO**; **no apareció** en esta pasada.

**Si no sale.** En `demo-1` a t=12 la lista de `forecasts` estuvo **vacía**. Cambia a `demo-gates` y avanza.

---

### Tarjeta de decisión, veto y alternativa

**Qué hace.** Lo grave no se ejecuta solo. Ves dos futuros y eliges.

**Cómo actúa por delante.** `ALWAYS_APPROVE`: evacuar, parar, pedir externa. Cerrar zona también. Megafonía puede pedir persona (`autonomy: approve`).

**Cómo probarla.** `demo-1` + K + S hasta ver *«¿PARAR EL CONCIERTO…?»* o *«¿PEDIR AYUDA EXTERNA…?»*. En ficha: **VETAR**, o:

```bash
curl -sS -X POST $HOST/api/approve -H 'Content-Type: application/json' \
  -d '{"action_id":"A-00XX","ok":false,"note":"alternativa de prueba"}'
```

**Qué deberías ver.** Aprobar: `ok: true`. Vetar: `status: "rejected"` y el `why` con *«Si dices no: …»*. Lo grave: segundo clic *CONFIRMAR*.

**Si no sale.** A/V sin pendientes → toast *«No hay ninguna decisión pendiente.»*

---

### Decisión que caduca y escalada al suplente

**Qué hace.** Si no contestas, avisa al suplente. No ejecuta lo grave sola.

**Cómo actúa por dentro.** `window_min` (3 para externa, ~10–12 para parar/cerrar). `escalate_t` ≈ mitad de ventana. `escalated: true`, sigue `awaiting_approval`. Log: *«si no contesta, en N min sube a …»*.

**Cómo probarla.** K en demo-1, **no** apruebes `request_external`, avanza 2–3 min.

**Qué deberías ver.** En la ficha: *ESCALADO AL SUPLENTE*. JSON: `deputy` = Director o Jefe de seguridad, `escalated: true`.

**Si no sale.** Si apruebas antes, no escala.

---

### Golpes de quien avisa y presupuesto

**Qué hace.** Rompe el mundo simulado (no la conversación), 3 veces por partida.

**Cómo actúa por dentro.** `JURY_BUDGET = 3` global y 3 por `client_id` en origen `jury`. 4.º → **429** *«El jurado ya ha gastado sus 3 golpes en esta partida»*. `GET /api/strike/{n}` sigue el golpe (`outcome`: `pending` → p. ej. `absorbed`).

**Cómo probarla.** `/asistente` → Poner a prueba → Tormenta. O:

```bash
curl -sS -X POST $HOST/api/strike -H 'Content-Type: application/json' \
  -d '{"preset":"storm","origin":"jury","client_id":"yo"}'
curl -sS $HOST/api/jury
curl -sS $HOST/api/strike/1
```

**Qué deberías ver.** `left` 2,1,0 luego 429. Marcador jurado — MANDO en la app.

**Si no sale.** Origen `chaos` (mesa / `/caos`) no gasta el cupo del público.

---

### Más de cinco frentes a la vez

**Qué hace.** Sigue priorizando cuando hay muchos; dice a quién deja esperando.

**Cómo actúa por dentro.** Misma fórmula. `why_waiting` tipo *«espera ambulancia… le llega X en ~18 min, cuando acabe M-003»*.

**Cómo probarla.** `demo-11` o `demo-12`, o muchos avisos distintos + **S**. En una carga de prueba: **12 incidentes, 9 frentes**.

**Qué deberías ver.** Cola larga, varios `life_threat`, recursos agotados, explicación de espera.

**Si no sale.** Un solo aviso no basta; cambia de caso.

---

### Contenido sensible enmascarado

**Qué hace.** Menores / agresiones no se leen en claro en la Sala.

**Cómo actúa por dentro.** Tras unos ticks: `label: "Incidente reservado"`, `reserved: true`, `type: null`. Telegram (código) responde neutro.

**Cómo probarla.** Chat: *«He encontrado a un niño de seis años solo y llorando en los baños»* + 2–3 **S**.

**Qué deberías ver.** Ficha con etiqueta RESERVADO. El texto literal **no** queda como título.

**Si no sale.** Justo al enviar, un instante puede verse el relato; el enmascarado entra al integrar.

---

### Varios operadores y decisión duplicada (409)

**Qué hace.** Una decisión atómica: el segundo no pisa al primero.

**Cómo actúa por dentro.** `operators.decide`. Misma acción otra vez → 409.

**Cómo probarla.**

```bash
# dos veces el mismo action_id
curl -sS -o /tmp/a1.json -w '%{http_code}\n' -X POST $HOST/api/approve \
  -H 'Content-Type: application/json' -d '{"action_id":"A-00XX","ok":true}'
curl -sS -o /tmp/a2.json -w '%{http_code}\n' -X POST $HOST/api/approve \
  -H 'Content-Type: application/json' -d '{"action_id":"A-00XX","ok":true}'
```

**Qué deberías ver.** 200 luego **409** `ya lo decidió operador-1 hace 0 s`.

**Si no sale.** Sin pendientes, 400. **No se probaron dos tokens distintos** (solo el duplicado del operador local).

---

### Espejo del despacho por Telegram

**Qué hace.** Reproduce en local aviso → asignaciones Telegram → alguien acude / no puede / timeout → escalada a voz, **sin bot ni plataforma**.

**Cómo actúa por dentro.** `POST /api/demo/telegram` (operador). Espejo en `state.telegram` (alias, nunca teléfonos).

**Cómo probarla.**

```bash
curl -sS -X POST $HOST/api/demo/telegram -H 'Content-Type: application/json' \
  -d '{"zone":"front_pit"}'
```

**Qué deberías ver.** `ok: true`, `n: 10`. Marta `accepted` (ETA 3, `gate_a`). Seguridad: declined / timeout. Escalada `workflow_voz: "mando-despacho-seguridad"`. En la ficha: bloque AGENTE HR · TELEGRAM.

**Si no sale.** 401/403 si hay URL pública y no eres operador.

---

### Enrutado a workflow y caída al genérico

**Qué hace.** Cada oficio tiene nombre de workflow; si falta o falla, se intenta el despacho genérico.

**Cómo actúa por dentro.** Nombres **genéricos** (no copies slugs de un workspace):

| Oficio | Nombre |
|---|---|
| sanitario | `mando-despacho-sanitario` |
| seguridad | `mando-despacho-seguridad` |
| técnico | `mando-despacho-tecnico` |
| logística | `mando-despacho-logistica` |
| director | `mando-escalada-director` |
| externos | `mando-aviso-servicios-externos` |
| difusión | `mando-difusion-publico` |
| relevo | `mando-relevo-y-refuerzo` |
| personal / sms / email / avisos externos | `mando-ingesta-…` / `mando-avisos-externos` |

Si no hay hook del oficio → slot `dispatch`. `workflow_history` guarda ambos intentos.

**Cómo probarla.** `/clasico` → panel «HappyRobot · estado de workflows», o `state.happyrobot`. En `sim` las claves existen y el modo es simulado.

**Qué deberías ver.** El espejo Telegram de demo ya cita `mando-despacho-seguridad` al escalar.

**Si no sale.** Sin `HR_HOOK_*` no hay lanzamiento real; no es un fallo del recinto.

---

### Caída de HappyRobot y modo simulado rotulado

**Qué hace.** Si la plataforma no está o falla, **sigue** el recinto y lo dice en pantalla.

**Cómo actúa por dentro.** `presentation.happyrobot`: `simulado` / `degradado` / `real configurado; pendiente de confirmar`. Banner `voz simulada` o *«voz simulada: sin conexión con la plataforma»*. `fell_back` en llamadas.

**Cómo probarla.** Arranque vacío o `demo`. Mira el banner y `GET /api/state` → `presentation`, `calls.mode`.

**Qué deberías ver.** En esta guía: `happyrobot: simulado`, `telegram: apagado`, `voice: simulada`, `banner: voz simulada`.

**Si no sale.** Si configuraste mal y el banner sigue «real… pendiente», `doctor --sin-red` no certifica audio: hace falta un run y su callback.

---

### Memoria día 1 → día 2 y aprobación

**Qué hace.** Enseña lo observado ayer y **tú** apruebas el cambio de parámetro. No se autoaplica.

**Cómo actúa por dentro.** `GET /api/memoria` (observaciones con N, propuestas, comparación). `POST /api/memoria/decide` `{id, approve, by}`. Efectivo en la **siguiente** sesión.

**Cómo probarla.** Abre `/memoria`. Botones **Aprobar** / **Rechazar**.

**Qué deberías ver.** `available: true` si hay ficheros de memoria. Cada línea lleva **N**. Intervalo que incluye 0 → no afirma mejora.

**Si no sale.** Sin `memory.day1.json` la página dice que no hay observaciones. **No se pulsó Aprobar en esta verificación** (escribe ficheros de tuning).

---

### Informe posterior

**Qué hace.** Acta de **esta** partida.

**Cómo actúa por dentro.** `GET /api/informe`: métricas, incidentes, cadenas de planes, decisiones, latencia humana, llamadas, golpes.

**Cómo probarla.** Avanza el caso, abre `/informe` o `curl -sS $HOST/api/informe`.

**Qué deberías ver.** Pie *«Cifras de UNA ejecución (N=1 caso)»*. Campos: `critical_failed`, `replans`, `assumptions_broken`, `calls_failed` → `calls_recovered`, `merges`, `fronts_peak`.

**Si no sale.** A t=0 casi todo es cero.

---

### Historial y exportación

**Qué hace.** Graba el estado público ya enmascarado en SQLite y deja consultarlo.

**Cómo actúa por dentro.** Tablas `escenas`, `avisos`, `incidentes`, `planes`, `acciones`, … Export `/api/historial/export.json` y `.csv`.

**Cómo probarla.** Arranca **sin** `MANDO_DB=off`. Abre `/historial`, elige escena, descarga.

**Qué deberías ver.** Con `MANDO_DB=off`: **503** `Historial desactivado con MANDO_DB=off` (comprobado). Con base: lista de escenas.

**Si no sale.** Disco lleno: el reloj sigue; el historial no.

---

### Teclas K y R

**Qué hace.** K: salta al momento clave simulado. R: escena a cero.

**Cómo actúa por dentro.** `key_moment` crea sesión nueva del caso `MANDO_DEMO_CASE` (defecto `demo-1`), playbook seed, avanza hasta **antes** del golpe (t=7, golpe ambulancia a t=8). `reset` reinicia la sesión actual.

**Cómo probarla.** K, mira el reloj. En `demo-gates`, K **cambia el caso** a demo-1 (comprobado). R vuelve a t=0.

**Qué deberías ver.** Pausado, `moment.effect.resource = amb_1`. R: t=0, cola limpia del caso.

**Si no sale.** K exige comunicaciones `sim`.

---

### `doctor`

**Qué hace.** Diagnóstico de configuración. **Nunca lanza llamadas.** `--sin-red` no sale a internet.

**Cómo actúa por dentro.** Comprueba claves, hooks, contactos, NEVER_DIAL, LiveKit local, Telegram. Niveles: imprescindible / necesario / opcional.

**Cómo probarla.**

```bash
uv run --project motor/server python -m motor.server doctor --sin-red
uv run --project motor/server python -m motor.server doctor --json /tmp/mando-doctor.json
```

**Qué deberías ver.** Líneas OK / AVISO / FALTA. `./mvp.sh demo` lo ejecuta antes de servir. Sin plataforma: FALTA en API key, secreto, URL pública, contactos locales.

**Si no sale.** Un 401 de la API **no** prueba permisos. Un doctor verde **no** prueba que el teléfono suene.

---

### Tests (`./mvp.sh check`)

**Qué hace.** Unidad del mundo, casos, Mando, banco, servidor; coherencia de `demo.jsonl`; doctor.

**Cómo actúa por dentro.** `unittest` de esos módulos + `python3 -m motor.cases check-world …` + doctor.

**Cómo probarla.** `./mvp.sh check` desde la raíz (necesita `uv` y, la primera vez, generar jsonl).

**Qué deberías ver.** OK de tests. Doctor puede avisar y el script sigue (`|| true`).

**Si no sale.** **No se lanzó el check completo** en esta guía (otros procesos tocaban el árbol). Sustituto verificado: `ensayo --case demo-1` → `ok: true`, 7 hitos (`avisos_fusionados`, `despacho_aceptado`, `supuesto_roto`, `plan_nuevo`, `tarjeta_decision`, `aprobacion_operador_simulado`, `informe`).

---

### Evals (`python3 -m motor.evals`)

**Qué hace.** Seis suites de simulación (seguridad de decisión, comprensión, conversación, adversario, notificaciones, lectura de plataforma). Escribe `motor/evals/out/informe.md` y `resultados.json`.

**Cómo actúa por dentro.** `--rapido` = pasada &lt; 60 s. `--out` cambia carpeta. No toca la base, ni el puente, ni workflows `fa-*`.

**Cómo probarla.**

```bash
python3 -m motor.evals --help
python3 -m motor.evals --rapido
python3 -m unittest motor.evals.test_evals -v
```

**Qué deberías ver.** Informe con fallos **sin maquillar**, semilla y caso. Toda cifra con su N.

**Si no sale.** **`--rapido` no se ejecutó** aquí (solo `--help`).

---

### Banco de medida (`python3 -m motor.harness`)

**Qué hace.** Mide MANDO contra una lista fija en los **mismos** casos y semillas. Toda cifra lleva **N** e intervalo. No copies titulares viejos: regenéralos.

**Cómo actúa por dentro.** Huella de código en cada salida. `--freeze` copia código y casos. Preflight: si revienta, código 3 **sin escribir cifras**.

**Cómo probarla.** `python3 -m motor.harness --help` y el subcomando. **No cites resultados de una corrida ajena.**

| Subcomando | Qué mide |
|---|---|
| `run` | Una tanda: `--agent mando\|baseline\|baseline_plus`, `--cases`, `--n`, `--chaos none\|random\|smart` |
| `compare` | MANDO vs lista fija, pareado, mismos ids/semillas |
| `headline` | Titular reproducible (también `./mvp.sh cifras`) |
| `learn` | Rondas de lecciones (solo train → validar) |
| `curve` | Evolución ronda a ronda (alimenta `/curva`) |
| `report` | Informe en markdown |
| `regress` | Re-ejecuta casos bloqueados |
| `load` | Degradación con la carga (más frentes / niveles) |
| `day2` | Día 1 → propuestas → aprobación → mismos casos |
| `pick` | Elige casos heldout duros |
| `all` | El ciclo (mejor con `--freeze`) |

**Qué deberías ver.** JSON/MD en `motor/harness/out/` con `n`, intervalos, huella. Si el código cambia a mitad, aborta.

**Si no sale.** Faltan `train.jsonl` / `heldout.jsonl`: genéralos (o deja que `mvp.sh` lo haga). **No se midió N grande en esta guía.**

---

## 5. Conectar lo real

### HappyRobot

1. Clave API **distinta** del secreto de webhooks. Fuera del repo.
2. Publica workflows en development. Copia **la URL del editor**, no inventes el path.
3. Rellena `.env`: `HR_API_KEY`, `HR_SECRET`, `HR_HOOK_*` / `HR_WORKFLOW_*`, `MANDO_PUBLIC_URL`, lista blanca, `contacts.local.json` (desde el ejemplo, **tus** números consentidos).
4. `./mvp.sh real` o `--comms happyrobot --lan`.
5. `doctor` (con red cuando toque). Imprescindibles en verde.
6. Ingesta **sin** llamada: POST a `{MANDO_PUBLIC_URL}/hr/events` con `X-Mando-Token` y `type: public_report`. Debe nacer un aviso.
7. Primera **web call** (`MANDO_VOICE_MODE=web_call`): despacho pendiente → `/llamada/…` por https o localhost → DESCOLGAR → ACEPTO y los minutos. Comprueba callback `real: true` y sello ACEPTA.
8. Primer **teléfono**: `MANDO_VOICE_MODE=phone`, número en `MANDO_ALLOWED_NUMBERS` **y** en contactos. Solo un móvil **tuyo**. NEVER_DIAL no puede coincidir.

Pasos **manuales** en la plataforma: crear clave, publicar cada workflow, copiar trigger, northstars/tests si los usáis, widget de chat (el código **no** adivina la URL). Difusión al público no se convierte en llamadas masivas.

### Telegram

| Modo | Quién recibe los mensajes | Cuándo |
|---|---|---|
| `poll` | Este proceso (long poll, **sin** túnel de entrada) | Un solo MANDO, sin puente. |
| `send_only` | Un puente / webhook fuera; aquí solo `sendMessage` | Ya hay webhook (p. ej. carpeta `puente/` del repo de entrega, **no** va en este árbol del motor). |
| `off` | Nadie | Esta guía; o para no pisar el puente. |

**Un bot, un consumidor.** Si el puente está en marcha, no lances `poll` a la vez.

Espejo (HappyRobot despacha por Telegram y MANDO **solo mira**): eventos `tg_incident` / `tg_assignment` / … a `/hr/events` con el mismo `HR_SECRET`. Para enseñarlo sin plataforma: `POST /api/demo/telegram`.

### Comprobar

```bash
uv run --project motor/server python -m motor.server doctor
curl -sS $HOST/api/version
# Banner en /clasico y presentation en /api/state
```

---

## 6. Limitaciones y cosas a medias

- **Recinto, gente, equipos y reloj son simulación.** Las cifras de una partida son N=1. Las del banco son simulación con su N, no un festival real.
- **Sin `.env` no hay voz real, ni Telegram, ni SMS, ni email.** Los botones están ocultos o 404/503.
- **`/jurado` no es otra app:** redirige a `/asistente`.
- **K ignora el caso actual** y carga `MANDO_DEMO_CASE` (defecto demo-1). En `demo-gates` te cambia la historia. El título de sesión de `demo-gates` sale vacío.
- **La tecla Q no está en la Sala** (`/`); sí en `/clasico`.
- **`/porque` está enlazado en `/clasico` y no existe** (404).
- **Tope de 5 preguntas:** el motor lo publica; un mareo cerró a las 3; el texto fuera de tema cierra sin gastar cupo. No se forzó un hilo hasta la 5.ª pregunta útil.
- **EVITADO:** la UI y el motor lo tienen; en `demo-gates` se vieron PREVISTO / CUMPLIDO / NO_CUMPLIDO, no EVITADO.
- **Llamada web DESCOLGAR / ACEPTO:** página y botones existen; en `sim` no hay `webcalls` que abrir.
- **Bot de Telegram, email, SMS, teléfono real, Docker run, `./mvp.sh check`, `python3 -m motor.evals --rapido`, harness con N grande, dos operadores con tokens distintos, `MANDO_TWO_PERSON`, pulsar Aprobar en `/memoria`:** no verificados en vivo aquí.
- **Historial:** solo se comprobó el 503 con `MANDO_DB=off`.
- **Puente `puente/`:** no está en este repositorio del motor.
- **El gemelo no adivina el futuro del guion** y no garantiza lo que pasará. EVITADO no es causalidad.
- **Pulseras:** perfiles de demo; no suben prioridad; no son GPS.
- **Nunca marca el 112** ni ningún número de emergencias. El botón prepara un parte.
- **Slugs, teléfonos y secretos de un workspace no van en esta guía.** Cópialos tú desde la plataforma a `.env`.

---

## 7. Chuleta (una página)

```bash
# Local simulado
./mvp.sh
# Wifi
./mvp.sh lan
# Presentación pausada
./mvp.sh demo
# Plataforma
./mvp.sh real
# Tests / titular del banco
./mvp.sh check
./mvp.sh cifras

uv run --project motor/server python -m motor.server --case demo-1 --speed 1 --port 8000 --comms sim
uv run --project motor/server python -m motor.server demo --case demo-1 --port 8000 --lan
uv run --project motor/server python -m motor.server doctor --sin-red
uv run --project motor/server python -m motor.server ensayo --case demo-1
python3 -m motor.evals --rapido
python3 -m motor.harness headline
python3 -m motor.harness load
```

```bash
export HOST=http://127.0.0.1:8000
curl -sS $HOST/api/version
curl -sS $HOST/api/cases
curl -sS $HOST/api/state
curl -sS -N '$HOST/api/stream?limit=1'          # SSE: una foto y corta
curl -sS -X POST $HOST/api/control -H 'Content-Type: application/json' -d '{"cmd":"step"}'
# cmd: play|pause|toggle|step|speed|reset|key_moment
curl -sS -X POST $HOST/api/chat -H 'Content-Type: application/json' \
  -d '{"text":"Persona inconsciente en el foso, no responde","zone_hint":"front_pit"}'
curl -sS -X POST $HOST/api/report -H 'Content-Type: application/json' \
  -d '{"channel":"web","text":"Pelea en puerta A","zone":"gate_a"}'
curl -sS $HOST/api/report/j-001
curl -sS -X POST $HOST/api/approve -H 'Content-Type: application/json' \
  -d '{"action_id":"A-0001","ok":true}'
curl -sS -X POST $HOST/api/whatif -H 'Content-Type: application/json' \
  -d '{"kind":"reroute","zone":"gate_b","to":"gate_a","fraction":0.5,"minutes":15}'
curl -sS -X POST $HOST/api/strike -H 'Content-Type: application/json' \
  -d '{"preset":"storm","origin":"jury","client_id":"yo"}'
curl -sS -X POST $HOST/api/demo/telegram -H 'Content-Type: application/json' -d '{"zone":"front_pit"}'
curl -sS $HOST/api/informe
curl -sS $HOST/api/memoria
curl -sS $HOST/qr?path=/asistente               # cabecera X-Jurado-Url
```

| Ruta | Quién |
|---|---|
| `/` `/sala` | Sala de control |
| `/asistente` | Quien avisa (`/jurado` redirige aquí) |
| `/centro` | Previsiones y equipo |
| `/clasico` | Vista técnica (Q = QR) |
| `/duelo` `/memoria` `/informe` `/curva` `/caos` `/historial` `/personal` `/simulacro` `/acceso` `/llamada/{id}` `/qr` | Resto |

| Tecla | `/` Sala | `/centro` | `/clasico` |
|---|---|---|---|
| Espacio | play/pausa | igual | igual |
| S / R / K | +1 min / reset / momento clave | igual | igual |
| A / V | 1.ª decisión | decisión visible | 1.ª decisión |
| E | escena | pantalla grande | escena |
| Q | — | — | QR |
| M | — | — | sonido |
| Esc | cierra ficha | cierra ficha | cierra QR |

Parar el servidor: **Ctrl+C**. Esto no es el 112.
