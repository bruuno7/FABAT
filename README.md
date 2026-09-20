# ResQval — coordinación de incidentes con MANDO

ResQval ayuda al puesto de mando de un festival a recibir avisos, coordinar personal y seguir compromisos y cambios de plan. FABAT es el proyecto; MANDO es su motor persistente. HappyRobot conversa y propone, pero no es la autoridad sobre los recursos ni puede aprobar decisiones graves.

**MVP de demostración, no sistema certificado de emergencias.** No sustituye a profesionales ni a los protocolos del recinto. No usar con víctimas reales o números de emergencias.

## Estado y alcance

- **Implementado:** incidentes, personal, asignaciones/reservas, propuestas, aprobación humana, entregas, callbacks y auditoría en SQLite. La sala ResQval consume snapshot, SSE y comandos de MANDO.
- **Evidencia histórica real:** Telegram → Vercel → Railway → HappyRobot, **N=1 llamada telefónica de prueba**, resultado `accept`, destino confirmado y **ETA de 2 minutos**, con callbacks aplicados. No fue webcall ni `followup_question`; tampoco acredita el código local actual, llegada física o todos los escenarios.
- **Workflow rápido:** fork v2 adaptado pero **no publicado/no live**. Su v1 sigue live en `development`. Hay pruebas de contrato en **SIMULACIÓN N=11 casos de nodos puros y N=7 tests locales**, no un recorrido completo del agente. Falta validar la respuesta HTTP, el candidato público y el trigger antes de publicar.
- **Candidata local no publicada:** resultados finales de suites, navegador, instalación limpia y despliegue aún pendientes de consolidar. No se declara lista para demo conectada; ver [puertas de aceptación](PENDIENTE.md).
- **Separación de modos:** `motor/world` es simulación histórica. `web/` conserva un prototipo Next con estado en memoria, aislado del recorrido operativo; no desplegar sus handlers como segunda autoridad.

## Arquitectura

```text
Telegram → puente/Vercel → MANDO/Railway ⇄ SQLite
                              ⇅
                     HappyRobot + callbacks
ResQval ⇄ API de MANDO (snapshot, SSE, comandos)
```

MANDO valida identidad, capacidad, versión, disponibilidad y deduplicación. Aceptación, ETA con destino confirmado, llegada, localización y finalización son hechos distintos. Evacuar, parar un espectáculo o pedir ayuda externa exige aprobación humana vigente. Una entrega incierta **no provoca rellamada automática**; `local_required` exige comunicar manualmente y registrar lo realmente confirmado.

La UI operativa se sirve desde `motor/server/static/sala-operativa.html`. El [Dockerfile](Dockerfile) empaqueta `motor`; [vercel.json](vercel.json) construye `puente`, no `web/`. Esto describe la configuración versionada, no certifica qué revisión está desplegada. Plano esquemático, sin seguimiento GPS ni gemelo físico calibrado.

## Arranque local

Para una **demo aislada con cuatro personajes, guía interactiva y canales reales opcionales**,
consulta [DEMO-JURADO.md](DEMO-JURADO.md). Reutiliza esta Sala sin modificar el bot ni la base del despliegue habitual.

Requisitos: Python ≥3.12, `uv`, Git y Node ≥20 para puente/tests JS. Versiones comprobadas: Python **3.13.7**, `uv` **0.8.22**, Node **24.19.0**. Desde la raíz:

```sh
uv sync --project motor/server --frozen
./mvp.sh preflight --seed 1701 --output /tmp/resqval-preflight-nuevo
```

Elegir un directorio de salida nuevo. El preflight usa SQLite aislada, bloquea red y simula proveedores; devuelve fallo si no cumple sus comprobaciones. Su existencia no equivale a un resultado verde del árbol actual. Instalación desde limpio y ejecución final siguen pendientes.

Para abrir la sala local:

```sh
test -e .env || cp .env.example .env
# Editar .env en privado: MANDO_OPERATOR_TOKEN=<token aleatorio>,
# MANDO_OPERATIONAL_DB=<ruta absoluta a una base nueva>,
# MANDO_EXTERNAL_DELIVERY=0; dejar desactivadas las credenciales externas.
./mvp.sh operational
```

Abrir `http://127.0.0.1:8000/sala` y autenticarse. Con token configurado, localhost también exige autenticación. `POST /salir` elimina las cookies de sesión; no revoca credenciales o cookies previamente copiadas. No guardar tokens en URL, `localStorage`, capturas o Git.

**Sin argumentos y sin `MANDO_OPERATIONAL=1`, `./mvp.sh` arranca el simulador legacy**, no esta sala. `.env` se carga como configuración de shell; revisar que no active entregas reales. `--lan` expone el servicio a la red y requiere revisar autenticación/origen.

## Configuración por servicio

Solo nombres y formatos; secretos en `.env` privado o variables del alojamiento:

| Servicio | Variables | Uso |
|---|---|---|
| Backend | `MANDO_OPERATIONAL=1`, `MANDO_OPERATIONAL_DB` | Modo persistente y ruta SQLite; en Railway, `/data/operations.sqlite` sobre volumen |
| Backend | `MANDO_OPERATOR_TOKEN` o `MANDO_OPERATORS` | Acceso obligatorio en el lanzador operativo; formato multioperador en [servidor](motor/server/README.md#seguridad-y-contrato-http) |
| Backend | `MANDO_EXTERNAL_DELIVERY=0` | Ensayo sin proveedores; `1` permite efectos externos y requiere autorización |
| Backend + puente | `MANDO_BRIDGE_SECRET` | Secreto compartido, distinto del acceso de operador |
| Backend | `MANDO_PUBLIC_URL=https://<backend-autorizado>`, `HR_SECRET` | Origen público y firma de capacidades por entrega |
| Puente/Vercel | `MANDO_OPERATIONAL=1`, `TELEGRAM_MODE=webhook`, `MANDO_BACKEND_URL` | Selecciona MANDO; no polling ni API Next |
| Puente/Vercel | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET` | Bot y autenticación del webhook |
| Backend/Telegram | `TELEGRAM_BOT_TOKEN`; `MANDO_CONTROL_CHAT_ID` opcional | Envíos a destinos privados de actores/control |
| Backend/HappyRobot | `HR_API_BASE`, `HR_API_KEY`, `HR_ENV` | Clúster, credencial y entorno explícito; el defecto es `development` |
| Backend/HappyRobot | `HR_WORKFLOW_DISPATCH`, `HR_WORKFLOW_RAPIDO` | Solo habilitar versiones publicadas y compatibles; el rápido adaptado sigue bloqueado |
| Backend/HappyRobot | `MANDO_ALLOWED_NUMBERS` | Destinos consentidos en formato internacional **separados por comas**, nunca emergencias |

La barrera del worker operativo es `MANDO_EXTERNAL_DELIVERY=0`, no `TELEGRAM_MODE=off`. `MANDO_DB`, LiveKit/webcall y opciones LLM del legacy no sustituyen la base ni acreditan canales del operativo. No habilitar credenciales para superar tests simulados.

## Uso de la sala

1. Autenticarse con identidad de operador y registrar personal ficticio, rol, zona y disponibilidad; canal `web` para ensayo sin proveedor.
2. Registrar un aviso y su zona. Aclarar referencias ambiguas; no fusionar personas por compartir texto o ubicación.
3. Revisar prioridad, necesidades, ofertas y reservas. Un recurso ofrecido todavía no ha aceptado y ya está reservado.
4. Registrar aceptación/rechazo realmente recibido; después ETA y destino, llegada, localización y finalización por separado.
5. Ante un cambio, revisar el plan y su motivo. Una rectificación confirmada puede reducir demanda sin retirar de golpe al equipo activo; al liberarlo no debe reabrirse la demanda retirada.
6. Aprobar/vetar decisiones graves sobre contenido y versión vigentes. Un 409 exige recargar y revisar, no reenviar una decisión antigua.
7. Cerrar cuando las tareas/necesidades lo permitan y salir de la sesión. Si hay `local_required`, comunicar por canal humano; si hay incertidumbre, reconciliar antes de autorizar otra llamada.

Detalle, contratos HTTP y recuperación: [MVP-OPERATIVO.md](MVP-OPERATIVO.md). Guion con imprevisto y plan B: [PRESENTACION.md](PRESENTACION.md).

## Pruebas y despliegue

```sh
./mvp.sh check
uv run --project motor/server python -m motor.server doctor --sin-red
```

`check` aísla fuentes/bases, limpia credenciales y ejecuta suites core/server, corpus de **SIMULACIÓN train N=3000 y heldout N=1000**, semilla 1, y `check-world` (**SIMULACIÓN N=12 casos**). No sustituye tests/build del puente ni navegador. El doctor está orientado a canales legacy: puede devolver 1 por credenciales opcionales ausentes; no usar `|| true` ni tomarlo como certificación del operativo. Resultados finales con revisión, N, semillas, códigos de salida y límites: pendientes de incorporar a la evidencia de entrega, sin reciclar recuentos históricos.

- **Railway:** activar `MANDO_OPERATIONAL=1`, volumen SQLite y una sola réplica/worker escritor. Configurar explícitamente `uv run --project motor/server python -m motor.server --lan --port ${PORT:-8000}` con expansión de shell; el CLI no lee `PORT` automáticamente y el Dockerfile conserva argumentos legacy. Mantener entregas apagadas durante verificación.
- **Vercel:** la raíz construye `puente/dist/**` y exporta `api/index.ts`. Webhook Telegram único, autenticado y apuntando a MANDO. Ver [puente/README.md](puente/README.md).
- **HappyRobot:** callback `/hr/events`, herramientas `/hr/tools/*`, `X-Mando-Token` por entrega; no enviar el secreto raíz. Revisar [estado y bloqueo del rápido](MVP-OPERATIVO.md#estado-del-workflow-rápido) antes de publicar. La llamada histórica de despacho no valida ese fork.
- **Publicación:** no cambiar ramas, webhook, volumen ni despliegues como efecto lateral. Preparar el MVP no autoriza publicar workflows, hacer push o entregar al concurso. No ejecutar `hackspain watch` ni `hackspain submit` sin `--draft` antes de la entrega autorizada.

## Recuperación y límites

Backup consistente y restauración aislada: [runbook](MVP-OPERATIVO.md#backup-restauración-y-rollback). No copiar solo SQLite mientras hay WAL activo ni reactivar outbox sin reconciliar efectos externos. Rollback y restauración del despliegue requieren ensayo propio.

| Síntoma | Acción segura |
|---|---|
| 401 / sesión caducada | Volver a autenticar en el mismo origen |
| 403 | Revisar rol, origen y secreto sin desactivar controles |
| 409 | Recargar; comprobar si el comando ya se aplicó y revisar la nueva decisión |
| Callback o Telegram ausentes | Revisar correlación, entorno, secreto, URL y disponibilidad; no fabricar éxito |
| `local_required` / `uncertain` | Comunicar manualmente / reconciliar; nunca rellamada ciega |
| Estado perdido o SSE antiguo | Parar decisiones no confirmadas; revisar conexión, ruta y volumen antes de restaurar |

No se acredita exactly-once externo, alta disponibilidad, validación clínica, retención/GDPR, costes o latencia telefónica representativa. La replanificación no demuestra aprendizaje online. Aforo, clima y rutas del simulador no son sensores operativos.

## Documentación y contribución

[Reglas del repositorio](AGENTS.md) · [Guía operativa](MVP-OPERATIVO.md) · [Servidor](motor/server/README.md) · [Simulador histórico](MVP.md) · [Pendientes](PENDIENTE.md) · [Presentación](PRESENTACION.md).

Contratos compartidos: [motor/INTERFACES.md](motor/INTERFACES.md) y [motor/contracts.py](motor/contracts.py); incluyen contexto del simulador, no reemplazan el contrato HTTP operativo. No modificarlos sin coordinación. El inventario completo se entrega como **adjunto final**, con su corte y límites de lectura; no se presenta como auditoría semántica terminada.

No se ha identificado licencia de proyecto en el árbol revisado: los titulares deben definirla, sin inferirla de que el repo sea público. HappyRobot, Telegram, Railway y Vercel son proveedores, no avales; las dependencias conservan sus licencias.
