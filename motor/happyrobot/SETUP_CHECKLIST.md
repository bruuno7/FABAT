# Montaje en la plataforma en menos de 2 horas, y preguntas para los mentores

Carpeta privada. Workspace: `platform.eu.happyrobot.ai/<workspace>` («<nombre del workspace>», EU, motor V3).
Quien monte esto necesita abiertos: `WORKFLOWS.md` (nodos), `PROMPTS.md` (textos), `webhook_contract.json`
(ejemplos para pegar) y, al final, `TESTS.md`.

## Reglas antes de tocar nada

- **No se llama a ningún número de emergencias real. Nunca.** El «112» de la demo es un móvil nuestro.
- Solo se llama o escribe a teléfonos de la lista blanca (equipo y jueces que lo hayan consentido
  dejando su número en la página del jurado).
- Nombres neutros en la plataforma: `fa-despacho`, `fa-aclaracion`, `fa-entrada`, `fa-externo`,
  `fa-seguimiento`, `fa-webcall`, `fa-notifica`. Nada de estrategia en nombres ni descripciones.
- El workflow `test` que ya existe no se toca: se crea todo nuevo (Create workflow → Version 3 →
  From Scratch).
- Las credenciales las teclea una persona. El token `X-Mando-Token` se genera en local
  (`openssl rand -hex 16`) y se pega a mano en los nodos de webhook y en el `.env` del servidor. No va
  a ningún repo.
- Lo marcado **POR CONFIRMAR** se pregunta o se prueba en el momento; no se da por hecho.

## Orden de trabajo (120 min)

El orden sigue el del proyecto: **una llamada real primero**. Si algo se atasca más del tiempo
indicado, se salta y se pregunta a un mentor.

### Bloque 0 · Preparación (10 min)

- [ ] Conseguir el **código de acceso de `docs.happyrobot.ai`** (sigue cerrado el 18-sep). Abrir
      «Outbound Call», «Webhook» y «Workflows» (existen: salen en buscadores).
- [ ] Levantar el servidor local con el receptor mínimo: `POST /hr/events` que guarda cabeceras y
      cuerpo en un fichero y responde `{"ok": true}` en < 200 ms. (Lo hace quien lleva `motor/server`;
      si aún no existe, sirve cualquier receptor local de peticiones.)
- [ ] Abrir un túnel al servidor local y apuntar la URL pública → `MANDO_CALLBACK_URL`.
      Qué túnel usar y si la red del evento lo permite: **pregunta 4**.
- [ ] Integrations: ver qué está ya conectado para el hackathon (SMS vía Twilio, Telnyx, WhatsApp).
      No conectar cuentas personales.
- [ ] Apuntar el número de teléfono asignado al workspace, si lo hay: **pregunta 1**.

### Bloque 1 · `fa-despacho`: la llamada real (35 min) — lo primero que tiene que funcionar

- [ ] Create workflow → `fa-despacho` → trigger **Incoming hook** (POST).
- [ ] Event Setup › Params: pegar las claves del ejemplo `dispatch_request` del contrato (33 campos
      planos; si hay prisa, los 12 que usa el prompt: `to_number`, `action_id`, `session_id`, `t`,
      `callback_url`, `mode`, `resource_spoken`, `zone_spoken`, `priority_label`, `order_text`,
      `access_hint`, `sms_text`). Pestaña **Development**. Copiar la URL del hook → `HR_HOOK_DISPATCH`.
      Si hay «Enhanced Security»: activarla y apuntar cabecera y clave → `HR_API_KEY` (POR CONFIRMAR).
- [ ] Añadir el nodo **Outbound Voice Agent**. «To number» = `@to_number`. Voz: español de España, la
      más clara y algo lenta (**pregunta 6**). Idioma: es-ES.
- [ ] Prompt node: **Initial Message** y **Prompt** de `PROMPTS.md › A` (bloque común incluido).
      Comprobar que cada `@variable` queda resuelta (se pone de color o como etiqueta).
- [ ] **Primera llamada ya**, sin herramientas ni webhook: botón Play → pegar valores de prueba con
      **tu móvil** en `to_number` → «Trigger … Version» → contestar → mirar el Run y la transcripción.
      **Hito 1: suena el teléfono y dice la orden.** Hacerle una foto a la pantalla del Run.
- [ ] Añadir dentro del Prompt los Tool nodes `registrar_respuesta` y `pasar_a_sms`
      (nombre + descripción de `WORKFLOWS.md › A`; acción = webhook POST a `@callback_url/hr/events`
      con el cuerpo `dispatch_result`, `seq: 1`, `final: false`). Cabecera `X-Mando-Token`.
      Si el campo URL no admite variables: pegar la URL del túnel a mano y apuntarlo aquí → ☐
- [ ] Nodo **AI › Extract** tras la llamada con las 8 variables de la tabla de A.
- [ ] Nodo de webhook final con el cuerpo `dispatch_result` (`seq: 9`, `final: true`).
- [ ] Probar T-A-01 y T-A-02 (`TESTS.md`). **Hito 2: el servidor local recibe `accept` con `eta_min`.**
- [ ] Si queda tiempo del bloque: Condition de número prohibido (T0-03) y rama de SMS (T-A-06).
      Si no hay SMS habilitado: dejar la rama preparada y seguir.

### Bloque 2 · `fa-entrada`: el jurado avisa (25 min)

- [ ] Create workflow → `fa-entrada` → trigger **Inbound Text Message** (y/o WhatsApp).
      Si no admite varios triggers: duplicar después para **Inbound to number**.
- [ ] Nodo webhook `identificar` → `POST <túnel>/hr/identify` (el servidor puede contestar siempre
      `{"ok": true, "route": "public_report", "role": "public"}` hasta que el backend real esté).
- [ ] Condition por `route` (dejar solo `public_report` funcionando; las otras ramas, vacías).
- [ ] Agente de texto con `PROMPTS.md › C-texto` y la tabla de instrucciones aprobadas pegada dentro.
- [ ] Tool `enviar_aviso` → `POST <túnel>/hr/events` con `public_report`. Comprobar que el agente
      lee `ref_spoken` de la respuesta.
- [ ] AI › Extract con las variables de `extracted` + webhook final.
- [ ] Probar T-C-01 y T-C-02 desde un móvil. **Hito 3: un WhatsApp o SMS real se convierte en un
      `public_report` en el servidor.**

### Bloque 3 · `fa-webcall`: el plan B (15 min)

- [ ] Create workflow → `fa-webcall` → trigger **Web call**. Copiar el prompt de A.
- [ ] Mirar cómo se incrusta el SDK (fragmento de código, clave pública, dominio permitido) y si
      acepta variables al iniciar: **pregunta 9**. Apuntar el fragmento para quien lleva la pantalla.
- [ ] Si no acepta variables: Tool `obtener_orden` → `POST <túnel>/hr/webcall/next`.
- [ ] Probar T-F-01 desde el portátil. **Hito 4: la misma conversación sin teléfono.**

### Bloque 4 · `fa-externo` con sus dos cerrojos (15 min)

- [ ] Incoming hook con los campos de `external_request`.
- [ ] Condition cerrojo 1 → webhook `approval_check` → Condition cerrojo 2 → Outbound Voice Agent
      (`PROMPTS.md › D`) → Extract → webhook final.
- [ ] Probar **primero** T-D-02 y T-D-03 (no debe sonar ningún teléfono) y luego T-D-01 con un
      compañero haciendo de sala. `to_number` = móvil de ese compañero.
- [ ] Transferencia a una persona: probar si el Tool de transferencia existe y funciona con nuestros
      números (**pregunta 10**). Si no: el agente dice «El centro de control le llama ahora. Corto.»
      y el resultado es `transferred_to_human` igualmente (la llamada la hace la persona).

### Bloque 5 · `fa-aclaracion`, `fa-seguimiento`, `fa-notifica` (15 min)

Son copias de A con otro prompt y otro Extract. Usar **Fork** o duplicar.
- [ ] `fa-seguimiento`: prompt E, Tool `registrar_estado`, Extract de `status_code`. Probar T-E-01.
- [ ] `fa-aclaracion`: Condition por canal, prompts B-voz y B-texto. Probar T-B-01.
- [ ] `fa-notifica`: enviar SMS/WhatsApp con `@message_text` + webhook. Probar con un móvil.

### Bloque 6 · Northstars, Tests y publicar (15 min)

- [ ] Evals › **Northstars**: ver cuáles ha extraído sola la plataforma del prompt. Completar a mano
      las **P0** de `NORTHSTARS.md` que falten (NS-01 a NS-10), cada una con su ejemplo bueno y malo.
      Categoría correcta: Notes, Style, Tool o Sequential.
- [ ] Evals › **Tests**: cargar al menos AP-03 (falso director), AP-04 (inyección), AP-07 (se
      retracta) y AP-01 (grita). Ejecutar. Apuntar aprobado/suspenso con versión y N.
- [ ] Muestreo de auditoría al 100 % si se puede configurar.
- [ ] **Publish** cada workflow; copiar las URL del hook del entorno publicado a las variables
      `HR_HOOK_*` del servidor (pueden ser distintas de las de Development).
- [ ] Apuntar en el canal privado del equipo: URL de los 5 hooks, número de teléfono, versión
      publicada de cada workflow. **No en el repo público.**

### Si sobra tiempo

- [ ] Google Sheets › «libro de incidencias» (nodo opcional de C).
- [ ] Slack › mensaje al canal del centro de control en cada petición de aprobación.
- [ ] *Keyword boosting* con los nombres de zona y las palabras de control.
- [ ] Suite adversaria autogenerada (30) con `suite_generation_prompt`.
- [ ] Mirar **Experiments** para comparar dos versiones del Initial Message de A (con y sin «sistema
      automático» al principio) y medir duración de llamada.

## Variables de entorno que hay que entregar a quien lleva `motor/server`

```text
HR_HOOK_DISPATCH=      HR_HOOK_CLARIFY=      HR_HOOK_NOTIFY=
HR_HOOK_EXTERNAL=      HR_HOOK_FOLLOWUP=     HR_API_KEY=            (si hay Enhanced Security)
MANDO_CALLBACK_URL=    MANDO_HR_TOKEN=       MANDO_ALLOWED_NUMBERS=+346...,+346...
MANDO_VOICE_MODE=phone|web_call              MANDO_CONTROL_NUMBER=  (móvil de la persona del centro de control)
MANDO_EXTERNAL_NUMBER=                       (móvil que hace de coordinación externa; nunca un número real de emergencias)
```

## Preguntas para los mentores de HappyRobot

Por orden de urgencia. Las diez primeras bloquean el diseño; apuntar la respuesta al lado y pasar
lo que cambie a `WORKFLOWS.md` y al contrato.

**Acceso y canales**

1. **Números de teléfono:** ¿tenemos un número asignado al workspace del hackathon? ¿De qué país
   (queremos +34)? ¿Sirve para llamadas salientes y entrantes, y para SMS? ¿Podemos llamar a
   móviles españoles de jueces y compañeros? ¿Qué identificador de llamada ve quien recibe?
2. **Límites:** ¿cuántas llamadas y minutos tenemos en total? ¿Cuántas llamadas **a la vez**
   (concurrencia)? ¿Hay límite de ejecuciones de workflows, de tests o de mensajes? ¿Qué pasa al
   llegar al límite: encola o rechaza?
3. **SMS y WhatsApp:** ¿están habilitados en este workspace? ¿Con qué proveedor (Twilio, Telnyx)?
   ¿WhatsApp exige plantilla aprobada para el primer mensaje saliente, o solo podemos contestar
   dentro de la ventana que abre el usuario? ¿Hay un número o un QR de WhatsApp ya listo?
4. **Webhook local:** ¿cómo recomendáis exponer un servidor local (qué túnel)? ¿La red del evento lo
   permite? ¿El campo URL del nodo de webhook admite variables (`@callback_url`) o es fija? ¿Qué
   timeout y cuántos reintentos hace el nodo si nuestro servidor tarda o falla? ¿Desde qué IP salen
   las peticiones?
5. **Documentación:** ¿nos dais el código de acceso de `docs.happyrobot.ai`?

**Voz**

6. **Idiomas y voces:** ¿qué voces hay en español de España y cuál aguanta mejor el ruido? (La web
   dice «30+ idiomas»; en la presentación entendimos «50+».) ¿Puede el agente **cambiar de idioma a
   mitad de llamada** si le contestan en inglés, o hay que montar un agente por idioma?
7. **Latencia:** ¿qué latencia por turno debemos esperar en la región EU con el motor V3? ¿Dónde se
   ve desglosada (transcripción, modelo, voz, red)? ¿Qué ajustes la bajan más: modelo, longitud del
   prompt, Initial Message fijo, número de Tool nodes? ¿El Initial Message se dice sin pasar por el modelo?
8. **Llamada saliente:** ¿cómo se configura el tiempo de timbre, la detección de buzón de voz y los
   reintentos en el Outbound Voice Agent? ¿Qué variables de salida da el nodo (estado de la llamada,
   duración, transcripción, motivo de fin)? ¿Cómo se distingue «no contestó» de «colgó» y de «buzón»?
   ¿Podemos subir palabras al *keyword boosting* (zonas, «afirmativo», «negativo»)? ¿Hay algún ajuste
   de sensibilidad al ruido o a las interrupciones para un entorno de concierto?
9. **Web call:** ¿cómo se incrusta el SDK? ¿Se pueden pasar variables al iniciar la llamada (para
   darle el `action_id` y la orden)? ¿Funciona en el navegador de un móvil? ¿Cuenta contra el mismo
   límite de llamadas?
10. **Transferencia a una persona:** ¿el agente puede transferir la llamada a un móvil nuestro durante
    el hackathon? ¿Transferencia en frío o con presentación?

**Workflow**

11. **Variables:** ¿el selector `@` resuelve JSON anidado (`@incident.zone`) o solo claves planas?
    ¿Cómo se llama la variable con el id de la ejecución, para usarla de `event_id`? ¿Se puede
    construir un cuerpo JSON con `null`, números y booleanos sin que todo salga como texto?
12. **Respuestas por SMS:** cuando el Outbound Text Agent manda un SMS y la persona responde, ¿la
    respuesta vuelve a **esa** ejecución o entra por el trigger «Inbound Text Message»? (Tenemos
    diseño para ambos casos; necesitamos saber cuál.)
13. **Varios triggers** en un mismo workflow (SMS + WhatsApp + llamada entrante): ¿se puede, o un
    workflow por trigger? ¿Se puede llamar a un workflow desde otro («Workflow Function Request»)
    para no copiar el prompt tres veces?
14. **Bucles y esperas:** ¿hay nodo de espera y de reintento? (Hemos dejado los temporizadores en
    nuestro backend; ¿lo veis bien?)
15. **Tools durante la llamada:** mientras se ejecuta un Tool node (webhook a nuestro servidor), ¿el
    agente se queda en silencio? ¿Se puede lanzar sin esperar respuesta? ¿Qué timeout tiene?
16. **Memoria entre ejecuciones:** ¿cómo se usa? (Nos serviría para que el agente de entrada sepa que
    ese número ya avisó hace dos minutos, sin preguntar a nuestro backend.)
17. **MCP Server y Custom LLM Server:** ¿merece la pena exponer nuestro backend como servidor MCP
    en vez de cinco Tool nodes con webhooks? ¿Alguien lo ha hecho ya en un hackathon?

**Gobierno: lo que queremos usar de verdad, no solo citar**

18. **Northstars:** ¿se pueden escribir a mano o solo se extraen del prompt? ¿Evalúa bien el juez
    en español? ¿Cómo se fija prioridad y tasa de muestreo? ¿Una northstar de tipo Tool o Sequential
    puede comprobar que se llamó a una herramienta **antes** de un turno concreto?
19. **Tests y Adversarial Agents:** ¿funcionan con agentes de **voz** o solo de texto? ¿El usuario
    simulado puede colgar, quedarse callado o hablar en otro idioma? ¿Se puede simular ruido? ¿Un
    test llama a nuestros webhooks reales? ¿Se puede convertir un Run fallido en test con un clic?
    ¿Se pueden importar muchos tests de golpe (tenemos 24 personas en JSON)?
20. **Experiments:** ¿qué es exactamente (comparar versiones de prompt con tráfico real)? ¿Qué
    métrica usa?
21. **Twin, Interfaces y Frontal:** ¿qué son y para qué los usaríais vosotros en un caso como el
    nuestro? ¿«Twin» sirve para simular al interlocutor (un jefe de equipo) a escala? ¿«Interfaces»
    sirve para montar la pantalla donde la persona aprueba o veta, o es mejor nuestra pantalla
    propia? ¿«Frontal» es el panel del cliente final?
22. **Versiones y Pull requests:** ¿el flujo recomendado es Fork → editar → Pull request → Publish?
    ¿Los tests se ejecutan solos al abrir un pull request?

**Criterio**

23. Nuestro caso es vuestra operación de Utilities (recibir el aviso, despachar por voz, confirmar
    y cerrar el bucle) llevada a una vertical nueva: la coordinación de incidentes en un evento
    masivo. ¿Qué os gustaría ver que **no** suelen enseñaros los equipos?
24. ¿Valoráis más que la llamada sea a un teléfono real del jurado en directo, o que el vídeo lo
    enseñe sin riesgo? (Tenemos las dos rutas: teléfono y Web call.)
25. ¿Hay algo que **no** debamos hacer con la plataforma durante el hackathon (llamadas a terceros,
    volumen, contenido)?
