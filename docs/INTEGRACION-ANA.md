# HappyRobot en la Sala Python de Ana

## Circuito implementado

```text
Sala → Equipo → Probar HappyRobot
    → POST /api/workflows/rapido (operador)
    → aviso en MANDO → incidente → prueba-ana-rapido
    → POST /hr/tools/decidir (fase rapida)
    → grafo HappyRobot: prueba-ana-equipo / especialistas
    → POST /hr/tools/decidir (fase revision)
    → Equipo / Enjambre / Recursos / Comunicaciones

Telegram → puente → fa-entrada-tg
    → callback agent_reply al puente → public_report a MANDO
    → siguiente tick del recinto → mismo circuito rápido
```

Se usa `MANDO_CEREBRO=agente`. El backend lanza **un run rápido por incidente**;
la revisión y los especialistas los coordina el grafo de HappyRobot. No combinar
este circuito con un segundo lanzamiento del rápido desde `fa-entrada-tg`.
El modo `abanico` sigue siendo la alternativa que lanza especialistas directamente
desde MANDO; no dispara además el rápido.

La configuración es opt-in. Sin `HR_WORKFLOW_RAPIDO`, los avisos no lanzan runs.
El botón consulta el diagnóstico de `workflow_rapido` en `/api/state` y permanece
deshabilitado si faltan valores. «Configurado» no acredita que la versión esté
publicada ni que HappyRobot pueda alcanzar el callback.

## Preparar development

Usar el `.env` local ignorado por Git o los secretos del despliegue:

```dotenv
MANDO_CEREBRO=agente
HR_WORKFLOW_RAPIDO=<ID de prueba-ana-rapido>
HR_API_BASE=https://platform.eu.happyrobot.ai/api/v2
HR_ENV=development
HR_API_KEY=<clave de la API EU>
HR_SECRET=<secreto compartido de callbacks>
MANDO_PUBLIC_URL=https://<host-publico-del-backend>
MANDO_OPERATOR_TOKEN=<token de operador>
MANDO_CEREBRO_TIMEOUT_S=90
TELEGRAM_MODE=off
MANDO_LLM=0
```

No escribir secretos en archivos versionados, mensajes ni capturas. El navegador
no recibe la API key ni el token de callback.

Antes de ejecutar, comprobar en HappyRobot la **versión publicada en development**
de `prueba-ana-rapido` y de cada workflow al que llama. No se modifican ni publican
workflows desde la Sala. El ID debe corresponder al workflow, no a un run ni a un
nodo. Cambiar `HR_ENV` solo tras verificar qué versión está publicada allí.

Arrancar con `./mvp.sh local`, que lee `.env` y usa comunicaciones simuladas,
y entrar en `/acceso` para iniciar sesión de operador. Con URL pública, incluso
el navegador local necesita esta autenticación. Mantener la API de MANDO
accesible desde HappyRobot durante el run.

### Callback de agentes

`callback_url` es la **URL base**, por ejemplo `https://mando.example`.
Los nodos HTTP del workflow añaden `/hr/tools/analizar_situacion`,
`/hr/tools/acciones_posibles`, `/hr/tools/decidir`, etc. No introducir
`/hr/events` ni `/hr/tools/decidir` en `MANDO_PUBLIC_URL`.

Todos esos nodos envían `X-Mando-Token: <callback_token>`. Las herramientas,
incluidos votos, memoria y revisiones, conservan sus contratos y validaciones.

El run recibe los campos de entrada de `prueba-ana-rapido`:

- `entrada_json`: texto, canal, zona sugerida, idioma, alias del informante,
  `incident_id`, `correlation_id` y marca temporal del aviso.
- `texto`, `canal`, `zona_sugerida`, `idioma`, `remitente`, `correlation_id`:
  también disponibles como campos individuales.
- `callback_url` y `callback_token`: solo del lado servidor.

El agente debe devolver el `incident_id` confirmado y conservar `correlation_id`.
Las correlaciones que crea esta integración contienen la sesión y el aviso.
MANDO rechaza una correlación de otra sesión o vinculada a otro incidente;
si el agente devuelve `incident_id: "nuevo"` con una correlación conocida,
se utiliza el incidente ya creado. Esto evita duplicarlo. Al reiniciar la
simulación, los callbacks antiguos que conserven la correlación se rechazan.
No se cancela el run remoto al reiniciar.

### Probar desde la Sala

1. Abrir **Equipo → Probar HappyRobot**.
2. Introducir un aviso y una zona, por ejemplo «Hay una pelea en la puerta B».
3. Pulsar **Lanzar en HappyRobot**. Esto ejecuta un workflow real, aunque el
   recinto y las comunicaciones de MANDO estén simulados.
4. El endpoint registra el aviso y avanza dos minutos simulados para entregarlo
   al agente del recinto. Cada prueba representa **N = 1 aviso simulado**.
5. Seguir el ID del run y seleccionar el incidente para ver la decisión,
   bloqueos, aprobaciones y revisión en los paneles existentes.

Repetir la petición con el mismo `request_id` y contenido devuelve el aviso
original. Otro contenido con esa clave devuelve 409. Un aviso fusionado con
un incidente que ya tuvo run no lanza otro; un mensaje «todo en orden» que no
abra incidente tampoco. La Sala informa cuando no se inicia un nuevo run.

Hay como máximo tres runs en curso y cien runs por sesión. La Sala muestra los
últimos veinte. El seguimiento vive en la sesión; las decisiones y efectos
siguen usando la persistencia y el ledger existentes. Reiniciar borra ese
seguimiento y las claves de reintento.

Un run `succeeded` **no** se muestra como decisión aplicada si no llegó la
herramienta de vuelta. Se muestra «esperando decisión» hasta el timeout.
Una decisión recibida puede contener acciones bloqueadas o pendientes de
aprobación; consultar siempre la ficha del incidente.

El timeout y las barandillas usan `MANDO_CEREBRO_TIMEOUT_S`: 90 segundos por
defecto con el rápido configurado, 8 sin él. Un fallo de red no reintenta el
POST de lanzamiento, porque la plataforma pudo haberlo aceptado. MANDO
conserva su fallback local/reglas en los siguientes ticks; con el reloj
pausado hay que reanudarlo o avanzar un paso. Riesgo vital y aprobación humana
siguen bajo control de MANDO.

## Entrada y despacho Telegram

En el puente, configurar `HR_HOOK_TG` con el trigger de `fa-entrada-tg`,
`MANDO_BACKEND_URL` con la base de MANDO y el mismo `HR_SECRET`.
Conservar el circuito ya existente:

- HappyRobot → puente: `POST /hr/events`, cabecera `x-hr-secret`, cuerpo
  `HrToMando` con `event: "agent_reply"`, `correlation_id`, `channel: "telegram"`,
  `chat_id`, `reply_text` y `report`/`extract`.
- Puente → MANDO: `POST /hr/events`, cabecera `X-Mando-Token`, evento
  `mando.hr.v1` / `public_report`. El `event_id` deduplica el aviso.
- `fa-rol-tg`, `fa-despacho-tg` y `fa-respuesta-tg` usan las rutas de roster,
  despacho y respuesta ya existentes. Sus eventos `tg_*` alimentan
  Comunicaciones, Recursos y el historial.

Para los avisos que llegan de Telegram, el reloj debe estar en marcha o
avanzarse manualmente: el callback solo registra el aviso. La Sala de pruebas
avanza los dos pasos explícitamente.

Ver [Espejo Telegram](../motor/server/ESPEJO-TELEGRAM.md) para el esquema de
`tg_incident`, `tg_assignment`, `tg_staff` y aprobaciones. MANDO no lanza
workflows de despacho Telegram directamente desde este formulario.

`TELEGRAM_MODE=off` apaga el bot de Python; **no** apaga el puente ni los envíos
que un workflow HappyRobot haga por su cuenta. En las pruebas locales se
simula el HTTP, sin ejecutar workflows ni enviar Telegram. Para la prueba
real, usar los workflows y chats de prueba del entorno elegido.

## mando-despacho-telefono

Se conserva el adaptador y la whitelist existentes. Para una prueba de voz
posterior, configurar `HR_WORKFLOW_DISPATCH` con este workflow,
`HR_LAUNCH_MODE=runs`, `MANDO_VOICE_MODE=phone`, contactos locales y
`MANDO_ALLOWED_NUMBERS`. Mantener el arranque `./mvp.sh local` hasta esa prueba;
`./mvp.sh real` activa `--comms happyrobot` y las comunicaciones reales.

El payload telefónico sigue siendo exactamente:
`action_id`, `to_number`, `role`, `order_text`, `zone_spoken`, `priority`,
`callback_url`, `callback_token`.

En teléfono, a diferencia de las tools de agentes, `callback_url` es la
**ruta completa** `MANDO_PUBLIC_URL + /hr/events`; la construye MANDO.
El workflow devuelve `dispatch_progress` y `dispatch_result` con
`schema: "mando.hr.v1"` y un `event_id` único. Nunca introducir una URL vacía
en un lanzamiento manual. La Sala conserva el seguimiento por acción y
las aprobaciones; no marca emergencias ni números fuera de la whitelist.

## Verificación local

```sh
uv run --frozen --project motor/server python -m unittest \
  motor.server.test_rapido motor.server.test_dos_velocidades \
  motor.server.test_cerebro_tools motor.server.test_equipo_agentes \
  motor.server.test_sala
node --check motor/server/static/sala.js
```

`test_rapido` sustituye todo el HTTP saliente por `httpx.MockTransport`.
Comprueba el lanzamiento, callbacks, revisión, Telegram, reintentos,
correlación, reset, fallos, timeout y ausencia de secretos en el estado.
Estas pruebas no verifican la publicación del grafo, sus razonamientos,
la conectividad del túnel ni una llamada o mensaje real.
