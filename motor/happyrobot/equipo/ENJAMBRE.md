# Enjambre — pizarra, revisión entre pares y confianza

Red de agentes que se hablan, se corrigen y aprenden. Las barandillas no se tocan: lo grave lo decide una persona; lo vital no espera.

Contrato de herramientas: [HERRAMIENTAS](../cerebro/HERRAMIENTAS.md). Adaptación a tres escalas: [ADAPTATIVO](ADAPTATIVO.md). Este documento es lo que hay que montar en HappyRobot; **no publica nada**.

## Cadena de decisión (nunca en silencio)

```
plataforma HappyRobot
    → si no contesta a tiempo: equipo local con LLM (cerebro_llm.py, mismos prompts, misma pizarra)
        → si también falla: reglas de motor/mando, último recurso
```

Las reglas **nunca** deciden sin rotular: `S.session.modo_degradado` = «modo degradado: reglas» (rojo en la Sala) y un evento `cerebro` en el log. Lo único fijo son las barandillas (lista blanca, lo grave → persona, despacho vital inmediato). Tras un despacho vital reflejo, el equipo razona el resto.

El contexto que recibe cada agente (pizarra, confianza, lecciones, episodios parecidos) cambia con lo vivido: dos situaciones distintas no producen el mismo razonamiento.

## Pizarra

`POST /hr/tools/pizarra/publicar` y `/hr/tools/pizarra/leer`.

Mensaje: `{de, para (agente o «todos»), incidente, tipo, texto, datos, confianza, enlaza?, gravedad?}`.

Tipos: `observacion|propuesta|decision|revision|objecion|correccion|pregunta|respuesta`.

`leer` para un agente e incidente: lo dirigido a él primero, luego el resto relevante (últimos N). Incluye **solo** sus lecciones aprobadas y las globales. Nada de reservado en claro.

Vista pública `S.enjambre`:

```json
{
  "modo": {"id": "calma", "porque": "…"},
  "agentes": [{"id": "recursos", "estado": "activo", "ultimo_mensaje": "…",
               "confianza": 0.62, "n": 4, "tendencia": "sube", "lecciones_activas": ["L-1"]}],
  "mensajes": [],
  "aristas": [{"de": "critico", "para": "recursos", "n": 3}]
}
```

## Revisión entre pares

Una `revision` / `objecion` / `correccion` **enlaza** el id de la propuesta del otro (`enlaza`).

Cadena de supervisión (además del crítico):

| Quién | Revisa a | Tool |
|---|---|---|
| recursos | prioridad | `pizarra_publicar` tipo `revision` |
| avisos | recursos | igual |
| vigía | el plan entero | igual |
| crítico | el especialista que se equivocó | `correccion` o `objecion` |

`decidir` **no ejecuta** una decisión conjunta con objeciones de gravedad `alta` abiertas: responde `resolver primero` y la lista. Si no se resuelven en `MANDO_ENJAMBRE_OBJECION_S` (defecto 45 s), escala a una persona (tarjeta). Lo vital se despacha igual.

## Confianza aprendida

Al cerrar un incidente y al llegar resultados (`aceptó`, `rechazó`, `silencio`, `llegó`, `evitó`, `cumplió`) se actualiza la puntuación del agente **por familia**:

`score = (α + aciertos) / (α + β + N)` con prior débil `α = β = 1`.

Si **N < 3** la etiqueta es **«sin evidencia»**: no se usa como peso. El coordinador, cuando dos propuestas compiten y ambos tienen N≥3, pesa por esa puntuación (el de más acierto gana voz). La regla está en `GET /api/explica` → `enjambre.regla_peso`.

## Lecciones por agente

`memoria/lecciones` acepta `para_agente`. Una persona aprueba. `contexto` y `pizarra/leer` entregan a cada agente solo las suyas + las globales. `revocar` las saca.

## Nodos exactos a añadir en cada workflow `prueba-ana-*`

Tools hijas del Prompt, Method `POST`, header `X-Mando-Token` = secreto de callbacks, body `payload_json`. `B` = `{{callback_url}}` o `$MANDO_PUBLIC_URL`.

### En **cada** especialista
(`prueba-ana-triaje`, `prueba-ana-prioridad`, `prueba-ana-recursos`, `prueba-ana-avisos`, `prueba-ana-vigia`, `prueba-ana-critico`)

1. **Al inicio del Prompt** (primera tool que llama el agente): Tool **`pizarra_leer`**
   - URL `B/hr/tools/pizarra/leer`
   - body: `{"agente":"<id>", "incidente":"@incident_id", "n":12}`
2. **Antes de terminar** (después de razonar, **antes** de `entregar_resultado`): Tool **`pizarra_publicar`**
   - URL `B/hr/tools/pizarra/publicar`
   - body: `{"de":"<id>", "para":"todos", "incidente":"@incident_id", "tipo":"propuesta", "texto":"@porque", "confianza":0.7}`

Herramientas de observación ya existentes (`contexto`, etc.) se quedan. Añadir las pequeñas (`zona`, `recurso`, `rutas`, `staff`, `previsiones`, `incidentes_parecidos`, `protocolo`, `confianza`, `acciones_posibles`, `ensayar`, `comparar_opciones`) bajo el mismo Prompt para que elija rama.

### `prueba-ana-critico` (además)

3. Tool **`pizarra_publicar`** para devolver correcciones al especialista:
   - `tipo`: `correccion` o `objecion`
   - `para`: el especialista que se equivocó (`recursos`, `prioridad`, …)
   - `enlaza`: id de su propuesta
   - `gravedad`: `alta` si bloquea la ejecución

### `prueba-ana-equipo` (coordinador)

4. Tool **`analizar_situacion`** al empezar (elige rama y modo; publica el porqué en la pizarra).
5. Tool **`confianza`** **antes** de componer: pesa propuestas que compiten por la puntuación (el backend también lo aplica en `decidir`).
6. Tool **`acciones_posibles`** y **`comparar_opciones`** (hasta 5; la tabla **no** elige).
7. Tras `APROBAR` / `ESCALAR A PERSONA`: `decidir` como ahora. El backend rechaza con `resolver primero` si hay objeciones altas.
8. `pizarra_leer` al inicio y `pizarra_publicar` tipo `decision` antes de terminar.

### `prueba-ana-vigia` / `prueba-ana-reevalua`

9. Tool **`cambio`**: relanzar **solo** los especialistas de `afectados` (prioridad/recursos/avisos tocados). No rehacer el equipo entero.
10. Ritmo: consultar `GET /api/adaptacion` → `ritmo_vigia.cada_min` (más a menudo si volátil).

### `prueba-ana-aprende`

11. `memoria/lecciones` con `para_agente`.
12. `POST /hr/tools/resultado` al cerrar.
13. `POST /hr/tools/prompt/proponer` (diff + evidencia N). Aprobar en Sala (`POST /api/prompt/versiones`). Nunca usar una versión no aprobada.

No se editan aquí los prompts `.md` de cada agente: otro agente los mejora.
