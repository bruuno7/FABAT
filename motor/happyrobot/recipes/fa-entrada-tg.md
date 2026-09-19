# Receta UI — `fa-entrada-tg`

Usar si el usuario elige **(B) solo receta UI**. Si elige **(A)** con API key Editor, replicar estos nodos vía API/MCP.

## 1. Crear workflow

- Nombre: `fa-entrada-tg`
- Environment: `development`
- Cluster: EU

## 2. Trigger — Incoming Hook

Expected payload (pegar como schema / ejemplo):

```json
{
  "event": "public_report",
  "channel": "telegram",
  "reported_at": "2026-09-19T12:00:00.000Z",
  "text": "Hay una persona caída cerca del escenario principal",
  "reporter": {
    "external_id": "tg:123",
    "display_name": "Ana",
    "chat_id": "123",
    "perfil_color": "adulto"
  },
  "location_hint": "escenario",
  "correlation_id": "tg-123-1710000000"
}
```

Copiar URL **development** del hook → variable `HR_HOOK_TG` en el server (nunca commitear).

## 3. Nodo Extract / Agent

Extraer JSON:

```json
{
  "incident_type": "medica|aglomeracion|agresion|clima|infra|otro",
  "sector": "string",
  "severity": 1,
  "triage_color": "rojo|amarillo|verde|negro|desconocido",
  "perfil_color": "menor|pmr|adulto|personal|vip",
  "summary": "string corta ES"
}
```

Prompt corto: confirmar hechos, no inventar recursos, no cerrar crisis sola.

## 4. Webhook saliente → MANDO

POST `{{MANDO_CALLBACK_URL}}/hr/events`

Header: `x-hr-secret: {{HR_SECRET}}`

Body ejemplo:

```json
{
  "event": "agent_reply",
  "correlation_id": "{{trigger.correlation_id}}",
  "channel": "telegram",
  "chat_id": "{{trigger.reporter.chat_id}}",
  "reply_text": "Recibido. Estamos priorizando tu aviso en el sector indicado.",
  "extract": {
    "incident_type": "medica",
    "sector": "escenario",
    "severity": 4,
    "triage_color": "rojo",
    "perfil_color": "adulto",
    "summary": "Persona caída cerca del escenario"
  },
  "hr_run_id": "{{run.id}}"
}
```

## 5. Publish development

Probar con curl al Incoming Hook usando el mismo JSON de ejemplo.
