# Workflows de HappyRobot para Mando

Carpeta privada. Nada de esto se sube a ningún repo ni servicio externo. Este documento es la
especificación para montar los workflows a mano en `platform.eu.happyrobot.ai/hackspainteam6`.
El JSON exacto de cada mensaje está en `webhook_contract.json` (fuente de verdad: si este documento
y el contrato discrepan, manda el contrato). Los prompts están en `PROMPTS.md`, las reglas en
`NORTHSTARS.md`, las pruebas en `TESTS.md`.

## 0. Qué sabemos de la plataforma y con qué certeza

Etiquetas: **V** = leído en página pública de happyrobot.ai el 18-sep-2026 · **SV** = solo resumen de
buscador sobre `docs.happyrobot.ai` (la página real pide código) · **PLAT** = visto en nuestro
workspace (TRASPASO §3) · **POR CONFIRMAR EN LA PLATAFORMA** = no hay fuente; no darlo por hecho.

| Dato | Certeza | Fuente |
|---|---|---|
| `docs.happyrobot.ai` pide código de acceso («Access Restricted») en todas sus páginas | V | comprobado 18-sep, 4 URL |
| Cuatro tipos de nodo: **Action**, **Prompt**, **Condition**, **Tool**. «Tool nodes can only be added under a Prompt node» | V | tutorial del hub |
| Las variables de nodos anteriores se insertan escribiendo `@` en cualquier campo | V | tutorial del hub |
| Trigger webhook: panel «Event Setup» con *Params*, pestañas de entorno (Production, Staging, Development), «Enhanced Security» y *Schema* | V | tutorial del hub |
| El Prompt node tiene: modelo, **Initial Message**, Prompt, «Chat Playground» y un **MetaPrompter** | V | tutorial del hub |
| Existe un nodo agente «Outbound Text Agent» con canal Email, SMS o WhatsApp | V | tutorial del hub |
| Botón Play → «Trigger Staging Version»; pestaña Runs con estado, versión, entorno, transcripción y errores | V | tutorial del hub |
| Las versiones publicadas no se editan: se hace **Fork** | V + PLAT | tutorial, workspace |
| El LLM puede, durante la llamada, «make an API call, make a call transfer, send a message, or run some custom code» | V | blog técnico |
| Todo agente puede exponerse como flujo WebRTC; telefonía SIP, Twilio, Telnyx, Vonage | V | blog técnico |
| VAD entrenado para separar voz de ruido de fondo; detección de fin de turno; *keyword boosting*; precisión numérica | V | página Voice AI |
| «30+ languages» (la página de voz) frente a «50+» (lo anotado en TRASPASO §3) | V, contradictorio | preguntar |
| Northstars de cuatro categorías: Notes, Style, Tool, Sequential; se extraen del prompt; juez de IA; aprobado/suspenso | V | governance/northstars |
| Adversarial: se escribe un prompt adversario (persona, objetivos, estrategia), sesión aislada de dos agentes, auditoría contra cada northstar; suites con «generation prompt» y «generation count» | V | governance/adversarial-agents |
| Nodo «Outbound Voice Agent» con campo «To number»; nodos «AI > Classify» y «AI > Extract» tras la llamada; trigger en «Webhooks > Incoming hook» | SV | resumen de buscador de `docs…/examples/outbound-call` |
| «configurable voicemail handling, retry logic, business hours enforcement, callback detection» | SV | hub, comparativa con Retell |
| Triggers Incoming hook (GET/POST/PUT), Inbound to number, Inbound Text Message, Web call, Chatbot Request, Workflow Function Request; integraciones WhatsApp, SMS vía Twilio, Telnyx, MCP Server, Custom LLM Server, Google Sheets, Slack | PLAT | TRASPASO §3 |
| Latencia por turno en milisegundos | **POR CONFIRMAR** | no publican cifra |
| Nombre exacto del nodo de webhook saliente, si su URL admite variables, reintentos y timeout | **POR CONFIRMAR** | — |
| Si `@` resuelve rutas anidadas de un JSON (`@resource.name`) | **POR CONFIRMAR** | por eso las cargas van planas |
| Cómo detecta buzón de voz, tiempo de timbre, reintentos del nodo de voz, y qué variables de salida da (estado de la llamada, duración, transcripción) | **POR CONFIRMAR** | — |
| Si el agente puede cambiar de idioma a mitad de llamada | **POR CONFIRMAR** | — |
| Si «Web call» admite variables al iniciar la sesión | **POR CONFIRMAR** | — |
| Si una respuesta por SMS vuelve a la misma ejecución del Outbound Text Agent o entra por «Inbound Text Message» | **POR CONFIRMAR** | hay diseño para ambos casos |
| Números de teléfono, país, límites de llamadas y concurrencia, WhatsApp habilitado | **POR CONFIRMAR** | ver `SETUP_CHECKLIST.md` |

## 1. Principios de diseño (valen para todos los workflows)

1. **HappyRobot habla; el backend decide.** El backend compone el texto operativo exacto
   (`order_text`, `sms_text`, `question_text`, `parte_text`). El agente lo dice, confirma por
   repetición y recoge la respuesta. No prioriza, no asigna, no replanifica, no inventa.
2. **Conversaciones de cuatro turnos.** Despacho completo en menos de 30 s. El primer turno es el
   *Initial Message* (texto fijo con variables, sin pasar por el LLM si la plataforma lo permite): es
   la forma más barata de bajar la latencia percibida.
3. **Dos avisos por conversación.** Uno en caliente desde un **Tool node** en cuanto hay respuesta
   (`seq: 1`, `final: false`) y otro al terminar desde el nodo de webhook (`seq: 9`, `final: true`).
   Si la llamada se corta, el segundo llega igual con lo que haya. El backend deduplica por
   `event_id` y cierra la acción con el `final`.
4. **Nunca en el camino crítico.** Con `severity ≥ 8` el backend manda `max_attempts: 1`: un solo
   intento de voz de 25 s, SMS inmediato y `no_answer` al backend para que reasigne. No se espera a
   una segunda llamada para mover otro recurso.
5. **La voz se cae → SMS, y el caso no se pierde.** Dos turnos seguidos sin entenderse = «No te
   copio. Te lo mando por SMS. Corto.» y se sigue por texto con el mismo `action_id`.
6. **Los temporizadores viven en el backend.** HappyRobot no conoce `t`. El seguimiento (E) lo
   dispara el backend cuando toca; no se usan nodos de espera de la plataforma.
7. **Dos cerrojos para lo grave.** `request_external` solo sale del backend tras la aprobación humana
   y, además, el workflow D pregunta al backend (`/hr/approval_check`) antes de marcar. Evacuar y
   parar el concierto **no tienen workflow**: ningún agente de voz puede ejecutarlos.
8. **Lista blanca de teléfonos y números prohibidos.** El backend solo envía `to_number` que estén en
   `MANDO_ALLOWED_NUMBERS`. Cada workflow repite la comprobación de números de emergencia reales
   (112, 061, 091…) con un Condition node. **En el hackathon no se llama jamás a un servicio de
   emergencias real**: el «112» de la demo es un móvil del equipo o de un juez que lo ha consentido.
9. **El agente se identifica siempre como sistema automático.** Dos palabras: «sistema automático».
10. **Nombres neutros en la plataforma.** Los mentores ven el workspace. Workflows: `fa-despacho`,
    `fa-aclaracion`, `fa-entrada`, `fa-externo`, `fa-seguimiento`, `fa-webcall`, `fa-notifica`.
    («fa» = Festival Abierto.) El nombre que dice el agente es la variable `agent_name`
    (por defecto «Control»), no hace falta que diga «Mando».

Notación de los nodos: `[Trigger]`, `[Condition]`, `[Action]`, `[Prompt]`, `[Tool]` (dentro de un
Prompt), `[AI Extract]`, `[AI Classify]`. Las variables se escriben `@nombre`.

---

## A. Despacho por voz — `fa-despacho`

**Objetivo.** Dar una orden a un jefe de equipo en 15 s (qué, dónde, prioridad) y devolver al
backend una de cuatro salidas: ACEPTA (con ETA si la da), RECHAZA (con motivo), NO PUEDE OÍR (→ SMS)
o NO CONTESTA. Sirve también para `recall` (quitar un recurso de una tarea menor).

**Trigger.** Incoming hook, POST. Params = todos los campos de `dispatch_request`.

**Payload de entrada** (exacto, ver `webhook_contract.json › messages.dispatch_request`):

```json
{
  "schema": "mando.hr.v1", "message": "dispatch_request", "session_id": "demo-0919-01",
  "action_id": "a-0042", "kind": "dispatch", "t": 14, "autonomy": "auto",
  "callback_url": "https://ejemplo-tunel.trycloudflare.com", "mode": "live", "lang": "es",
  "to_number": "+34600000002", "resource_id": "med_2", "resource_kind": "medical",
  "resource_spoken": "Médico dos", "leader_name": "Lucía", "resource_zone_spoken": "puesto médico uno",
  "incident_id": "i-007", "incident_type": "unconscious_person", "incident_type_spoken": "persona inconsciente",
  "zone_id": "front_pit", "zone_spoken": "frente de escenario", "zone_detail": "lado izquierdo, junto a la valla",
  "severity": 9, "priority": 8.7, "priority_label": "roja",
  "order_text": "Persona inconsciente en frente de escenario, lado izquierdo. Prioridad roja. Acude ya con el desfibrilador.",
  "access_hint": "Entra por pasillo sur.",
  "sms_text": "MANDO a-0042: persona inconsciente en FRENTE DE ESCENARIO, lado izq. Prioridad ROJA. Responde 1 VOY o 2 NO PUEDO.",
  "recall_from_spoken": null, "max_attempts": 1, "ring_timeout_s": 25,
  "fallback_channel": "sms", "sms_reply_timeout_s": 90
}
```

**Nodos, en orden.**

1. `[Trigger]` Incoming hook.
2. `[Condition] numero_permitido`: `@to_number` no empieza por ninguno de los prohibidos y no está
   vacío. Rama NO → `[Action] webhook` con `dispatch_result {result: "no_answer", detail: "number_not_allowed", final: true}` y fin.
3. `[Action] webhook progreso` → `POST @callback_url/hr/events` con `progress {stage: "call_started"}`.
   (Opcional; quitarlo si añade más de 300 ms antes de marcar.)
4. `[Prompt] Outbound Voice Agent` — To number: `@to_number`. Voz en español de España. Initial
   Message y prompt: `PROMPTS.md › A`. *Keyword boosting* (si existe el campo): afirmativo, negativo,
   repite, corto, Alicante, Barcelona, Cádiz, pasillo, escenario, PMR, desfibrilador.
   Tiempo de timbre = `@ring_timeout_s`; detección de buzón activada → colgar sin dejar mensaje.
   Configuración exacta: POR CONFIRMAR EN LA PLATAFORMA.
   - `[Tool] registrar_respuesta` (dentro del Prompt). Descripción para el agente: «Llámala en
     cuanto la persona acepte o rechace, antes de despedirte. Llámala otra vez si cambia de
     opinión.» Argumentos: `result` (accept|reject), `eta_min` (entero o vacío), `reason_code`,
     `reason_text`, `new_info_text`, `heard_text`. Acción: `POST @callback_url/hr/events` con
     `dispatch_result {seq: 1, final: false, channel_used: "voice"}`.
   - `[Tool] pasar_a_sms`. Descripción: «Llámala si en dos turnos seguidos no entiendes a la persona
     o si dice que no te oye.» Sin argumentos. Marca la variable `cannot_hear = true` y termina la llamada.
5. `[AI Extract] resultado_llamada` sobre la transcripción. Variables extraídas:

   | Variable | Tipo | Regla |
   |---|---|---|
   | `outcome` | enum `accepted · rejected · changed_mind · cannot_hear · no_answer · voicemail · hung_up · wrong_person` | `changed_mind` si aceptó y luego se retractó en la misma llamada: **gana lo último que dijo** |
   | `eta_min` | entero o vacío | solo si la persona dijo un número **y** el agente lo repitió sin que lo corrigiera |
   | `reason_code` | enum de `catalogs.reason_code` o vacío | |
   | `reason_text` | texto corto | palabras de la persona |
   | `new_info_text` | texto o vacío | información nueva sobre el recinto (rutas cortadas, otra incidencia vista) |
   | `heard_text` | texto | la frase decisiva, literal |
   | `confirmed_by_repetition` | booleano | el agente repitió zona y decisión y la persona no corrigió |
   | `lang` | es/en/… | idioma en que acabó la conversación |

6. `[Condition] hay_que_pasar_a_texto`: `outcome ∈ {cannot_hear, no_answer, voicemail, hung_up}` **y**
   `@fallback_channel ≠ none`.
   - **Sí →** 7a. **No →** 8.
7. a. `[Action] webhook progreso` `progress {stage: "fallback_sent", channel_used: "sms"}`.
   b. `[Prompt] Outbound Text Agent` — Channel: SMS (o WhatsApp si `@fallback_channel = whatsapp`).
      Primer mensaje: `@sms_text`. Prompt: `PROMPTS.md › A-texto`. Espera respuesta hasta
      `@sms_reply_timeout_s`. Si la respuesta a un SMS no vuelve a esta ejecución sino que entra por
      «Inbound Text Message» (POR CONFIRMAR), este nodo solo **envía** y la respuesta la recoge el
      workflow C por la rama `staff_reply` (ver C, nodo 3).
   c. `[AI Extract] resultado_texto`: `outcome_text` ∈ `accepted_by_sms · rejected_by_sms · no_answer`,
      `eta_min`, `reason_text`.
8. `[Condition] max_attempts`: si `outcome = no_answer`, no hubo respuesta por texto y
   `@max_attempts = 2` → volver a 4 una sola vez. (Si la plataforma no permite bucles: duplicar el
   nodo 4 como «segundo intento». POR CONFIRMAR.)
9. `[Action] webhook final` → `POST @callback_url/hr/events`, cabecera `X-Mando-Token`.

**Payload de salida** (exacto; tres ejemplos en el contrato):

```json
{
  "schema": "mando.hr.v1", "message": "dispatch_result", "event_id": "@run_id-final",
  "session_id": "@session_id", "action_id": "@action_id", "t_sent": @t, "seq": 9, "final": true,
  "mode": "@mode", "hr_run_id": "@run_id",
  "result": "accept", "detail": "accepted",
  "text": "Afirmativo, vamos. Cuatro minutos.", "eta_min": 4,
  "reason_code": null, "reason_text": null, "new_info_text": null,
  "channel_used": "voice", "attempts": 1, "lang": "es",
  "confirmed_by_repetition": true, "call_duration_s": 23, "data": {}
}
```

Tabla de salida (`outcome` → lo que recibe el backend):

| Lo que pasó | `result` | `detail` | Qué hace el backend |
|---|---|---|---|
| ACEPTA por voz | `accept` | `accepted` | Action DONE · recurso EN_ROUTE con `eta_min` (si es `null`, la estima por zonas) · programa el seguimiento E |
| RECHAZA | `reject` | `rejected` | Action REJECTED · aplica `reason_code` (ver contrato) · `new_info_text` → Report nuevo · reasigna |
| Acepta y luego dice que no | `reject` | `changed_mind` | igual que rechazo; si ya había actuado con el aviso `seq: 1`, lo deshace |
| NO PUEDE OÍR → SMS → «1» | `accept` | `accepted_by_sms` | igual que ACEPTA, `channel_used: "sms"`. En pantalla: «voz caída → SMS» |
| NO PUEDE OÍR → SMS → «2» | `reject` | `rejected_by_sms` | reasigna |
| NO PUEDE OÍR → SMS sin respuesta | `no_answer` | `cannot_hear_sms_sent` | Action FAILED · reasigna · el SMS queda enviado por si contesta tarde (entra por C como `staff_reply`) |
| NO CONTESTA, buzón, cuelga | `no_answer` | `no_answer` · `voicemail` · `hung_up` | Action FAILED · reasigna · dos seguidos = `resource_no_answer` |
| Contesta otra persona | `no_answer` | `wrong_person` | Action FAILED · marca el contacto como dudoso |

**Reintentos y silencio.** Un intento de voz (`severity ≥ 8`) o dos (resto), 25 s de timbre, sin
mensaje en el buzón. Después, SMS de respaldo siempre. El backend no espera al SMS para reasignar
cuando la prioridad es roja: reasigna al recibir el `progress fallback_sent` si quiere, y cancela la
segunda orden si la primera persona acaba contestando «1» (regla del backend, no del workflow).

**Autonomía.** AUTO. Despachar y retirar un recurso no piden aprobación.

---

## B. Aclaración — `fa-aclaracion`

**Objetivo.** Conseguir **un** dato que falta de quien dio un aviso ambiguo: qué puerta, cuántas
personas, si responde, si respira con normalidad, si sigue ocurriendo.

**Trigger.** Incoming hook, POST. Payload: `clarify_request` (contrato).

```json
{
  "schema": "mando.hr.v1", "message": "clarify_request", "session_id": "demo-0919-01",
  "action_id": "a-0051", "kind": "ask", "t": 17, "autonomy": "auto",
  "callback_url": "https://ejemplo-tunel.trycloudflare.com", "mode": "live", "lang": "es",
  "to_number": "+34600000099", "channel": "whatsapp", "contact_role": "public", "contact_name": null,
  "report_id": "r-0029", "incident_id": "i-009",
  "context_text": "Hace dos minutos avisaste de mucha gente atascada en una puerta.",
  "question_key": "gate", "question_text": "¿En qué puerta estás?", "answer_type": "zone",
  "options_spoken": "A de Alicante, B de Barcelona o C de Cádiz", "max_attempts": 1, "reply_timeout_s": 120
}
```

**Nodos.**

1. `[Trigger]` Incoming hook.
2. `[Condition] numero_permitido` (igual que A).
3. `[Condition] canal`: `@channel = voice` → 4a; si no → 4b. **Regla del backend:** público = texto
   (en un concierto no oye una llamada); personal = voz.
4. a. `[Prompt] Outbound Voice Agent` con el prompt `PROMPTS.md › B-voz`.
   b. `[Prompt] Outbound Text Agent` (SMS o WhatsApp) con `PROMPTS.md › B-texto`.
   En ambos: `[Tool] registrar_dato` (argumentos `answer_text`, `answer_value`, `zone_id`) →
   `clarify_result {seq: 1, final: false}`.
5. `[AI Extract] dato`:

   | Variable | Tipo | Regla |
   |---|---|---|
   | `outcome` | `answered · does_not_know · refused · no_answer · hung_up · off_topic` | |
   | `answer_text` | texto literal | |
   | `answer_value` | según `@answer_type`: id de zona de `catalogs.zones`, entero, `yes/no/unknown`, texto | si la zona no casa con ningún alias → vacío, y `answer_text` lleva lo que dijo |
   | `zone_id` | id de zona o vacío | solo si se confirmó por repetición |
   | `confirmed_by_repetition` | booleano | |
   | `extra_info_text` | texto o vacío | lo que dijo sin preguntarle |

6. `[Condition]` si voz y `outcome ∈ {no_answer, hung_up}` → enviar la misma pregunta por SMS (nodo
   4b) una vez.
7. `[Action] webhook final` → `clarify_result`.

```json
{
  "schema": "mando.hr.v1", "message": "clarify_result", "event_id": "@run_id-final",
  "session_id": "@session_id", "action_id": "@action_id", "t_sent": @t, "seq": 9, "final": true,
  "mode": "@mode", "hr_run_id": "@run_id",
  "result": "answer", "detail": "answered", "text": "La B, la de Barcelona. Hay un torno roto.",
  "question_key": "gate", "answer_value": "gate_b", "zone_id": "gate_b",
  "confirmed_by_repetition": true, "extra_info_text": "Dice que hay un torno roto.",
  "channel_used": "whatsapp", "lang": "es"
}
```

**Reintentos y silencio.** Texto: un mensaje y un recordatorio a los 60 s («¿Sigues ahí? Solo
necesito saber: @question_text»); a los `@reply_timeout_s` → `no_answer`. Voz: un intento y paso a
SMS. **Mando no se queda esperando**: mientras la pregunta está en el aire, el backend trata el
incidente con `confidence` baja y, si la gravedad observada es `life_threat`, despacha igualmente a
la zona más probable.

**Autonomía.** AUTO.

---

## C. Entrada de avisos del público y del jurado — `fa-entrada`

**Objetivo.** Recibir avisos por SMS, WhatsApp y llamada entrante; acusar recibo; extraer
tipo, zona y gravedad observada; pedir la ubicación si falta; dar **una** instrucción de seguridad
de la lista aprobada; reenviar el aviso estructurado al backend. **Nunca diagnostica.** Es también
el enrutador de las respuestas por SMS del personal (si la plataforma no las devuelve a la
ejecución que envió el mensaje).

**Triggers.** Tres entradas con la misma lógica. Si la plataforma no permite varios triggers por
workflow (POR CONFIRMAR), son tres workflows que comparten prompt: `fa-entrada-voz` (Inbound to
number), `fa-entrada-sms` (Inbound Text Message), `fa-entrada-wa` (WhatsApp).

**Payload de entrada.** No lo envía nuestro backend: lo da el trigger (número de origen, texto).
Nombres de las variables del trigger: POR CONFIRMAR EN LA PLATAFORMA (aquí `@from_number`, `@text`).
Para fijar la zona sin preguntar, el QR de cada zona abre WhatsApp o SMS con un texto ya escrito:
`AVISO ZONA gate_b:` y el asistente completa la frase. El backend genera un QR por zona.

**Nodos.**

1. `[Trigger]` Inbound Text Message · WhatsApp · Inbound to number.
2. `[Action] webhook identificar` → `POST <base>/hr/identify` (la base aquí es **fija**, no hay
   `callback_url` porque la conversación no la inició el backend):

   ```json
   {"schema": "mando.hr.v1", "from_number": "@from_number", "channel": "sms", "first_text": "@text", "zone_qr": null}
   ```
   Respuesta: `route`, `role`, `resource_id`, `display_name`, `pending_action_id`, `pending_message`,
   `session_id`, `recent_reports`. Si el backend no contesta en 2 s: seguir como `public_report` con
   `role: unknown` (un aviso nunca se pierde porque el backend esté lento).
3. `[Condition] ruta`:
   - `staff_reply` → `[AI Extract]` sobre `@text` con el vocabulario del SMS de respaldo («1», «voy»,
     «2», «no puedo», un número = ETA; en seguimiento «1/2/3/4») → `[Action] webhook` con
     `dispatch_result` o `followup_result` de `@pending_action_id`, `final: true`. Fin.
   - `clarification_reply` → igual, con `clarify_result`. Fin.
   - `blocked` → respuesta fija «Este número no puede enviar avisos ahora. Si hay una emergencia,
     busca al personal con chaleco o llama al 112.» Fin. (Solo lo decide el backend, p. ej. tras
     20 avisos falsos; aun así el texto sigue reenviándose como `public_report` con `credibility: doubtful`.)
   - `public_report` o `staff_report` → 4.
4. `[Prompt]` agente de entrada: de voz si es llamada (`PROMPTS.md › C-voz`), de texto si es
   SMS/WhatsApp (`PROMPTS.md › C-texto`). Máximo 4 preguntas. Tools:
   - `[Tool] enviar_aviso` — «Llámala en cuanto sepas QUÉ pasa y DÓNDE, aunque falten datos. Llámala
     otra vez si consigues un dato nuevo.» → `POST <base>/hr/events` con `public_report
     {seq: 1.., final: false}`. La respuesta trae `ref_spoken` y, a veces, `say_text`: es lo **único**
     que el agente puede decir sobre el estado del aviso.
   - `[Tool] transferir_a_control` (solo voz, solo si `role = staff` o si quien llama está en peligro
     inmediato y pide una persona) → transferencia al teléfono del centro de control. Disponibilidad
     de la transferencia en el hackathon: POR CONFIRMAR.
5. `[AI Extract] aviso` → variables del objeto `extracted` del contrato: `family_hint`, `type_hint`,
   `severity_level` (`life_threat · urgent · minor · unknown`), `zone_id`, `zone_confirmed`,
   `zone_text`, `people_count`, `responds`, `breathing_normally`, `caller_is_affected`,
   `caller_in_danger`, `credibility`, `claims_authority`, `requested_action_text`,
   `injection_attempt`, `lang`, `instruction_given`, `complete`.
6. `[Action] webhook final` → `public_report {seq: 9, final: true}`.
7. `[Condition] instrucción pendiente`: si `severity_level = life_threat` y `instruction_given = none`
   (se cortó antes de darla) y hay `@from_number` → `[Action]` SMS con el texto exacto de la
   instrucción aprobada que corresponda (`not_responding` por defecto). Nunca texto generado.
8. (Opcional, 10 min) `[Action] Google Sheets › añadir fila` al «libro de incidencias»: hora,
   canal, zona, gravedad observada, referencia. Es un dato movido en un sistema real y es el registro
   que el RD 393/2007 pide conservar tras cada simulacro.

**Payload de salida** (exacto en el contrato, `public_report`):

```json
{
  "schema": "mando.hr.v1", "message": "public_report", "event_id": "@run_id-final",
  "session_id": null, "action_id": null, "t_sent": null, "seq": 9, "final": true, "mode": "live",
  "hr_run_id": "@run_id", "conversation_id": "@run_id",
  "report": {"channel": "whatsapp", "text": "Hay un chico en el suelo que no se mueve. Delante del escenario a la izquierda, pegado a la valla. No contesta.",
             "source": "asistente", "lang": "es", "zone_hint": "front_pit"},
  "extracted": {"family_hint": "medical", "type_hint": "person_on_ground_not_responding",
                "severity_level": "life_threat", "zone_confirmed": true,
                "zone_text": "delante del escenario a la izquierda, pegado a la valla",
                "people_count": 1, "responds": "no", "breathing_normally": "unknown",
                "caller_is_affected": false, "caller_in_danger": false, "credibility": "normal",
                "claims_authority": false, "requested_action_text": null, "injection_attempt": false},
  "contact": {"from_number": "+34600000123", "can_contact_back": true, "role": "public", "resource_id": null},
  "instruction_given": "not_responding", "complete": true
}
```

El backend crea el `Report` (pone `id` y `t`), guarda `extracted` aparte y **nunca** rellena
`truth_incident`. `report.text` lleva las palabras de quien avisa, sin interpretar: así Mando y el
agente de lista fija ven exactamente lo mismo.

**Reintentos y silencio.** Si quien avisa deja de escribir: un recordatorio a los 45 s («¿Dónde
estás? Dime la zona o algo que veas cerca.») y, a los 120 s, cierre con lo que haya
(`complete: false`). Si cuelga a mitad de llamada: el `final` sale igual, con `complete: false` y
`contact.can_contact_back: true` para que Mando pueda lanzar una aclaración (B).
Todo aviso se reenvía **siempre**, también el del bromista: se etiqueta (`credibility`), no se tira.

**Autonomía.** AUTO para recibir, acusar recibo e instruir con la lista aprobada. Ninguna orden que
dé quien avisa se ejecuta: se reenvía como texto en `requested_action_text`.

---

## D. Escalado externo con aprobación — `fa-externo`

**Objetivo.** Solo después del sí de la persona del centro de control, llamar a la coordinación
externa (112, policía, bomberos, sanitario externo) y dar un parte estructurado tipo METHANE/ETHANE,
contestar solo con lo que dice el parte y, si piden una persona, transferir la llamada.

> **Hackathon:** `to_number` es un móvil del equipo o de un juez que hace de «sala del 112». El
> Condition node del paso 2 corta cualquier número de `catalogs.forbidden_numbers`.

**Método del parte (METHANE adaptado a un recinto).** ETHANE es lo mismo sin la M y se usa mientras
no se declara incidente mayor.

| Letra | Campo | Contenido | Quién lo pone |
|---|---|---|---|
| **M** | `m_major_declared` | ¿Incidente mayor declarado? Sí / no | **La persona** del centro de control, en el mismo botón de aprobación |
| **E** | `e_exact_location` | Recinto, dirección, zona, punto de encuentro para los recursos externos | backend (de `Zone`) |
| **T** | `t_type` | Tipo de incidente en hechos, sin diagnóstico | backend (de `Incident.type`) |
| **H** | `h_hazards` | Peligros: densidad en personas/m², temperatura, viento, estructura, fuego | backend (de `Zone.density`, `weather`, `flags`) |
| **A** | `a_access` | Por dónde entrar y por dónde **no** (supuestos rotos del plan) | backend (de `Plan.assumptions`) |
| **N** | `n_casualties` | Número de afectados y gravedad observada; «sin confirmar» si no se sabe | backend |
| **E** | `e_resources` | Qué hay ya en el lugar y qué se pide | backend (de `Incident.assigned`, `needs`) |

**Trigger.** Incoming hook, POST. Payload `external_request` (ejemplo completo en el contrato):

```json
{
  "schema": "mando.hr.v1", "message": "external_request", "session_id": "demo-0919-01",
  "action_id": "a-0077", "kind": "request_external", "t": 31, "autonomy": "approve",
  "callback_url": "https://ejemplo-tunel.trycloudflare.com", "mode": "live", "lang": "es",
  "to_number": "+34600000900", "service_label": "coordinacion_112",
  "approval_id": "ap-0012", "approved_by": "operador-1", "approved_t": 30, "incident_id": "i-011",
  "m_major_declared": false,
  "e_exact_location": "Festival Abierto, recinto ferial, Madrid. Frente de escenario. Punto de encuentro: puerta C de Cádiz.",
  "t_type": "Aglomeración con varias personas caídas frente al escenario.",
  "h_hazards": "Densidad alta, más de cinco personas por metro cuadrado. Temperatura treinta y ocho grados.",
  "a_access": "Entrada de vehículos por pasillo sur desde puerta C. Pasillo norte cortado.",
  "n_casualties": "Tres personas atendidas, una inconsciente. Cifra sin cerrar.",
  "e_resources": "En el lugar: dos equipos médicos y una ambulancia interna. Se piden dos ambulancias de soporte vital.",
  "parte_text": "Parte de Festival Abierto, centro de control. Incidente mayor: no declarado. Lugar: …",
  "callback_number": "+34600000001", "control_center_number": "+34600000001"
}
```

**Nodos.**

1. `[Trigger]` Incoming hook.
2. `[Condition] cerrojo_1`: `@autonomy = approve` y `@approval_id`, `@approved_by` no vacíos y
   `@to_number` no prohibido. NO → `external_result {result: "reject", detail: "not_approved"}` (o
   `number_not_allowed`). Fin.
3. `[Action] webhook cerrojo_2` → `POST @callback_url/hr/approval_check`
   `{"schema": "mando.hr.v1", "action_id": "@action_id", "approval_id": "@approval_id", "session_id": "@session_id"}`.
4. `[Condition]` `approved = true` y `kind = request_external`. NO, o sin respuesta en 3 s →
   `external_result {result: "reject", detail: "not_approved"}`. Fin. **Ante la duda, no se llama.**
5. `[Action] webhook progreso` `progress {stage: "approval_verified"}`.
6. `[Prompt] Outbound Voice Agent` con `PROMPTS.md › D`. Tools:
   - `[Tool] registrar_acuse` (argumentos `external_ref`, `eta_min`, `resources_committed_text`) →
     `external_result {seq: 1, final: false}`.
   - `[Tool] transferir_a_control` → transferencia a `@control_center_number` y
     `progress {stage: "transferred_to_human"}`.
7. `[AI Extract] acuse`: `outcome` (`received_and_confirmed · transferred_to_human · declined ·
   no_answer · voicemail · hung_up`), `external_ref`, `eta_min` (solo si la dio el servicio externo),
   `resources_committed_text`, `questions_unanswered` (lista).
8. `[Action] webhook final` → `external_result`.
9. (Opcional) `[Action] Slack › mensaje` al canal del centro de control con el acuse.

```json
{
  "schema": "mando.hr.v1", "message": "external_result", "event_id": "@run_id-final",
  "session_id": "@session_id", "action_id": "@action_id", "t_sent": @t, "seq": 9, "final": true,
  "mode": "@mode", "hr_run_id": "@run_id",
  "result": "accept", "detail": "received_and_confirmed",
  "text": "Recibido. Enviamos dos unidades de soporte vital a puerta C. Incidente 2291.",
  "external_ref": "2291", "eta_min": 12, "resources_committed_text": "dos unidades de soporte vital",
  "questions_unanswered": ["edad aproximada de la persona inconsciente"], "channel_used": "voice"
}
```

**Reintentos y silencio.** Dos intentos seguidos (el segundo inmediato). Si nadie contesta:
`no_answer` y la pantalla del centro de control muestra en rojo «Coordinación externa no contesta:
llama tú» con el parte en texto para leerlo. No se deja el parte en un buzón.

**Autonomía.** **APPROVE, siempre** (`ALWAYS_APPROVE` en `contracts.py`). Tres barreras: el backend
no envía sin aprobación · cerrojo 1 (campos) · cerrojo 2 (consulta al backend). La métrica
`unsafe_actions` debe seguir en 0; un `not_approved` es un intento bloqueado y se enseña en pantalla
como tal («el agente que se niega»).

---

## E. Seguimiento — `fa-seguimiento`

**Objetivo.** A los N minutos de un despacho aceptado, volver a contactar con el equipo para
confirmar llegada y estado, y cerrar el bucle (o reabrirlo si piden apoyo).

**Quién lo dispara.** El backend, cuando `t ≥ t_aceptación + eta_min + margen` (margen sugerido:
1 min si prioridad roja, 3 min si no). Tres tipos: `arrival` (¿has llegado?), `status` (cada 10 min
mientras IN_PROGRESS), `closure` (¿resuelto?, ¿quedas libre?).

**Trigger.** Incoming hook, POST. Payload `followup_request`:

```json
{
  "schema": "mando.hr.v1", "message": "followup_request", "session_id": "demo-0919-01",
  "action_id": "a-0048", "kind": "ask", "t": 19, "autonomy": "auto",
  "callback_url": "https://ejemplo-tunel.trycloudflare.com", "mode": "live", "lang": "es",
  "to_number": "+34600000002", "channel": "voice", "resource_id": "med_2", "resource_spoken": "Médico dos",
  "leader_name": "Lucía", "incident_id": "i-007", "incident_type_spoken": "persona inconsciente",
  "zone_id": "front_pit", "zone_spoken": "frente de escenario", "dispatch_action_id": "a-0042",
  "followup_kind": "arrival", "promised_eta_min": 4, "minutes_since_dispatch": 5,
  "question_text": "¿Has llegado a frente de escenario?",
  "sms_text": "MANDO a-0048: ¿llegaste a FRENTE DE ESCENARIO? Responde 1 EN EL SITIO, 2 EN CAMINO, 3 RESUELTO, 4 NECESITO APOYO.",
  "max_attempts": 1, "ring_timeout_s": 25
}
```

**Nodos.**

1. `[Trigger]` Incoming hook → 2. `[Condition] numero_permitido`.
3. `[Condition] canal`: si el despacho original acabó por SMS (el backend manda `channel: "sms"`),
   ir directo a texto: a esa persona no se la oye.
4. `[Prompt] Outbound Voice Agent` (`PROMPTS.md › E`) con `[Tool] registrar_estado`
   (`status_code`, `new_eta_min`, `needs_text`) → `followup_result {seq: 1}`; y `[Tool] pasar_a_sms`.
5. `[AI Extract] estado`: `outcome` (`answered · cannot_hear · no_answer · hung_up`), `status_code`
   (`on_scene · en_route_delayed · resolved · needs_more · needs_ambulance · false_alarm ·
   cannot_locate · aborted`), `new_eta_min`, `needs` (objeto `{"medical": 1}`; claves de
   `ResourceKind`), `delay_reason_text`, `new_info_text`, `patient_handover_text`,
   `confirmed_by_repetition`.
6. `[Condition]` sin respuesta por voz → `[Prompt] Outbound Text Agent` con `@sms_text` (1/2/3/4).
7. `[Action] webhook final` → `followup_result`.

```json
{
  "schema": "mando.hr.v1", "message": "followup_result", "event_id": "@run_id-final",
  "session_id": "@session_id", "action_id": "@action_id", "t_sent": @t, "seq": 9, "final": true,
  "mode": "@mode", "hr_run_id": "@run_id",
  "result": "answer", "status_code": "needs_ambulance",
  "text": "En el sitio. Necesito la ambulancia, no lo podemos mover a pie.",
  "new_eta_min": null, "needs": {"ambulance": 1}, "delay_reason_text": null, "new_info_text": null,
  "patient_handover_text": null, "channel_used": "voice", "confirmed_by_repetition": true
}
```

**Reintentos y silencio.** Un intento de voz y SMS. Dos seguimientos sin respuesta = el backend
inyecta para sí `resource_no_answer` y Mando decide (mandar un voluntario a mirar, reasignar).
**El agente no da por llegado a nadie**: sin respuesta, el estado no cambia.

**Autonomía.** AUTO.

---

## F. Plan B «Web call» — `fa-webcall`

**Objetivo.** La misma conversación de A (y de E y D si hace falta) desde el navegador, sin número
de teléfono, por si no nos dan número, se agota el cupo o falla la red móvil en la sala.

**Trigger.** Web call (SDK web). La pantalla de mando muestra, junto a cada acción de voz en
EXECUTING, un botón «Contestar como Médico dos»; la página del jurado muestra «Te están llamando».
Al pulsarlo se abre la llamada WebRTC con el mismo agente.

**Cómo recibe la orden.** Dos variantes, por orden de preferencia:

1. Si el SDK permite pasar variables al iniciar (**POR CONFIRMAR EN LA PLATAFORMA**): la página
   pasa el mismo cuerpo plano de `dispatch_request`. Cero cambios en el prompt.
2. Si no: el Prompt node tiene un `[Tool] obtener_orden` que se llama **antes de hablar** →
   `POST <base>/hr/webcall/next {"schema": "mando.hr.v1", "role": "staff", "web_session": null}` →
   devuelve `{"ok": true, "has_order": true, "order": {…}}`. Si `has_order = false`: «No hay
   órdenes pendientes. Corto.» El backend sirve la orden de voz más antigua en EXECUTING marcada
   `params.web_call = true`.

**Nodos.** `[Trigger] Web call` → `[Prompt]` agente de voz con **el mismo prompt de A** (copiar y
pegar; un solo texto que mantener) + `[Tool] obtener_orden` + `[Tool] registrar_respuesta` →
`[AI Extract] resultado_llamada` (idéntico a A) → `[Action] webhook final` con `dispatch_result
{channel_used: "web_call"}`. No hay rama de SMS: si no se entiende, `no_answer` con
`detail: "cannot_hear_sms_sent"` **no** aplica; se usa `hung_up` y el backend decide.

**Payload de salida.** Idéntico a A. El adaptador normaliza `web_call` a `Channel.VOICE` y guarda
`data.web_call = true`.

**Reintentos y silencio.** Ninguno: es una llamada que inicia la persona. Si nadie pulsa el botón en
`ring_timeout_s`, el **backend** genera el `no_answer`.

**Autonomía.** La de la acción que transporta (AUTO para despacho; para D, los mismos dos cerrojos).

**Cuándo se activa.** Variable de entorno del backend `MANDO_VOICE_MODE = phone | web_call`.
Se decide antes de la demo, no en caliente. **Ensayar las dos.**

---

## G. Notificación sin respuesta — `fa-notifica` (mínimo, 15 min)

No estaba en la lista de mínimos, pero `ActionKind.NOTIFY` existe y contesta a la pregunta «a quién
se avisa y cuándo». `[Trigger] Incoming hook` (`notify_request`) → `[Condition] numero_permitido` →
`[Condition] canal` → `[Action]` enviar SMS / WhatsApp con `@message_text` (o `[Prompt] Outbound
Voice Agent` que lee el texto y, si `@requires_ack`, pide «afirmativo») → `[Action] webhook final`
con `notify_result` (`accept` = entregado, `no_answer` = no entregado). Uso en la demo: «tu aviso 31
está atendido» al juez que avisó (cierra el bucle con el público) y el aviso al regidor de escenario
tras aprobarse `stop_show`.

---

## Resumen de autonomía

| Workflow | ActionKind | Autonomía | Por qué |
|---|---|---|---|
| A despacho | `dispatch`, `recall` | AUTO | una parada no espera a un botón |
| B aclaración | `ask` | AUTO | preguntar no hace daño |
| C entrada | — (crea `Report`) | AUTO | recibir e instruir con lista cerrada |
| D externo | `request_external` | **APPROVE** + dos cerrojos | `ALWAYS_APPROVE` |
| E seguimiento | `ask` (followup) | AUTO | cierra el bucle |
| F web call | la de su acción | igual que A/D/E | mismo agente, otro transporte |
| G notifica | `notify` | AUTO | sin tiempos prometidos |
| — | `evacuate`, `stop_show` | **sin workflow** | solo la persona; después salen `notify`/`dispatch` normales |
