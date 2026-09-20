# Runbook del MVP operativo persistente

Este documento describe el recorrido **ResQval → MANDO SQLite → proveedores → MANDO**, no el reloj del simulador. Requisitos, variables y despliegue: [README.md](README.md). Guion: [PRESENTACION.md](PRESENTACION.md). Pendientes de aceptación: [PENDIENTE.md](PENDIENTE.md).

## Arranque y autoridad

- `./mvp.sh operational` exporta `MANDO_OPERATIONAL=1`, exige credencial de operador y deja `MANDO_EXTERNAL_DELIVERY=0` salvo configuración explícita. Lee el `.env` privado; revisar que no active entregas reales accidentalmente.
- `/`, `/sala` y `/interfaz` sirven la sala operativa de `motor/server/static/sala-operativa.html`, no el prototipo Next de `web/`. Autenticación en `/acceso`, cookie HttpOnly same-origin; con token configurado también se exige en loopback. `POST /salir` borra las cookies y redirige al acceso; no revoca una credencial copiada.
- `MANDO_OPERATIONAL_DB` selecciona la SQLite persistente (por defecto `motor/server/data/operations.sqlite`). Para ensayo, escoger una base nueva fuera del checkout; para alojamiento, una ruta en volumen, por ejemplo `/data/operations.sqlite`.
- Una sola instancia backend/worker escritor para este MVP. WAL ayuda a la concurrencia local; **no es alta disponibilidad entre máquinas**.
- Incidentes, actores, tareas, reservas, propuestas, aprobaciones, inbox, outbox y auditoría pertenecen a MANDO. El plano y las tarjetas son proyecciones, no almacenamientos alternativos.
- Este modo no crea automáticamente víctimas, aceptación, ETA ni desenlaces ficticios. La simulación de transporte significa que **no hubo comunicación externa**, no que un equipo haya aceptado.

La instalación limpia, aceptación en navegador y validación del despliegue son comprobaciones distintas del preflight sin red. Sus resultados finales deben corresponder al árbol que se vaya a presentar; ver [pendientes](PENDIENTE.md).

## Recorrido de una tarea

1. Registrar personal con roles autorizados (`organizador`, `medico`, `policia`, `bomberos`, `staff_entradas`) y canal. `web` permite registrar manualmente hechos del ensayo sin llamar. Para Telegram, el ID es `tg:<from.id>` y el contacto privado debe corresponder a esa persona, no a un chat de grupo.
2. Registrar el aviso. Si falta ubicación o aclaración, mantener el pendiente y pedirla; no despachar a una zona deducida sin confirmación ni confundir dos víctimas distintas. Una referencia ambigua no permite escoger arbitrariamente un incidente previo: aclarar identidad antes de actualizarlo.
3. Ofrecer tarea a un actor disponible con rol/capacidad adecuados. La oferta reserva capacidad antes de la aceptación.
4. Recibir aceptación o rechazo. Registrar únicamente lo realmente recibido. El rechazo es un imprevisto que obliga a revisar/replanificar; una reserva no se convierte en disponibilidad por un cambio visual.
5. Comunicar ETA con destino confirmado. Un destino incorrecto invalida la confirmación. ETA no significa llegada.
6. Confirmar llegada, localización cuando sea obligatoria y finalización, cada una por separado. Una revocación tardía se procesa según la versión vigente.
7. Si cambia un dato, corregir el incidente; reducir gravedad o necesidades exige rectificación confirmada por operador. Se cancelan ofertas que ya no hacen falta, pero se conserva al equipo activo hasta una transición autorizada. Al liberarlo se elimina la demanda retirada: no debe generarse otra oferta para esa necesidad. Revisar motivo, reservas y comunicaciones pendientes.
8. Para evacuar, parar espectáculo o solicitar ayuda externa, revisar propuesta vigente y aprobar/vetar con identidad humana autorizada. No puede aprobarse desde una herramienta del agente.
9. Cerrar solo cuando las necesidades y tareas lo permitan; conservar el rastro de decisión y entrega. No borrar la base para limpiar la pantalla.

## Contrato HTTP vigente

| Ruta | Contrato |
|---|---|
| `POST /salir` | Operador autenticado y validación de origen; elimina cookies y redirige a `/acceso` |
| `GET /api/operations/state` | Snapshot autenticado con revisión, hora del servidor, incidentes, actores, asignaciones, aprobaciones, entregas, workflows y eventos; sin contactos/transcripciones privados |
| `GET /api/operations/stream` | SSE con revisión y reconexión; recuperar snapshot tras desconexión |
| `POST /api/operations/command` | Cookie/token de operador, `command_id`, `kind` y campos; mutaciones de entidad con `expected_version` |
| `POST /api/operations/telegram` | Update original y `X-Mando-Bridge-Token` igual al secreto compartido |
| `POST /api/operations/happyrobot` | Espejo de solo lectura (`tg_incident`, `tg_assignment`, `tg_staff`) y `X-Mando-Bridge-Token`; no crea ofertas ni reserva capacidad |
| `POST /hr/events` | Resultado telefónico con `X-Mando-Token` **de esa entrega**, no el secreto raíz |
| `POST /hr/tools/{contexto,acciones_posibles,analizar_situacion,decidir,memoria/guardar,cambio}` | Capacidad vinculada a entrega; HappyRobot propone y MANDO valida |

Una clave `command_id` repetida con el mismo contenido recupera su resultado, no repite efectos. Reutilizarla con contenido diferente se rechaza. Un `expected_version` antiguo provoca conflicto: revisar el estado y generar una decisión nueva, no sobrescribir por fuerza.

Los updates de Telegram conservan `update_id` y se registran en SQLite antes de que el puente confirme recepción. Repetición idéntica es idempotente; reutilización con contenido distinto se rechaza.

### Quién decide a quién avisar

El ciudadano escribe al bot y el puente entrega el mismo aviso a MANDO (autoridad y
pantalla) y a HappyRobot (`fa-entrada-tg` / `fa-despacho-tg` / `fa-respuesta-tg`), que
decide el rol (médico, bomberos, policía, staff…), ofrece con botones aceptar/no
puedo, pide y devuelve la ETA, traslada las preguntas del equipo al informante y su
respuesta de vuelta, y cierra el incidente. Cada decisión se refleja en MANDO por
`POST /api/operations/happyrobot` y aparece en el snapshot como `telegram`: personal
disponible, asignaciones por Telegram (rol, alias, estado, ETA, desde dónde) y
preguntas. Es un espejo de **solo lectura**: no crea ofertas, no reserva capacidad ni
toca versiones de asignación.

La coordinación normal es de HappyRobot. Los botones de la Sala sobre una asignación
que HappyRobot ya decidió se presentan como **override** y exigen confirmación
explícita de que el operador anula esa decisión; sin decisión de HappyRobot, siguen
siendo la coordinación operativa normal. Los workflows Telegram/Redis no deben asignar
recursos por su cuenta: su efecto en MANDO es el espejo, no una segunda autoridad.

### Quién manda el mensaje

`MANDO_HAPPYROBOT_DECIDES=1` (por defecto): MANDO **no auto-oferta** los avisos que
entran por el bot. Deciden HappyRobot y su despacho; MANDO sólo espeja. Si el operador
hace override, MANDO registra el hecho y delega la coordinación en HappyRobot: lanza
`fa-despacho-tg` (`HR_WORKFLOW_TG_OFFER` con su slug/UUID) para que sea HappyRobot
quien ofrezca, recoja aceptación/ETA y traslade las preguntas del equipo al informante.
MANDO no redacta ni envía ese Telegram.

El espejo se compone en el workflow con el nodo Sandbox **`Espejo a MANDO`**
(`motor/happyrobot/sandbox/fa_espejo.py`): toma el `payload_json` ya construido y el
incidente (`inc_json`) y añade la lista `mirror`. Se regenera y despliega así:

```bash
cd motor/happyrobot/sandbox
python3 build_nodes.py --add fa_espejo <PID-nodo-padre> label="Espejo a MANDO" \
  PAYLOAD=<PID-del-sandbox-anterior> INC=<PID-de-Leer-incidente>   # → update_workflow_nodes action=add
```

Publicado en `development`: `fa-despacho-tg` v7 y `fa-respuesta-tg` v6 (cada una con su
nodo `Espejo a MANDO` y el `telegram_send` de coordinación apuntando a él).

### HappyRobot: correlación, no fe en la conversación

Configurar `HR_API_BASE`, `HR_API_KEY`, `HR_ENV` (por defecto `development`), `HR_SECRET`, `MANDO_PUBLIC_URL` HTTPS y:

- `HR_WORKFLOW_DISPATCH`: llamada saliente; además `MANDO_ALLOWED_NUMBERS` con destinos consentidos en formato internacional, separados por comas. Nunca números de emergencias.
- `HR_WORKFLOW_RAPIDO`: propuesta operativa. No habilitar el fork adaptado hasta cerrar los bloqueos de publicación descritos abajo; el ID del workflow no fija por sí solo versión ni entorno.

El lanzamiento API v2 manda `environment` y `payload`. La llamada lleva `callback_token`, `callback_url`, `action_id`, `assignment_id`, `expected_assignment_version`, `destination_zone_id` y `correlation_id`. El callback de llamada es `/hr/events`; las herramientas viven bajo `/hr/tools/`. Los nodos del workflow deben conservar la correlación y devolver la capacidad de su ejecución. **No basta copiar un UUID de un workflow antiguo.**

Ejemplo de resultado de contrato, no una llamada ejecutada (IDs ilustrativos):

```json
{
  "type": "dispatch_result",
  "action_id": "<delivery_id>",
  "call_id": "<stable_call_id>",
  "hr_run_id": "<provider_run_id>",
  "assignment_id": "<assignment_id>",
  "expected_assignment_version": 1,
  "sequence": 1,
  "result": "accept",
  "destination_confirmed": true,
  "destination_zone_id": "front_pit",
  "eta_min": 4
}
```

`call_id` puede diferir de `hr_run_id`, pero ambos se vinculan al lanzamiento. `sequence` ordena correcciones. Aceptar puede incorporar ETA, nunca llegada. `unclear`, `unknown`, `no_answer`, `timeout` y `provider_failed` no son equivalentes. `new_report: {id, text, zone}` permite otro aviso durante la llamada con ID estable, sin duplicarlo al terminar.

Las propuestas rápidas llevan fase, agente, correlación, incidente y justificación. Las decisiones graves requieren crítica/especialistas y aprobación humana vinculada a hash, versión y caducidad. Distinguir `aplicado`, `pendiente_persona` y error; una aprobación no demuestra ejecución física.

### Antecedente telefónico y harness de despacho

La evidencia histórica comunicada corresponde a **Telegram → Vercel → Railway → HappyRobot, N=1 llamada telefónica real de prueba**, `accept`, destino confirmado y ETA de **2 minutos**. Run `3a5abeb0-ff3b-463b-bbc6-b35210c22464`, despacho v8 (`01a0bc3c-2afb-7332-b874-dad3cb505d4e`), clúster EU y `HR_ENV=production`; callbacks de progreso/final aplicados en revisiones 15 y 16. No fue webcall ni `followup_question`, que pertenecían a otra fase. No se atribuye al SHA/árbol local actual ni demuestra llegada, negativos o adaptación completa.

El `test_all` anterior de despacho registró dos errores por `callback_url` vacío; el run real posterior sí completó callbacks. Son contextos distintos: el éxito posterior no arregla ni valida el harness. Revalidar sus entradas/correlación con transporte mock y callback completo; no ejecutar un `test_all` que incluya telefonía para resolver un fixture incompleto. No se ha repetido esa llamada ni cerrado ese gate con la evidencia del rápido.

### Estado del workflow rápido

| Elemento | Estado comprobado en la evidencia adjunta |
|---|---|
| Workflow | `01a0ba7a-62cb-74f4-acf7-7772dd1c410c` |
| v1 | `01a0ba7a-62d5-7dc8-8a14-b3be47d5f7e1`: publicada/live, `development` |
| Fork v2 | `01a0bd6a-3ff9-745d-b8d7-76f8281f5884`: **Published=false, Live=false**, 15 nodos |
| Entorno del fork | Metadata `production`; los tests de nodos se pidieron en `development`. No confundir metadata con activación |

El fork usa contrato operativo, validadores de entrada/propuesta/salida y consulta `cambio`; conserva seis papeles —triaje, prioridad, recursos, avisos, vigía y crítico— revisados por un agente, **no seis agentes independientes**. Se eliminó la invocación automática al equipo legacy. Las propuestas quedan `pendiente_persona`, `aplicado=false`; el modelo no puede inventar una aprobación backend.

Pruebas adjuntas: **SIMULACIÓN N=11 casos de nodos Python puros** y **SIMULACIÓN N=7 tests locales worker/mock + HTTP ASGI**, con resultados esperados. La repetición de la misma suite no suma cobertura. Los fixtures de crítica son sintéticos escritos a mano: prueban forma y rechazo, no calidad de razonamiento. No se ejecutaron el agente, trigger, `test_all`, HTTP remoto ni telefonía del fork.

**No publicar todavía:**

1. `POST decidir` no tiene variables inferidas y la salida referencia `response`; falta observar la respuesta HTTP real y validar ese enlace. No sustituirla por datos inventados del modelo.
2. Falta un backend candidato público aislado y validado; `candidate.invalid` es solo un fixture. No se ha probado el recorrido HappyRobot → backend actualizado → salida.
3. El diagnóstico de prompt no había iniciado la generación de issues. «No prompt issues found» en ese estado no es una validación completa.
4. Falta ejecutar el agente con crítica real, cambio relevante y nueva propuesta vigente; detectar/informar un cambio no demuestra por sí solo replanteamiento autónomo.
5. Repetir el contrato offline tras congelar backend y fijar explícitamente entorno/`HR_ENV` antes de una activación autorizada.

Conservar exportación saneada, DAG, resultados y guía del rápido como evidencia adjunta. Publicación y rollback no ejecutados. La v1 live no acredita compatibilidad con el contrato operativo nuevo y no debe usarse como fallback silencioso. Una futura reversión requiere detener lanzamientos y reconciliar entregas/aprobaciones; cambiar versión no deshace efectos externos.

## Entregas, fallos y recuperación

Cada efecto se registra en la outbox antes del intento externo. El worker reclama un lease y liquida el resultado. Con `MANDO_EXTERNAL_DELIVERY=0`, `DeliveryWorker(external=False)` registra transporte simulado: no hace HTTP al proveedor.

- Una respuesta perdida al lanzar una llamada queda incierta; no volver a llamar automáticamente ni interpretar lease vencido como «no se llamó».
- Telegram puede reintentar fallos transitorios; un mensaje puede duplicarse tras perder su respuesta. Eso no debe duplicar el efecto operativo del botón.
- La telefonía automática soporta ofertas de tarea; avisos de actualización/cancelación y otras finalidades no soportadas quedan `local_required`. **El operador debe comunicarlas manualmente** por un canal humano y registrar solo lo confirmado; aprobación o anotación local no significa aviso entregado. Un timeout de workflow no autoriza inventar respuesta ni destruye por sí solo el plan seguro previo.
- Cambiar disponibilidad o esperar a que venza una oferta no resuelve una entrega `uncertain`. Antes de otra llamada se exige comprobación humana y seguimiento explícito (`followup`, con versión y motivo); no es una rellamada automática ni un éxito retroactivo del envío incierto.
- El modo `simulation`, `real`, `mixed` o `unconfirmed` y el detalle de cada entrega deben acompañar la demo. «Configurado» no equivale a «llamada atendida».
- Ante 401/403 revisar sesión, rol, origen y secretos; ante 409 recargar y revisar. Un error de persistencia impide considerar aplicado el comando. No saltar controles para despejar la UI.

## Backup, restauración y rollback

La base, WAL, copias y logs pueden contener contactos o información sensible. Guardar backups fuera del checkout, con permisos restrictivos y almacenamiento cifrado administrado. Definir retención y responsables antes de uso real. **No copiar solo el archivo `.sqlite` mientras está abierto con WAL.**

### Copia consistente con SQLite

Procedimiento de administración local, **no ejecutado contra datos de producción**. Crear previamente un directorio privado de destino; sustituir rutas por las reales sin publicar su contenido. El destino debe ser nuevo:

```sh
BACKUP_SOURCE=/data/operations.sqlite \
BACKUP_DEST=/ruta-privada/operations-backup.sqlite \
uv run --project motor/server python - <<'PY'
from contextlib import closing
from pathlib import Path
import os
import sqlite3

source = Path(os.environ["BACKUP_SOURCE"]).resolve(strict=True)
destination = Path(os.environ["BACKUP_DEST"]).resolve()
if source == destination or destination.exists():
    raise SystemExit("El destino debe ser nuevo y distinto del origen")
fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
os.close(fd)
with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as src:
    with closing(sqlite3.connect(destination)) as dst:
        src.backup(dst)
        if dst.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise SystemExit("Copia no válida: no utilizar para restauración")
print("Backup consistente e integridad SQLite verificada; no imprime datos")
PY
```

Conservar junto a la copia la revisión del código y la configuración requerida (sin secretos en documentación pública). La integridad SQLite verifica estructura, no que cada decisión humana fuese correcta.

### Ensayo de restauración

1. Usar el mismo procedimiento para copiar **el backup** a otra ruta nueva; no abrir el respaldo maestro como base activa ni sobrescribir producción.
2. Quitar credenciales de proveedores y fijar `MANDO_EXTERNAL_DELIVERY=0`. Abrir la copia con la revisión compatible del servicio; una apertura con proveedores activos podría consumir outbox pendiente.
3. Verificar snapshot, incidentes, reservas, aprobaciones, eventos y estados inciertos. Comparar con el inventario esperado del backup y revisar integridad.
4. Para puesta en servicio real, detener entradas y worker antiguos, conservar el conjunto anterior de SQLite/WAL/SHM y cambiar a un destino verificado. No mezclar el WAL de una base anterior con la restaurada. Reconciliar qué efectos externos pudieron ocurrir después de la copia.
5. Solo el responsable puede reactivar proveedores, tras revisar entregas pendientes/inciertas y comunicar la ventana de pérdida potencial. La restauración no revierte llamadas o mensajes ya enviados.

### Rollback de versión

Congelar entradas/entregas; tomar backup consistente; identificar la revisión/imagen anterior y su compatibilidad con el esquema; ensayar esa revisión contra una copia **sin red**. Revertir versión en el alojamiento únicamente con autorización. Si exige volver a una copia anterior de datos, contabilizar los eventos posteriores y efectos externos: no existe rollback transaccional entre SQLite y un teléfono. Mantener una sola instancia consumiendo la outbox. El rollback del despliegue sigue pendiente de ensayo; no se acredita con una reapertura local de SQLite.

## Evidencia y puertas de aceptación

Comando de ensayo sin red, desde la raíz y con un directorio nuevo:

```sh
./mvp.sh preflight --seed 1701 --output /tmp/resqval-operativo-nuevo
```

El preflight genera `preflight.json`, `demo.json`, `demo-trace.json` y escenarios aislados. Comprueba rechazo sintético y alternativa, deduplicación, aprobación, etapas y persistencia tras reapertura. Leer su resultado real, N, semilla y fingerprint antes de presentarlo; no anticipar `ok=True`.

`./mvp.sh check` añade suites core/server y corpus sintético aislado. Los recuentos finales de suites/preflight y la prueba de backup/restauración deben incorporarse con su revisión y códigos de salida; permanecen pendientes de consolidación. Ningún recuento de otra fase certifica el árbol actual. La evidencia parcial del rápido está delimitada arriba.

La demo conectada requiere bot/chat autorizado, workflow compatible publicado, HTTPS, whitelist y evidencia saneada de run/callback sobre la candidata elegida. Mantener separados el antecedente telefónico histórico, las simulaciones de contrato y una futura validación conectada. Consultar [PENDIENTE.md](PENDIENTE.md) antes de declarar lista la entrega.
