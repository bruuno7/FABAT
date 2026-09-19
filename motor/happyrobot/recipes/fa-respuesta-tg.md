# Receta UI — `fa-respuesta-tg`

Respuesta del personal por botones (`acc` / `dec` / `eta` / `loc` / `apr` / `vet`).

El puente POST el `staff_response` a `HR_HOOK_TG_RESPONSE` (este workflow). MANDO aplica el
cerrojo (vía `POST {{PUENTE_URL}}/hr/tg/staff-response`): el primer `acc` de un rol queda
`accepted`; el resto, `covered`. Un `dec` reasigna al siguiente puesto de la misma familia
(p. ej. bomberos → policía).

## 1. Crear workflow

- Nombre: `fa-respuesta-tg`
- Trigger: **Incoming Webhook** (el payload trae `reporter` anidado)

Expected payload:

```json
{
  "event": "staff_response",
  "channel": "telegram",
  "kind": "acc",
  "callback_data": "acc|asg-1",
  "callback_query_id": "cq-1",
  "chat_id": "123",
  "assignment_id": "asg-1",
  "correlation_id": "tg-123-1",
  "text": "acc asg-1",
  "reporter": {
    "display_name": "Marta",
    "chat_id": "123",
    "role": "medico"
  }
}
```

LIVE en development: [fa-respuesta-tg](https://platform.eu.happyrobot.ai/hackspainteam6/workflows/9x6aihxeg9g2/editor/3wdztka8zmb2)

Copiar URL **development** del Incoming Hook → `HR_HOOK_TG_RESPONSE` en Vercel / `.env` (nunca en git).
Copiar `HR_SECRET` desde `fa-entrada-tg`.

## 2. Variables

Las mismas que `fa-despacho-tg`: `PUENTE_URL`, `HR_SECRET` (oculta).

## 3. Nodo POST puente `/hr/tg/staff-response`

URL: `{{PUENTE_URL}}/hr/tg/staff-response`

Cabecera: `x-hr-secret: {{HR_SECRET}}`

Body:

```json
{
  "kind": "{{0.data.kind}}",
  "callback_data": "{{0.data.callback_data}}",
  "assignment_id": "{{0.data.assignment_id}}",
  "chat_id": "{{0.data.chat_id}}",
  "alias": "{{0.data.reporter.display_name}}",
  "correlation_id": "{{0.data.correlation_id}}"
}
```

MANDO actualiza el espejo (`tg_assignment`, `tg_staff`, `tg_approval`) y devuelve:

- `outbound` — mensaje al chat que pulsó (ETA/zona, «ya cubierto», «busco a otro»)
- `next_outbound` — si hubo `dec`, el aviso con botones al siguiente puesto

## 4. POST al puente (hasta dos `telegram_send`)

URL: `{{PUENTE_URL}}/hr/events`  
Cabecera: `x-hr-secret: {{HR_SECRET}}`

Cuerpo = el objeto `outbound` / `next_outbound` tal cual (ya trae `event: telegram_send`).
Un nodo Code + loop evita mandar `null` cuando no hay siguiente.

Botones ETA/zona que emite MANDO:

```
eta|<assignment_id>|2   loc|<assignment_id>|front_pit
eta|<assignment_id>|5   loc|<assignment_id>|gate_a
eta|<assignment_id>|10  loc|<assignment_id>|main_stage
```

El puente ya parsea `kind|id|extra`. No hace falta cambiar `callback_data`.

## 5. Publish development

Probar: aceptar → botones de ETA; rechazar con otro puesto reclamado → le llega a ese.
Dos `acc` seguidos del mismo rol: el segundo ve «ya cubierto».
