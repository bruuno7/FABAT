# WEBHOOKS — todo lo que cruza entre `motor/server` y HappyRobot, en los dos sentidos

Fuente de verdad de los cuerpos: `motor/happyrobot/PLATAFORMA_REAL.md` §3 y §4 (workflows reales) y
`motor/happyrobot/webhook_contract.json` (contrato `mando.hr.v1`). Aquí, la tabla y un `curl` de cada uno.
En los ejemplos: `B=https://<tu-túnel>` (= `MANDO_PUBLIC_URL`), `S=$HR_SECRET`. Nada de esto lleva secretos escritos.

## 1. De nuestro servidor a HappyRobot (salientes)

| Qué | Dónde | Cuerpo | Código |
|---|---|---|---|
| Despacho por TELÉFONO (`MANDO_VOICE_MODE=phone`) | `POST $HR_HOOK_DISPATCH` (o `HR_HOOK_DISPATCH_<HR_ENV>`); con `HR_LAUNCH_MODE=runs`: `POST $HR_API_BASE/workflows/$HR_WORKFLOW_DISPATCH/runs` `{payload, environment}` | EXACTAMENTE `action_id, to_number, role, order_text, zone_spoken, priority` (palabra: roja/amarilla/verde)`, callback_url` (= `B/hr/events`)`, callback_token` (= `S`) | `comms_happyrobot.wire_payload`, `_post` |
| Despacho por LLAMADA WEB (al DESCOLGAR en `/llamada/<id>`) | `POST $HR_API_BASE/voice/tokens/` `{workflow_id: $HR_WORKFLOW_WEBCALL, env: $HR_ENV, ttl_seconds, data}` | `data` = las mismas claves MENOS `to_number` (7) | `answer_webcall` |
| Cambio de orden en plena llamada | `POST $HR_API_BASE/signals` `{key: "session.<hr_session_id>", env, payload}` | `payload = {type: "orden_cambiada", orden_cambiada: true, orden_nueva, text, action_id}` | `change_orders`, `signal` |
| Escuchar / tomar una llamada | `POST $HR_API_BASE/voice/tokens/` `{session_id, should_takeover}` | — | `takeover_token` |
| Entendimiento delegado de un texto | `POST $HR_HOOK_INTAKE` | `text, channel, source, zone_hint, lang, reply_to, callback_url, callback_token` | `intake.DelegatedIntake.understand` |
| Otros workflows del contrato (ask, notify, external, followup) | `HR_HOOK_ASK/NOTIFY/EXTERNAL/FOLLOWUP` | contrato `mando.hr.v1` + `callback_token` | `_clarify_payload`… (no hay workflows reales montados) |

Guardas antes de marcar: número en `MANDO_ALLOWED_NUMBERS` (OBLIGATORIA), nunca `NEVER_DIAL`, E.164, y `REQUEST_EXTERNAL` solo con aprobación registrada.

```sh
# lo que manda el servidor al hook de teléfono (para lanzar UNA llamada a mano a TU móvil)
curl -X POST "$HR_HOOK_DISPATCH" -H 'Content-Type: application/json' -d '{"action_id":"A-0042","to_number":"+34XXXXXXXXX",
 "role":"Jefe de seguridad · Seguridad 2","order_text":"Aglomeración en puerta B de Barcelona. Prioridad roja. Acude ya.",
 "zone_spoken":"puerta B de Barcelona","priority":"roja","callback_url":"'$B'/hr/events","callback_token":"'$S'"}'
```

## 2. De HappyRobot a nuestro servidor (entrantes). Cabecera `X-Mando-Token`

`HR_SECRET` vale para todo. `HR_CHAT_TOKEN` (el del widget de chat, PÚBLICO en el navegador) solo vale para `public_report`,
`public_report_update` y `report_status_query`: con él, lo demás da 403. Sin `HR_SECRET` configurado: 503. Token malo: 401.
Si el JSON llega ROTO (comillas sin escapar en `transcript`), `/hr/events` recupera los campos cortos con una expresión regular,
lo deja en el registro y NO devuelve 500. Todos los valores llegan como CADENA (`eta_min` incluido: «4», «», «cuatro o 5 min»).

| `POST` | `type` / `message` | Campos | Qué hace | Respuesta |
|---|---|---|---|---|
| `/hr/events` | `dispatch_progress` / `progress` (`stage: order_confirmed`) | `action_id, result: accept\|reject, eta_min, reason, hr_run_id, channel_used` | resultado EN CALIENTE (provisional): Mando lo sabe ya | `{ok, result, eta_min}` |
| `/hr/events` | `dispatch_result` | `action_id, result: accept\|reject\|unclear, eta_min, reason, call_status, hr_session_id, transcript, hr_run_id` | final: completa la ficha; si contradice al provisional, lo CORRIGE. `unclear` = `no_answer` (Mando pasa al siguiente). `eta_min` vacío → ETA estimada por el backend (`data.eta_estimated`) | `{ok, already_confirmed?, corrected?}` |
| `/hr/events` | `public_report` (final, o `partial:true` + `report_ref`) | `channel` (voice\|email\|sms\|telegram\|sensor\|chat), `report{…}`, `extracted{…}`, `category`, `reply_to`, `hr_run_id` | entra al mundo por el MISMO camino que `/api/report`; con `report_ref`, el final completa el aviso parcial | `{ok, report_id, ref_spoken, say_text}` |
| `/hr/events` | `public_report_update` | `report_ref, field, value` | actualización enlazada al mismo aviso (nunca otro incidente verdadero) | `{ok, report_id, update_id}` |
| `/hr/events` | `report_status_query` | `report_ref, reason` | — | `{ok, say_text}` corto, neutro, sin tiempos |
| `/hr/events` | contrato: `progress`, `transcript`, `*_result`, `public_report` | ver `webhook_contract.json` | igual que en la fase 2 | `{ok, duplicate}` |
| `/hr/identify` | — | `from_number` | quién llama (personal con orden pendiente / público) | ruta y contexto |
| `/hr/approval_check` | — | `action_id, approval_id` | segundo cerrojo de lo grave | `{approved, reason}` |
| `/hr/webcall/next` | — | — | siguiente orden pendiente para una llamada web entrante | `{has_order, order}` |
| `/mcp` (Streamable HTTP, `Authorization: Bearer $MANDO_MCP_TOKEN`) | tools | `obtener_orden, confirmar_orden, hay_cambio_de_plan, registrar_aviso, estado_zona, consultar_aprobacion` | `confirmar_orden` = mismo camino que `dispatch_progress` | JSON por tool |

Casado: el `action_id` emitido lleva un nonce distinto por partida. Se acepta ese id emitido o un `hr_run_id` ya
registrado al lanzar la llamada. Un run desconocido solo se registra si devuelve el id con nonce de esta partida;
el primer callback con un id interno desnudo no acredita el run. Los callbacks de plataforma (`type`) sin run también
necesitan el id emitido. Los ejemplos `A-0042` de abajo son ilustrativos: sustituir por el id real recibido. Idempotencia: `event_id` (si falta se sintetiza: `<run>-progress-<result>`, `<run>-final`,
`<report_ref>-partial|final`), más el cierre por acción (`_closed`): un segundo final se ignora.

```sh
# en caliente (tool confirmar_orden del agente de voz)
curl -X POST $B/hr/events -H "X-Mando-Token: $S" -H 'Content-Type: application/json' -d '{"schema":"mando.hr.v1","type":"dispatch_progress",
 "message":"progress","stage":"order_confirmed","final":false,"channel_used":"phone","action_id":"A-0042","result":"accept","eta_min":"4","reason":"","hr_run_id":"run-1"}'
# al colgar
curl -X POST $B/hr/events -H "X-Mando-Token: $S" -H 'Content-Type: application/json' -d '{"schema":"mando.hr.v1","type":"dispatch_result",
 "message":"dispatch_result","final":true,"channel_used":"phone","action_id":"A-0042","result":"accept","eta_min":"4","reason":"",
 "call_status":"completed","hr_session_id":"ses-1","transcript":"assistant: Orden…\nuser: Afirmativo, cuatro minutos.","hr_run_id":"run-1"}'
# aviso entrante ya entendido (cualquier canal)
curl -X POST $B/hr/events -H "X-Mando-Token: $S" -H 'Content-Type: application/json' -d '{"schema":"mando.hr.v1","type":"public_report",
 "message":"public_report","final":true,"hr_run_id":"run-2","channel":"email","reply_to":"","category":"sanitario",
 "report":{"channel":"email","text":"Una chica se ha mareado en la puerta B","zone_hint":"","source":"asistente","lang":"es"},
 "extracted":{"location":"puerta B","description":"mareo por calor","people":"1","responsive":"si"}}'
# conversación guiada: parcial, actualización y consulta de estado (mismo report_ref)
curl -X POST $B/hr/events -H "X-Mando-Token: $HR_CHAT_TOKEN" -H 'Content-Type: application/json' -d '{"type":"public_report","partial":true,"final":false,
 "report_ref":"run-3","hr_run_id":"run-3","channel":"chat","report":{"text":"hay un chico en el suelo"},"extracted":{"responsive":"no"}}'
curl -X POST $B/hr/events -H "X-Mando-Token: $HR_CHAT_TOKEN" -H 'Content-Type: application/json' -d '{"type":"public_report_update","report_ref":"run-3","field":"ubicacion","value":"frente de escenario"}'
curl -X POST $B/hr/events -H "X-Mando-Token: $HR_CHAT_TOKEN" -H 'Content-Type: application/json' -d '{"type":"report_status_query","report_ref":"run-3","reason":"pregunta si viene alguien"}'
# MCP: lista de tools
curl -X POST $B/mcp -H "Authorization: Bearer $MANDO_MCP_TOKEN" -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
 -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

## 3. Telegram (no es un webhook: el servidor PREGUNTA)

`telegram_bot.py` hace long polling a `https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getUpdates`; contesta con `sendMessage`.
No hace falta túnel ni URL pública. Para probar sin Telegram: `python -m motor.server.mock_telegram` + `TELEGRAM_API_BASE`.

Comprobación de todo lo anterior sin lanzar ninguna llamada: `uv run --project motor/server python -m motor.server doctor`.

Antes de consumir `event_id` o cerrar una llamada se validan estructuras, booleanos y datos de aclaración. Un cuerpo inválido devuelve 422 y admite reintento corregido con el mismo id. La confirmación y el vencimiento se finalizan bajo el mismo cerrojo. Cada webhook válido reconstruye estado y aumenta la versión SSE, incluso en pausa. Los avisos de prueba se registran sin su texto.
