# TRASPASO FABAT → instancia siguiente

> Generado para continuar el agente **Puente telegram happyrobot**.  
> Repo al recibir este traspaso: solo `README.md` en `main` (código motor/consejo aún no versionado aquí).

## 1. Quiénes somos y el producto

Equipo FABAT, track HappyRobot, evento 18–20 sep 2026.

Producto interno: **MANDO** (chasis ResQFlow). HappyRobot habla; el backend decide.

Escenario: Festival Abierto — 40.000 asistentes, 30.000 m², 1 escenario, varios sectores, 3 días (día 1 incidencias menores → día 2 mayor; “aprender” día1→día2).

Crisis: clima, médica, aglomeraciones, agresiones, falta de recursos, fallos de infra, etc.

Consejo (`consejo/DECISION.md`): titular «Sabe cuándo su plan ha dejado de valer»; Web call; tarjeta de decisión para lo grave; rebanada vertical HR urgente; cero LLM en el núcleo del planificador.

## 2. Lo que el usuario pidió al inicio

Resumen “increíble” de funcionalidades de HappyRobot (docs.happyrobot.ai, código oshappyrobot).

Encaje con el festival + créditos sponsors: Cloudflare 100$, Vercel.ai 50$, fal 50$, Exa 50$, Cognition 200$, Quiver 50$.

Características del escenario (arriba) + colores por tipo de persona (menor, PMR, adulto…).

Preguntar dudas antes de concluir.

Fetch a docs.happyrobot.ai desde el agente = 403. Fuente usable: `material/happyrobot-docs/RESUMEN.md` + `motor/happyrobot/DOCS_CONFIRMADO.md`.

## 3. Decisiones del usuario en esta conversación

| Tema | Decisión |
|------|----------|
| Canal demo principal | Opción A: Web call / chat en navegador |
| Colores persona | A + B a la vez: perfil preventivo (QR/pulsera) + triage en incidente |
| Implementar desde Cursor | Sí vía API/MCP/SDK, con clics finales en UI |
| Acceso a su cuenta HR | Pedida API key Editor + OK workflows; **aún no entregada** |
| Telnyx US | Configuró móvil Telnyx; confundió con Telegram |
| Inbound teléfono US desde España | Tasas internacionales; **no usar inbound PSTN desde ES** |
| Telegram API key en HR | **No existe** integración nativa |
| Bot Telegram + estructura HR | Pedido; **falta token y elección A/B API** |
| Último mensaje | Quiere este traspaso para otra instancia |

Plan guardado antes: HappyRobot festival map (capacidades + colores dos capas + créditos).

## 4. Resumen HappyRobot (lo esencial)

Modelo: Workflow (1 trigger) → nodos → agentes (Voice / Text / Reasoning) → Tools → webhooks a backend. Clúster equipo: EU (`platform.eu.happyrobot.ai`, workspace típico `hackspainteam6`, SDK cluster: `"eu"`).

Útil para el festival:

- Web Call + SDK (`POST /voice/tokens` + data); Listen / Takeover (`should_takeover`)
- Outbound/Inbound Voice; SMS; WhatsApp (Meta); Slack/Teams/Email; Chatbot
- Signals a `session.<id>` (escenario cambia en llamada)
- AI Extract (JSON Schema + enums), AI Classify, OCR/KB
- Contact Intelligence (memoria por contacto; beta) — no sustituye aprendizaje del recinto en Mando
- Northstars, Audits, Adversarial/E2E, extract-from-run, latency breakdown
- MCP: `https://mcp.platform.eu.happyrobot.ai/{workflows,frontal,twin}/mcp`

Arquitectura acordada: HappyRobot habla/confirma; Mando prioriza/asigna/replanifica.

Specs: `motor/happyrobot/WORKFLOWS.md`, contrato `motor/happyrobot/webhook_contract.json`. Servidor: `motor/server` (`/hr/events`, `/telegram/webhook`, etc.).

Colores dos capas:

1. `perfil_color` estable (menor/PMR/adulto/personal/VIP)
2. `triage_color` dinámico en incidente (rojo/amarillo/verde…)

Pantalla: dos chips; triage manda cola médica; perfil modifica protocolo.

Créditos: CF = túnel/adaptador; Vercel = UI; fal/Exa/Quiver opcionales; Cognition = acelerar código; HR = interacción real.

## 5. Aclaraciones del CEO de HappyRobot

- Podéis comprar número americano en la plataforma; lo cubren ellos.
- Outbound: no deberían cobraros nada.
- Inbound: mejor trigger **Web Call** (no inbound telefónico).
- SMS con número americano funciona bien.
- WhatsApp: necesitáis vuestra cuenta Meta Business.
- Alternativa gratuita a WhatsApp, setup más fácil: **bot Telegram + integración por API**. No hay integración nativa. Se valora por igual WhatsApp y Telegram.

Puente:

```
Usuario TG → Bot → nuestro backend → webhook HappyRobot → agente → webhook vuelta → backend → sendMessage TG
```

## 6. Telefonía / Telegram — aclaraciones

- Telnyx en Assets → Calling Status Synced → trigger Inbound to Number + Inbound Voice Agent → Publish. Un número = un workflow entrante.
- HappyRobot no tiene Telegram nativo.
- Llamar un +1 desde móvil ES = tasas internacionales.
- Evitar inbound PSTN para demo; Web call o outbound a +34.

## 7. Acceso HR (pendiente)

Imprescindible:

- API key org con rol **Editor** (nacen Viewer)
- Confirmación workspace (`hackspainteam6` EU?)
- Permiso explícito crear/editar `fa-webcall` / `fa-entrada-tg` en development

Útil: OAuth MCP EU en Cursor.  
Para demo: workflow id/slug, `MANDO_CALLBACK_URL` (túnel), `HR_SECRET`.

Nunca: password login, secretos en repo público / commits.

Variables: ver `motor/server/README.md` y `.env.example`.

## 8. Bot Telegram — estado

Usuario: “bot muy básico + estructura en HappyRobot; dime qué necesitas antes”.

**Falta respuesta del usuario:**

1. Token BotFather + nombre del bot
2. Dónde vive el puente (default: `motor/server` `POST /telegram/webhook`) — **scaffold hecho en esta rama**
3. HappyRobot: (A) API key Editor para crear workflow, o (B) solo receta UI
4. URL pública HTTPS vs polling `getUpdates` en local

Dueños AGENTS.md: `motor/server` = Ana; `motor/happyrobot` = Bruno. Cambios → `buzon/`.

## 9. Archivos clave

| Ruta | Qué |
|------|-----|
| `CLAUDE.md` / `AGENTS.md` / `TRASPASO.md` / `INSTRUCCIONES.md` | Contexto equipo |
| `consejo/DECISION.md` | Decisiones consejo |
| `material/happyrobot-docs/RESUMEN.md` | Doc HR privada |
| `motor/happyrobot/*` | Specs workflows, prompts, northstars, contrato |
| `motor/server/*` | Backend + adaptador HR + puente TG |
| `PREGUNTAS-MENTORES.txt` | Preguntas abiertas (+ respuestas CEO) |

Reglas duras: no hackspain watch; no submit sin `--draft`; no leer código de rivales; datos pitch con etiqueta verificado/sin verificar.

## 10. Qué debería hacer la siguiente instancia

Si continuar bot Telegram:

1. Esperar token + (A o B) acceso HR + HTTPS vs polling.
2. Plan concreto (scaffold ya en rama):
   - endpoint Telegram en server → `public_report` del contrato
   - workflow `fa-entrada-tg` (Incoming hook → agent/extract → webhook)
   - buzón a Bruno/Ana
3. No publicar secretos; no tocar repo público con claves.
4. Actualizar `PREGUNTAS-MENTORES.txt` con respuestas del CEO al implementar (hecho en esta rama).

Si pide el mapa HappyRobot festival: el plan ya existe; volcar a doc privado solo con OK.

## 11. Frases útiles de evaluación

Jurado HappyRobot: ejecutar, no solo chat; voz &lt;300 ms deseable (no afirmable sin medir); adversarial/northstars/audits son su vocabulario.

Diferencia: su adversario ataca la conversación; el nuestro ataca el mundo (escenario/recursos/supuestos).

Filtro 9 preguntas antes de construir (algo real, bloques eval, jurado puede romper, vídeo sin sonido, número, humano interviene, no commodity, comprador, cabe en horas).

## Estado de esta rama (`cursor/telegram-hr-bridge-8963`)

- [x] Persistido este traspaso
- [x] Scaffold `motor/server` puente TG ↔ HR (sin secretos)
- [x] Contrato `webhook_contract.json` + receta `fa-entrada-tg`
- [x] Buzón Ana/Bruno
- [ ] Live: token TG + HR Editor key + túnel HTTPS (bloqueado por usuario)
