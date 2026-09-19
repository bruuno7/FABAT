# Interfaz completada y contrato pendiente — 19/09/2026

Cambios persistentes de este trabajo: únicamente `motor/server/static/`. Sin git, sin `hackspain`, sin publicación y sin editar Python.

## Pantallas

- Mando: selección cruzada de aviso, incidente, zona, recurso y plan; detalle lateral con prioridad, planes, supuestos, ensayo, llamadas, fichas de conversación e instrucción. Las instrucciones de avisos sin conversación se consultan en `/api/report/{id}.safety`.
- Ensayo: desvío con destino y porcentaje, restricción/cierre/apertura y parada del espectáculo; SVG por zona, cifras por minuto accesibles y métricas de pico/minutos > 4 y > 5. Pausa la simulación al ensayar; `Ordenar esto` aplica exactamente `response.action`. Una prueba pierde validez al cambiar los controles, la partida o el minuto.
- Decisión: conserva el foco, la nota y las tablas abiertas mientras actualiza ventana y escalada. Reutiliza el SVG y, para acciones compatibles, calcula una vez los dos futuros mediante `/api/whatif`. N = 1 por opción; el ensayo mantiene las órdenes actuales y no simula nuevas decisiones del planificador.
- Embudo: usa `state.funnel` y su canal real, con SVG para voz, SMS, Telegram, email, web y sensor. Conexiones de Telegram y HappyRobot visibles. Sonido opcional con botón o M, solo después de activarlo.
- Duelo: cifras y zona de máxima densidad actual leídas de cada lado; el pico histórico se identifica aparte. Un imprevisto aparece simultáneamente en ambos lados. La lista seleccionada se identifica a partir del estado, sin fingir variantes disponibles.
- Memoria: tarjetas con evidencia y N, Aprobar/Rechazar, estado honesto de aplicación, tabla e intervalos SVG. Cuando `observations` está vacío se muestra la evidencia textual de las propuestas, marcada como tal. No se fabrican intervalos ni mejoras.
- Asistente: respeta respuestas rápidas `{label,value}`, incluida la lista vacía; usa fichas del servidor, valores booleanos y ubicación estructurada. `instruction.metronome: false` prevalece sobre cualquier inferencia. Eliminado el filtro provisional `sitrep` tras comprobar que el backend actualizado bloquea esas preguntas en `Session._route_ask` y `ChatHub.route_ask`. La selección normal de acciones solo incluye preguntas dirigidas al informante.
- Asistente: instrucción en el flujo del documento, por encima del mini-plano; enlaces de voz/Telegram configurados y email/SMS solo si llegan enlaces válidos. Corregido el enlace vacío que abría la propia página. Foco contenido y restaurado en la hoja de selección. Movimiento reducido respetado.
- Jurado: redirección a `/asistente`, conservando parámetros y fragmento con JS; enlace y refresh como respaldo sin JS.

## Comprobación realizada

- Servidor local con el comando solicitado, `PYTHONDONTWRITEBYTECODE=1` y caché UV en `/private/tmp/codex-uv-cache`. Solo puerto 8791; no se ha tocado el servidor ajeno.
- `node --check`: los 9 `.js` de static. También validada sintaxis de scripts inline presentes en las cinco páginas del encargo.
- Curl: las cinco páginas, recursos JS/CSS, `/api/festival`, `/api/cases`, `/api/state`, `/api/stream?limit=1`, `/api/control`, `/api/session`, `/api/whatif` (desviar, restringir, cerrar, parar), `/api/whatif/order`, `/api/report`, `/api/report/{id}`, `/api/report/{id}/answer`, `/api/chat`, `/api/chat/{id}/events?limit=1`, `/api/strike`, `/api/strike/{id}`, `/api/jury`, `/api/approve`, `/api/memoria`, `/api/memoria/decide`, `/api/duel/state`, `/api/duel/session`, `/api/duel/control`, `/api/duel/stream?limit=1`, `/api/webcalls` y QR. Se verificaron formas de JSON y 15 muestras por serie.
- `/api/report/{id}/answer`: comprobada respuesta 409 sin pregunta pendiente; no se obtuvo una pregunta pendiente en los tres avisos de prueba. `/api/memoria/decide`: validación 404 con id inexistente para no escribir decisiones fuera de static. La aprobación de una acción pendiente sí devolvió 200.
- La prueba de un endpoint de regresión preexistente creó `motor/server/regression_live/test-012.json`; se comprobó su autor y hora de prueba y se retiró inmediatamente. Ninguna regresión anterior se modificó.
- Comprobadas por ejecución JS aislada: escape HTML, valores ausentes, umbrales estrictos > 4 / > 5 y precedencia de `metronome: false/true`. IDs únicos y referencias DOM definidas; sin dependencias externas en las cinco páginas.
- Contraste calculado de texto principal, secundario y semántico sobre fondo/panel/panel secundario: mínimo 6,33:1 en oscuro y 4,77:1 en claro. No equivale a una auditoría visual completa de todos los estados.
- **Pendiente visual:** la revisión automática de permisos rechazó abrir `http://127.0.0.1:8791` en el navegador por permiso denegado. No se intentó sortear el bloqueo. Queda pendiente recorrer con teclado en navegador, ver las curvas y comprobar el plano en un móvil real.

## Campos que faltan del servidor (añadidos al final)

1. **Observaciones independientes de las propuestas.** `/api/memoria` devolvió `observations: []` aunque existe el fichero de memoria. Publicar el resumen de `resupply`, `contacts`, `duplicates`, `locate`, `weather` con datos reales:
   ```json
   {"observations":[{"id":"resupply-water-n","text":"Texto de la observación real","n":50}]}
   ```
   El frontend ya admite esta forma y da prioridad a ella sobre la evidencia extraída de las propuestas.

2. **Comparación antes/después y nivel de confianza.** `/api/memoria.comparison` trae `rows: []`, `n: null`, `verdict: null`; `raw_keys` menciona `splits` y `n_per_arm`, pero no entrega sus datos. No es posible reconstruir la comparación desde HTTP. Forma consumida (valores numéricos reales, no estos marcadores):
   ```json
   {"comparison":{"n":400,"verdict":"sin evidencia de mejora","fingerprint":"huella real","rows":[{"name":"Métrica","split":"heldout","before":0.0,"after":0.0,"delta":0.0,"ci":[-0.1,0.1],"confidence":0.99,"n":400,"significant":false,"verdict":"sin evidencia de mejora"}]}}
   ```
   `ci` es el intervalo de la diferencia pareada; `confidence` indica su nivel real (no se presupone 95 %). Si hay más de una partición, una fila por métrica y partición. El veredicto recibido se muestra literal.

3. **Aplicación de memoria.** El endpoint de decisión registra `applied_to_mando: false` según su implementación; el frontend informa que queda guardada sin aplicar. Para mostrar aplicación real, `/api/memoria/decide` debe devolver `{"ok":true,"id":"C-01","status":"approved","applied_to_mando":true}` solo cuando efectivamente llegue a la configuración. Conviene publicar también ese estado en `proposals[].decision` para conservarlo tras recargar.

4. **Variantes de lista fija.** `Duel` sigue construyendo `agent_kind="baseline"`; `/api/duel/session` ignora `baseline`. Solo se ofrece la lista original, con explicación visible. Para habilitar otras sin inventar nombres ni aceptación:
   ```json
   {"session":{"baseline":"baseline","baselines":[{"id":"baseline","label":"Lista fija original"},{"id":"ID_REAL","label":"Nombre real"}]}}
   ```
   `POST /api/duel/session` debe aceptar `{"case_id":"demo-gates","seed":7,"baseline":"ID_REAL"}` y el siguiente estado confirmar qué variante corre. El selector ya lee `session.baselines` (también admite `baselines` en la raíz).

5. **Series oficiales de decisiones no ensayables desde whatif.** Las tarjetas actuales no incluyen `card.series`; `whatif` solo admite desvío, cambio de acceso, parada y megafonía. Para otros tipos se muestran las consecuencias recibidas y se declara la ausencia de curvas. Forma preparada:
   ```json
   {"approvals":[{"id":"A-...","card":{"series":{"t":12,"minutes":15,"zones":{"gate_b":"Puerta B"},"mando":{"series":{"gate_b":[2.0,2.1]}},"alternative":{"series":{"gate_b":[1.9,1.8]}}}}}]}
   ```
   En una tarjeta, `mando` representa veto/mantener y `alternative` aprobación; cada serie debe tener las muestras correspondientes a `minutes`. No enviar densidades inventadas para una decisión sin efecto comparable.

`quick_replies`, `state.slots` como lista, `instruction.title/steps/metronome` y todas las claves de `state.links` ya se verificaron en el servidor actualizado: **no faltan**. Los enlaces de canales están a `null` cuando no se ha configurado el servicio; la UI lo muestra como no disponible.
