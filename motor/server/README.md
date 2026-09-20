# Servidor MANDO: operativo persistente y legado

Esta carpeta contiene código público del backend y también rutas posibles de **datos privados locales**, que no se deben versionar. El servidor puede alojarse en Railway con autorización; no es correcto describir toda la carpeta como privada ni afirmar que nunca se despliega.

La referencia del producto es [README raíz](../../README.md). Runbook, callbacks y recuperación: [MVP-OPERATIVO.md](../../MVP-OPERATIVO.md). Guion actual: [PRESENTACION.md](../../PRESENTACION.md).

## Selección de modo

| Modo | Activación | Interfaz/API |
|---|---|---|
| Operativo ResQval | `MANDO_OPERATIONAL=1` o `./mvp.sh operational` | `/`, `/sala`, `/interfaz`; `/api/operations/state`, `/stream`, `/command` bajo el prefijo `/api/operations` |
| Simulador legacy | Sin esa variable | Sala antigua, `/asistente`, `/duelo`, `/caos`, etc.; `/api/state` y reloj sintético |

`app.create_app()` elige la app operativa antes de crear una escena legacy. La sala persistente es `static/sala-operativa.html` y sus scripts. No usa el estado de la app Next como autoridad ni consume `/api/state` para representar operación real. `web/` queda como prototipo aislado con `Map` en memoria: no lo empaqueta Docker ni lo construye Vercel raíz, que ejecuta el puente. No activar sus handlers como un segundo backend operativo. [MVP.md](../../MVP.md) documenta el simulador, no la candidata actual.

## Arranque desde la raíz

```sh
uv sync --project motor/server --frozen
./mvp.sh preflight --seed 1701 --output /tmp/resqval-preflight-nuevo
```

Para arrancar en localhost, definir en privado `MANDO_OPERATOR_TOKEN` (o `MANDO_OPERATORS`), `MANDO_OPERATIONAL_DB` a una base nueva y `MANDO_EXTERNAL_DELIVERY=0`, y ejecutar `./mvp.sh operational`. Abrir `http://127.0.0.1:8000/sala`; el CLI escucha en loopback salvo `--lan`. `MANDO_PORT` configura el puerto del lanzador. El CLI Python acepta `--port`, no lee `PORT` por sí solo.

En alojamiento, definir `MANDO_OPERATIONAL=1` y usar `uv run --project motor/server python -m motor.server --lan --port ${PORT:-8000}` con expansión de shell. El Dockerfile raíz conserva un arranque legacy: configurar el modo y el comando explícitamente. Montar volumen para SQLite y no arrancar varias réplicas consumidoras de la outbox.

La validez de los comandos no certifica instalación limpia, navegador ni alojamiento. Los resultados finales de aceptación deben corresponder a la revisión elegida, no al antecedente histórico de telefonía.

## Persistencia y módulos

- `operational.py`: transiciones e invariantes del dominio.
- `operational_service.py`: SQLite, idempotencia, inbox/outbox, revisiones y snapshot.
- `operational_http.py`: app operativa, autenticación de rutas y validación de callbacks.
- `operational_worker.py`: `DeliveryWorker`, leases e intentos externos. `external=False` no hace HTTP al proveedor.
- `preflight.py` / `operational_scenarios.py`: ensayo determinista aislado, artefactos y fallos no silenciosos.
- `security.py` / `multi.py`: acceso, cookies e identidad de operador.

`MANDO_OPERATIONAL_DB` es la autoridad persistente. `MANDO_DB` pertenece al ledger legacy. No sustituir una por otra, no importar una escena del simulador como confirmación operativa y no borrar bases al reiniciar una presentación. Backup y restauración usando la API SQLite: [runbook](../../MVP-OPERATIVO.md#backup-restauración-y-rollback).

## Seguridad y contrato HTTP

- Acceso en `/acceso`: credencial privada, cookie HttpOnly, SameSite y origen controlado. En HTTPS, comprobar cookie Secure detrás del proxy.
- La API acepta `X-Mando-Operator` para clientes autorizados; el navegador usa sesión same-origin. No meter tokens en URLs, `localStorage` ni logs.
- `MANDO_OPERATORS` usa entradas privadas `nombre:papel:token` separadas por coma/punto y coma/salto de línea; los tokens deben ser distintos. Un `MANDO_OPERATOR_TOKEN` único atribuye todos los actos a `operador-1`, no da trazabilidad humana individual.
- El nombre/rol visible del operador y los roles/capacidades del personal son conceptos distintos; no asumir un RBAC granular solo por etiquetar un operador.
- Con `MANDO_OPERATOR_TOKEN` o `MANDO_OPERATORS` configurado, localhost no omite autenticación. El lanzador operativo exige esa configuración; no confiar en loopback como autorización. El formulario de personal no acredita credenciales profesionales; las asigna un operador autorizado.
- `POST /salir` está implementado: requiere operador, borra las cookies de operador/local y redirige con 303 a `/acceso`. Es cierre de la sesión del navegador, no revocación central de tokens o cookies previamente copiadas. La aceptación de login/logout, expiración, origen y acceso posterior sigue requiriendo pruebas sobre la candidata.

Rutas operativas:

| Método/ruta | Propósito |
|---|---|
| `POST /salir` | Borra cookies y redirige al acceso; requiere operador/origen válido |
| `GET /api/operations/state` | Snapshot autenticado y saneado; sin contactos/transcripciones privados |
| `GET /api/operations/stream` | SSE de revisiones, con reconexión |
| `POST /api/operations/command` | `command_id`, `kind`, campos y `expected_version` al mutar entidad |
| `POST /api/operations/telegram` | Update original, `X-Mando-Bridge-Token`; SQLite antes de ACK |
| `POST /hr/events` | Resultado telefónico correlacionado y capacidad de entrega |
| `POST /hr/tools/*` | Lectura/propuesta/cambio mediante capacidad, sin autoridad de aprobación humana |

No se identificó `/healthz` en la app operativa revisada. Un healthcheck a `/acceso` solo acredita respuesta HTTP, no persistencia ni servicio externo. Errores de permisos/origen se rechazan; una versión antigua devuelve conflicto, no «última escritura gana».

## Adaptación y comunicación manual

`/hr/tools/cambio` consulta el contexto persistido y su versión, no devuelve un `false` fijo. Cambios relevantes invalidan propuestas obsoletas; el planificador conserva equipos activos y revisa los recursos disponibles. Detectar un cambio no acredita que el agente externo ya haya producido una nueva propuesta válida.

La rectificación confirmada puede reducir gravedad/necesidades: conserva al equipo activo hasta su transición autorizada, y al liberarlo elimina la demanda retirada para evitar nuevas ofertas indebidas. Ante referencias ambiguas a avisos anteriores, aclarar identidad antes de actualizar; no seleccionar un incidente arbitrario. Estas invariantes y sus regresiones forman parte de la validación final pendiente de consolidación.

`local_required` es una entrega **no enviada**: la telefonía automática solo soporta ofertas, por lo que actualizaciones, cancelaciones y otros avisos requieren comunicación humana manual. Registrar lo confirmado, no marcar una aprobación como aviso recibido. `uncertain` conserva que pudo existir efecto externo; ni la expiración de una oferta ni volver a disponible al actor autoriza rellamada automática. El seguimiento explícito (`followup`) requiere operador, versión y motivo tras reconciliación humana.

## Proveedores

Configuración completa en [README raíz](../../README.md#configuración-por-servicio). Resumen de diferencias importantes:

- Puente: `MANDO_OPERATIONAL=1`, `TELEGRAM_MODE=webhook`, `MANDO_BACKEND_URL`, `MANDO_BRIDGE_SECRET`, token bot y secreto webhook. Su guía está en [puente/README.md](../../puente/README.md).
- Backend operativo: `MANDO_EXTERNAL_DELIVERY=0` es la barrera de simulación. **`TELEGRAM_MODE=off` por sí solo no bloquea el worker operativo si se habilitan entregas externas.**
- Teléfono: `HR_WORKFLOW_DISPATCH`, `HR_API_BASE`, `HR_API_KEY`, `HR_ENV`, `HR_SECRET`, HTTPS y whitelist `MANDO_ALLOWED_NUMBERS` en formato internacional separado por comas, solo destinos consentidos, nunca emergencias.
- Propuesta: `HR_WORKFLOW_RAPIDO`; la API manda `environment` y `payload`. El fork v2 adaptado sigue **no publicado/no live**, con metadata `production`; la v1 permanece live en `development`. Faltan binding HTTP, candidato público, trigger y ejecución del agente: [bloqueos y evidencia](../../MVP-OPERATIVO.md#estado-del-workflow-rápido). No habilitarlo ni presentar v1 como compatible por su mera publicación.
- Callbacks: `/hr/events` y `/hr/tools/*`, token por entrega en `X-Mando-Token`. `HR_SECRET` es raíz de firma, no un permiso universal que deba circular por conversaciones.
- Webcall/LiveKit y otros adaptadores legacy no se convierten automáticamente en funcionalidades de la sala persistente.

`configured` o `ready` significan configuración suficiente según el código, no que haya audio, aceptación o ejecución física. Una entrega incierta exige revisión; el transporte simulado no debe colorearse como llamada real.

## Diagnóstico y pruebas sin proveedores

```sh
uv run --project motor/server python -m motor.server doctor --sin-red
./mvp.sh preflight --seed 1701 --output /tmp/resqval-preflight-otro
./mvp.sh check
```

El doctor solo configura/inspecciona ficheros sin red y puede devolver 1 por canales reales incompletos. No debe envolverse en `|| true`: en `check` hay una lista explícita de ausencias opcionales del perfil simulado (API key/secreto/workflow webcall/origen público/contactos/LiveKit). Otros fallos imprescindibles y fallos de ledger bloquean; un error de tests propaga salida no cero.

`check` no carga `.env`; copia fuentes/fixtures a un directorio temporal, fuerza bases allí, limpia credenciales ambientales y bloquea conexiones externas del proceso Python. Usa `uv` para disponer de FastAPI/httpx. Genera **SIMULACIÓN train N=3000 y heldout N=1000**, semilla 1, y descubre suites core/server. Necesita Git para fingerprint y Node ≥20 para tests JS invocados por Python. No instala navegador ni hace despliegues; no reemplaza las pruebas específicas del puente ni la aceptación visual.

Alcances de la evidencia:

- Preflight, suites completas, pruebas aleatorias y navegador sobre el árbol final: resultados pendientes de consolidación con N, semillas, revisión y salida. No reutilizar recuentos de pruebas anteriores.
- Rápido externo: **SIMULACIÓN N=11 casos de nodos puros** y **SIMULACIÓN N=7 tests locales mock/ASGI** en los adjuntos; no son ejecución completa del agente ni telefonía. Repetir contrato al congelar el backend.
- Antecedente histórico: **Telegram → Vercel → Railway → HappyRobot, N=1 llamada telefónica real de prueba**, `accept`, destino confirmado, ETA **2 minutos** y callbacks aplicados. No fue webcall ni `followup_question`; no acredita el SHA/árbol actual. El harness de despacho con `callback_url` vacío conserva un gate distinto, aunque el run posterior sí completase callbacks.

Los resultados sintéticos no son efectividad clínica, tasa de éxito de proveedores ni garantía de concurrencia a cualquier escala. No activar credenciales reales para resolver una regresión de test.
