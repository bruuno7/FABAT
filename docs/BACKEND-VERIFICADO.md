# Backend verificado (rama `ana`, 19-sep-2026)

Alcance: `motor/server` (FastAPI). No se tocó `motor/evals` ni `motor/happyrobot/equipo/*.md`. Servidores de humo: `TELEGRAM_MODE=off MANDO_DB=off` en `:8861` (demo-1) y `:8862` (demo-gates). Secreto de prueba `humo-live` (no es un secreto de producción).

## Batería

| Corrida | Comando | Resultado |
|---|---|---|
| 1 y 2 (fase 1) | `uv run --project motor/server python -m unittest discover -s motor/server -p 'test_*.py' -t .` | **557 tests, 0 fallos, 0 errores** (93 s y 90 s) |
| Tras el test de humo | misma batería + `test_backend_humo.py` | ver fase 3 al pie |

## Fallos de la batería que había y arreglo

| Fallo | Causa | Arreglo | Test |
|---|---|---|---|
| `TransportTest.test_role_contacts_choose_specialist_without_resource` (6 errores, ruta `None`) | En `phone`, `MANDO_HR_PHONE_KINDS` (por defecto despacho/recall/resupply) cortaba **todo** NOTIFY, también el aviso a un oficio sin recurso | NOTIFY a un rol con workflow propio (`ROLE_SLOTS`) usa ese hook o cae al genérico; ASK sigue simulado salvo que se pida | `test_enrutado.TransportTest` + `test_connection.ConfigurationTest.test_phone_mode_only_dispatch_is_real_by_default_and_caps_inflight` |
| `PlatformPayloadTest.test_mcp_server_with_sdk_client` (`hay_cambio` True «sin cambio») | En demo-1, al tick 6 el núcleo ya rompe un supuesto y `change_orders` rellena `plan_changes` | El test compara dos lecturas **sin** avanzar el reloj (tras vaciar el cambio automático) y otra tras `change_orders` | `test_phase3.PlatformPayloadTest.test_mcp_server_with_sdk_client` |
| `TelegramTest.test_report_ask_answer_and_closing` (snapshot `starting`, `('', None)`) | El hilo del bot pasa a `on` y reconstruye el estado; el test leía el snapshot **antes** de esa reconstrucción. `TELEGRAM_MODE` ajeno podía dejar el bot en `send_only` | `state()` / `state_json()` mezclan canales vivos; el test fija `TELEGRAM_MODE=poll` y espera a `telegram_bot.status == on` en el estado público | `test_phase3.TelegramTest` + `test_connection.TelegramBridgeTest` (`send_only` sigue sin `getUpdates`) |

Otros arreglos descubiertos por el humo:

| Fallo | Causa | Arreglo | Test |
|---|---|---|---|
| `TypeError` → 500 en `/hr/tools/*` con `limit` dict / tipos raros | `int(limit)` y similares no eran `ValueError` | `_invoke` convierte `TypeError`/`OverflowError` en **422** «entrada de tipo incorrecto» | `test_backend_humo.HumoTest.test_tools_cuerpos_malos_unicode_y_enormes` |
| `POST /api/call/{id}/token` → **502** si el `action_id` no existe | `takeover_token` trataba la ficha vacía como «sesión desconocida» (RuntimeError → 502) | `KeyError` si no hay llamada → **404** | `test_backend_humo` (ruta con `A-no`) |

## Humo vivo (servidor de verdad)

Misma matriz en demo-1 (`:8861`) y demo-gates (`:8862`): **293 peticiones, 0 fallos** (ningún 500, ninguna traza). Códigos: 200×149, 401×33, 422×43, 404×10, 400×5, 403×4, 503×8 (historial con `MANDO_DB=off`; login de operador sin token de operador).

### GET (1 petición cada una, salvo indicación)

| Ruta | Resultado |
|---|---|
| `/`, `/sala`, `/jurado`, `/asistente`, `/acceso`, `/personal`, `/duelo`, `/llamada/{id}`, `/qr`, `/porque` | 200 |
| `/centro`, `/clasico`, `/curva`, `/caos`, `/memoria`, `/informe`, `/simulacro` | 200 (pantallas archivadas o vivas) |
| `/api/state`, `/api/stream?limit=1`, `/api/version`, `/api/cases`, `/api/festival`, `/api/explica`, `/api/adaptacion`, `/api/memoria`, `/api/ledger/stats`, `/api/chats`, `/api/jury`, `/api/regression`, `/api/webcalls`, `/api/evidence`, `/api/simulacro/status`, `/api/chaos/suggest`, `/api/curve`, `/api/informe`, `/api/operators/me`, `/api/personal/catalog`, `/api/duel/state`, `/api/duel/stream?limit=1` | 200 |
| `/api/historial/*` (escenas, incidentes, decisiones, recursos, servicios, resumen, incidente/{id}) | 503 (`MANDO_DB=off`) |
| `/api/historial/export.json`, `export.csv` | 422 |
| `/historial` | 503 |
| `/api/agentes/{id}` (id inventado), `/api/pulsera/XX-1`, `/api/strike/99`, `/api/webcall/abc`, `/api/chat/no-existe/events` | 404 |
| `/api/report/j-no-existe` | 200 (ficha vacía, no 500) |
| `/hr/tg/roster` GET | 401 sin token |
| `/canal/sms` | 404 (número no configurado) |
| `/openapi.json` | 200 |

### POST `/hr/tools/*` (6 cada una: sin token + vacío + unicode + tipos + válido + JSON roto extra)

| Herramienta | Sin token | Cuerpo malo | Válido |
|---|---|---|---|
| `contexto`, `analizar_situacion`, `acciones_posibles`, `confianza`, `previsiones`, `protocolo`, `staff`, `pizarra/leer`, `memoria/guardar`, `memoria/buscar`, `memoria/lecciones`, `prompt/listar`, `prompt/comparar` | 401 | 422 o 200 (campos opcionales) | 200 |
| `ensayar`, `decidir`, `cambio`, `comparar_opciones`, `pizarra/publicar`, `recurso`, `rutas`, `zona`, `resultado`, `prompt/proponer` | 401 | 422 | 200 con cuerpo bueno |
| JSON `{` (roto) en todas | — | 400 | — |

Otras `/hr/*`: `events`, `identify`, `approval_check`, `webcall/next` → 401 sin token, 200 con token y cuerpo usable. `tg/dispatch`, `tg/roster`, `tg/staff-response` → 401 / 422. `/mcp` → 401 sin token.

### POST `/api/*` (muestra)

| Ruta | Resultado |
|---|---|
| `/api/report`, `/api/chat`, `/api/strike`, `/api/whatif`, `/api/control`, `/api/session`, `/api/demo/telegram`, `/api/ledger/export`, `/api/simulacro/start`, `/api/simulacro/cancel` | 200 |
| `/api/approve`, `/api/memoria/decide`, `/api/whatif/order`, `/api/report/{id}/answer`, `/api/duel/control` | 400 (entrada incompleta) |
| `/api/call/A-no/token` | 404 |
| `/api/personal/status`, `/api/personal/order/{aid}`, `/api/personal/me`, `/api/operators/local` | 403 (falta unidad / token de personal) |
| `/api/prompt/versiones`, `/api/memoria/lecciones`, `/api/personal/links`, `/api/external-notice` | 422 |

### Ciclo del equipo (HTTP)

`contexto` → `analizar_situacion` → `decidir` (triaje, incidente nuevo) → `acciones_posibles` → `ensayar` → `comparar_opciones` → votos parciales (`prioridad`, `recursos`) → `pizarra/publicar` propuesta + **objeción alta** del crítico → `memoria/guardar` → lección proponer / aprobar / revocar → `GET /api/adaptacion` → `GET /api/agentes/{id}` → `GET /api/explica`.

Estado público (`GET /api/state`): `agentes` incluye el incidente, `enjambre` tiene mensajes/agentes, `telegram` es un dict (espejo vacío o bot `off` en estos arranques).

## Qué queda

- **502** sigue existiendo si hay llamada real y la plataforma de voz no contesta (`_hr` en `app.py`). No es un 500 ni una traza.
- **503** de historial con `MANDO_DB=off` y de `/api/operator/login` sin token de operador: esperado.
- El **OpenAPI** de FastAPI avisa si un default no es JSON-serializable; las tools ya no registran la función Python como parámetro.
- No se certificó audio, SIP, Telegram real ni publicación de workflows. El doctor de `demo` lo dice.
- `motor/evals` y los prompts `.md` del equipo son de otro agente.

## Fase 3 (comandos al cierre)

Se ejecutan en este mismo trabajo: batería completa, `motor.world` + `motor.mando`, `node --check` de `motor/server/static/*.js`, tres `ensayo --case demo-1` idénticos, servidores apagados.
