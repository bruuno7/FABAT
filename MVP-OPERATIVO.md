# MVP multicanal persistente

## Arranque local

Python 3.12 o posterior, `uv` y Node 22 para el puente. Copiar `.env.example` a
`.env`, definir `MANDO_OPERATOR_TOKEN` y ejecutar `./mvp.sh operational`.
La raíz sirve la Sala operativa. El enlace «Iniciar sesión» permite introducir
el token y obtener una cookie HttpOnly. Sin token configurado el acceso se rechaza.

El modo operativo se activa con `MANDO_OPERATIONAL=1`; no avanza el reloj del
simulador ni crea víctimas, recursos o confirmaciones ficticias. El simulador
anterior sigue disponible arrancando sin esa variable.

El estado se guarda en `MANDO_OPERATIONAL_DB`, por defecto
`motor/server/data/operations.sqlite`. En Docker debe montarse un volumen
persistente en `/app/motor/server/data`. Mantener un único backend y su worker
en un disco local; SQLite WAL no es una solución de alta disponibilidad entre
máquinas. La base, WAL y copias contienen información privada: no subirlos al
repositorio. Para una copia consistente utilizar la API de backup de SQLite.

## Recorrido de demostración

1. Registrar desde la Sala un coordinador `organizador` y trabajadores disponibles
   con roles `medico`, `policia`, `bombero`, `tecnico` o `voluntario`.
2. Con canal `web` se puede probar el ciclo sin proveedores. Con Telegram,
   el identificador debe ser `tg:<from.id>` y el contacto el mismo `from.id`
   numérico privado; un chat de grupo no identifica a un trabajador.
3. Registrar avisos distintos de calor, desmayo y aglomeración. Un aviso sin zona
   permanece pendiente de ubicación; no recibe un destino inventado.
4. Aceptar una asignación y confirmar su destino al comunicar ETA. Llegada,
   localización y finalización son transiciones diferentes y explícitas.
5. Abrir dos vistas: un botón revisado con una versión antigua devuelve conflicto
   y obliga a revisar de nuevo. La Sala no repite comandos de resultado incierto.
6. Reiniciar el backend conservando la base. Los incidentes, reservas, decisiones,
   inbox y outbox permanecen; la Sala recupera el estado por SSE o polling.

## Telegram y HappyRobot

`MANDO_EXTERNAL_DELIVERY=0` registra envíos simulados, sin HTTP externo.
Para habilitar proveedores se necesitan `MANDO_EXTERNAL_DELIVERY=1` y:

| Canal | Configuración |
|---|---|
| Telegram backend | `TELEGRAM_BOT_TOKEN`, `MANDO_CONTROL_CHAT_ID` privado opcional |
| Puente Telegram | `MANDO_OPERATIONAL=1`, `TELEGRAM_MODE=webhook`, `MANDO_BACKEND_URL`, `MANDO_BRIDGE_SECRET`, `TELEGRAM_WEBHOOK_SECRET` |
| Backend del puente | El mismo `MANDO_BRIDGE_SECRET`, independiente del token de operador |
| HappyRobot | `HR_API_BASE`, `HR_API_KEY`, `HR_ENV`, `MANDO_PUBLIC_URL` HTTPS |
| Llamadas | `HR_WORKFLOW_DISPATCH`, `MANDO_ALLOWED_NUMBERS` con destinos autorizados |
| Propuestas | `HR_WORKFLOW_RAPIDO`, contrato de herramientas indicado abajo |

El webhook del puente conserva el update de Telegram y espera a que MANDO lo
registre en SQLite antes de responder. `update_id` repetido con el mismo
contenido es idempotente; otro contenido con el mismo ID se rechaza. El worker
recupera la inbox pendiente después de un reinicio.

Los workflows `-tg` históricos no deben ejecutar asignaciones paralelas al
modo operativo. Pueden aportar conversación mediante el contrato de MANDO;
Redis y el router anterior no son otra autoridad en este recorrido.

## Contrato HTTP y de workflows

- `GET /api/operations/state`: snapshot público operativo autenticado, revisión,
  hora del servidor, incidentes, actores, asignaciones, aprobaciones, entregas,
  workflows y eventos. Omite contactos y transcripciones.
- `GET /api/operations/stream`: SSE con revisión monotónica y reconexión.
- `POST /api/operations/command`: token/cookie de operador, `command_id`, `kind`
  y campos del comando. Los cambios sobre entidades requieren `expected_version`.
- `POST /api/operations/telegram`: update original y `X-Mando-Bridge-Token`.
- `POST /hr/events`: resultado de llamada con `X-Mando-Token` de la entrega.
- `POST /hr/tools/{contexto,acciones_posibles,analizar_situacion,decidir,memoria/guardar,cambio}`:
  token de la entrega; HappyRobot propone, MANDO valida y aplica.

El lanzamiento por API v2 envía `environment` y `payload`, con
`callback_token`, `callback_url`, `action_id`, `assignment_id`,
`expected_assignment_version`, `destination_zone_id` y `correlation_id`.
No basta con configurar el UUID de un workflow antiguo: sus nodos deben
conservar esos campos y devolver el token de esa ejecución.

Ejemplo de resultado (identificadores ilustrativos, sin datos reales):

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

`call_id` puede diferir de `hr_run_id`; ambos quedan vinculados al lanzamiento.
`sequence` aumenta para correcciones. Una aceptación explícita puede incorporar
ETA, pero no confirma llegada. `unclear`, `unknown`, `no_answer`, `timeout` y
`provider_failed` conservan significados distintos. Un destino incorrecto
invalida el ETA. `new_report: {id, text, zone}` permite comunicar otro incidente
durante la llamada; su ID estable evita duplicarlo en el callback final.

Una propuesta rápida lleva `fase: "rapida"`, `agente: "rapido"`,
`correlation_id`, `incident_id`, tipo, zona, prioridad y justificación.
Las acciones graves requieren crítica documentada, especialistas y aprobación
humana vinculada a versión/hash/plazo. La respuesta distingue `aplicado`,
`pendiente_persona` y error. No se puede aprobar desde una herramienta del agente.

Errores: 400 formato, 403 permisos, 409 versión/transición, 422 dominio y 503
dependencia/persistencia. Las rutas públicas limitan cuerpos a 8 KiB.

## Entregas y recuperación

Cada efecto se registra antes de contactar al proveedor. El worker reclama
leases y liquida resultados. Una respuesta perdida al lanzar una llamada queda
`uncertain`: no se vuelve a llamar automáticamente. Un lease telefónico vencido
tampoco acredita que la llamada no se realizara. Telegram reintenta errores
transitorios hasta tres intentos; pueden repetirse mensajes tras una respuesta
perdida, pero no el efecto operativo de un botón.

Las revisiones de la Sala no prueban entrega externa. El modo `simulation`,
`real`, `mixed` o `unconfirmed` y el estado de cada entrega muestran esa diferencia.
El timeout de un workflow conserva el plan seguro existente.

## Verificación reproducible

```sh
uv run --project motor/server python -m unittest motor.server.test_operational motor.server.test_operational_http -q
uv run --project motor/server python -m unittest discover -s motor/server -p 'test_*.py' -t .
node --test motor/server/test_sala_interface.cjs
uv run --project motor/server python -m motor.server.benchmark_operational --n 120 --seed 17 --workers 8
cd puente
npm ci
npm test
npm run typecheck
npm run build
```

El benchmark es **simulación**, N=120, semilla=17, 8 conexiones SQLite
independientes con WAL: cada informante envía un aviso y su duplicado. Mide
latencias y comprueba conservación después de reinicio y exclusividad.
No estima tiempos de llegada humanos ni latencias reales de HappyRobot.

La aceptación de proveedor exige un bot/chat de prueba, workflows publicados
compatibles y backend HTTPS accesible. Las pruebas locales con HTTP simulado
no certifican ese circuito ni llamadas entrantes; deben conservarse por separado
las ejecuciones reales y sus evidencias privadas.
