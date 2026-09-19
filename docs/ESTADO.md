# Estado del equipo de agentes en HappyRobot (rama `ana`) — sáb 19-sep, 19:00

## `MANDO_CEREBRO` — qué poner en cada demo

Valores: `reglas` | `agente` | `hibrido` | `abanico`. Si falta o no encaja, el backend usa `reglas`.
Nada de esto elude las barandillas (lista blanca, lo grave → persona, despacho vital ya).

| Valor | Quién decide | Cuándo usarlo |
|---|---|---|
| **`agente`** | Agente rápido de HappyRobot (`decidir` con `fase: rapida`, `agente: rapido`) y después el enjambre (`fase: revision`, CONFIRMA/CORRIGE). Si HappyRobot no contesta en `MANDO_CEREBRO_TIMEOUT_S` (8 s), el mismo equipo con LLM local; si también falla, reglas en rojo. | **Demo real** (Sala + plataforma). Es el camino de dos velocidades. |
| **`reglas`** | Planificador determinista (`motor/mando`). La Sala no espera a HappyRobot. | **Demo pública sin claves** (Render). Arranca y se entiende sin `HR_API_KEY` ni LLM. |
| **`agente`** + `MANDO_LLM=1` y `AGENTES_LLM_KEY` | Igual que `agente`, pero el plan B es el LLM local en vez de ir directo a reglas. | **Demo pública con clave LLM** y sin HappyRobot. A los N s decide el equipo local. |
| **`abanico`** | El backend lanza los seis especialistas en paralelo (`abanico.py`) y compone. Misma cadena plataforma → LLM local → reglas. | Demo del enjambre en abanico; hace falta `HR_API_KEY` y los `HR_AGENTE_*`. |
| **`hibrido`** | Las reglas proponen y ejecutan; el agente puede corregir por `decidir`. | No es la demo del reto; útil si la plataforma va a trompicones y se quiere un plan B que no espere. |

La Sala pinta las seis tarjetas por papel en `S.agentes[inc].agentes` (triaje, prioridad, recursos, avisos, vigía, crítico) y la línea «Decisión rápida en N s · enjambre: CONFIRMA/CORRIGE/pendiente». En `abanico` añade «Primera decisión en N s · enjambre completo en N s».

## Publicado en *development* (listo para correr)
| Workflow | Papel |
|---|---|
| `prueba-ana-agente-triaje` | Qué información importa: fusiona, descarta rumores y bromas, una sola pregunta si falta algo |
| `prueba-ana-agente-prioridad` | Qué va primero, con los medios que quedan, y a quién se deja esperando |
| `prueba-ana-agente-recursos` | Dónde van los recursos; ensaya repartos en el gemelo |
| `prueba-ana-agente-avisos` | A quién se avisa, por qué canal y qué se le dice; ejecuta por `decidir` |
| `prueba-ana-agente-vigia` | Cuándo tirar el plan: qué supuesto se ha roto |
| `prueba-ana-agente-critico` | Revisa la decisión conjunta: aprobar, corregir o escalar a persona |
| `prueba-ana-equipo` | Coordinador: rama vital primero, luego llama a los especialistas como herramientas, `decidir` y `memoria_guardar` |
| `prueba-ana-equipo-hook` | Entrada de prueba del equipo (Incoming hook) |
Pendientes de publicar: `prueba-ana-cerebro`, `prueba-ana-cerebro-hook`, `prueba-ana-aprende`.

## Cómo se publicó (para repetirlo)
La plataforma exige abrir «View Tool Call Result» en cada tool. Atajo: abrir en el navegador
`<URL del editor>?type=tool&node-id=<id del nodo tool>&tool-result=true` para cada tool (los ids salen de
`get_workflow_details` con `include_nodes`), y después `manage_versions publish` a `development` por MCP.

## Primera ejecución: BLOQUEADA ahora mismo por la plataforma
- `trigger_run` (API de HappyRobot) devuelve **502 Bad Gateway** de Cloudflare (lado de HappyRobot) desde las 16:33.
- El hook de desarrollo `https://workflows.platform.eu.happyrobot.ai/hooks/development/<slug>` responde **401 «Invalid API key»**
  con la clave `x-api-key` que muestra el editor (y también con la API key de la organización).
- Siguiente intento: botón ▷ (probar) del editor en `prueba-ana-equipo-hook`, o preguntar a un mentor de HappyRobot por el 401
  del hook de desarrollo con seguridad reforzada.

## Avisos
- Las variables del disparador (`entrada_json`, `callback_url`, `callback_token`) salen como «no resueltas (informativo)» al
  publicar; si en la ejecución llegan vacías, hay que declararlas como parámetros del disparador (lo está haciendo otro agente).
- El túnel gratuito cambia de URL al reconectarse: la vigente está siempre en `.env` (`MANDO_PUBLIC_URL`).
