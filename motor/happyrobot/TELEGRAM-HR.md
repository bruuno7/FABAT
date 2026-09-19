# Telegram ↔ HappyRobot: el bucle completo del incidente (sin MANDO)

Estado a 19-sep (development, org `hackspainteam6`). Todo el procesamiento vive en HappyRobot;
el puente (`puente/`, Vercel) solo transporta. Memoria compartida: Redis (Upstash, credencial `fabat-redis`).

```
Telegram ──► puente ──► fa-entrada-tg (v9)  ──call──► fa-despacho-tg (v6) ──► puente ──► Telegram
   botones ─► puente ──► fa-respuesta-tg (v5) ────────────────────────────────► puente ──► Telegram
   /rol /baja /estado ─► fa-rol-tg (v1)
```

## Workflows

| Workflow | Qué hace |
|---|---|
| `fa-entrada-tg` | Cualquier texto de cualquier chat. `Leer estado del chat` → `Leer puestos` → **Contexto del remitente** (¿asistente o equipo? ¿qué incidente tiene abierto? ¿pregunta pendiente?) → `Leer incidente activo` → `Identify Explicit Data` (extractor) → **Decidir coordinación** (LLM: `relacion`, roles, pregunta, instrucciones, `mensaje_reenvio`) → **Serializar decisión** (relación → `mode` + respuesta inmediata) → POST reply al puente → call `fa-despacho-tg`. |
| `fa-despacho-tg` | Ejecuta el `mode`: despacha al primer puesto libre, guarda incidente/puestos/estado de chat y manda hasta 3 mensajes (puesto, asistente, otro). |
| `fa-respuesta-tg` | Botones del equipo: `acc` `dec` `eta` `loc` `lle` `enc` `fin` (`apr` `vet`). Cerrojo primer-acepta-gana, siguiente puesto, disponibilidad, hitos y cierre. |
| `fa-rol-tg` | Directorio de puestos `/rol` `/baja` `/estado`. |

La lógica de los Sandbox está versionada en [`sandbox/`](sandbox/) (`# --- COMMON ---` se sustituye por
`fa_common.py`). `python3 sandbox/test_local.py` simula Redis y encadena los tres workflows: 11 escenarios.
`sandbox/build_nodes.py <sandbox>` genera el JSON de `configuration` para `update_workflow_nodes`.

## Relación del mensaje → modo

El LLM clasifica cada mensaje con el contexto del remitente y del incidente abierto:

| `relacion` (LLM) | remitente | `mode` (despacho) | Efecto |
|---|---|---|---|
| `nuevo` | cualquiera | `new` | crea incidente, elige puesto por `roles_orden`, oferta con botones, guarda estado de ambos chats |
| `actualizacion` / `respuesta_a_pregunta` / `pregunta_al_equipo` | asistente | `answer_info` | completa incidente (zona…), reenvía al puesto activo |
| `respuesta_a_pregunta` con `pregunta_de` | asistente | `answer_to_staff` | «Respuesta del asistente a tu pregunta: …» al puesto que preguntó |
| `cierre` | asistente | `close` | cierra, avisa a los puestos activos, libera |
| `pregunta_al_asistente` | equipo | `staff_question` | «El equipo X pregunta: …» al asistente; su siguiente mensaje vuelve al equipo |
| `actualizacion` | equipo | `staff_note` | «El equipo X informa: …» al asistente |
| `estado_llegado` / `estado_localizado` / `estado_finalizado` | equipo | `staff_status` | aviso al asistente; `finalizado` cierra y libera el puesto |
| `charla` | cualquiera | `chat` | respuesta amable, sin incidente |
| (estado `staff_disponibilidad`) | equipo | `answer_availability` | «en 10 min» → `busy_until` |

Reglas: si no hay incidente abierto → `nuevo`; si el incidente está `cerrado` o han pasado >45 min → `nuevo`.
Botones = los mismos efectos que los estados por texto.

## Redis

| Clave | Contenido |
|---|---|
| `fa:seats` | `{rol: {chat_id, alias, claimed_at, busy_until?, incident_id?}}` |
| `fa:inc:<id>` | incidente: `estado` (`abierto`/`cerrado`), `zona`, `roles_orden`, `assignments[]` (con `hitos`), `actualizaciones[]`, `preguntas[]`, `reporter_chat_id` |
| `fa:chat:<chat_id>` | asistente: `{kind:'asistente_activo', incident_id, pregunta?, pregunta_de?, last_at}` · equipo: `{kind:'staff_activo', role, incident_id, assignment_id?}` o `{kind:'staff_disponibilidad', role}` |
| `fa:scratch:*`, `fa:chat:none`, `fa:inc:none` | claves basura: los nodos Redis Write siempre se ejecutan; cuando no hay nada que escribir apuntan aquí |

Las escrituras son lectura-modificación-escritura (no atómicas). Con cinco personas vale; en producción haría falta `SETNX`/Lua.

## Contrato con el puente

- Entrada: `POST HR_HOOK_TG` (`public_report`), `POST HR_HOOK_TG_RESPONSE` (`staff_response` con `callback_data`), `POST HR_HOOK_TG_ROSTER`.
- Salida: `POST {PUENTE_URL}/hr/events` con `x-hr-secret`, eventos `agent_reply` y `telegram_send` (`reply_markup` opcional).
- Los payloads entre workflows (call workflow) llegan **en la raíz** del trigger, no bajo `data.*`; los Sandbox leen los dos.

## Variables de workflow

`PUENTE_URL`, `HR_SECRET` (idéntico en los cuatro workflows y en Vercel). Nunca en el repo.
