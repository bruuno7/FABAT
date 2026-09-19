# Espejo del despacho por Telegram

HappyRobot decide y despacha por Telegram (`fa-entrada-tg`, `fa-despacho-tg`, `fa-respuesta-tg`).
Twin no está provisionado: el directorio rol↔chat_id y el cerrojo primer-acc-gana viven en MANDO
(`GET/POST /hr/tg/roster`, `POST /hr/tg/dispatch`, `POST /hr/tg/staff-response`). El espejo **no está
en el camino crítico de Telegram**: recibe `tg_*` (desde esos endpoints o desde un webhook HR) y lo
publica en `S.telegram` para la Sala de control.

## Autenticación

| Cabecera | Valor |
|---|---|
| `Content-Type` | `application/json` |
| `X-Mando-Token` | `HR_SECRET` (mismo secreto que el resto de webhooks `mando.hr.v1`) |

Sin secreto configurado el endpoint responde **503**. Token incorrecto → **401**. Token del widget (`HR_CHAT_TOKEN`) → **403**.

## URL del webhook

```
{MANDO_CALLBACK_URL}/hr/events
```

Por defecto `http://127.0.0.1:<puerto>/hr/events`. En producción, `MANDO_PUBLIC_URL` + `/hr/events`.

Todos los eventos llevan `schema: "mando.hr.v1"` y un `event_id` único (idempotencia: repetir el mismo `event_id` devuelve `duplicate: true`).

---

## Tipos de evento

### `tg_incident` — aviso entendido por HappyRobot

El aviso entra por el contrato normal de Mando (`Report` con canal Telegram y fuente «HappyRobot · Telegram»).

```json
{
  "type": "tg_incident",
  "schema": "mando.hr.v1",
  "event_id": "inc-42-0",
  "id": "inc-42",
  "texto": "Una persona se ha desplomado junto a la valla y no responde",
  "tipo": "medica",
  "zona": "front_pit",
  "gravedad": "vital",
  "prioridad": 9,
  "requiere_aprobacion": true,
  "alias_informante": "Asistente",
  "recursos_requeridos": [
    {"rol": "medico", "cantidad": 1},
    {"rol": "seguridad", "cantidad": 1}
  ]
}
```

| Campo | Obligatorio | Notas |
|---|---|---|
| `id` | sí | Id del incidente en Twin |
| `texto` | sí | ≤ 400 caracteres |
| `tipo` | no | `medica`, `aglomeracion`, `seguridad`, `incendio`, `clima`, `infraestructura`, `menor`, `otro` |
| `zona` | no | Id de zona del festival (`motor/world/festival.json`) |
| `gravedad` | no | `vital`, `emergencia`, `urgente`, `leve`, `sin_clasificar` |
| `prioridad` | no | 0–10 |
| `requiere_aprobacion` | no | booleano JSON |
| `recursos_requeridos` | no | `[{rol, cantidad}]`, roles del vocabulario cerrado |
| `alias_informante` | no | Alias, nunca `chat_id` ni teléfono |

**Respuesta:** `{"ok": true, "incident_id": "inc-42", "report_id": "R-…"}`

---

### `tg_assignment` — estado de una asignación a staff

```json
{
  "type": "tg_assignment",
  "schema": "mando.hr.v1",
  "event_id": "inc-42-a1",
  "incident_id": "inc-42",
  "rol": "medico",
  "estado": "accepted",
  "alias": "Marta",
  "eta_min": 3,
  "from_zone": "gate_a",
  "intento": 1
}
```

| Campo | Obligatorio | Notas |
|---|---|---|
| `incident_id` | sí | Debe existir un `tg_incident` previo en la partida |
| `rol` | sí | `medico`, `seguridad`, `organizador`, `staff_entradas`, `bomberos`, `policia`, … |
| `estado` | sí | `pending`, `accepted`, `declined`, `timeout`, `covered` |
| `alias` | no | Alias del staff, **nunca** `chat_id` ni teléfono |
| `eta_min` | no | 0–240 |
| `from_zone` | no | Id de zona; en `S.telegram` sale como `desde_zona` |
| `intento` | no | 1–3 (mismo tope que `fa-despacho-tg`) |

**Escalada:** si tras el último intento (`INTENTOS_MAX = 3`) nadie acepta un rol requerido, `S.telegram.escaladas` incluye
`workflow_voz` según `hr_routing` (p. ej. `mando-despacho-seguridad`).

---

### `tg_staff` — disponibilidad del personal

```json
{
  "type": "tg_staff",
  "schema": "mando.hr.v1",
  "event_id": "staff-1",
  "disponibles": 4,
  "total": 5
}
```

Si no llega, el espejo deriva `staff` de las asignaciones vistas.

---

### `tg_approval` — decisión del organizador en Telegram

```json
{
  "type": "tg_approval",
  "schema": "mando.hr.v1",
  "event_id": "inc-42-apr",
  "incident_id": "inc-42",
  "decision": "apr",
  "por": "organizador",
  "nota": "adelante con ambulancia externa (simulación)"
}
```

| `decision` | Significado |
|---|---|
| `apr` | Aprobada en Telegram |
| `vet` | Vetada en Telegram |

**Regla (demo):** se registra en el log con autor «organizador por Telegram». Si el aviso de Telegram está
fusionado con un incidente de Mando que tiene acciones en `awaiting_approval`, la tarjeta de la Sala recibe
`telegram_decision` con el texto «Decidido en Telegram por el organizador: APRUEBA» o «… VETA» y queda marcada.
La acción grave **solo se ejecuta** si `MANDO_TRUST_TG_APPROVAL=1` en el entorno de MANDO (por defecto **no**:
sin esa variable la tarjeta se sella en pantalla pero no se llama a `approve()`).

`por` debe ser `organizador`, `director` o `coordinador` (cargo en Twin; el log usa siempre «organizador por Telegram»).

---

## Nodo Webhook en HappyRobot (Bruno)

Añadir un nodo **Webhook** al final de cada workflow, **después** de escribir en Twin:

### `fa-entrada-tg` (tras Write incidents + Call fa-despacho-tg)

| Parámetro | Valor |
|---|---|
| URL | `{{MANDO_CALLBACK_URL}}/hr/events` |
| Método | POST |
| Cabecera | `X-Mando-Token: {{HR_SECRET}}` |
| Cuerpo | Ver `tg_incident` arriba; `event_id` = `{{incident.id}}-0` |

### `fa-despacho-tg` (tras cada Write assignments / timeout)

| Parámetro | Valor |
|---|---|
| URL | `{{MANDO_CALLBACK_URL}}/hr/events` |
| Cabecera | `X-Mando-Token: {{HR_SECRET}}` |
| Cuerpo | `tg_assignment` con el estado actual (`pending`, `timeout`, …) |
| Opcional | `tg_staff` tras Query Twin de disponibles |

### `fa-respuesta-tg` (tras aceptar / rechazar / ETA / zona / apr / vet)

| Parámetro | Valor |
|---|---|
| URL | `{{MANDO_CALLBACK_URL}}/hr/events` |
| Cabecera | `X-Mando-Token: {{HR_SECRET}}` |
| Cuerpo | `tg_assignment` para `acc`/`dec`/`eta`/`loc`; `tg_approval` para `apr`/`vet` |

Variables de workflow: replicar `MANDO_CALLBACK_URL` y `HR_SECRET` (oculta) como en `fa-entrada-tg`.

---

## curl de prueba (local)

```bash
export HR_SECRET=cambia-esto
export BASE=http://127.0.0.1:8000

# Aviso
curl -sS -X POST "$BASE/hr/events" \
  -H "Content-Type: application/json" \
  -H "X-Mando-Token: $HR_SECRET" \
  -d '{
    "type": "tg_incident",
    "schema": "mando.hr.v1",
    "event_id": "prueba-1-0",
    "id": "prueba-1",
    "texto": "Persona inconsciente en el foso",
    "tipo": "medica",
    "zona": "front_pit",
    "gravedad": "vital",
    "prioridad": 9,
    "requiere_aprobacion": false,
    "recursos_requeridos": [{"rol": "medico", "cantidad": 1}]
  }'

# Asignación aceptada
curl -sS -X POST "$BASE/hr/events" \
  -H "Content-Type: application/json" \
  -H "X-Mando-Token: $HR_SECRET" \
  -d '{
    "type": "tg_assignment",
    "schema": "mando.hr.v1",
    "event_id": "prueba-1-a1",
    "incident_id": "prueba-1",
    "rol": "medico",
    "estado": "accepted",
    "alias": "Marta",
    "eta_min": 3,
    "from_zone": "gate_a",
    "intento": 1
  }'

# Secuencia completa sin plataforma (solo operador)
curl -sS -X POST "$BASE/api/demo/telegram" \
  -H "Content-Type: application/json" \
  -H "X-Mando-Operator: $MANDO_OPERATOR_TOKEN" \
  -d '{"zone": "front_pit"}'
```

Mock local (`motor.server.mock_happyrobot`): rutas `/mock/tg-incident`, `/mock/tg-assignment`, `/mock/tg-staff`,
`/mock/tg-approval` y `/mock/tg-secuencia` reenvían al callback con el `type` correcto.

---

## Contrato público `S.telegram`

```json
{
  "staff": {"disponibles": 4, "total": 5},
  "asignaciones": [
    {
      "incident_id": "tg-demo-1",
      "rol": "medico",
      "estado": "accepted",
      "alias": "Marta",
      "eta_min": 3,
      "desde_zona": "gate_a",
      "intento": 1,
      "t": 0
    }
  ],
  "escaladas": [
    {
      "incident_id": "tg-demo-1",
      "rol": "seguridad",
      "motivo": "3 avisos por Telegram sin nadie que acuda; queda la llamada por voz (seguridad).",
      "workflow_voz": "mando-despacho-seguridad"
    }
  ]
}
```

La Sala pinta este nodo solo si existe la clave `asignaciones` (espejo activo). Sin eventos de espejo, `telegram` conserva
el estado del bot (`{"status": "off"}`) para no romper `/centro` ni `/asistente`; el bot dedicado está en `telegram_bot`.

Nunca aparecen `chat_id`, `message_id` ni teléfonos en el estado público.

## Directorio durable (privado)

Los cinco puestos del bot (`medico`, `staff_entradas`, `organizador`, `bomberos`, `policia`) se
guardan en SQLite privado (`MANDO_TG_ROSTER`, por defecto `motor/server/data/tg_roster.db`).
`/rol` y `/baja` del puente hacen `POST /hr/tg/roster`. HappyRobot lee `GET /hr/tg/roster` y
despacha con `POST /hr/tg/dispatch`. **Esas rutas llevan `chat_id` y exigen `HR_SECRET`.** No
reutilizar el token del widget.

Si dos `tg_assignment` `accepted` llegan para el mismo aviso y rol, el espejo deja el primero
`accepted` y marca el resto `covered`.
