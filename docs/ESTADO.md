# Estado del equipo de agentes en HappyRobot (rama `ana`) — sáb 19-sep, 16:40

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
