# WORKFLOWS — Festival Abierto / MANDO

Cluster: EU · Workspace típico: `hackspainteam6` · Env demo: `development`

## Principio

HappyRobot habla / confirma / extrae. MANDO prioriza / asigna / replanifica.  
Cero LLM en el núcleo del planificador.

## Workflows

| Slug | Trigger | Rol |
|------|---------|-----|
| `fa-webcall` | Web Call | Demo principal jurado |
| `fa-entrada-tg` | Incoming Hook | Entrada Telegram vía puente MANDO |
| `fa-outbound-sms` | (opcional) | SMS +1 HR si hace falta |

## `fa-entrada-tg` (prioridad puente)

1. **Incoming Hook** — payload = `public_report` (`webhook_contract.json`)
2. **AI Extract / Text Agent** — incident_type, sector, severity, triage_color, summary
3. **Webhook out** → `MANDO_CALLBACK_URL` `/hr/events` con `agent_reply` + `extract_ready`
4. MANDO decide; si hay `reply_text`, backend hace `sendMessage` a Telegram

Receta UI: `recipes/fa-entrada-tg.md`.

## `fa-webcall`

1. Web Call trigger + SDK token
2. Agent Voice (ES)
3. Tools → webhook MANDO `/hr/events`
4. Signals `session.<id>` si el escenario cambia mid-call
5. Takeover humano (`should_takeover`) en grave

## Northstars (vocabulario jurado)

- Reporta incidencia con sector + tipo en &lt;N turnos
- No inventa recursos; pide a MANDO
- Escala a humano si triage rojo / agresión / médico grave

## Adversarial

Su adversario ataca la conversación. El nuestro ataca el mundo (recursos, clima, supuestos del día 1 vs día 2).
