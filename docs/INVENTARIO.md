# Inventario del repo (rama `ana`, 19-sep-2026)

Mapa de **primer y segundo nivel**. Uso en el diseño nuevo (PLAN-GIRO): **SÍ** / **PLAN B** / **NO**.
«Quién lo carga» = imports Python, rutas en `app.py` o scripts de arranque. Nada se borra: lo **NO** está en `archivo/` (ver `docs/LIMPIEZA.md`).

Leyenda de carga: `app.py` = `motor/server/app.py`.

## Raíz

| Ruta | Qué es | Diseño | Quién lo carga |
|---|---|---|---|
| `README.md` | Qué es MANDO y cómo arrancar | SÍ | humanos |
| `GUIA.md` | Cómo se usa (texto largo; plan B de reglas + pantallas viejas) | SÍ (con nota) | humanos |
| `COMO-DECIDE.md` | Cómo prioriza y tira el plan (fórmulas = plan B) | PLAN B + nota agentes | humanos |
| `COBERTURA-RETO.md` | Matriz del enunciado HappyRobot | SÍ | humanos |
| `AGENTS.md` | Normas del repo público | SÍ | humanos / agentes |
| `mvp.sh` | Arranque y `check` | SÍ | `./mvp.sh` |
| `.env.example` | Variables sin secretos | SÍ | copiar a `.env` (gitignored) |
| `.gitignore` | Ignora `.env`, `*.db`, `harness/out/`, `dist/` | SÍ | git |
| `Dockerfile` | Imagen del servidor | SÍ | deploy |
| `package.json` / `package-lock.json` | Scripts del puente en Vercel | SÍ | `npm test` → `puente` |
| `vercel.json` | Rewrites → `api/index.ts` | SÍ | Vercel |
| `mvp.sh` | 3 modos + tests | SÍ | equipo |
| `archivo/` | Lo que ya no es la demo; ruta relativa conservada | NO (a propósito) | nadie en runtime |
| `docs/` | Plan del giro, inventario, limpieza | SÍ | humanos |
| `motor/` | Mundo, reglas-plan-B, servidor, herramientas, Sala | SÍ + PLAN B | `python -m motor.server` |
| `puente/` | Telegram / callbacks → backend | SÍ | Vercel / `npm --prefix puente` |
| `api/` | Entrada Node de Vercel | SÍ | `api/index.ts` importa `puente/dist` |
| `public/` | Stub HTML del puente en Vercel | SÍ | `vercel.json` outputDirectory |

**Archivados (estaban en la raíz):** `agentes/`, `web/`, `design/`, `MVP.md`, `PENDIENTE.md`, `LEEME-COMPARTIR-EQUIPO.txt` → `archivo/` (NO).

## `docs/`

| Ruta | Qué es | Diseño | Quién lo carga |
|---|---|---|---|
| `docs/PLAN-GIRO.md` | Diseño: equipo de agentes decide | SÍ | humanos |
| `docs/ARQUITECTURA-CEREBRO-HR.md` | Cableado cerebro HR | SÍ | humanos |
| `docs/PRUEBALO.md` | Cómo probar el cerebro/herramientas | SÍ | humanos |
| `docs/INVENTARIO.md` | Este fichero | SÍ | humanos |
| `docs/LIMPIEZA.md` | Qué se movió y cómo deshacerlo | SÍ | humanos |

## `motor/` (segundo nivel)

| Ruta | Qué es | Diseño | Quién lo carga |
|---|---|---|---|
| `motor/__init__.py` | Paquete | SÍ | imports |
| `motor/contracts.py` | Tipos compartidos (no cambiar sin avisar) | SÍ | `app.py`, mando, world, harness |
| `motor/INTERFACES.md` | Contrato entre carpetas | SÍ | humanos |
| `motor/world/` | Simulador del recinto | SÍ | `app.py` (`World`, `SimComms`); harness; tests |
| `motor/mando/` | Planificador de **reglas** | PLAN B | `app.py` `load_agent_class`; harness; cerebro_tools (lexicon/parser/rehearsal) |
| `motor/baseline/` | Lista fija (vara de medir) | PLAN B | harness; `app.py` si `agent_kind=baseline`; duelo API |
| `motor/caos/` | Adversario al mundo | PLAN B / demo jurado | harness; `app.py` `load_chaos`; `/api/strike` |
| `motor/cases/` | Casos + generador | SÍ | `app.py` `load_case`; harness; `mvp.sh` genera train/heldout |
| `motor/harness/` | Banco de medida | PLAN B (vara) | `python -m motor.harness`; `mvp.sh cifras` |
| `motor/server/` | FastAPI: herramientas, barandillas, Sala, APIs | SÍ | `python -m motor.server` |
| `motor/happyrobot/` | Prompts, northstars, cerebro, equipo | SÍ | humanos + `equipo.py` / `cerebro_llm.py` leen `equipo/` |
| `motor/intake/` | Chat del público (slots/protocolo) | SÍ | `motor/server/chat.py` → `IntakeSession`; evals |
| `motor/protocolos/` | Textos de consignas al público | SÍ | intake; `chat.py` |
| `motor/evals/` | Batería local de audits | SÍ | `python -m motor.evals` (no va en `mvp.sh check`) |

`motor/harness/out/` y `*.db` son salidas de runtime (ya en `.gitignore`). No se versionan.

## `motor/happyrobot/` (segundo nivel)

| Ruta | Qué es | Diseño | Quién lo carga |
|---|---|---|---|
| `cerebro/` | Prompt + contrato de herramientas | SÍ | humanos; doctor no lo importa |
| `equipo/` | Prompts de triaje/prioridad/recursos/avisos/vigía/crítico | SÍ | `cerebro_llm.py`, `equipo.py` |
| `recipes/` | Receta `fa-entrada-tg` | SÍ | humanos (Bruno) |
| `WORKFLOWS.md`, `PROMPTS.md`, `NORTHSTARS.md`, `TESTS.md`, … | Spec voz / northstars | SÍ (voz) | humanos |
| `webhook_contract.json` | Contrato `/hr/events` | SÍ | humanos / adaptador |

## `motor/server/` — qué carga `app.py` (no se listan todos los tests)

Imports directos de `app.py`: `intake`, `memoria`, `regression_live`, `views`, `whatif`, `validation`, `privacy`, `cerebro`, `comms_happyrobot`, `telegram_bot`, `hr_config`, `llm_parser_factory`, `ledger`, `security`, `forecast`, `multi`, `personal` (clase `FieldStaff`, no la pantalla), `espejo_telegram`, `state_refresh`, `evidence_runtime`, `db`, `operator_audit`, `chat`, `presentation`, `cerebro_tools`, `ensayo`, `hr_routing`, `hr_text_delivery`, `explica`, `mcp_server` (opcional), `team_routes`, `evidence_routes`, `historial_routes`, `equipo`.

Páginas HTML que **sí** se sirven: `/` y `/sala` → `sala.html` (otro agente; **no tocado**); `/jurado`, `/asistente`, `/llamada/{id}`, `/acceso`, `/qr`.

Páginas **NO** (archivadas; la ruta redirige a `/`): `/centro`, `/clasico`, `/duelo` (sigue llamando `D()` para tests/API), `/curva`, `/caos`, `/memoria`, `/informe`, `/historial`, `/personal`, `/simulacro`. Las APIs (`/api/duel/*`, `/api/memoria`, `/api/historial/*`, `/api/personal/*`, `/api/simulacro/*`, `/api/explica`, `/porque`) se quedan.

`memoria_db.py`, `cerebro*.py`, `cerebro_tools.py`, `equipo.py`, `static/sala*` — **no se tocan**.

## `puente/` (segundo nivel)

| Ruta | Qué es | Diseño | Quién lo carga |
|---|---|---|---|
| `puente/src/` | Código del puente | SÍ | `tsc` / tests (**no tocado**) |
| `puente/scripts/` | setWebhook | SÍ | npm script |
| `puente/README.md`, `SETUP-TELEGRAM.md` | Cómo cablear Telegram | SÍ | humanos |
| `puente/package.json` | tests | SÍ | `npm --prefix puente test` |

## `api/` y `public/`

| Ruta | Qué es | Diseño | Quién lo carga |
|---|---|---|---|
| `api/index.ts` | `createApp()` desde `puente/dist/app.js` | SÍ | Vercel |
| `public/index.html` | «si ves esto, abre /health» | SÍ | Vercel estático |

## Lo comprobado antes de archivar `web/`

`web/src/lib/client-api.ts` pega a `/api/board` y `/api/demo/public-report` **de Next.js**, no a `motor/server`. `web/src/app/api/board/route.ts` construye un tablero en memoria (`buildBoard()`). No hay import desde `motor/` ni desde `mvp.sh`. **NO** — a `archivo/web/`.

## Lo comprobado antes de archivar `agentes/`

`python -m agentes` no lo importa nadie del producto. AGENTS.md lo decía: apoyo al desarrollo, no producto. **NO** — a `archivo/agentes/`.

## Criterio de lo que se QUEDA aunque no sea el diseño nuevo

Plan B y vara de medir: `motor/mando`, `motor/world`, `motor/cases`, `motor/harness`, `motor/baseline`, `motor/caos`.
Entrada de público y jurado: `/asistente`, `/jurado`.
Llamada web: `/llamada/{id}`.
