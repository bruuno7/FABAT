# Personal de campo — especificación lista para montar, NO desplegada

Verificado en código local: `motor/server/personal.py`, `team_routes.py`, `mock_staff.py`.
No se ha accedido a la plataforma ni probado una llamada real. Canales y nodos se basan en el contrato existente de `PLATAFORMA_REAL.md` y `DOCS_CONFIRMADO.md`.

## Identidad y entrada

Centro → «Enlaces del personal» → unidad y cargo → enlace `/personal#token=…` y QR.
El HMAC liga unidad, cargo y escena; el servidor lo comprueba y caduca al terminar/reiniciar.
El fragmento se guarda en sessionStorage y se elimina de la barra. Las peticiones usan X-Mando-Unit.
No se muestran teléfonos. No basta decir un id de unidad en voz alta para acreditarlo.

Workflow propuesto: llamada entrante o Web call del personal → verificar identidad de unidad → agente de radio → AI Extract → Webhook POST /hr/events.
Para Web call, el lanzador autenticado debe introducir `unit_token` en los datos privados del trigger, junto a `unit_id`; nunca lo extrae el modelo ni lo dicta la persona.
Para llamada entrante, resolver la identidad con la lista privada de contactos y obtener un enlace/token desde el backend autorizado; si no puede acreditarse, registrar aviso público sin privilegios y pedir validación al centro. `/hr/identify` por sí solo no emite tokens de personal.
Para texto: `/personal` envía el mismo parte directamente; un trigger de texto autenticado puede usar este mismo Webhook. El token público HR_CHAT_TOKEN NO autoriza staff_status ni external_notice.

## Prompt corto del agente

«Eres la radio del centro. Confirma la unidad acreditada por el sistema y pide un parte breve: estado, zona y si necesita apoyo. Si dice otra unidad, no la suplantes: pide reconexión con su enlace. Repite una frase con lo entendido, envía el parte inmediatamente y termina. No retrases una actuación ni des instrucciones clínicas. No prometas recursos ni tiempos. Si informa de otra incidencia, recoge su texto y márcalo new_notice. No solicites ni pronuncies teléfonos o tokens. Si falta la zona de una ruta bloqueada, pregunta solo la zona. Confirma “Parte recibido” únicamente si el webhook devuelve ok; si falla, dilo y pide comunicarlo al centro por la radio habitual.»

## AI Extract y Webhook exacto

Campos: `unit_id` (debe coincidir con la identidad acreditada), `status`, `zone`, `needs_support` (booleano JSON), `free_text` (máx. 400).
Estados: en_route, on_scene, stabilized, transport, needs_support, route_blocked, exhausted, free, note, new_notice, false_alarm.
Zona: id del recinto; route_blocked la exige. La respuesta del equipo solo puede referirse a su incidente asignado; para algo distinto usar new_notice.

POST a `$MANDO_PUBLIC_URL/hr/events`; `Content-Type: application/json`; `X-Mando-Token: $HR_SECRET`.
Sustituir con el serializador JSON del workflow, no concatenar texto sin escapar:

```json
{
  "schema": "mando.hr.v1",
  "type": "staff_status",
  "event_id": "run-demo-staff-001-parte-1",
  "hr_run_id": "run-demo-staff-001",
  "unit_id": "amb_1",
  "unit_token": "<token privado del trigger firmado por el servidor>",
  "status": "route_blocked",
  "zone": "corridor_s",
  "needs_support": true,
  "free_text": "Pasillo bloqueado por la multitud",
  "channel": "voice"
}
```

Respuesta: `{ok:true, report_id, status, duplicate:false, say_text:"Parte recibido por el centro de control."}`.
Reintento mismo event_id/unidad: duplicate:true, sin repetir efectos. Datos inválidos: 422 sin consumir el id.
Token de unidad inválido: 403; HR_SECRET incorrecto: 401. Ambos son necesarios. No se recupera JSON roto para partes privilegiados.
Report usa RADIO o VOICE con source exacto = unidad; el canal eleva la confianza frente al público.
Los partes operativos se guardan como Report y se vinculan a su incidente; Observation actualiza recursos y rutas. Confirmación/desmentido usa el procesamiento sitrep existente de Mando. Un aviso nuevo usa la fusión normal.

## Seis casos locales

1. med_1 / on_scene en general, enlace correcto: recurso ocupado, Report con source med_1, confirmación del incidente asignado y línea de log.
2. amb_1 / route_blocked en corridor_s: indisponible, zona bloqueada, supuesto roto y plan nuevo al siguiente tick si había plan dependiente.
3. med_2 / needs_support con needs_support:true: aumenta necesidad de ese tipo en su incidente y replanifica.
4. sec_1 / false_alarm: el procesamiento sitrep desmiente su incidente asignado; no modifica incidentes ajenos.
5. token caducado/otra unidad, HR_CHAT_TOKEN o needs_support:"false": 403/422, sin efectos ni consumo del event_id.
6. Reintento mismo event_id: una sola aplicación; free libera la unidad y new_notice entra como aviso nuevo que puede fusionarse.

Mock: POST `/mock/staff-status` con `{callback_url:"http://127.0.0.1:8000/hr/events",callback_token:"<HR_SECRET de prueba>",event:{...cuerpo anterior...}}` devuelve `{status,reply}`. Solo uso local; no hace llamadas de voz.
Servicios externos: `/mock/external-notice` usa el mismo envoltorio; event = `{type:"external_notice",event_id:"external-001",source:"112",text:"Información recibida por coordinación",zone:"gate_a"}`. Se registra como servicios externos, nunca ejecuta ayuda externa sin aprobación.
