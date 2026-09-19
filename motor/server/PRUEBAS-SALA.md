# Recorrido de punta a punta — Sala de control (`/sala`)

Servidor de esta pasada (sáb 19-sep 2026):

```sh
TELEGRAM_MODE=off uv run --project motor/server python -m motor.server demo --case demo-gates --port 8821
```

Base: `http://127.0.0.1:8821`. `TELEGRAM_MODE=off`: el bot no sondea Telegram; el espejo de despacho entra por `POST /api/demo/telegram` (operador). En localhost el TestClient y curl cuentan como operador. Con `MANDO_OPERATORS` configurado, aprobar/vetar/inyectar/whatif exigen `X-Mando-Operator` (lo cubre `test_sala.DecisionesTest`).

JS: `node --check motor/server/static/sala.js` y `sala-plano.js` — sintaxis OK.
Batería: `uv run --project motor/server python -m unittest discover -s motor/server -p "test_*.py" -t .` — 493 tests, 0 fallos en esta pasada.

## 1. La pantalla se sirve, sin CDN

| Ruta | Código | Notas |
|---|---|---|
| `GET /` | 200 | misma página que `/sala` (9956 bytes) |
| `GET /sala` | 200 | título «Sala de control» |
| `GET /centro` | 200 | vista del centro (no se toca) |
| `GET /clasico` | 200 | vista técnica (no se toca) |
| `GET /static/sala.html` `.css` `.js` `sala-plano.js` | 200 | CSS propio, sin `https://` en el HTML |

El HTML lleva «Entorno de demo · Ficticio», «posición simulada», «estimación del simulador» y «NO marca». No dice GPS.

## 2. Estado inicial (`demo-gates`, pausado)

`GET /api/state`:

- caso `demo-gates`, `t=0`, `running=false`, `speed=1`, reloj `18:30` día 2
- 17 zonas (las de `festival.json`), 15 recursos, 0 incidentes
- `telegram` es `{status: off}` (bot apagado). La Sala **no pinta** despacho: `telegramState()` exige `staff` + `asignaciones`
- `chat_id` no aparece en el JSON
- `calls.mode = sim`

## 3. Reloj, cola, plano, previsiones

`POST /api/control {"cmd":"step","n":14}` → `t=14`.

- 1 incidente abierto, 1 frente, 0 aprobaciones (en `demo-gates` el minuto 14 no pide persona; en `demo-1` sí: `test_sala.DecisionesTest`)
- 1 previsión del gemelo: `density` en `gate_a`, `eta_min=12`, `status=PREVISTO` — la ficha la pinta como cuenta atrás `T−12 min`
- `scoreboard.left = 3` golpes
- El plano usa esas 17 zonas; CAMPAMENTO, EVAC-*, PUERTA D, PE-1 y PASILLO ESTE son decoración gris sin datos

Teclas (en `sala.js`): espacio pausa, S +1 min, K momento clave, R reinicia, A/V aprueba/veta la primera pendiente, E modo escena, flechas velocidad, Intro abre la ficha de la primera decisión, Esc cierra cajones. Filtros, buscador y clic cruzado fila–marcador–recurso siguen en el cliente.

## 4. Tarjeta de decisión: dos futuros, Aprobar / Vetar

`POST /api/control {"cmd":"key_moment"}` deja `t=7` y dos pendientes:

- `A-0002` `broadcast` con `card.if_approved` y `card.if_vetoed`
- `A-0014` `request_external` (ayuda externa; el botón **112 EMERGENCIAS** abre el cajón que **no marca** ningún número y pide confirmación)

`POST /api/approve {"action_id":"A-0002","ok":true,"note":"HTTP sala"}` → 200. Esa id ya no está en `approvals`.

Vetar es el mismo endpoint con `"ok": false` (`test_sala` lo ejecuta sobre `demo-1`). Con tokens de operador, sin cabecera responde 401/403.

## 5. Chat · Agente HR

`POST /api/chat {"text":"hay un desmayo en la pista central","channel":"whatsapp"}` → 200, `degraded: false`.
Tras `step n=2`, `GET /api/chats` → `n=1`, canal `whatsapp`. POST a `/api/chats` es 405. El contenido reservado no sale (`test_sala.ChatPanelTest`).

## 6. `S.telegram` (contrato compartido)

`POST /api/demo/telegram {"zone":"front_pit"}` → 200, 10 eventos, 1 escalada.

`GET /api/state` entonces lleva:

```
telegram.staff = {disponibles: 4, total: 5}
telegram.asignaciones = 4  (accepted, declined, timeout, timeout)
telegram.escaladas = [{incident_id, rol: seguridad, motivo, workflow_voz: mando-despacho-seguridad}]
```

Sin `chat_id` ni teléfonos. La Sala, si el objeto tiene esa forma, pinta:

- columna **AGENTE HR**: «Telegram → médico: pendiente N s», «ACUDE Marta · 3 min · desde Puerta A», «No puede → reasignando (intento 2)», «Cubierto», o «ESCALADA POR VOZ»
- grupo **Staff por Telegram · 4/5 disponibles**
- cronología y caja **ESCALADA POR VOZ** en la ficha
- si `telegram` no tiene `staff`/`asignaciones`, no pinta nada de despacho

## 7. Mesa de inyección y 112

`POST /api/strike {"preset":"close_gate","origin":"chaos"}` → 200 (localhost = operador). Un golpe en `strikes`. La mesa es un cajón de la Sala, solo operador.

El HTML del 112 dice «NO marca». No hay `tel:` ni números reales en `sala.*`.

## 8. SSE, tema, reconexión, ensayo

`GET /api/stream?limit=1` entrega `event: state` con el mismo JSON que `/api/state`.
`GET /api/whatif` (desvío `gate_a` → `gate_b`, 15 min) → 200, `verdict` de esa ejecución.
HTML `data-theme="light"` y CSS `[data-theme=dark]`; tecla del conmutador ◐.
Banda `#reconnect`: «Reconectando… se conservan la selección y los últimos datos recibidos.»

## 9. Qué no se ha pulsado en el navegador

Este recorrido es HTTP contra el servidor. El clic cruzado, las teclas y el solape a 1280×720 se cubren en código (rejilla de tres columnas + HUD absoluto sobre el mapa + `min-width:0`) y en `test_sala.PagesTest.test_layout_tres_columnas_sin_solape`. Para verlo: abrir `/sala` a 1280×720 y a 1920×1080; el panel derecho no debe montar sobre el plano.
