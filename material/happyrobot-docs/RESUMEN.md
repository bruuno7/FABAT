# HappyRobot — resumen privado (usable sin docs.happyrobot.ai)

Fuente: conversación equipo + CEO + material previo. Fetch docs.happyrobot.ai desde agentes = 403.

## Modelo

Workflow (1 trigger) → nodos → agentes (Voice / Text / Reasoning) → Tools → webhooks a backend.

Clúster: **EU** — `platform.eu.happyrobot.ai`, SDK `cluster: "eu"`. Workspace típico hack: `hackspainteam6`.

## Canales relevantes Festival Abierto

| Canal | Uso demo |
|-------|----------|
| Web Call + SDK | Principal |
| Outbound Voice / SMS (+1 cubierto por HR) | Secundario |
| WhatsApp | Requiere Meta Business propia |
| Telegram | **Sin nativo**; puente API en nuestro backend |
| Incoming Hook | Trigger para reports TG / sensores |

## MCP EU

`https://mcp.platform.eu.happyrobot.ai/{workflows,frontal,twin}/mcp`

## CEO (verbatim interpretado)

- Número US en plataforma: lo cubren ellos.
- Outbound: no deberían cobrar.
- Inbound demo: preferir Web Call.
- Telegram = alternativa valorada como WhatsApp, vía APIs.
