# Presentación ResQval / FABAT

Guion de una **demostración controlada**, no de una emergencia real. Estado y arquitectura: [README.md](README.md). Puertas de aceptación: [PENDIENTE.md](PENDIENTE.md).

## Qué se puede afirmar hoy

- MANDO SQLite es la autoridad; ResQval proyecta su estado y envía comandos. HappyRobot conversa/propone, MANDO valida, una persona autoriza lo grave.
- Existe evidencia histórica del recorrido **Telegram → Vercel → Railway → HappyRobot, N=1 llamada telefónica real de prueba**, `accept`, destino confirmado y ETA **2 minutos**, con callbacks aplicados. No fue webcall ni `followup_question`; no acredita el SHA/árbol actual, llegada física o todos los escenarios.
- El rápido adaptado es un fork v2 **no publicado/no live**. La v1 permanece live en `development`; el fork tiene metadata `production`, no activación. Hay pruebas de contrato en **SIMULACIÓN N=11 casos de nodos puros y N=7 tests locales mock/ASGI**; no se ejecutó el agente completo ni su trigger.
- El rápido sigue bloqueado por el enlace de respuesta HTTP, candidato público y recorrido del agente. No usar una propuesta sintética como si procediera de un run real.
- Preflight, suites finales y aceptación visual quedan pendientes de consolidar sobre la candidata. Los guiones son un recorrido propuesto: no se consideran ensayados ni medidos hasta guardar su evidencia.

No decir «sin fallos», «100 % seguro», «salva vidas», «todos los canales funcionando», «aprende solo» ni «gemelo exacto». El plano es esquemático y los resultados sintéticos no son evidencia clínica.

## Preparación y reparto

| Papel | Responsabilidad |
|---|---|
| Presentador/a | Cuenta el problema, distingue real/simulado y anuncia el plan B si hay fallo |
| Operador/a de mando | Única persona que manipula la sala y aprueba/veta; sesión individual privada |
| Persona de equipo | Interpreta a sanitario A/B. Contesta teléfono **solo si esa llamada fue previamente autorizada**; en simulación lee sus respuestas al operador |
| Suplente técnico | Vigila tiempo, estado de conexión y artefactos; no corrige datos silenciosamente durante el guion |

Puede haber dos personas físicas acumulando papeles, pero se explica quién decide y quién responde. El jurado no aporta su teléfono ni recibe mensajes por sorpresa.

Preparar el ensayo en localhost sin proveedores. Exponer red, desplegar o llamar requiere autorización específica:

1. Validar en navegador la revisión elegida: login con token también en localhost, logout implementado, navegación, SSE y conflictos. No presentar un recorrido interactivo que nadie ha probado.
2. Preparar base **nueva y ficticia**, operador, dos sanitarios disponibles (`medic-a`, `medic-b`) y coordinador. Plano de zonas del festival; no mostrar contactos ni consola con secretos.
3. Modo seguro por defecto: `MANDO_EXTERNAL_DELIVERY=0`, sin credenciales de proveedor. Rotular «SIMULACIÓN; respuestas del equipo representadas por personas».
4. Solo si se autoriza y valida antes una versión conectada: destinatario consentido en whitelist, workflows compatibles y coste/límite aceptados. No configurar cuentas ni intentar publicar workflows ante el jurado.
5. Ejecutar preflight con base nueva, revisar `preflight.json`, `demo.json`/`demo-trace.json` y preparar solo resultados saneados realmente obtenidos. Una grabación solo puede usarse si existe, se revisó y se rotula con revisión/fecha/modo; no se presupone su disponibilidad.
6. Comprobar que `POST /salir` borra la sesión y que el acceso posterior pide autenticación. En equipo compartido, usar perfil dedicado; el logout no revoca credenciales/cookies previamente copiadas.
7. No borrar producción para preparar el ensayo. Cada repetición usa datos aislados nuevos y conserva artefactos anteriores. Al terminar, cerrar la sesión y guardar evidencia fuera del repositorio, sin secretos ni datos personales.

Preflight reproducible, sin red ni servidor:

```sh
./mvp.sh preflight --seed 1701 --output /tmp/resqval-ensayo-nuevo
```

Elegir directorio nuevo fuera del checkout. Si falla, se muestra el fallo y no se fabrica un `ok`. Si pasa, mostrar N y semilla; no extrapolar porcentajes de éxito.

## Guion hablado — aproximadamente 3 minutos

Tiempo orientativo; ensayar con pausas para leer pantalla. El bloque hablado se puede leer tal cual. No hace falta ejecutar todos los botones en tres minutos: mostrar el caso preparado o la evidencia de preflight, siempre rotulada.

### 0:00–0:30 · Problema y límites

**Pantalla:** título y sala con indicador de modo; operador sin actuar todavía.

> «En un festival, el problema no es solo recibir un aviso: es saber quién se ha comprometido a actuar, dónde va y qué ha cambiado. ResQval ayuda al puesto de mando a mantener esa coordinación. Lo que mostramos hoy es un ensayo con datos ficticios. No es un sistema certificado de emergencias ni sustituye a los profesionales del recinto.»

### 0:30–1:00 · Una autoridad

**Pantalla:** diagrama Telegram → puente → MANDO → HappyRobot → callback, seguido del incidente.

> «Telegram entra por un puente en Vercel. MANDO, alojable en Railway, conserva la operación en SQLite. HappyRobot puede conversar, pedir una aclaración y devolver una propuesta o respuesta. Pero no es quien tiene la última palabra sobre los recursos: MANDO comprueba identidad, versión, disponibilidad y permisos. ResQval muestra ese mismo estado; no mantiene una segunda lista de incidentes.»

### 1:00–1:35 · Compromiso e imprevisto

**Pantalla:** aviso de persona desmayada en puerta A, tarea ofrecida al equipo A, después rechazo y alternativa B.

> «Aquí hay una persona desmayada en puerta A. La tarea reserva al equipo A, pero ofrecer no significa aceptar. Introducimos el imprevisto del ensayo: el equipo A no puede continuar. No tapamos el rechazo: queda registrado y aparece una alternativa con el equipo B. Lo importante es poder ver el plan anterior, el dato que lo invalida y el motivo del cambio, sin asignar dos veces el mismo recurso.»

### 1:35–2:10 · No confundir palabras con hechos

**Pantalla:** tarea B y eventos; persona de equipo dice su respuesta al operador en modo simulado.

> «B acepta y confirma destino y tiempo estimado. Eso todavía no significa que haya llegado, localizado a la persona o terminado. Son estados distintos. En este ensayo las respuestas son representadas; no estamos haciendo pasar una llamada simulada por una llamada real. Si el proveedor falla, MANDO conserva la incertidumbre y el operador pasa a un canal alternativo, sin repetir llamadas a ciegas.»

### 2:10–2:40 · La persona decide lo grave

**Pantalla:** propuesta sintética de parada de espectáculo, hash/versión/caducidad y decisión humana.

> «Para mostrar el límite de autoridad, añadimos una propuesta grave de prueba. Una conversación no puede autorizar por sí sola parar un espectáculo. El operador revisa la propuesta vigente y aprueba o veta. Si otro dato cambia mientras la revisa, debe volver a comprobarla. La auditoría conserva quién decidió y sobre qué contenido.»

### 2:40–3:00 · Evidencia y cierre

**Pantalla:** evidencia histórica saneada rotulada «N=1 llamada de prueba; no es directo». Si se añade un preflight, mostrar únicamente el resultado final disponible con etiqueta SIMULACIÓN, N, semilla y revisión.

> «Tenemos un antecedente real acotado: Telegram, Vercel, Railway y HappyRobot, una llamada de prueba aceptada con ETA de dos minutos. No certifica esta revisión. El rápido adaptado sigue en borrador. Nuestra propuesta es una sola autoridad persistente y responsabilidad humana visible.»

## Guion interactivo — 5 a 7 minutos

Objetivo: terminar alrededor de 6 minutos, dejando margen para una pregunta. El modo de canal se anuncia antes del primer aviso. Si hay un fallo, usar el plan B, no consumir todo el tiempo depurando.

| Tiempo | Pantalla/acción concreta | Quién actúa / frase guía | Resultado que comprobar |
|---|---|---|---|
| 0:00–0:40 | Sala, modo de canales y plano esquemático | Presentador: «Una autoridad persistente; esto es un ensayo» | Sin contactos ni tokens visibles; conexión/revisión identificables |
| 0:40–1:15 | Personal: dos sanitarios disponibles y coordinador, zona | Operador muestra registros preparados; no se entretiene rellenando todos los campos | Roles, disponibilidad y capacidad proceden de MANDO, no de una etiqueta local |
| 1:15–1:55 | Nuevo aviso: «Persona desmayada en puerta A», zona `gate_a` | En modo conectado autorizado, una persona envía Telegram; en modo seguro, operador usa el formulario y lo declara | Un incidente, necesidades y tarea/oferta persistidos; si falta zona, preguntar y esperar |
| 1:55–2:30 | Tarea ofrecida al equipo A | Operador revisa la oferta automática o, si no existe, ofrece a un actor libre. Persona de equipo responde «No puedo continuar» | Rechazo registrado con motivo; reserva de A no queda indebidamente ocupada; aparece/revisa alternativa |
| 2:30–3:15 | Plan/tarea alternativa B, lista de eventos | Presentador: «Antes A; ahora B; cambió porque A rechazó». Operador muestra el motivo, no reescribe la historia | Tarea vigente de B, destino correcto y ausencia de doble asignación |
| 3:15–4:05 | Aceptar, comunicar ETA y confirmar destino | Persona B: «Acepto, puerta A, cuatro minutos». Operador registra respuesta representada; si fue llamada autorizada, espera callback y revisa correlación | `accepted`/`en_route` según respuesta, ETA/destino explícitos; aún no `arrived` |
| 4:05–4:55 | Propuesta grave **sintética** preparada y vigente | Operador lee motivo/acciones/hash/caducidad y aprueba o veta. Presentador: «No afirmamos que un desmayo por sí solo justifique parar el evento» | Decisión humana ligada a contenido/versión; el agente no puede autoaprobar. Si no hay propuesta válida, enseñar la evidencia del preflight, no fabricar una |
| 4:55–5:40 | Confirmar llegada, localización y finalización por separado; revisar cierre | Persona B narra cada hito ficticio; operador registra cuando corresponda | Necesidades/tareas determinan si se puede cerrar. Si no, mostrar pendiente sin forzar cierre |
| 5:40–6:20 | Eventos y resultado final de preflight con N/semilla/revisión | Presentador, solo si el ensayo lo acredita: «Esta prueba simulada conserva el estado al reabrir SQLite; no equivale a alta disponibilidad» | Si falta evidencia final, decirlo y no afirmar prueba superada. No reiniciar servidor real ante público sin ensayo previo |
| 6:20–7:00 | Pregunta del jurado o límites | Presentador responde con la tabla siguiente | Una limitación explícita y siguiente validación necesaria |

**El imprevisto no es una emergencia real:** por defecto, rechazo preparado del equipo A. Para elección del jurado, preparar y ensayar también indisponibilidad, un aviso nuevo prioritario o rectificación confirmada. Mostrar plan anterior → hecho nuevo → plan posterior → motivo → acción; no fingir que un caso preparado fue aleatorio. La rectificación conserva al equipo activo y elimina la demanda retirada al liberarlo; las referencias ambiguas se aclaran, no se adjudican arbitrariamente a otra víctima. Si pide aforo/clima/rutas solo soportados por el simulador, declararlo fuera de alcance operativo.

Capacidades ilustradas: conversación externa (solo en modo conectado validado), coordinación con recursos limitados, adaptación e intervención humana. El formato/tiempo y los criterios oficiales del track requieren confirmación; no se presupone que este guion acredite su cumplimiento completo.

**Quién atiende el teléfono:** persona de equipo con número consentido y en whitelist, solo en modo conectado autorizado. No se marcan teléfonos en modo seguro. El antecedente telefónico real N=1 se identifica como histórico, nunca como directo ni prueba de llamadas universales.

**Comunicación pendiente:** si aparece `local_required`, el operador debe comunicar manualmente el aviso por un canal humano; no basta aprobar ni anotarlo en pantalla. Si una entrega es `uncertain`, no hay rellamada automática. Comprobar qué ocurrió antes de autorizar un seguimiento explícito.

## Plan B obligatorio

| Fallo | Qué decir | Qué hacer | Qué no hacer |
|---|---|---|---|
| HappyRobot no lanza, no hay audio o no llega callback | «El proveedor no ha confirmado; no lo marcamos como aceptación» | Revisar incertidumbre y contactar manualmente con la persona. Si se pasa a representación, hacerlo en el ensayo aislado rotulado; enseñar evidencia simulada disponible | Mezclar una respuesta ficticia con un envío real incierto, reintentar a ciegas o fabricar callback |
| Una actualización queda `local_required` | «Este aviso no se ha enviado por teléfono» | Operador comunica manualmente y registra lo efectivamente confirmado | Presentar aprobación o anotación local como entrega externa |
| Telegram/Vercel no entrega | «Este canal no está disponible ahora» | Usar formulario autorizado de sala si backend está sano; indicar que no se demostró Telegram | Cambiar a una base o `Map` en el puente como autoridad alternativa |
| Backend/SQLite no responde | «No podemos confirmar ninguna nueva operación» | Parar comandos; mostrar evidencia saneada guardada o ejecutar preflight aislado con nueva base, rotulado como simulación | Cambiar de DB silenciosamente, crear confirmaciones locales o restaurar producción en directo |
| Sesión caducada / conflicto 409 | «El servidor exige revisar identidad o versión» | Reautenticar fuera de proyección si hay secreto; recargar y revisar. Si no se resuelve rápidamente, usar evidencia | Desactivar autenticación, reciclar la clave idempotente para otro comando |
| No hay vídeo/capturas preparados | «Tenemos evidencia de terminal, no una grabación» | Mostrar solo salida y JSON saneado del preflight realmente ejecutado | Afirmar que existe un vídeo, usar capturas de otro árbol sin decirlo |
| El preflight también falla | «Esta candidata no supera el ensayo; no la damos por lista» | Mostrar fallo, explicar el alcance y parar la demostración operativa | Editar el reporte para que salga verde o esconder una regresión crítica |

El cambio a plan B se anuncia verbalmente y en la etiqueta de modo. No cambiar de simulación a proveedor real como respuesta a un fallo. No abrir consola de secretos, paneles privados del proveedor ni SQLite con datos personales ante el jurado.

## Preguntas previsibles del jurado

| Pregunta | Respuesta defendible |
|---|---|
| ¿Qué decide el agente? | HappyRobot conversa, extrae respuestas y propone; MANDO aplica reglas/transiciones y decide qué propuesta es admisible. No hay autoridad directa del modelo sobre la base o sobre aprobaciones graves. |
| ¿Qué valida MANDO? | Identidad/capacidad, entidad y versión, rol y disponibilidad, reservas, destino y etapas, vigencia de propuestas e idempotencia. La base persistida es la referencia. |
| ¿Dónde está la adaptación? | En reaccionar al rechazo o cambio confirmado: conservar el hecho, revisar el plan y mostrar una alternativa con motivo. No hace falta afirmar entrenamiento online para demostrar adaptación. |
| ¿Qué pasa si llega dos veces el mismo mensaje? | La inbox/comandos usan IDs estables. El mismo ID/contenido devuelve el resultado sin repetir el efecto; mismo ID con otro contenido se rechaza. Fuera del servidor, un proveedor aún puede dejar un envío incierto. |
| ¿Y dos operadores a la vez? | Versiones esperadas y transacciones impiden sobrescribir una decisión antigua o reservar capacidad dos veces. El conflicto obliga a revisar. No prometemos escalabilidad multi-región de SQLite. |
| ¿Puede evacuar sola la IA? | No debe poder aprobar esa acción: se exige decisión humana sobre contenido, versión y plazo vigentes. Autorizar una propuesta no demuestra que la evacuación física haya ocurrido. |
| ¿Cómo protegéis el acceso? | Sesión HttpOnly same-origin, token exigido también en loopback cuando está configurado y secretos separados. Logout implementado elimina cookies, no revoca credenciales copiadas. Navegador, expiración y acceso posterior requieren aceptación final; no es una certificación absoluta. |
| ¿Qué datos ve el jurado? | Solo datos ficticios o evidencia saneada. No contactos, números, tokens, transcripciones personales ni bases privadas. SQLite y backups requieren permisos, cifrado administrado y política de retención pendiente para uso real. |
| ¿Qué pasa si falla HappyRobot? | Outbox y estado incierto quedan auditados. No damos aceptación por hecha ni llamamos de nuevo a ciegas; el operador usa otro canal y registra lo realmente confirmado. |
| ¿Cuánto cuesta? | No hemos medido coste real por incidente aquí. Depende de conversación/minutos, workflows y alojamiento; antes de conectar se acuerdan límites y se mide una prueba consentida. No inventamos un ahorro. |
| ¿Aprende con cada festival? | No hay aprendizaje online demostrado. Hay historial, replanificación y experimentos de políticas fuera de línea; una mejora requiere evaluación y aprobación separadas. |
| ¿Es un gemelo digital? | El recinto es esquemático y el simulador sirve para ensayos sintéticos. No se ha calibrado un gemelo físico con datos reales ni se afirma predicción clínica. |
| ¿Qué habéis probado de verdad? | Antecedente histórico: Telegram → Vercel → Railway → HappyRobot, N=1 llamada telefónica real de prueba, accept y ETA 2 minutos, sin extrapolar al árbol actual. Rápido: SIMULACIÓN N=11 casos de nodos puros y N=7 tests locales; falta agente/trigger completo. Suites y preflight finales pendientes de consolidación. |
| ¿Está publicado el rápido adaptado? | No: v2 es borrador/no live; v1 sigue live en development. Falta validar respuesta HTTP, candidato público, diagnóstico y ejecución del agente. No presentamos crítica escrita a mano como razonamiento del modelo. |
| ¿Lo usaríais mañana en una emergencia? | No como sistema certificado. Es una candidata de demostración: requiere validación operativa/sanitaria, seguridad, privacidad, proveedores y procedimientos de continuidad. |

## Cierre recomendado

> «No queremos que una conversación parezca una operación resuelta. Queremos que cada compromiso, cambio y aprobación tenga una autoridad, un estado y un responsable verificables.»
