# Publicar el equipo de agentes — development

Estado comprobado por MCP EU el 19-09-2026: **10 workflows LIVE en development; prueba-ana-cerebro sigue en borrador**. Hubo publicaciones concurrentes durante la revisión. Esta tabla describe los pendientes finales, no los errores iniciales. No republicar los que ya están LIVE.

| Workflow | Estado | Tools con «View Tool Call Result» pendiente |
|---|---|---|
| `prueba-ana-agente-triaje` | LIVE development | Ninguna |
| `prueba-ana-agente-prioridad` | LIVE development | Ninguna |
| `prueba-ana-agente-recursos` | LIVE development | Ninguna |
| `prueba-ana-agente-avisos` | LIVE development | Ninguna |
| `prueba-ana-agente-vigia` | LIVE development | Ninguna |
| `prueba-ana-agente-critico` | LIVE development | Ninguna |
| `prueba-ana-cerebro` | Borrador; publicar en development | `contexto`, `ensayar`, `decidir`, `memoria_buscar` |
| `prueba-ana-equipo` | LIVE development | Ninguna |
| `prueba-ana-aprende` | LIVE development | Ninguna |
| `prueba-ana-equipo-hook` | LIVE development | Ninguna |
| `prueba-ana-cerebro-hook` | LIVE development | Ninguna |

## Clics pendientes exactos

Solo en **prueba-ana-cerebro**, versión 1 (la versión seleccionada actualmente como origen del nodo de respuesta en su hook). Durante el cierre apareció una versión 2 creada concurrentemente: también se intentó publicar en development y devuelve exactamente los mismos cuatro bloqueos. Estas instrucciones conservan la selección inspeccionada del hook.

1. Abrir el editor y, bajo **Prompt**, seleccionar la tool **contexto** → **View Tool Call Result** → cerrar el panel.
2. Seleccionar **ensayar** → **View Tool Call Result** → cerrar el panel.
3. Seleccionar **decidir** → **View Tool Call Result** → cerrar el panel.
4. Seleccionar **memoria_buscar** → **View Tool Call Result** → cerrar el panel.
5. Pulsar **Publish**, elegir **development** y confirmar la publicación; comprobar **LIVE / development**.

No pulsar **Generate**, ejecutar el workflow ni iniciar llamadas o mensajes para estos clics.

## Orden de publicación

Para versiones nuevas: los seis `prueba-ana-agente-*` de la tabla primero; después **prueba-ana-equipo**; al final **prueba-ana-equipo-hook**. En la otra cadena: **prueba-ana-cerebro** antes de **prueba-ana-cerebro-hook**. **prueba-ana-aprende** es independiente. En el estado actual solo falta cerebro: su hook ya está publicado y su destino seguirá sin estar disponible hasta publicar cerebro.

## Configuración comprobada y límites

- Los Workflow Function Request declaran `entrada_json`, `callback_url` y `callback_token`. Las referencias usan el `persistent_id` del trigger; se comprobaron con `get_available_variables`.
- El coordinador llama a los seis especialistas en development, pasando `entrada_json` desde `payload_json` de cada tool y ambos callbacks directamente desde su trigger. El hook de equipo recibe y transmite esos tres campos mediante `data.*`.
- El hook de cerebro es Predefined Request: se declararon sus parámetros y se corrigieron las referencias a campos directos, sin `data.`. Los hooks de equipo y aprende conservan Incoming hook y su esquema `data.*`; su autenticación se completó con claves privadas.
- AVISOS tiene `decidir` → serializador con revisión del crítico → POST al backend `/hr/tools/decidir`. Voz se solicita mediante esa tool; la selección del despacho y la lista blanca corresponden al backend. Telegram incluye `mensaje` y `botones` en `decision.avisar` para que el backend lo refleje. El coordinador pide primero el plan, obtiene aprobación del crítico y delega la aplicación en AVISOS sin volver a llamar a su propio `decidir`.
- Los prompts publicados de AVISOS y equipo conservan este protocolo. La guardia pasó cuatro comprobaciones locales sin red (aprobación, dos rechazos y escalado); no son pruebas de llamadas.
- **«Missing variables» sigue apareciendo como aviso informativo de publicación**, aunque las variables están declaradas y disponibles. La API lo confirmó al publicar correctamente el hook de cerebro. No se afirma que ese texto haya desaparecido. La última validación bloqueante de cerebro contiene únicamente las cuatro tools anteriores.
- `fix_broken_vars` no detectó referencias rotas en los borradores que pudo revisar. Las revisiones de workflows publicados concurrentemente fueron rechazadas por la plataforma por estar publicados; no se modificaron esas versiones. Los tests de nodos con fixtures fallan por JSON de ejemplo, falta de salida previa o callbacks ficticios, por lo que **no acreditan ejecución extremo a extremo**.
- Sin git ni CLI hackspain, sin acciones en production, sin compras y sin llamadas ni mensajes reales. Solo se modificaron workflows autorizados `prueba-ana-*`.
