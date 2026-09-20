# Pendientes y puertas de aceptación

**Estado: candidata local no publicada; no lista para declarar cerrada la demo conectada.** Hay implementación operativa y evidencia parcial, pero faltan validación final, aceptación visual y recorrido completo del workflow rápido. No equivale a certificación para emergencias reales. Arranque: [README.md](README.md); contratos y recuperación: [MVP-OPERATIVO.md](MVP-OPERATIVO.md).

## Implementación y evidencia disponibles

- Autoridad persistente MANDO/SQLite, API `/api/operations/*`, sala del backend y separación del simulador. `web/` queda como prototipo Next aislado, sin despliegue desde Docker/Vercel raíz; no activar su store ni handlers en paralelo.
- Autenticación con token también en loopback y handler `POST /salir` que borra cookies. El logout ya existe; la aceptación de sesión/caducidad/origen y navegador es una prueba pendiente, no una función ausente.
- Adaptación del backend: contexto global/cambio, propuestas obsoletas rechazadas, rectificación confirmada con retirada de demanda al liberar equipo y tratamiento conservador de referencias ambiguas. Sus regresiones deben formar parte de la validación final.
- Limitación explícita: telefonía automática de ofertas; `local_required` exige comunicación manual de actualizaciones/cancelaciones/otros avisos. Una entrega `uncertain` requiere reconciliación humana, sin rellamada automática.
- Antecedente histórico: **Telegram → Vercel → Railway → HappyRobot, N=1 llamada telefónica real de prueba**, `accept`, destino confirmado, ETA **2 minutos**, callbacks aplicados. No fue webcall ni `followup_question`, y no acredita el SHA/árbol actual.
- Rápido: fork v2 de 15 nodos adaptado, **no publicado/no live**; v1 sigue live en `development`. Evidencia parcial de **SIMULACIÓN N=11 casos de nodos puros y N=7 tests locales mock/ASGI**, no ejecución del agente ni recorrido end-to-end. [Estado y bloqueos](MVP-OPERATIVO.md#estado-del-workflow-rápido).
- Preflight sin red y guiones disponibles. Los resultados numéricos finales de suites, preflight y aleatoriedad quedan **pendientes de consolidación**, sin anticipar verde ni sumar repeticiones como cobertura adicional.

## Puertas antes de presentar el recorrido conectado

| Prioridad | Responsable funcional | Pendiente | Evidencia para cerrar |
|---|---|---|---|
| Bloqueante de candidatura final | Integración/QA | Congelar el árbol y ejecutar suites relevantes, aleatoriedad, contratos y revisión del diff | Revisión/estado local, comandos, códigos de salida, N, semillas, fallos/skips y artefactos saneados |
| Bloqueante del rápido | HappyRobot + backend | Resolver binding de respuesta de `POST decidir`, candidato HTTPS, diagnóstico prompt y ejecución real del agente/trigger | Respuesta backend observada, read-back, crítica real y propuesta pendiente vigente; ningún efecto antes de aprobar |
| Bloqueante de publicación del rápido | Responsable HappyRobot | Fijar versión y entorno explícitos tras pasar contrato completo | Autorización y evidencia de la versión publicada; metadata `production` no equivale a live |
| Bloqueante de demo UI | QA de navegador | Login/logout, expiración, SSE/reconexión, dos vistas, tareas, 409, móvil/accesibilidad | Navegador sobre la candidata; no basta leer el handler ni pasar tests JS |
| Bloqueante de despliegue | Responsable Railway | Instalación/build, modo/puerto explícitos, volumen, una instancia, backup/restauración y rollback | Estado y pendientes conservados al reiniciar; copia restaurada con proveedores apagados |
| Bloqueante de entrada real actual | Responsable Vercel/Telegram | Webhook único autenticado, backend correcto, update repetido y caída del backend | Aviso persistido una sola vez; no fingir éxito si MANDO falla |
| Bloqueante de voz real actual | Responsable HappyRobot | Revalidar versión/entorno de despacho, negativos y correlación; reconciliar harness con callback completo | Run/callback saneados de la candidata, destino consentido, `accept`/ETA diferenciados de llegada |
| Bloqueante de auditoría completa | Revisión de archivos | Consolidar seis inventarios previos y completar lectura semántica mantenida; refrescar corte final | Inventario adjunto con procedencia por ruta/SHA, consumidores y límites, no solo clasificación mecánica |
| Necesario para evidencia legacy | QA del motor | Resolver/delimitar gates que aceptan fallos o conjunto vacío; revisar fixtures obsoletos sin rebajar aserciones | Casos vigentes realmente ejecutados y fallo no silencioso |
| Bloqueante de uso con personas | Responsable operativo/sanitario | Protocolos, consentimiento, formación, privacidad y retención | Aprobación formal independiente de esta demo |
| Necesario para distribuir | Titulares | Definir licencia y revisar atribuciones | Licencia autorizada; no inferirla del repositorio público |

El despacho v8 tuvo dos errores históricos de `test_all` por `callback_url` vacío; el run telefónico posterior sí completó callbacks. Ese éxito no certifica el harness ni el rápido. Probar primero contratos con mock y contexto completo; no lanzar telefonía para arreglar fixtures.

## Inventario como adjunto final

El corte disponible clasifica **493 rutas: 479 versionadas y 14 nuevas locales**, sin ausentes/extras/duplicados. Distingue **40 lecturas íntegras o focales y 453 clasificaciones mecánicas**: no demuestra auditoría semántica completa. Recomendaciones del corte: 397 conservar, 11 actualizar, 85 históricas, ninguna retirada; no son eliminaciones ejecutadas. Los recuentos deben refrescarse al finalizar los cambios compartidos.

La consolidación de los seis adjuntos previos quedó bloqueada por descarga autenticada no disponible/HTTP 401. Falta incorporar su contenido por ruta y revisión, sin atribuir lecturas históricas al árbol actual. El CSV, manifest y validación se entregan **fuera del repositorio como adjuntos finales**, no como plan de commits ni registro de trabajo dentro del producto.

Hallazgos a conservar visibles hasta su resolución:

- `motor/evals/__init__.py` puede terminar en 0 pese a fallos; `notifications.py` no exige `duplicate=true` para su éxito; el harness de regresión puede aceptar cero casos tras filtrar huellas. En el corte estático de **SIMULACIÓN N=11 fixtures**, 0 eran vigentes y 11 obsoletos; no fue una ejecución del harness.
- Documentos históricos fuera de estas guías pueden orientar a otro modo: `web/README.md`, `LEEME-COMPARTIR-EQUIPO.txt`, `COBERTURA-RETO.md` y enlaces ausentes en `motor/server/CONEXION-HAPPYROBOT.md`. No usarlos como aceptación del operativo; corregirlos con sus responsables sin borrar historia.
- Conservar trabajo local, memoria y fixtures `motor/server/regression_live/test-012.json` y `test-013.json`. Hay indicios sintéticos, pero procedencia y campos libres requieren revisión antes de publicar; no incorporarlos ni eliminarlos automáticamente.

## Preparación de presentación y publicación

- Elegir revisión/imagen y conservar identificación de cambios no publicados; validar de nuevo las dependencias afectadas si el árbol cambia.
- Configurar secretos en privado, whitelist en formato internacional separado por comas y límites de gasto. Nunca números de emergencia ni contactos sin consentimiento.
- Localhost puede arrancarse para ensayo con proveedores desactivados según [README](README.md#arranque-local); es distinto de exponer red, publicar o hacer llamadas reales.
- Verificar modo, puerto, volumen y origen antes de desplegar. No cambiar ramas, PRs, webhook o proveedores como efecto lateral de una prueba local.
- No publicar el rápido todavía: falta respuesta HTTP/trigger/agente. La v1 live no es un fallback operativo validado; no activar con defaults de entorno.
- Ensayar los guiones de [PRESENTACION.md](PRESENTACION.md), comprobar sus tiempos y confirmar formato oficial del track. Preparar evidencia saneada y plan B; no inventar coste, vídeo ni mediciones.
- Mantener `hackspain watch`/`hackspain submit` en `--draft` hasta autorización de entrega definitiva.

## Criterio de salida y no-go

**Demo simulada:** preflight y pruebas relevantes de la candidata satisfactorios, datos ficticios, entregas externas apagadas, etiqueta SIMULACIÓN y plan B ensayado. Si se proyecta UI interactiva, requiere aceptación en navegador.

**Demo conectada:** además, versiones/entornos de proveedores verificados, consentimiento, whitelist, límites de gasto, operador y suplente, callbacks y adaptación con evidencia sobre la candidata. Si falta, mostrar plan B y decir qué no se ha validado.

**No-go:** secretos visibles, autoridad duplicada fuera de MANDO, pérdida de estado, doble asignación, aprobación grave eludible, regresión crítica sin resolver, demanda retirada que reaparece o proveedor fallido presentado como éxito. No compensarlo con una grabación antigua o una animación.

Fuera de alcance: certificación clínica, alta disponibilidad/multi-región, GIS/GPS en tiempo real, canales universales por existir adaptadores, aprendizaje online y exactly-once externo. Clasificar el inventario o leer el código no cierra las puertas de funcionamiento, seguridad o integración.
