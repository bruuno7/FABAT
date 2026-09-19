# PENDIENTE — servidor, corte del 19-sep tras revisión Codex

## Actualización B + C, 19-sep 10:11

Integración por configuración y presentación implementadas: `hr_config.py`, adaptador de comunicaciones,
ingesta/chat, Telegram `poll|send_only|off`, doctor fusionado con Aibo, estado por workflow y enlaces públicos.
`./mvp.sh demo` prepara el caso; R limpia sesiones/llamadas locales/presupuesto y K recupera minuto 7 simulado.
`security.py` exige operador con URL pública y limita avisos por IP/tamaño. `ensayo.py` comprueba siete hitos.
Guías: `CONEXION-HAPPYROBOT.md` y `PRESENTACION-SEGURA.md`. También hay cambios localizados en HTML/JS del mando/asistente.

Verificación posterior a este corte histórico: servidor `Ran 138 tests in 59.717s` / `OK`;
núcleo solicitado `Ran 83 tests in 0.689s` / `OK`; sintaxis de shell y JS correcta.
Tres ejecuciones consecutivas de ensayo demo-1 idénticas: 7/7 hitos, N=1 por ejecución, críticos fallidos 1/2.
Solo mocks: pendientes publicación/audio/Telegram reales y revisión visual (navegador denegado por permisos).
Parte A (`/gemelo`, pronóstico visible y accuracy) no realizada, conforme al orden de prioridad.
Lo siguiente conserva el corte anterior como contexto; sus cifras y afirmación de no tocar frontend son históricas.

Este corte sustituye el estado anterior de fase 3. Trabajo limitado al servidor y al reenganche H8 en
`motor/caos/chaos.py`. No se ha ejecutado git, ni hackspain, ni publicado nada, ni abierto túneles.
No se han editado los HTML/JS/CSS: otro proceso está trabajando sobre ellos.

## Hecho y comprobado

| Id / tarea | Resultado |
|---|---|
| H1 | `validation.strike_effect` valida todos los tipos de efecto admitidos antes de inyectar: campos, ids, finitud, rangos y booleanos. El reloj captura excepciones, publica `engine_error` y sigue vivo; un fallo del mundo pausa la simulación. Los errores del agente también quedan visibles, sin volcar el texto de la excepción. |
| H2 | Clasificación provisional reservada al recibir un aviso, antes del primer tick; se actualiza si el final lo marca sensible y se propaga a las actualizaciones del aviso. Proyección común en `privacy.py` para estado/SSE, log, llamadas, recursos referenciados, informe y golpes. Teléfonos y claves de contacto ocultos; los avisos en modo prueba no vuelcan texto. |
| H3 | `ok`, `approve`, `autoplay` y `takeover` son booleanos estrictos en HTTP; cadenas/números → 422. Una aprobación no aceptada por Mando no se audita como aprobada. |
| H4 | Validación antes de consumir `event_id` y cerrar `_inflight`, incluidos los campos internos de `data` de una aclaración y los `needs` trasladados desde el primer nivel. Un payload corregido puede reutilizar el id del rechazado. |
| H5 | Un solo cierre de vuelo, con `_closed` y la identidad del vuelo comprobados bajo cerrojo, también frente a `sweep`. El final de una confirmación provisional aún puede corregirla una vez. |
| H6 | Ids de sesión y nonce distintos; registros de ids emitidos y runs. Un callback de plataforma sin run exige el nonce emitido; un run nuevo con id interno desnudo se descarta. MCP utiliza el mismo id emitido al confirmar. |
| H7 | Webhooks y confirmaciones MCP reconstruyen estado y suben versión en pausa. El reloj detecta también revisiones del adaptador. |
| H8 | El clon usado por Caos reengancha `rehearsal.twin` al mundo que está ensayando. |
| App: preguntas | `sitrep`, preguntas a recursos y a responsables no llegan al informante. Web/chat/Telegram esperan a la persona hasta `MANDO_ASK_WAIT_S`; no responden por ella ni expiran el HOLD por minutos acelerados. |
| App: conversación | `motor.intake.IntakeSession` real, una por conversación con id único y reinicio al cambiar partida. `quick_replies`, `state.slots` como lista, `instruction` estructurada con metrónomo; acepta `source`, `preset`, `client_id`; conversación es/en. Degradación explícita si falta o falla el paquete. |
| Golpes | Tres por `client_id`, además del tope global de tres. `strike.id`, `broken[]`, `new_plans[]`, `locked_test` en estado y seguimiento. |
| Duelo | `BaselineReroute` por defecto; `?baseline=fixed` para la lista sin desvío. Cifras y zona de pico por lado, desvíos y `n: 1` para rótulos veraces. |
| Memoria | Observaciones reales, propuestas y comparación de `latest/day2.json` o `out/day2.json`, con N/intervalos/huella. Aprobar/rechazar usa la API de tuning y escribe parámetros locales que carga la siguiente sesión. |

El README de `motor/intake` apareció durante el trabajo: se ha leído y la integración se ha probado contra el paquete real,
además de los dobles de las pruebas antiguas. No se ha modificado ese paquete ni su fichero de protocolos.

## Verificación

Cada arreglo tiene una regresión reproducida antes de su corrección. Los fixtures antiguos de callbacks ahora registran
los runs lanzados; el circuito Telegram antiguo fuerza la degradación y las pruebas nuevas cubren el IntakeSession real.
No se han quitado tests: 39 originales y 37 regresiones nuevas. Los mocks usan HTTP local en 127.0.0.1; no son llamadas reales ni evidencia de latencia de campo.

```sh
UV_CACHE_DIR=/private/tmp/codex-uv-cache uv run --project motor/server python -m unittest discover -s motor/server -p "test_*.py" -t .
# Ran 76 tests in 35.961s
# OK
python3 -m unittest motor.world.test_world motor.cases.test_cases motor.mando.test_mando motor.harness.test_harness motor.baseline.test_baseline
```

Las ejecuciones se hicieron con `PYTHONDONTWRITEBYTECODE=1`. Hay avisos de deprecación de Starlette/httpx y del cliente
MCP; no son fallos de pruebas. Núcleo: `Ran 145 tests in 17.386s` / `OK`.

## Lo que queda para la entrega

1. **Integración visual, por el otro proceso**: probar `/asistente` contra el IntakeSession real; pintar las respuestas,
   slots, instrucciones y consecuencias del golpe desde los campos nuevos. Actualizar los rótulos de `/duelo` usando
   `session.baseline`, `left/right.kind`, `peak_zone_name`, `reroutes`, `score` y `n`, sin dar por supuesto ganador ni puerta.
2. **Recorrido manual y móvil real**: conversación → pregunta real → respuesta → cambio de estado, cambio de idioma,
   pérdida/reconexión de SSE, golpe que rompe un supuesto y golpe que queda bloqueado como test. No se ha validado UI,
   micrófono, accesibilidad, instalación ni audio desde un teléfono.
3. **Plataforma y Telegram reales**: no se han usado tokens ni hecho llamadas reales. Faltan la comprobación humana de
   workflows publicados, audio Web call, confirmación final, Signals y bot real. La configuración sigue documentada en
   `WEBHOOKS.md` y `motor/happyrobot/PLATAFORMA_REAL.md`; este trabajo no los publica ni abre conectividad externa.
4. **Idiomas del estado global**: `/api/chat` habla es/en, pero `label`, `explain`, `plan.why` y megafonía del motor en
   `/api/state` siguen en su idioma original. No existe traducción completa del estado de la sala.
5. **Límites que deben quedar rotulados**: consecuencias del golpe = atribución temporal (6 minutos y hasta el siguiente),
   no causal; `client_id` autodeclarado no autentica a una persona; cifras del duelo = simulación, N=1 por lado. La tabla
   de memoria es la evaluación histórica del fichero, no una evaluación nueva tras pulsar aprobar.
6. **Revalidar si cambian otros módulos durante la entrega**: intake/protocolos y frontend se estaban editando en paralelo.
   Este corte comprueba la API observada; no modifica sus reglas de clasificación ni los límites clínicos descritos en su README.

## Contratos que conviene conservar

- Un único camino de avisos: `submit_report` → `Session.report`; `update_of` comparte incidente verdadero.
- Las preguntas libres vuelven a Mando con `data` vacío, para que su parser lea el texto. No inventar datos al agotar plazo.
- Los callbacks válidos se correlacionan antes de consumir su id. Copiar el `action_id` recibido por el workflow, incluido
  el nonce; un `A-0001` de otra partida no acredita un run nuevo.
- `motor/mando/params.approved.json` sigue siendo de Mando y solo se lee. La API de tuning escribe en
  `motor/server/params.approved.local.json`; las decisiones se auditan en `memoria.decisions.local.json`. No versionar esos
  datos de ejecución. Reiniciar la sesión para aplicar cambios; sin API, comprobar `applied_to_mando: false`.
- La privacidad se aplica en el servidor antes de serializar: ningún consumidor debe recuperar datos reservados de los
  objetos internos. `engine_error` comunica tipo/origen/minuto, sin texto bruto que pueda contener un aviso.
