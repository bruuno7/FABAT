# Publicar el equipo de agentes — development

Actualización 19-09-2026: corrección de retorno y espera síncrona, basada en los runs `cbd133ee-2c67-4a5d-a88a-1cb21f65c4e1` y `8959a3fd-f2ff-49cf-84ca-bb3e5d841d7c`.

Los seis especialistas usan `entregar_resultado.payload_json` si es un objeto JSON; en su ausencia recuperan el último evento `_terminate` del agente (`events[].reasoning`). Si contiene JSON, lo devuelven; si es texto, devuelven `{agente,razonamiento,confianza:null}`. El retorno está fuera de las tools, con **Response node** activo. El prompt exige siempre `entregar_resultado`.

El coordinador espera a los seis especialistas (`fire_and_forget=false`, timeout 90 s, development explícito) y selecciona sus nuevos nodos de respuesta. Su prompt exige triaje → prioridad → recursos → avisos (planificar) → crítico → decidir → memoria_guardar. Vigía precede esa secuencia para cambios. Ante evidencia incompleta, conserva el error y escala sin fabricar aprobación ni ejecutar el plan. Avisos no recibe fase ejecutar del coordinador, evitando aplicar dos veces.

| Workflow | Versión LIVE development | Nodo final (node-id) | Clics pendientes |
|---|---|---|---|
| `prueba-ana-agente-triaje` | v3 | `01a0ba36-0e84-7a68-893b-2c49a1af3d73` | Ninguno |
| `prueba-ana-agente-prioridad` | v2 | `01a0ba39-0041-7ff4-a46b-17caf3c50bb4` | Ninguno |
| `prueba-ana-agente-recursos` | v2 | `01a0ba39-2ae3-7c7a-bd04-1277dce4033f` | Ninguno |
| `prueba-ana-agente-avisos` | v2 | `01a0ba39-5e4b-7319-b1d3-35dd7ada8149` | Ninguno |
| `prueba-ana-agente-vigia` | v2 | `01a0ba39-88d7-7edc-8acb-f11d82665bbe` | Ninguno |
| `prueba-ana-agente-critico` | v2 | `01a0ba39-b2d4-7278-b4c6-f95e819de0f0` | Ninguno |
| `prueba-ana-equipo` | v5 | No añadido; cambio de prompt y seis Call Workflow | Ninguno |

URLs exactas de los editores: fichero privado `/Users/anayang/workspace/hackspain-2026/motor/happyrobot/PLATAFORMA_REAL.md`, sección «Retorno robusto y espera síncrona — 19-09-2026». No hubo bloqueo de View Tool Call Result.

Verificación: cuatro casos locales del Python de retorno pasaron sin red (JSON de tool, JSON final sin tool, texto final y entrada vacía). Los seis Call Workflow se releían correctamente con espera, 90 s, development y nuevo nodo final. Las referencias events/payload se comprobaron disponibles. Publicación aceptada con avisos informativos Missing variables; no se acredita prueba extremo a extremo.

La revisión automática rechazó fix_broken_vars para avisos, vigía, crítico y coordinador: su dry-run invoca test-all e intenta POST. En triaje, prioridad y recursos los intentos con callback de ejemplo fallaron por URL sin protocolo; no hubo envío válido. Se sustituyó por inspección sin ejecución y pruebas locales. No se usó trigger_run, git ni hackspain; sin compras ni acciones en production. La próxima ejecución la lanza Ana.

---

## Historial anterior (sustituido por el estado de arriba)

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

## Retorno de Workflow Function — 19-09-2026

- `prueba-ana-agente-triaje`: versión 2 publicada LIVE en **development**, sustituyendo atómicamente la versión 1.
- La plataforma no ofrece un evento separado Workflow Function Response: se activa **Response node → Send this output back to Call Workflow** en una acción.
- Añadido **Devolver resultado validado** como hijo de **Triaje**, fuera de las tools; devuelve el objeto JSON de `entregar_resultado.payload_json`, cuya referencia se verificó con `get_available_variables`. El validador existente se conserva.
- Nodo final: `01a0ba22-b4f5-733e-9dd7-d1931345162f`. Versión: `01a0ba20-300c-7099-a3a5-bd771a286e51`. Editor real registrado en el fichero local `PLATAFORMA_REAL.md`; sin slugs privados aquí.
- Publicación aceptada sin bloqueos de **View Tool Call Result**. El test aislado falló por JSON vacío de ejemplo; no acredita el retorno en ejecución.
- Repetición del coordinador pendiente: la revisión automática rechazó `trigger_run` por el reenvío del payload y token al callback externo. No se creó un nuevo run. Se necesita autorización explícita para ese destino.
- Prioridad, recursos, avisos, vigía y crítico siguen intactos, pendientes de comprobar primero el retorno de triaje.
