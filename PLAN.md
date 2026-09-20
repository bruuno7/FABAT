# Plan de implementación: coordinación multicanal de HappyRobot

## 1. Punto de corte y resumen para retomar

**Corte de código: `c738a0336b2b5896f66ca9d2f31e1971b60df2f5` (`c738a03`), 20 de septiembre de 2026.**

- Rama original del corte: `integracion/coordinacion-multicanal`.
- PR: [#22 — Base multicanal: operaciones compartidas y persistencia atómica](https://github.com/bruuno7/FABAT/pull/22), **mergeado en `main`** (`e863add`). La base multicanal ya no vive en una rama aparte.

### Actualización tras el corte — Fase 2, rama `integracion/fase2-coordinador`

- La exportación del coordinador ya está en código: `build_nodes.py` emite `fa_coordinador` (`coordinator_rpc_input`), `fa_coordinador_contexto` (`context_input`) y `fa_coordinador_entidades` (`request_input`) con la fuente exacta de `fa_operaciones.py` + `fa_coordinador.py`, sin recortes por expresiones regulares.
- `workflow_artifacts.py` monta el grafo `fa-coordinador`: contexto → contexto público → LLM → entidades → contexto ampliado → composición → commit → resultado. El nodo del LLM se referencia por su persistent ID y el nombre de su campo de propuesta se declara explícitamente: no se inventa un nodo de IA.
- Verificación local: 14 pruebas nuevas del artefacto del coordinador y 77 en la batería del plan, `OK`; `sandbox/test_local.py` con 44 mensajes simulados, `OK`.
- Sigue **sin tocarse la plataforma**: no se ha creado ni instalado `fa-coordinador`, no hay trigger ni comprobación con el modelo real. `admin.py` todavía solo monta operaciones.
- Pendiente inmediato: comando de instalación autorizado, fork de la versión publicada de operaciones, `workflows-v2.json` con el estado LIVE real y el arnés, y `fa-comunicaciones` con recuperación programada.
- Todos los cambios de implementación realizados hasta ese corte están commiteados y subidos.
- La implementación se detuvo por indicación del usuario. Este documento registra el plan y el traspaso; no significa que se haya terminado ni que se deba reanudar sin pedirlo.
- La decisión confirmada es **continuar el plan original HappyRobot/Redis**, no sustituirlo por la arquitectura MANDO/SQLite del PR #23.
- No se ha hecho merge a `main`, cambiado el webhook del bot existente, migrado datos operativos v1 ni efectuado el corte a producción.
- El check de Vercel del PR para `c738a03` figura como `SUCCESS`. Eso acredita el check de despliegue, no la aceptación funcional de todo el plan.

**Dónde quedó exactamente:** existe la base de persistencia y operaciones, un consumidor exportable, adaptadores Telegram v2 y un coordinador local que prepara transacciones. El workflow aislado de operaciones está publicado en development. Falta conectar el coordinador local al LLM/workflow, montar comunicaciones y recuperación programada, terminar Telegram v2 y abordar voz, revisor, Sala/historial y aprendizaje.

**No confundir:** hay código reutilizable anterior de voz, Sala, simulador e historial en el proyecto y en el PR #18. Su existencia no significa que esas piezas estén integradas con el nuevo estado v2.

### Estado por fase

| Fase | Estado al corte | Qué falta para cerrarla |
|---|---|---|
| 0. Inventario, aislamiento y línea base | Parcial, con Preview y Redis de pruebas comprobados | Verificación del run completo, scheduler, retornos entre workflows y pruebas de canales |
| 1. Contrato, API técnica y operaciones | Base implementada; últimas extensiones pendientes de revalidación final | Validar cambios finales de eventos derivados, programación y recibos; sincronizar código desplegado |
| 2. Telegram sobre v2 | Parcial | LLM/coordinador, comunicaciones, recuperación, comandos y recorrido completo |
| 3. Voz saliente e identidad | Pendiente de integración v2 | Adaptador telefónico, identidades vinculadas y callbacks unificados |
| 4. Voz entrante y Web Call | Pendiente de integración v2 | Entrada, herramientas, identidad y retorno multicanal |
| 5. Herramientas, revisor y replanificación | Pendiente; algunos tipos de evento ya declarados | Handlers, workflow revisor, aprobaciones y reevaluación efectiva |
| 6. Sala e historial | Pendiente de integración v2 | Proyección sin efectos, interfaz y acciones humanas sobre el núcleo común |
| 7. Aprendizaje y evaluación | Pendiente; tipos de evento preparados | Ciclo de lecciones, evaluaciones integradas y documentación final |
| 8. Migración, corte y reversión | Pendiente | Ensayo de migración/rollback, aceptación y autorización de corte |

## 2. Qué se ha implementado y dónde

### Persistencia, contrato y API técnica

- `motor/happyrobot/event_contract.json`: contrato de eventos v2.
- `puente/src/lib/event-contract.ts`: validación de eventos, entidades, commits y mensajes.
- `puente/src/lib/redis-state.ts` y `redis-scripts.ts`: CAS con versiones, deduplicación, reservas, inbox/outbox, leases, asentamiento y reintentos acotados.
- Los documentos y eventos conservan JSON original para evitar que Lua/cjson convierta listas vacías en objetos.
- Los namespaces `test-...` tienen caducidad de pruebas; no se aplica esa política a `dev-...` ni `live-...`.
- `puente/src/hr/state-router.ts`: API privada con permisos separados de ingreso, lectura, commit y entrega.
- `puente/src/lib/operation-context.ts`: lectura acotada de entidades relacionadas; no selecciona recursos ni interpreta mensajes.
- Endpoints preparados para contexto de operaciones/coordinador, estado del evento y lectura de lotes de inbox/outbox.
- En el último commit se añadió soporte de transporte para `StateCommit.events`, eventos derivados atómicos, `not_before` y registro de writes/messages en el stream. **No equivale a tener los handlers de todos esos eventos ni un scheduler desplegado.**

### Núcleo y consumidor

- `motor/happyrobot/sandbox/fa_operaciones.py`: creación/actualización de avisos, ofertas por capacidad, roles mediante permiso vinculado y caducable, aceptación/rechazo, disponibilidad, ETA, hitos, preguntas y cierre.
- El cierre solicitado pide confirmación; las tareas requeridas sin completar impiden el cierre automático.
- Se añadieron índices de incidentes y preguntas pendientes por actor, asociación de conversación y limpieza de índices al cerrar.
- `fa_consumidor.py`: pasos puros para obtener snapshots, preparar operaciones, recalcular tras conflicto, finalizar intentos y normalizar resultados.
- El Sandbox Python de HappyRobot **no tiene acceso a red**. Las peticiones las realizan nodos Webhook externos al Sandbox.
- `build_nodes.py` exporta el código exacto de operaciones/consumidor y las entradas `fa_snapshot`, `fa_finish`, `fa_result`, sin recortar ese código por expresiones regulares.
- `workflow_artifacts.py`: construcción y referencias de los nodos del consumidor.

### Coordinador local: último bloque trabajado

- `motor/happyrobot/sandbox/fa_coordinador.py` recibe una **propuesta estructurada**; todavía no llama por sí mismo a un LLM.
- Construye contexto sin contactos ni permisos internos, comprueba referencias del remitente y prepara las operaciones sobre una copia del snapshot.
- Fusiona las escrituras y mensajes en **un commit del evento original**, evitando crear un aviso a medias si falla una operación posterior.
- Contempla conversación/aclaración, nuevo aviso, actualización, aceptación/rechazo, ETA, llegada/localización/finalización, disponibilidad, preguntas/respuestas y solicitud de cierre.
- Mantiene historial breve de conversación, decisiones con versiones leídas y referencias deterministas.
- Da prioridad a referencias verificadas del evento; una selección ambigua entre varias preguntas/incidentes exige aclaración.
- Conserva capacidades requeridas aunque no exista personal disponible: una tarea de coordinación no sustituye una tarea médica pendiente.
- `motor/happyrobot/coordinator-prompt.json`: prompt y JSON Schema de la propuesta del LLM.
- `sandbox/test_coordinador.py`: pruebas locales del ensamblado y las restricciones.
- **Actualizado:** la exportación ya está en `build_nodes.py` (`fa_coordinador`, `fa_coordinador_contexto`, `fa_coordinador_entidades`) y `workflow_artifacts.py` monta el grafo `fa-coordinador` con pruebas locales. Falta el comando de instalación autorizado y comprobarlo con el modelo real; `admin.py` sigue montando solo operaciones.

### Telegram y comunicaciones locales

- `puente/src/lib/telegram-v2.ts` y `src/telegram/router.ts`: cohorte v2 explícita en namespace de pruebas/desarrollo, dejando v1 como comportamiento por defecto.
- Persistencia conjunta de identidad Telegram verificada, permiso temporal de rol y evento; el PIN no se guarda en el evento.
- Callback ligado a destinatario, mensaje entregado, incidente y asignación; se soportan aceptación y rechazo del formato v2.
- Recibos de entrega indexados por destinatario y mensaje de proveedor; `reply_to_message_id` permite vincular texto a la pregunta concreta.
- Respuestas conversacionales sin inventar un incidente para poder enviarlas.
- `state-delivery.ts`: simulación por defecto, contacto verificado y lista blanca para Telegram real, validación de `ok` y `message_id` del proveedor, control de mensajes obsoletos y reintentos limitados de 429 explícitos.
- Un timeout/5xx ambiguo no provoca reenvío ciego.
- **Faltan el workflow `fa-comunicaciones`, la recuperación programada real, el resto de la adaptación de comandos/hitos y la prueba Telegram completa.**

### Herramientas de trabajo

- `motor/happyrobot/admin.py`: cliente MCP autorizado para inventario, sincronización de variables y montaje/pruebas del workflow de operaciones. Usa las dependencias existentes de `motor/server` y `mcp-remote@0.13.5`.
- `motor/happyrobot/probe_workflows.py`: prueba prevista del workflow nativo; sus intentos no se completaron por el error 502 de arranque.
- `motor/happyrobot/workflows-v2.json`: manifiesto de IDs y Preview. **Necesita actualización de estado antes de retomar; ver apartado 3.**
- `puente/scripts/provision-state-secrets.ts`: preparación/verificación local y subida por stdin de las claves al Preview de esta rama.
- `.vercelignore`: exclusiones explícitas de archivos privados para despliegues locales. La comprobación previa detectó que `.gitignore` por sí solo no excluía `puente/.env.test` de ese despliegue; se corrigió antes de subirlo.

### Commits de referencia

| Commit | Contenido principal |
|---|---|
| `0303182` | Primera base multicanal y persistencia técnica |
| `335551e` | Núcleo ampliado y comprobación con Redis real |
| `89fb88a` | Consumidor, Telegram aislado y entrega durable |
| `6e506af` | Configuración del Preview, exclusiones y prueba HTTP con Redis real |
| `81015bc` | Contexto de operaciones, artefactos y montaje parcial de HappyRobot |
| `c738a03` | Coordinador local, índices/recibos y últimas extensiones de eventos |

## 3. Estado de los servicios y configuración

### HappyRobot

Se crearon recursos separados en la carpeta `PR22 - Pruebas multicanal aisladas` (`01a0bbc8-0fa0-74cc-be7d-e9a9c255aa9a`). No se sustituyeron los workflows existentes del bot.

| Recurso | IDs y estado comprobado |
|---|---|
| `fa-pr22-operaciones` | Workflow `01a0bbc8-0fde-77ab-937d-c26d69dddf8e`; versión `01a0bbc8-0fec-77d8-8a67-e16efe47cfd7`; v1 publicada en **development**, LIVE |
| Trigger de operaciones | `01a0bbc8-0ff5-76f5-afc6-a0958b065cf5`; parámetro `event_id`; enhanced security configurada |
| Respuesta de operaciones | Nodo `01a0bbd9-bc31-78d9-9c2b-372bdee613f2`, `Resultado operación` |
| `fa-pr22-pruebas-operaciones` | Workflow `01a0bbed-be77-748c-8d48-11fbaf46e2ed`; versión `01a0bbed-be82-77af-817d-7102a858d03c`; **borrador**, no LIVE |
| Trigger del arnés | `01a0bbed-be91-7e3e-98c2-8fc674f73a25` |
| Call Workflow del arnés | `01a0bbed-be95-75f7-86b4-2368c6888adf` |

Editores devueltos por la plataforma:

- [Operaciones](https://platform.eu.happyrobot.ai/hackspainteam6/workflows/ytrf1jn1zefs/editor/r8iby4ztthjp)
- [Arnés de pruebas](https://platform.eu.happyrobot.ai/hackspainteam6/workflows/0l0vpukwtmxc/editor/mh7kyk9nf7hy)

**Desajustes importantes para retomar:**

1. `workflows-v2.json` todavía dice `status: "draft"` para operaciones, pero la versión está publicada. No editar esa versión directamente: hacer fork y registrar sus IDs reales.
2. El manifiesto no incluye todavía el arnés de pruebas.
3. El núcleo y coordinador del commit `c738a03` no se han vuelto a exportar completos a HappyRobot. El código en Git y el workflow publicado no están sincronizados.
4. No existen aún los nuevos workflows integrados de coordinador, comunicaciones, recuperación, voz, revisor o aprendizaje. No asumir que los nombres del diseño ya son recursos creados.
5. No hay un Cron v2 de recuperación activado por este trabajo.

### Vercel y Redis

- Equipo Vercel: `FABAT`, slug `fabat1`, ID `team_BlUk2LQTWR2ARD4AZ2Z3EJdQ`.
- Proyecto: `fabat`, ID `prj_uNJEqq0IJGmVumWtzbUuJZnZjiVe`.
- Configuración añadida únicamente a `preview` y `gitBranch=integracion/coordinacion-multicanal`.
- Últimos valores configurados para la rama: `HR_STATE_API_ENABLED=1`, `HR_STATE_NAMESPACE=test-pr22`, `HR_STATE_TELEGRAM_MODE=off`, `HR_STATE_DELIVERY_MODE=sink`.
- Los despliegues manuales de pruebas usaron el override `HR_STATE_NAMESPACE=test-pr22-6e506af`.
- Último Preview probado funcionalmente durante la implementación: `https://fabat-4qa23r3q0-fabat1.vercel.app`, deployment `dpl_ERHK5Kpcno8KE6NKgbNe3WE6ZgTv`.
- Ese URL es un despliegue inmutable anterior al último bloque `c738a03`. Sigue siendo el URL del manifiesto y el valor que se configuró en `STATE_API_URL` del workflow de operaciones.
- El push de `c738a03` tiene check Vercel satisfactorio: [inspector del check](https://vercel.com/fabat1/fabat/GoVMvNe7NKqjNWvoFTo6PMHdV2Sz). No se hizo una aceptación funcional de ese Preview nuevo ni se actualizó automáticamente el workflow para apuntar a él.
- Antes de continuar, elegir y verificar un único Preview/namespace, actualizar referencias y volver a sembrar fixtures. No mezclar datos de `test-pr22` con los de `test-pr22-6e506af`.
- La protección de Vercel se mantuvo activada. No se compraron números ni se modificaron variables de producción.

### Secretos: ya preparados, no volver a bloquearse aquí

`puente/.env.test` existe localmente, está ignorado por Git y se verificó con permisos `0600`. Contiene las claves privadas de pruebas:

- `HR_STATE_INGRESS_SECRET`
- `HR_STATE_READ_SECRET`
- `HR_STATE_COMMIT_SECRET`
- `HR_STATE_DELIVERY_SECRET`
- `VERCEL_AUTOMATION_BYPASS_SECRET`

Las cuatro claves de API se copiaron como sensibles al Preview de la rama. También se configuraron, junto con el acceso al Preview, como variables ocultas de development en el workflow aislado de operaciones; sus valores de staging/production quedaron vacíos.

**Preferencia explícita del usuario:** utilizar el secreto de automatización existente; no exigir una rotación para continuar ni insistir en cambiarlo. No hace falta pedir al usuario que edite de nuevo `.env.test` por ese motivo.

No incluir valores en este documento, código, prompts, fixtures, logs o commits. No extraer tokens internos del CLI. Si una sesión oficial caduca, usar su login normal. No ejecutar de nuevo la subida de variables a ciegas: primero comprobar qué está configurado, sin descifrar valores innecesariamente.

## 4. Verificación realizada y límites de la evidencia

| Evidencia | Resultado y alcance |
|---|---|
| Pruebas iniciales contra Redis | 7 pruebas pasaron en la sesión anterior, con prefijos aislados y caducidad |
| API de Preview con Redis real | 8 tests pasaron: permisos, deduplicación, listas JSON, CAS concurrente Telegram/teléfono, reconciliación, cuarentena, entrega simulada y diferidos |
| Última suite Python ejecutada antes de las últimas ampliaciones | 61 tests pasaron, incluyendo las primeras pruebas del coordinador local |
| Batería del plan tras la Fase 2 (`integracion/fase2-coordinador`) | 77 tests pasaron, incluidos los 14 del artefacto del coordinador; `test_local.py` con 44 mensajes simulados |
| Última suite Node ejecutada antes de las últimas ampliaciones | 95 tests pasaron; 2 suites remotas opt-in se omitieron en esa ejecución local |
| Escenarios v1 | Los 11 escenarios existentes pasaron; 44 mensajes **simulados** |
| Typecheck/build | Pasaron durante el trabajo; el check de Vercel del último commit también figura como satisfactorio |
| Nodos de HappyRobot | 9 nodos de operaciones se probaron individualmente; la revisión de referencias terminó con 0 referencias rotas antes de publicar |
| Workflow nativo completo | **No verificado**: los intentos de arranque devolvieron HTTP 502 |
| Telegram/telefonía físicos sobre v2 | **No realizados**; ninguna entrega simulada acredita una llamada o mensaje real |

Las ampliaciones finales de `required_roles`, algunas pruebas nuevas y los cambios de eventos derivados/`not_before` no recibieron una nueva pasada completa antes de detener el trabajo. Los números anteriores no deben presentarse como certificación de todo `c738a03`.

### Bloqueo de arranque de HappyRobot

- `trigger_run`, tanto mediante MCP como mediante el cliente autorizado, devolvió `502 origin_bad_gateway` desde `api.platform.eu.happyrobot.ai`.
- Los inventarios consultados después no mostraron runs del nuevo workflow.
- Se probó un arnés con Call Workflow. Su prueba de nodo devolvió un `child_run_id` de ejemplo y un resultado de timeout; **no se confirmó una ejecución real del hijo**.
- La publicación también devolvió avisos informativos de referencias. Las pruebas individuales no sustituyen una ejecución completa que compruebe esas referencias en runtime.
- No seguir repitiendo peticiones de arranque sin comprobar el estado. Registrar el fallo, respetar el backoff y avanzar con tareas independientes.
- Este bloqueo no explica todo lo pendiente: faltan implementaciones e integración, no solo levantar el endpoint.

### Particularidades comprobadas de la plataforma

- El Sandbox Python no puede hacer peticiones de red; separar cálculo puro de nodos Webhook.
- Los Webhook v2 utilizados devolvieron los campos del cuerpo **directamente**: `status`, `event_json`, etc. No usar automáticamente `response.status` en esos nodos.
- AI Extract tiene sus propias rutas de salida; inspeccionarlas en la versión concreta. No extrapolar las de Webhook.
- Se añadieron `api_status_code` y JSON serializado de resultado en endpoints propios para pasar información inequívoca al Sandbox.
- `test_all` puede devolver `skipped` con texto `success`; no contarlo como un nuevo test ejecutado.
- Un `set_custom_output` o un esquema generado no demuestra efectos reales. Confirmar estado en Redis y runs.
- `loop_end` puede aparecer como hijo del último nodo del cuerpo, no directamente del loop. No asumir esa relación al reconstruir el grafo.
- Referencias a nodos existentes: usar persistent IDs reales, no nombres ni índices de otra petición. Tras cambios masivos, ejecutar `fix_broken_vars` y revisar lo que no pueda resolver.

## 5. Orden recomendado para la siguiente sesión

1. **Revalidar sin empezar de cero:** estado de Git, último `main`, PR #22, versiones publicadas, consumidores y responsables. Mantener el trabajo de esta rama; no resetear ni incorporar el PR #23.
2. **Reejecutar las suites sobre `c738a03`** antes de añadir funcionalidad. Revisar especialmente eventos derivados, `not_before`, recibos, capacidades requeridas, cierre e índices de preguntas.
3. **Corregir el manifiesto y alinear el despliegue:** registrar el estado LIVE real, incluir el arnés, obtener el Preview del SHA elegido y configurar el mismo URL/namespace en todos los consumidores. Fork de operaciones antes de actualizar código publicado.
4. **Terminar el coordinador local y exportarlo:** añadir su artefacto a `build_nodes.py`; inicializar de forma autorizada el actor de servicio `service-coordinator` y el directorio v2; no inventar personal disponible ni copiar el roster real sin un plan de migración.
5. **Crear y cablear `fa-coordinador`:** lectura de contexto → contexto sin contactos → LLM con el esquema de `coordinator-prompt.json` → carga de entidades necesarias → validación/composición → commit atómico → resultado confirmado. Separar eventos estructurados de interpretación de texto.
6. **Crear `fa-comunicaciones` y recuperación programada:** consumir outbox, entregar por adaptador, registrar proveedor/recibo y recuperar pendientes. Los endpoints batch y funciones locales de recuperación no son un Cron en funcionamiento.
7. **Cerrar Telegram v2** con comandos, botones, ETA/hitos, múltiples preguntas, respuestas rápidas y reconexión. Probar el recorrido entero antes de activar una cohorte real.
8. **Implementar fases 3–7** descritas abajo: voz, revisor/aprobaciones, proyección/Sala e historial, aprendizaje.
9. **Ensayar fase 8**, completar la matriz de aceptación y preparar la reversión. Solo después solicitar el corte real.

Puntos concretos a revisar en el código parcial:

- Añadir handlers y productores reales de `coordination.requested`, revisión, lecciones y vencimientos. Declararlos en el enum no los implementa.
- Validar que el estado, outbox y eventos derivados se confirman juntos; un fallo en un hijo no deja efectos parciales ni duplica el padre.
- Comprobar `not_before` tanto en la cola como en invocaciones directas por ID; el tiempo de recepción no debe confundirse con el de procesamiento.
- Mantener coherencia entre JSON Schema, validación TypeScript y validación Python.
- Comprobar límites de 32 entidades y de mensajes/preguntas con varios incidentes y equipos; fallar de forma explícita, no truncar o perder contexto.
- Mantener las referencias verificadas de Telegram por encima de las sugeridas por el LLM; si hay varias posibilidades, aclarar.
- Revalidar que el cierre limpia asociaciones y preguntas sin afectar otros incidentes activos.

## 6. Objetivo, decisiones y arquitectura completos

Consolidar Telegram y llamadas en un coordinador y un revisor, con operaciones compartidas, Redis atómico, una Sala de supervisión e historial derivados y aprendizaje aprobado por una persona, preservando el flujo existente durante la migración.

### Decisiones acordadas

- HappyRobot interpreta, propone planes, selecciona capacidades, pregunta, reevalúa y coordina.
- Telegram y teléfono son canales de un mismo incidente, no productos con estados o despachadores independientes.
- **Un coordinador y un revisor independiente**, no seis especialistas obligatorios.
- `puente/` puede autenticar, validar, persistir, comparar versiones y entregar; no interpreta avisos ni elige recursos.
- Voz entrante y saliente; empezar reutilizando el despacho saliente existente.
- Conservar preguntas trabajador → informante → trabajador, ubicación, disponibilidad, ETA, llegado/localizado/finalizado y cierre explícito por el equipo.
- Si solo el agente infiere que algo está resuelto, pedir confirmación al informante. El silencio y el fin de una llamada no cierran la incidencia.
- Redis es la autoridad operativa; SQLite es proyección, historial y soporte de lecciones, no un segundo despachador.

### Arquitectura objetivo

```text
Telegram / web / eventos estructurados
             | adaptador autenticado + ingreso durable
             v
      fa-coordinador <---- tools de fa-voz-entrada / fa-voz-salida
             |
             +-- contexto operativo y lecciones aprobadas
             +-- gemelo/rutas/protocolos opcionales
             +-- fa-revisor cuando corresponde
             v
       fa-operaciones
  valida transición y prepara cambios
             | API técnica CAS -> Redis: estado + eventos + outbox
             v
      fa-comunicaciones ---- Telegram / otros adaptadores
             +-------------- fa-voz-salida
                                  | resultado normalizado
                                  v
                         operaciones/coordinador

Eventos confirmados --> Sala + SQLite (proyección; no reingesta)
Cierre confirmado ---> fa-aprendizaje (propuesta; aprobación humana)
```

### Workflows objetivo: seis principales y uno de aprendizaje

1. **`fa-coordinador`**: evolucionar `fa-entrada-tg`, recuperar contexto, interpretar lenguaje y planificar con herramientas. Botones y eventos estructurados no necesitan reinterpretación LLM. Retornos JSON explícitos para voz.
2. **`fa-operaciones`**: consolidar directorio, planes, asignaciones, aceptación, ETA, rechazo, disponibilidad, preguntas, progreso, aprobación y cierre en una máquina de estados compartida.
3. **`fa-comunicaciones`**: consumir outbox, elegir el adaptador autorizado, enviar y registrar resultado/reintentos. No decidir destinatarios de negocio; no crear un workflow por rol.
4. **`fa-voz-salida`**: reutilizar `mando-despacho-telefono`, con `purpose` de oferta, pregunta o actualización y referencias comunes.
5. **`fa-voz-entrada`**: identidad validada, consulta y registro sobre el mismo núcleo. PSTN solo con número/trigger comprobados. Web Call puede necesitar un wrapper de entrada aparte.
6. **`fa-revisor`**: contexto y decisión versionados; salida confirmar/corregir/escalar. Sin permiso de despacho directo ni ejecución del backend decisor antiguo.
7. **`fa-aprendizaje`**: procesar cierre y episodios fuera del camino urgente; proponer lecciones con evidencia, nunca autopublicar políticas o prompts.

Los triggers que exijan entradas distintas pueden tener adaptadores mínimos adicionales. Durante la migración pueden coexistir wrappers v1/v2, pero no dos autoridades sobre un mismo incidente. No crear canales email/SMS hasta activarlos realmente.

## 7. Contrato, invariantes y persistencia

### Evento canónico

Campos base: `schema_version`, `event_id`, `event_type`, `occurred_at`, `received_at`, `channel`, `actor_id`, `conversation_id`, `incident_id?`, `assignment_id?`, `question_id?`, `causation_id?`, `correlation_id`, `source_message_id?`, `call_id?`, `payload`. El último avance añade `not_before?` para vencimientos programados.

- `event_id` deduplica; `correlation_id` solo traza el recorrido.
- Conservar tipos y normalizar raíz/`data.*` una sola vez; rechazar representaciones contradictorias, no concatenarlas.
- Roles, permisos, namespace y destinos proceden de identidad/configuración de confianza, no del texto del usuario ni de una declaración del LLM.
- Entrada y destino de una comunicación pueden usar canales distintos.

Entidades: actor, incidente, asignación, pregunta, conversación, decisión/revisión/aprobación, inbox/outbox y lección. Distinguir gravedad 1–5 de prioridad 0–10. Un rol no equivale a identidad ni a teléfono.

La caducidad de 45 minutos prevista para la asociación automática de conversación no debe borrar incidentes o asignaciones. No reabrir un cerrado silenciosamente. Una pregunta pendiente mantiene su identidad y contexto; una respuesta que no la resuelve no debe darse por contestada.

### Invariantes obligatorios

- Mismo efecto por botón, texto y voz.
- Nadie modifica asignaciones ajenas; ETA/localización no aceptan implícitamente ofertas rechazadas o ya cubiertas.
- Un ganador por tarea requerida; un incidente con varias capacidades puede tener varios equipos.
- Capacidades diferentes no se sustituyen indiscriminadamente. El organizador coordina una carencia, no satisface por ello la tarea médica o de bomberos.
- Persistir pregunta y asociación antes del envío. Diferenciar oferta enviada, aceptada y equipo en camino.
- Un evento repetido no vuelve a asignar, notificar o cerrar; uno tardío no hace retroceder estado.
- `call.ended` no completa asistencia; rectificaciones explícitas generan nuevos eventos versionados.
- Acciones graves requieren aprobación humana verificable vinculada a decisión y versión.
- Con varios equipos, finalizar una tarea informa al usuario; el cierre global exige no dejar tareas críticas abiertas o un cierre autorizado.

### Persistencia y entrega

- Scripts Lua fijos con comparación de versiones; un pipeline o una lectura seguida de MULTI no sustituyen CAS.
- Estado, reservas, deduplicación, eventos y outbox se confirman atómicamente.
- Conflicto de versión: recargar y recalcular con límite; no reenviar un snapshot obsoleto.
- Aceptar el webhook solo tras ingreso durable; un fallo de almacenamiento debe ser recuperable por el proveedor.
- Claim de outbox con lease y token; confirmación real del proveedor y recuperación programada.
- Vercel no garantiza que sobrevivan trabajos locales fire-and-forget tras devolver la respuesta.
- Timeout ambiguo de Telegram: `unknown`, no reenvío automático presentado como exactly-once.
- API sin comandos Redis arbitrarios, scripts enviados por el LLM, URLs libres, borrados masivos ni claves fuera del namespace.
- SQLite recibe proyecciones redactadas y ordenadas por versión; no llama a `Session.report` ni despacha.
- Lecciones con aprobación versionada en supervisión; Redis puede guardar una copia de lectura de las aprobadas, no otro editor independiente.

## 8. Qué incorporar del PR #18 y qué no

El análisis original se hizo sobre `revision-mando` en `1c4f19f`, con 217 archivos cambiados; era restitución de trabajo revertido, no un parche pequeño de llamadas. La rama de integración ya incorporaba PR #19 y después PR #16. Revalidar las referencias actuales antes de portar más cambios.

| Pieza | Decisión y adaptación |
|---|---|
| Sala en pestañas (`static/sala.*`) | Integrar incidentes multicanal, personas, comunicaciones, decisiones, revisiones y aprobaciones; mostrar coordinador/revisor, no seis agentes ficticios |
| `memoria_db.py`, `db.py`, `ledger.py` | Integrar con tests como historial/auditoría; migrar con copia y validación, sin desplazar la autoridad Redis |
| Contexto, recursos, rutas, previsiones y ensayos | Reutilizar separando datos operativos y simulados; gemelo opcional, con N/procedencia y sin inventar ETA real |
| Decisión rápida y revisión | Un coordinador y un revisor; ejecución única y revisión versionada sin despacho directo |
| Supuestos e invalidación | Reactivar al mismo coordinador por rechazo, nueva información, vencimiento o bloqueo |
| Lecciones y episodios | Propuesta/aprobación/revocación con evidencia; solo aprobadas entran en contexto |
| Evals y regresiones | Adaptar a los nuevos canales/contratos; conservar separados los tests del simulador |
| Privacidad, seguridad y diagnóstico | Conservar mejoras pertinentes de `comms_happyrobot`, `security`, `privacy`, `doctor` y sus tests |
| Seis especialistas y `abanico.py` | Fuera del circuito operativo; referencia/experimento, no segunda autoridad |
| Decisor local de respaldo | Solo simulación explícita; una caída de HappyRobot deja cola/degradación/escalada, no despacho real alternativo |
| Confianza/autonomía adaptativa | Métricas, no reducción automática de controles; aceptación no demuestra corrección |
| Archivado masivo de carpetas/generados | Fuera de alcance; no eliminar pantallas, `web/`, `agentes/` ni incorporar regresiones generadas indiscriminadamente |
| Docs/pitch en inglés | Incorporar tras contrastar con evidencia y arquitectura vigentes |

No mergear el PR #18 entero ni cherry-pickear ciegamente su restitución. Portar cambios funcionales, dependencias y atribución. Coordinar `motor/server/` y Sala con sus responsables; no cambiar `motor/contracts.py` o `motor/INTERFACES.md` sin acuerdo.

Riesgos de integración ya identificados en el diseño original:

1. `toMandoPublicReport` convierte `agent_reply` en `public_report`: no usarlo para reingestar cada respuesta v2.
2. `TelegramMirror._incident` llama a `Session.report()`: no es una proyección pasiva.
3. Herramientas del PR dependen de recursos/IDs/reloj del simulador; no sirven directamente para personas y tiempo reales.
4. `dispatch_progress`, `dispatch_result` y `dispatch_outcome` deben reconciliarse como un mismo ciclo, no tres ejecuciones.
5. Read-modify-write de los Sandbox v1, asociación por último incidente y reglas duplicadas no garantizan exclusión mutua.
6. Responder antes de guardar la pregunta crea carreras con respuestas rápidas.
7. HTTP 200 del puente o un nodo verde no acreditan entrega al proveedor.
8. Los exportadores antiguos todavía tienen rutas con placeholders/concatenación de variables: ampliar la vía exacta, no copiar ese patrón a v2.
9. Cifras y pruebas históricas del PR no certifican esta integración.

## 9. Fases completas y criterios de salida

### Fase 0 — inventario, aislamiento y línea base

1. Revisar Git, último main/#18, consumidores y responsables. Al reanudar implementación, `git pull --rebase` solo con árbol seguro; nunca resetear trabajo ajeno.
2. Inventariar/exportar configuraciones sin secretos: versiones LIVE, entornos, triggers, nodos de respuesta y llamadas entre workflows. Fork de versiones publicadas.
3. Capturar línea base de Telegram, callbacks telefónicos y estado esperado; confirmar destinatarios y permisos de pruebas reales.
4. Preparar namespace y sink aislados. Development puede apuntar a servicios reales y no demuestra aislamiento por sí solo.
5. Verificar Redis/EVAL/CAS, scheduler, triggers/retornos de voz y bindings de credenciales. No cambiar proveedor, comprar números o quitar protección para salvar un bloqueo.

**Salida:** base reproducible, export/backups autorizados, versiones de reversión identificadas y cero envíos a terceros.

### Fase 1 — contrato, API técnica y operaciones

1. Completar contrato JSON y validación TypeScript, manteniendo adaptadores de payload antiguo.
2. Consolidar núcleo puro, identidad, estados y capacidades sin el fallback indiscriminado a cualquier rol.
3. Completar CAS/inbox/outbox y pruebas de concurrencia, duplicados y timeout.
4. Namespaces versionados sin borrar v1.
5. Exportador exacto, fallo ante placeholders, manifiesto real y comparación del artefacto local con el desplegado.
6. Revalidar las últimas extensiones de eventos derivados, programación y recibos del corte actual.

**Salida:** pruebas locales y Redis real acreditan ausencia de pérdida de cambios y una sola transición/outbox por evento repetido.

### Fase 2 — Telegram sobre v2

1. Preservar update/message/reply/callback IDs, identidad, asignación y argumentos; ETA/localización no se confunden con correlación.
2. Ingreso durable, PIN/permisos equivalentes, ack neutro y selección v1/v2 explícita.
3. Separar ingreso, entrega y proyección; la ruta nueva no transforma cada respuesta en otro reporte a MANDO.
4. Conectar `fa-coordinador` con contexto, modelo, herramientas y transacciones validadas.
5. Persistir preguntas antes de enviarlas; soportar múltiples preguntas y varias incidencias del mismo informante.
6. Crear `fa-comunicaciones` y recuperación programada con resultados reales del proveedor.
7. Completar comandos, estados, botones e idiomas relevantes; probar antes de cambiar el bot.

**Salida:** recorrido Telegram completo sobre v2, con roles, ETA, estados y conversación, sin crear incidentes por respuestas de ubicación.

### Fase 3 — llamadas salientes e identidad multicanal

1. Adaptar `mando-despacho-telefono` a `fa-voz-salida` con `purpose` de oferta/pregunta/actualización y contrato común.
2. Vincular persona, Telegram y teléfono mediante registro autorizado; un alias no prueba identidad.
3. Resolver teléfonos solo en el adaptador, con lista blanca, bloqueo de emergencias y límites de intentos/concurrencia.
4. Mapear `action_id` legado, `assignment_id` y `call_id`; confirmación provisional y callback final no repiten efectos.
5. Sustituir la doble vía de resultado al backend y al equipo antiguo, conservando compatibilidad de llamadas en curso.
6. Registrar rechazo y disponibilidad, incluyendo desconocida; replanificar sin esperar indefinidamente.

**Salida:** Telegram → llamada consentida → aceptación/ETA → actualización al informante, más pregunta por voz → respuesta Telegram al trabajador correcto.

### Fase 4 — voz entrante y Web Call

1. Verificar número y trigger entrante. No presentar el borrador Web Call como PSTN operativo.
2. Tools de consultar contexto, registrar mensaje, responder pregunta y actualizar asignación sobre el mismo contrato.
3. No crear un incidente por cada turno o por la transcripción final.
4. Retorno síncrono corto de consultas/transiciones; revisión profunda y aprendizaje fuera de la llamada inmediata.
5. Comprobar Call Workflow, nodo de respuesta y timeout.
6. Un desconocido puede reportar, no adquirir privilegios por decir que es personal.
7. Si sigue en llamada, actualizar la sesión; si colgó, usar un canal verificado o callback consentido, sin presuponer Telegram.
8. Compartir prompts/tools/permisos con Web Call; wrapper adicional solo si el trigger lo exige.

**Salida:** entrada por voz → incidente único → equipo Telegram → preguntas, respuestas e hitos por canales realmente disponibles.

### Fase 5 — herramientas, revisor y replanificación

1. Adaptar `cerebro_tools.py`, `observar.py`, protocolos y gemelo con proveedores separados de datos operativos y simulados.
2. No conectar `decidir` del backend antiguo como segundo ejecutor.
3. Decisiones con ID, versión base, prioridad, capacidades/tareas, destinatarios, justificación, supuestos y plazos de reevaluación.
4. Revisor independiente para incertidumbre, conflicto o impacto, no para cada ETA/pregunta.
5. CONFIRMA no despacha; CORRIGE propone sobre versión vigente; revisión tardía o de incidencia cerrada se audita sin efectos.
6. Rechazos, vencimientos y cambios reactivan al mismo coordinador con rondas limitadas y scheduler comprobado.
7. Aprobación humana ligada a decisión, versión y usuario autorizado. El LLM no aprueba por el organizador.
8. Atención urgente según protocolo validado sin esperar análisis profundo, usando las mismas reservas para evitar duplicados.

**Salida:** se replantea un solo plan; revisiones duplicadas no ejecutan otra vez; acciones graves esperan a una persona.

### Fase 6 — Sala, historial y aprobaciones

1. Adaptar Sala del PR sin archivar otras pantallas; coordinación/revisión, accesibilidad y temas.
2. Integrar/adaptar `memoria_db.py`, `db.py`, `ledger.py`, rutas de historial/equipo, `explica.py` y `app.py` según dependencias reales.
3. Implementar proyección autenticada, idempotente y por versión, sin `Session.report`, `agent._emit`, `comms.send` ni fallback decisor.
4. Alimentar vistas/SSE con incidentes y comunicaciones v2; distinguir real/simulado, recibido/entregado, ofrecido/aceptado y ETA humana.
5. Historial por incidente con preguntas, respuestas, decisiones, revisiones, latencias medidas y pendientes de entrega; sin secretos/contactos en endpoints públicos.
6. Botones del operador producen comandos autenticados al núcleo común; no duplicar con `session.approve()` del simulador.
7. Web pública operativa entra por el mismo coordinador; los golpes del simulador permanecen aislados.
8. Caída de Sala/gemelo no bloquea el bot ni causa otro despacho.

**Salida:** incidente único en Sala/historial, recuperación tras reinicio y bot independiente de la conexión de Sala.

### Fase 7 — aprendizaje, evaluaciones y documentación

1. Adaptar `prueba-ana-aprende`, episodios y UI de lecciones.
2. Propuestas con eventos/decisiones/resultados y N; aprobación, rechazo y revocación humanas. Solo aprobadas entran en contexto.
3. No trasladar heurísticas médicas ni aceptación=acierto como aprendizaje validado; separar entrega de calidad de coordinación.
4. Adaptar evals diversos, seguridad y regresiones a coordinador/revisor y ambos canales, registrando modelo y versiones.
5. Alinear README, GUIA, COMO-DECIDE, TELEGRAM-HR, recetas, BASE-DE-DATOS, ESPEJO-TELEGRAM, ejemplos y pitch con evidencia real.
6. Prompts/manifiestos sin credenciales; cambios aprendidos de prompt requieren revisión y publicación manual.

**Salida:** proponer no cambia decisiones; aprobar incorpora la lección; revocar la retira. Evaluación/documentación reproducibles.

### Fase 8 — migración, corte y reversión

1. Puente retrocompatible y vía nueva inicialmente desactivada; wrappers antiguos adaptados antes del corte.
2. Pruebas aisladas/shadow sin efectos y luego cohortes separadas; no usar el roster compartido ni enviar mensajes en shadow.
3. Durante una pausa breve del consumo, conservar entrada en inbox, drenar runs/llamadas y adaptar callbacks pendientes.
4. Migrar roster, incidentes, preguntas y asignaciones preservando IDs/aliases e invariantes; sin FLUSHDB ni sobrescritura masiva.
5. Un propietario v1/v2 por incidente; no lectura v2/escritura v1 concurrente. Resolver botones antiguos.
6. Publicar dependencias probadas antes del coordinador; redeploy comprobable por SHA/manifiesto, no solo health.
7. Ensayar reversión conservando inbox/outbox y versiones compatibles. No volver ciegamente a código que sobrescriba snapshots v2.
8. Retirar referencias y archivar/desactivar redundancias tras estabilidad y acuerdo específico; no borrar por ausencia de runs recientes.

**Salida:** Telegram y voz sin pérdidas durante redeploy, callbacks tardíos sin duplicaciones e inventario activo documentado.

## 10. Matriz obligatoria de aceptación

1. Telegram → aviso → pregunta de zona → respuesta inmediata: mismo incidente, cero duplicados.
2. Dos preguntas simultáneas: ninguna sobrescribe a la otra y cada respuesta llega a quien preguntó.
3. Dos incidentes de un informante: referencias explícitas correctas y aclaración de ambigüedades.
4. Botones y texto producen iguales estados de aceptación/ETA/llegado/localizado/finalizado.
5. Telegram → llamada saliente → aceptación/ETA → actualización; callback final no repite confirmación provisional.
6. Voz entrante → equipo Telegram → pregunta → respuesta en llamada activa; alternativa tras colgar por canal autorizado.
7. Dos aceptaciones de la misma tarea: un ganador. Dos capacidades distintas pueden tener dos asignaciones.
8. Un trabajador no ocupa dos tareas incompatibles; nadie sustituye capacidad médica/bomberos sin equivalencia.
9. Rechazo → disponibilidad desconocida/no ahora/en quince minutos → corrección y replanificación.
10. Reintentos, fallo de entrega, timeout ambiguo, caída de HappyRobot/Redis/Sala y recuperación de cold start.
11. CONFIRMA no ejecuta; CORRIGE solo sobre versión vigente; revisión tardía no reabre; acciones graves requieren humano.
12. Preguntas/transiciones guardadas antes de responder; entrega confirmada por proveedor, no por nodo verde.
13. Fin de llamada no cierra asistencia; cierre explícito del equipo conserva la política; inferencia pide confirmación.
14. La proyección no llama al motor ni comunicaciones y no expone contactos/tokens.
15. Lección propuesta/aprobada/revocada con evidencia y N, sin autopromoción de permisos.
16. Migración/rollback con botones antiguos, llamadas activas y pendientes; mismo evento sin efectos en v1 y v2 a la vez.

Las pruebas con datos o proveedores simulados se identifican como tales. Las llamadas/mensajes a personas requieren destinatarios y guion confirmados. Sin staging funcional, no sustituirlo por una prueba encubierta sobre producción.

## 11. Comandos y archivos para retomar

Desde la raíz del repositorio, durante una sesión de implementación autorizada:

```bash
git status --short --branch
npm --prefix puente run typecheck
npm --prefix puente test
npm --prefix puente run build
python3 -B -m unittest motor.happyrobot.sandbox.test_operaciones motor.happyrobot.sandbox.test_consumidor motor.happyrobot.sandbox.test_operation_artifact motor.happyrobot.sandbox.test_coordinador motor.happyrobot.test_workflow_artifacts
python3 -B motor/happyrobot/sandbox/test_local.py
git diff --check
```

Para servidor/UI que se incorporen, con comunicaciones externas deshabilitadas y DB temporal:

```bash
uv run --project motor/server python -B -m unittest discover -s motor/server -p 'test_*.py' -t .
python3 -B -m unittest motor.world.test_world motor.mando.test_mando
node --check motor/server/static/sala.js
```

Verificar las claves locales sin imprimirlas, desde `puente/`:

```bash
node --import tsx scripts/provision-state-secrets.ts --verify
```

Para la suite remota, desde `puente/`, configurar `FABAT_TEST_PREVIEW_URL` con el URL **verificado** del despliegue aislado y usar:

```bash
DOTENV_CONFIG_PATH=.env.test DOTENV_CONFIG_QUIET=true FABAT_RUN_PREVIEW_TESTS=1 node --import dotenv/config --import tsx --test src/lib/preview-state.integration.test.ts
```

La suite Redis directa requiere además `FABAT_TEST_REDIS_URL`, `FABAT_TEST_REDIS_TOKEN` y `FABAT_RUN_REDIS_TESTS=1`, configurados de forma privada. No asumir que esas credenciales estén en `.env.test`: la conexión Redis se aprovisionó en Vercel.

Los comandos `admin install-operations` y `admin test-operations` exigen un borrador; con la versión actual publicada no deben ejecutarse sin fork y actualización del manifiesto. `admin probe-operations` se preparó para probar el workflow nativo, pero no pasó debido al 502 descrito. No interpretar su mera existencia como prueba realizada.

Mapa de archivos para las fases pendientes:

- Contrato/estado: `motor/happyrobot/event_contract.json`, `puente/src/lib/event-contract.ts`, `redis-state.ts`, `redis-scripts.ts`, `src/hr/state-router.ts`.
- Coordinación/exportación: `sandbox/fa_coordinador.py`, `fa_operaciones.py`, `fa_consumidor.py`, `build_nodes.py`, `workflow_artifacts.py`, `coordinator-prompt.json`, `workflows-v2.json`, `admin.py`.
- Telegram/entrega: `telegram-v2.ts`, `telegram-map.ts`, `state-delivery.ts`, `state-env.ts`, `src/telegram/router.ts`, `handle-update.ts`, `poll.ts`, `src/hr/router.ts`, `hr-client.ts`.
- Voz/compatibilidad: `motor/server/comms_happyrobot.py`, `hr_routing.py`, contratos y prompts de `motor/happyrobot/`; adaptadores nuevos según interfaces reales.
- Sala/proyección: `motor/server/app.py`, `static/sala.*`, `espejo_telegram.py`, rutas de historial/equipo, `db.py`, `ledger.py`; `hr_projection.py` y sus pruebas siguen siendo trabajo pendiente.
- Del PR #18: `memoria_db.py`, herramientas/observación, explicación/historial, prompts de coordinador/revisor/aprendizaje, evaluaciones y tests asociados.
- Documentación: `puente/README.md`, ejemplos de entorno y documentos del apartado de fase 7.

La fuente de los Sandbox es `motor/happyrobot/sandbox/`, no una copia divergente en `../hr-sandbox/`.

## 12. Límites y entregables finales

- No cambiar de arquitectura ni integrar el PR #23 sin una nueva decisión del usuario.
- No volver a proponer la rotación del secreto de automatización como condición para continuar.
- No usar `hackspain` para esta implementación; no efectuar entregas del concurso. Las reglas del repo también prohíben `watch`/`submit` finales sin la autorización correspondiente.
- No cambiar contratos compartidos ni carpetas de otros responsables sin coordinación.
- No comprar números, abrir conectividad externa nueva, hacer llamadas reales, eliminar workflows o efectuar migraciones destructivas sin confirmación específica.
- No afirmar latencias, exactitud o mejoras sin medida, versión y N. Desconocimiento/falta de recurso debe producir aclaración o escalada trazable, no invención.
- Mantener el PR en borrador hasta cumplir la matriz aplicable. Build correcto no significa sistema listo.

Orden de entregables revisables:

1. Contrato, persistencia técnica y núcleo común, con v2 apagado para el bot existente.
2. Coordinador, Telegram y comunicaciones completos, con wrappers y preguntas durables.
3. Voz saliente/entrante multicanal con identidades y callbacks unificados.
4. Herramientas, revisor, proyección, Sala e historial del PR #18, sin despacho duplicado.
5. Aprendizaje, evaluaciones, documentación y corte/reversión controlados.

Cada bloque debe poder revisarse y detenerse sin deshacer el sistema que ya funciona. Al retomar, actualizar este documento con commits, recursos, resultados y pendientes reales; no marcar fases completas por haber añadido un enum, un archivo, un esquema de salida o un workflow que todavía no ha recorrido el circuito completo.
