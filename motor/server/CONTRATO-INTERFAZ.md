# Contrato de interfaz — Sala de control y cliente externo

Para portar la Sala (`static/sala.*`) o una app Next.js en `web/` contra el backend MANDO.
Ejemplos capturados del servidor real con `demo-1` y `demo-gates` (TestClient, sin red).

## Origen y CORS

| Variable | Efecto |
|---|---|
| `MANDO_CORS_ORIGINS` | Lista blanca separada por comas: `https://app.example,http://localhost:3000`. Vacía por defecto → sin cabeceras CORS (comportamiento anterior). |
| `MANDO_OPERATOR_TOKEN` | Cabecera `X-Mando-Operator` para operar desde otro origen. La cookie de `/acceso` es `SameSite=strict` y no cruza orígenes. |
| `MANDO_PUBLIC_URL` | Si está definida, localhost también exige token de operador (entrada por `/acceso`). |

Cabeceras CORS permitidas: `Content-Type`, `X-Mando-Operator`, `X-Mando-Unit`, `X-Mando-Token`.
Métodos: `GET`, `POST`, `OPTIONS`. Sin `Access-Control-Allow-Credentials`.

---

## Instantánea y tiempo real

### `GET /api/state`

Quién: cualquiera en la red local (o con cookie/token si `MANDO_PUBLIC_URL`).

Respuesta (recorte `demo-1`, t=0, sin espejo):

```json
{
  "t": 0,
  "session": {
    "id": "s-27b2e92934cfe9da",
    "case": "c-d000001",
    "title": "Parada cardiaca con la ambulancia atrapada",
    "running": false,
    "speed": 1.0,
    "comms_mode": "sim",
    "agent": "Mando"
  },
  "telegram": {"status": "off"},
  "telegram_bot": {"status": "off"},
  "incidents": [],
  "reports": [],
  "approvals": [],
  "zones": [{"id": "front_pit", "name": "Frente de escenario", "density": 4.03, "ratio": 0.877}],
  "resources": [{"id": "med_1", "kind": "medical", "name": "Equipo médico 1", "status": "available"}],
  "fronts": [],
  "plans": [],
  "forecasts": [],
  "calls": {"mode": "sim", "calls": [], "fallbacks": 0},
  "happyrobot": {"dispatch": {"configured": false, "events": 0}},
  "presentation": {"happyrobot": "simulado", "telegram": "apagado", "voice": "simulada", "banner": "voz simulada"}
}
```

### `GET /api/stream`

Quién: igual que `/api/state`.

SSE: cada mensaje es `event: state` con el JSON completo de `/api/state` en `data`.
Parámetro opcional `?limit=N` corta tras N eventos (pruebas).

```text
event: state
data: {"version":3,"t":1,"session":{...},"telegram":{...},...}
```

---

## Operador

Cabecera `X-Mando-Operator: <MANDO_OPERATOR_TOKEN>` o cookie HttpOnly de `POST /acceso`.

| Método | Ruta | Cuerpo | Respuesta |
|---|---|---|---|
| POST | `/api/control` | `{"cmd":"play"}` / `pause` / `step` / `speed` / `reset` | `{"ok":true}` |
| POST | `/api/approve` | `{"action_id":"A-0001","ok":true,"note":""}` | `{"ok":true}` |
| POST | `/api/demo/telegram` | `{"zone":"front_pit"}` | Ver abajo |

### `POST /api/demo/telegram` (demo sin plataforma)

```json
{
  "ok": true,
  "n": 10,
  "escaladas": [
    {
      "incident_id": "tg-demo-1",
      "rol": "seguridad",
      "motivo": "3 avisos por Telegram sin nadie que acuda; queda la llamada por voz (seguridad).",
      "workflow_voz": "mando-despacho-seguridad"
    }
  ],
  "telegram": {
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
    "escaladas": [{"incident_id": "tg-demo-1", "rol": "seguridad", "workflow_voz": "mando-despacho-seguridad", "motivo": "…"}]
  }
}
```

Idéntico en `demo-1` y `demo-gates` (misma secuencia determinista).

---

## Webhook espejo (HappyRobot)

### `POST /hr/events`

Quién: `X-Mando-Token` = `HR_SECRET`.

Tipos del espejo: `tg_incident`, `tg_assignment`, `tg_staff`, `tg_approval`. Detalle en [ESPEJO-TELEGRAM.md](ESPEJO-TELEGRAM.md).

Respuesta `tg_incident`:

```json
{"ok": true, "duplicate": false, "incident_id": "tg-doc-1", "report_id": "R-0001"}
```

Errores de validación → **422** sin avanzar el reloj simulado.

---

## Qué campo pinta cada zona de la Sala

| Zona de pantalla | Campo(s) del estado |
|---|---|
| Reloj y caso | `t`, `clock`, `session` |
| Incidentes / frentes | `incidents`, `fronts`, `reports` |
| Plano y densidad | `zones` (`density`, `ratio`, `state`, `flags`) |
| Recursos del recinto | `resources` |
| Plan y supuestos | `plans` |
| Tarjeta de decisión | `approvals` (acciones `awaiting_approval` con `decision_card`) |
| Llamadas HappyRobot | `calls` |
| Previsiones 15 min | `forecasts` |
| **Despacho Telegram** | `telegram` **solo si** tiene `asignaciones` (contrato compartido) |
| Staff disponible (TG) | `telegram.staff.disponibles` / `telegram.staff.total` |
| Asignaciones TG | `telegram.asignaciones[]` |
| Escalada a voz | `telegram.escaladas[]` → botón con `workflow_voz` |
| Estado del bot (legacy) | `telegram_bot` o `telegram.status` cuando no hay espejo |
| Banner de canales | `presentation` |
| Workflows HR | `happyrobot` |

La Sala **no** debe pintar el panel de despacho Telegram si `telegram.asignaciones` no existe.

---

## Otros endpoints usados por la Sala

| Método | Ruta | Quién | Notas |
|---|---|---|---|
| GET | `/api/festival` | público | Zonas y metadatos del recinto |
| GET | `/api/cases` | público | Lista de casos demo |
| POST | `/api/session` | operador | Cambiar caso: `{"case_id":"demo-1"}` |
| POST | `/api/report` | público (cuota IP) | Aviso del jurado |
| POST | `/api/strike` | público / operador | Golpe del jurado (presets) |
| GET | `/api/chats` | operador | Panel CHAT · AGENTE HR |

---

## Ejemplo `S.telegram` tras demo (`demo-gates`)

```json
{
  "staff": {"disponibles": 4, "total": 5},
  "asignaciones": [
    {"incident_id": "tg-demo-1", "rol": "medico", "estado": "accepted", "alias": "Marta", "eta_min": 3, "desde_zona": "gate_a", "intento": 1, "t": 0},
    {"incident_id": "tg-demo-1", "rol": "seguridad", "estado": "declined", "alias": "Iván", "eta_min": null, "desde_zona": null, "intento": 1, "t": 0},
    {"incident_id": "tg-demo-1", "rol": "seguridad", "estado": "timeout", "alias": "Nadia", "eta_min": null, "desde_zona": null, "intento": 2, "t": 0},
    {"incident_id": "tg-demo-1", "rol": "seguridad", "estado": "timeout", "alias": "Bruno", "eta_min": null, "desde_zona": null, "intento": 3, "t": 0}
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
