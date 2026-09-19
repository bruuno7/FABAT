# Sistema agéntico adaptativo — tres escalas

Todo por la base única (`MANDO_DB`), con su N, revocable y **sin saltarse barandillas**. Visible en `GET /api/adaptacion` y en `S.enjambre`.

Cadena de decisión (detalle en [ENJAMBRE](ENJAMBRE.md)): plataforma → LLM local → reglas (último recurso, rotulado «modo degradado: reglas»).

## 1. Dentro del incidente (segundos–minutos)

El vigía replanifica ante cualquier cambio (`/hr/tools/cambio` → solo afectados).

El sistema elige **estrategia** con las señales de `/hr/tools/analizar_situacion`:

| Modo | Cuándo | Qué implica |
|---|---|---|
| `calma` | un incidente, medios de sobra | resolver bien y ahorrar recursos |
| `carga` | varios a la vez | priorizar y reservar |
| `crisis` | recurso crítico agotado o riesgo vital múltiple | reasignar, escalar antes, avisar más arriba |

El modo activo y su porqué salen en la pizarra y en `S.enjambre.modo`. El coordinador **elige la rama** (qué especialistas activar) y lo publica con su porqué; `analizar_situacion` no elige por él, solo da señales.

Tras un despacho vital reflejo, el equipo razona igual el resto (a quién más avisar, qué recurso, qué vigilar).

## 2. Dentro del día (minutos–horas)

### Autonomía adaptativa (por agente y tipo de situación)

Umbrales declarados (visibles en `/api/adaptacion.umbrales`):

- `n_min = 3`
- `alta = 0.7`
- `baja = 0.45`
- prior bayesiano débil `α = β = 1`

Con confianza **alta** y N suficiente, las propuestas de ese agente se ejecutan directamente (**salvo barandillas**: evacuar / parar / ayuda externa siguen siendo tarjeta). Con confianza **baja** y N≥3, pasan por revisión de un par. Si N<3: «sin evidencia»; no se inventa autonomía extra ni se usa como peso. Lo grave **nunca** pasa sin persona, da igual la puntuación.

### Ritmo adaptativo del vigía

Reevalúa más a menudo cuando la situación es volátil (muchos cambios por minuto, previsiones cerca del umbral) y menos en calma. `ritmo_vigia.cada_min`: crisis 1, carga 2, calma 5; volátil resta 2 (mínimo 1).

### Activación adaptativa

El coordinador aprende qué especialistas aportan en cada tipo (`especialista_aporte`: n, cambios de la decisión conjunta). Los que nunca cambian la decisión (`N≥3` y `cambios=0`) se saltan **en calma** para ahorrar tiempo. En **crisis** se activan siempre. Triaje, crítico y vigía no se saltan.

## 3. Entre días (lecciones y prompts)

Lecciones por agente: ver [ENJAMBRE](ENJAMBRE.md). Revocables.

**Evolución de prompts:** el agente de aprendizaje propone una versión nueva (`POST /hr/tools/prompt/proponer`: cuerpo, diff legible, evidencia, N). Una persona aprueba (`POST /api/prompt/versiones`). Se guarda versionada con quién y cuándo. Se puede **revertir** a la anterior (o al fichero `equipo/<agente>.md` si no hay otra aprobada). Una versión **no aprobada nunca se usa**. Comparación anterior vs nueva en los mismos escenarios: `POST /hr/tools/prompt/comparar` usa `motor/evals` (`demo.jsonl`) si existe, con su N.

## `GET /api/adaptacion`

```json
{
  "ok": true,
  "modo": {"id": "carga", "porque": "varios incidentes a la vez: priorizar y reservar"},
  "historial_modo": [],
  "autonomia": [{"agente": "recursos", "n": 4, "puntuacion": 0.71, "autonomia": "directo"}],
  "umbrales": {"n_min": 3, "alta": 0.7, "baja": 0.45},
  "ritmo_vigia": {"cada_min": 2, "volatil": false, "modo": "carga"},
  "especialistas": {"activar": ["triaje", "prioridad", "recursos"], "saltar": [], "porque": "…"},
  "lecciones": [],
  "prompts": [],
  "cadena": "plataforma",
  "degradado": false
}
```
