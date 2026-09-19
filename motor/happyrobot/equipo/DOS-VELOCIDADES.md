# Dos velocidades

Diseño configurado en EU el 19-09-2026. Solo development. No se han ejecutado runs, llamadas ni mensajes reales. Se conserva el equipo existente mediante fork.

## Recorrido

La Workflow Function rápida recibe `entrada_json`, `callback_url`, `callback_token`, `canal`, `texto`, `transcripcion`, `remitente`, `zona_sugerida`, `idioma` y `correlation_id`. Un Incoming hook de prueba separado reenvía esos campos desde `data.*` a la función, con enhanced security desactivada. Esa entrada añade un arranque de workflow: para medir el camino más corto, usar directamente la función.

Un solo Reasoning Agent con `gpt-5.6-luna-low` consulta `analizar_situacion` y `acciones_posibles`, decide y llama `decidir`. Las consultas usan POST a `{{callback_url}}/hr/tools/<nombre>`, cabecera `X-Mando-Token: {{callback_token}}` y body webhook EU v2 (`schemaVersion: 2`, `contentType: application/json`, `raw` con referencia al parámetro JSON de la tool). Las credenciales viajan como parámetros; nunca se incluyen en el razonamiento o la respuesta.

El agente llama `entregar_resultado` y termina. El grafo ejecuta Call Workflow hacia el equipo con `fire_and_forget: true`, `use_caller_environment: false` y destino development, pasando la misma entrada más `fase: revision` y `decision_rapida` (JSON final del rápido). Después, un nodo Python devuelve la decisión rápida. No espera el resultado del enjambre; los errores de lanzamiento se manejan sin bloquear esa respuesta. La respuesta rápida no acredita que la revisión haya terminado.

El coordinador conserva los seis especialistas y compara sus resultados con la decisión rápida. La entrada de revisión omite la rama de despacho vital previo para evitar duplicados. Al finalizar llama `decidir` con la fase, el dictamen y su motivo. No relanza otro ciclo. Ante evidencia incompleta o crítico que exige corrección, escala a persona sin inventar aprobación.

## Contrato

`decidir` recibe un objeto plano con los campos habituales (`incident_id`, `prioridad`, `porque`, `acciones`, `recursos`, `avisar`, `supuestos`, `vigilar`, `confianza`, `requiere_persona`, `correlation_id`) y:

| Campo | Rápida | Revisión |
|---|---|---|
| `fase` | `rapida` | `revision` |
| `agente` | `rapido` | `equipo` |
| `por_papel` | Seis líneas de justificación | Seis líneas de revisión |
| `revision` | No requerido | `CONFIRMA` o `CORRIGE` |
| `motivo_revision` | No requerido | Qué confirma/cambia y por qué |

`por_papel` es un objeto con claves `triaje`, `prioridad`, `recursos`, `avisos`, `vigia`, `critico`; cada valor es un texto de una línea basado en evidencia. Son perspectivas de un único agente en la fase rápida. No representan seis ejecuciones independientes.

La respuesta rápida contiene `fase`, `agente`, `estado`, `decision`, `resultado_backend`, `por_papel` y `correlation_id`. Revisión reutiliza el `incident_id` confirmado por backend. El serializador del equipo conserva los campos de fase y revisión exteriores al aplanar `decision`. El backend admite `revision` como alias de `veredicto`. CONFIRMA no repite acciones ni comunicaciones. Evacuar, parar y pedir ayuda externa mantienen aprobación humana.

## Tiempo y estado verificable

Objetivo de diseño: decisión rápida en ≤15 s desde la entrada directa a la función. No es un timeout garantizado: arranque, herramientas, inferencia y cola pueden superarlo. La revisión queda fuera de ese camino y puede seguir tardando más de dos minutos. El hook separado añade latencia de arranque.

N=0 ejecuciones de simulación en esta sesión; ningún benchmark acredita todavía el objetivo. Ana debe medir llegada, respuesta de `decidir`, respuesta final y fin de revisión con la misma correlación.

Equipo: nueva versión publicada en development. Hook: publicado en development. Rápido: borrador, publicación bloqueada por cuatro View Tool Call Result pendientes (las tres herramientas backend y `entregar_resultado`). El hook no completa su llamada hasta publicar el rápido. URLs, versiones y node-ids están en el registro privado `PLATAFORMA_REAL.md`, fuera de este repositorio.

La publicación también informa referencias sin esquema de salida resuelto. La revisión automática bloqueó `fix_broken_vars` incluso en dry-run porque puede ejecutar test-all/webhooks; solo se leyeron configuraciones y se intentó publicar. No se abrió View Tool Call Result ni se ejecutaron pruebas remotas. Ana debe revisar las salidas y referencias antes de su primera ejecución de simulación.
