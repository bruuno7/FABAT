# Receta UI — `fa-despacho-tg`

Despacho a un puesto de Telegram (simulación). Twin no está provisionado: el directorio
rol↔`chat_id` y el cerrojo viven en MANDO. HappyRobot no alcanza el túnel, así que llama al
puente Vercel (`POST /hr/tg/dispatch`), que reenvía a MANDO.

Tras el extract de `fa-entrada-tg`, este workflow elige un puesto reclamado (`/rol`) y manda
botones Acepto / No puedo vía el puente.

## 1. Crear workflow

- Nombre: `fa-despacho-tg`
- Environment: `development`
- Cluster: EU
- Trigger: **Predefined Webhook** (payload conocido), `callable_by_workflows: true`

Params del trigger:

```
incident_id, texto, tipo, zona, gravedad, prioridad, alias_informante, correlation_id, summary
```

LIVE en development: [fa-despacho-tg](https://platform.eu.happyrobot.ai/hackspainteam6/workflows/eyg6a9kat3ea/editor/k2he4ujp4n1h)

Copiar `HR_SECRET` desde `fa-entrada-tg` (variable oculta). Lo normal es un nodo
**Call Workflow** al final de `fa-entrada-tg`.

## 2. Variables (nunca commitear secretos)

| Key | Valor |
|---|---|
| `PUENTE_URL` | URL pública del puente (`https://fabat.vercel.app`) |
| `HR_SECRET` | oculto; el mismo que `x-hr-secret` / `X-Mando-Token` de `fa-entrada-tg` |

## 3. Nodo POST puente `/hr/tg/dispatch`

URL: `{{PUENTE_URL}}/hr/tg/dispatch`

Cabecera: `x-hr-secret: {{HR_SECRET}}` (el puente también manda `X-Mando-Token` a MANDO)

Body (raw JSON):

```json
{
  "incident_id": "{{0.incident_id}}",
  "texto": "{{0.texto}}",
  "tipo": "{{0.tipo}}",
  "zona": "{{0.zona}}",
  "gravedad": "{{0.gravedad}}",
  "prioridad": "{{0.prioridad}}",
  "alias_informante": "{{0.alias_informante}}",
  "correlation_id": "{{0.correlation_id}}",
  "summary": "{{0.summary}}"
}
```

MANDO elige el puesto libre, escribe `tg_incident` / `tg_assignment` / `tg_staff` en el espejo
y devuelve `outbound` listo para Telegram (`chat_id` + botones `acc`/`dec`).

## 4. Path: `dispatched`

Si `response.dispatched` es true → POST al puente:

URL: `{{PUENTE_URL}}/hr/events`

Cabecera: `x-hr-secret: {{HR_SECRET}}`

Cuerpo = el objeto `outbound` (ya trae `event: telegram_send` y el teclado).
Un nodo Code puede hacer `json.dumps` del outbound para no romper el JSON con saltos de línea.

Si no hay staff reclamado, el workflow termina sin escribir al bot. El espejo ya tiene el aviso.

## 5. Publish development

Probar: `/rol medico` en el bot, luego disparar el hook con un extract de persona caída.
El médico recibe el texto de simulación y dos botones.
