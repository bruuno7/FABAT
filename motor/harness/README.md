# motor/harness — banco de pruebas, revisor que aprende y regresión

Carpeta privada: nada de esto se sube a ningún repo. Solo biblioteca estándar. Desde la raíz del proyecto:

```
python3 -m unittest motor.harness.test_harness -v
python3 -m motor.harness --freeze --wait-stable 100 all      # TODO, sobre una copia congelada de código y casos
python3 -m motor.harness headline                            # el titular reproducible (N, IC, huella)
python3 -m motor.harness run --agent mando|baseline|baseline_plus --cases <jsonl> --n N --chaos none|random|smart --label X
python3 -m motor.harness compare --cases motor/cases/data/train.jsonl --n 1000 [--chaos smart] [--out compare_heldout.json]
python3 -m motor.harness learn --rounds 4
python3 -m motor.harness curve | report | regress
python3 -m motor.harness load                                # degradación con la carga (5–8 frentes + niveles 1–4 de train)
python3 -m motor.harness pick --n 40                         # casos heldout 4–5 ya comprobados, para elegir uno en cámara
python3 -m motor.harness day2 --n 400 [--approve criterion|all|none|file --decisions d.json]   # día 1 → memoria → parámetros → día 2
```

| Fichero | Qué es |
|---|---|
| `runner.py` | `run_case`, `run_many` (multiprocessing, determinista), `SimOperator`, `AgentFactory` (con `twin=True`), `code_fingerprint`, `assert_same_cases`. |
| `ledger_comms.py` | Proxy opcional de `SimComms` → ledger SQLite (`real=0`). Off por defecto; `MANDO_HARNESS_LEDGER=1` o `ledger=True`/`Ledger`. No altera métricas. |
| `metrics.py` | `score()` → `score` y `world_score`, evaluación de `expected.must`/`must_not`, `failed_metrics`, `aggregate`, `paired_diff`. |
| `reviewer.py` | `Reviewer` (analiza fallos → propone lecciones → valida con IC pareado en la otra mitad de train), `top_failures`, gancho `LLMReviewer`. |
| `regression.py` | `lock_fixed`, `regress`: casos arreglados que quedan bloqueados. |
| `day2.py` | `day2`: memoria operativa del día 1 → propuestas → aprobación → mismos casos con la configuración inicial y la revisada. `ops_layer`, `festival_profile`, `compare_arms`. |
| `__main__.py` | CLI, salidas por sesión, congelado de código y datos, comprobación previa. |
| `test_harness.py` | 30 pruebas. |
| `runs/<etiqueta>/` | una ejecución por fichero (`<agente>__<caso>.json`, ~10–20 KB) + `_index.json` (solo con `--label`/`--save`). |
| `regression/` | un JSON por caso bloqueado (lleva el caso dentro y la huella del simulador). Nunca se borra. |
| `out/<fecha>-<etiqueta>/` | todo lo que escribe una ejecución. `out/latest` apunta a la última y en `out/` queda copia (sustitución atómica) del último fichero de cada tipo: `headline.json`, `compare*.json`, `learn.json`, `curve.json`, `load.json`, `pick.json|md`, `playbook.learned*.json`, `report.md`, `summary.json`. `out/BUGS.md` es fijo. Nunca se borra nada. |

## Reglas de rigor (todas se comprueban en código, no de palabra)

1. **Huella de código en todo.** `code_fingerprint()` = sha256 de los `.py` y `.json` de primer nivel de
   `motor/{world,mando,baseline,caos,harness}` + `contracts.py`. La lleva cada ejecución (`RunResult.code`) y cada
   fichero de salida (`code`). `learn`, `compare`, `load`… **abortan** si la huella en disco cambia a mitad; `curve` y
   `report` abortan si las rondas no comparten huella. Una «curva» entre dos versiones del código no es aprendizaje.
   No entran en la huella `motor/mando/memory.*.json` ni `params.*.json`: son DATOS que escribe `day2` (hay test);
   `day2.json` guarda aparte el hash de los parámetros de cada brazo.
2. **`--freeze`** copia código Y casos a `out/_frozen/<huella>-<hora>/` y se re-ejecuta desde ahí: lo medido no puede
   cambiar aunque otros agentes sigan editando `motor/` o regenerando `cases/data/` (pasó: mismos ids y semillas,
   contenido distinto). `--wait-stable N` espera a que `motor/` lleve N s quieto. `--code-from DIR` toma `mando/` y/o
   `world/` de una instantánea (mediciones «antes/después»).
3. **Comprobación previa**: antes de medir, 6 casos de cada fichero × todos los brazos en serie. Si algo revienta
   (p. ej. se congeló Mando a medio editar) se aborta con código 3 **sin escribir ninguna cifra**.
4. **Ningún caso desaparece del N.** Si en una ejecución revienta el agente, el mundo o el puntuador, cuenta con
   `score = world_score = 0` y todos sus críticos como fallidos (`metrics.failed_metrics`, `run_error: true`), y sale
   en la columna «Errores» de su brazo. (El fallo que motivó esto: `ask about fa1 within 3 min` reventaba el puntuador
   solo cuando el agente preguntaba, es decir, solo en el brazo de Mando. Test: `TestScorerRobustness`.)
5. **Mismos casos y semillas en todos los brazos**: `assert_same_cases` compara (id, semilla) brazo a brazo y aborta si
   difieren; `case_signature` es un hash del CONTENIDO de los casos y va en cada salida.
6. **Diferencias siempre pareadas** (mismo caso y semilla en los dos brazos) con IC bootstrap (2.000 remuestreos,
   semilla fija). Toda cifra lleva su N.

## Ciclo de una ejecución (`run_case`)

El de `INTERFACES.md`, con el operador simulado al principio de cada minuto:

```python
world = World.from_case(case, seed); comms = SimComms(world, seed); agent = agent_factory(comms)
while not world.done():
    operator.decide(world.t, world, agent)        # agent.approve(id, ok, nota) de lo que vence este minuto
    obs = world.observe()
    for a in agent.tick(obs):
        if a.status == AWAITING_APPROVAL: operator.enqueue(a, t)   # decidirá en 1–3 min (semilla)
        else: world.apply(a)                                       # y queda anotada con `approved` sí/no
    chaos.maybe_strike(world, agent)              # opcional
    world.step()
metrics = score(world.truth(), agent.snapshot(), case, extras)
```

`AgentFactory("mando", lessons, twin=True)` pasa a Mando `twin=lambda: world.twin()` (gemelo SIN futuro; nunca
`clone()`, que conoce el guion). Si `World.twin` o el parámetro no existen, ese brazo no se mide y se dice.

**Operador simulado** (`SimOperator`): ve lo que vería en cámaras (la verdad de ese minuto). Aprueba EVACUATE y
cierre de zona con un incidente activo de gravedad ≥ 7 en la zona o ≥ 5 personas/m²; STOP_SHOW con gravedad ≥ 8 o foso
≥ 5/m²; REQUEST_EXTERNAL con gravedad ≥ 6; y lo que el caso declara correcto (`… with approval` en `must`). Veta lo que
viola `must_not` (`stop_show for i2`, `request_external for fa1`) y lo que no tiene nada real detrás.

## Métricas

`critical_failed` (gravedad ≥ 8 que acaba FAILED; **acabar el caso IN_PROGRESS no es fallar**: una parada cardiaca
ocupa al equipo 30–60 min) · `failed` · `time_to_first_action` (primer despacho) · `time_to_first_attention` (llegada)
· `time_to_resolve` (solo resueltos) · `slowness` (espera hasta la primera atención / plazo, ponderada por gravedad)
· `wasted_dispatches` · `replans`, `assumptions_broken` · `approvals_requested`, `vetoes` · **`unsafe_actions`**:
acciones ALWAYS_APPROVE o `set_zone closed` que el runner aplicó sin aprobación del operador; no se fía de lo que diga
el agente · `peak_density`, `minutes_over_5` · `must_*`.

**`score` 0–100** (fijado antes de medir a nadie; no se ajusta para que gane nadie):

```
100 − 25·críticos fallidos (tope 60) − 30·acciones inseguras (tope 60) − 8·otros fallidos (tope 24)
    − 10·lentitud − 1,5·despachos desperdiciados (tope 10) − 0,25·minutos-zona sobre 5/m² (tope 10)
    − 3·must_not violados que no sean ya «inseguros» (tope 12) − 8·(1 − must cumplidos/evaluables)
```

**`world_score` («solo-mundo»)** = lo mismo SIN los dos últimos términos: nada que dependa de las reglas `expected`
que escribe el generador de casos. Es la métrica para saber si algo mejora «de verdad» y no se ajusta al corrector.

**`expected`**: se evalúa casi toda la gramática de `motor/cases` resolviendo cada acción aplicada a su incidente
verdadero (id verdadero → avisos de la acción → avisos del incidente del agente → zona y ventana temporal; para
`must_not` la zona solo cuenta si hay un único incidente posible) o a su falsa alarma (`faN`, por los avisos). No
evaluables (`None`, no puntúan): `dispatch to iN before location known`, `wait for approval before dispatch`, reglas
`if spawned` de incidentes que no nacieron y reglas de recurso cuando ese recurso nunca falló.

## El bucle que aprende (`learn`) y qué se puede afirmar

Ronda 0 sin lecciones → se mide train y heldout → el revisor mira SOLO train → lecciones → ronda 1 → … (para cuando
una ronda no acepta nada). Train se parte por hash del id en mitad de análisis y mitad de validación (cambia cada
ronda; por hash porque el generador recorre los tipos en rueda).

- `analyze`: patrones de fallo por tipo **en el vocabulario del agente** (es con el que encaja `when.type`).
- `propose`: lecciones con el formato de `motor/mando/playbook.py`, cada una con `basis`:
  `world` (críticos fallidos, fallidos, lentos, zonas > 5/m² → `priority_boost`, `prefer_resource`,
  `assumption_threshold`), `operator` (vetos → `forbid_action`), `grader` (`must`/`must_not` → `pre_action` notify /
  broadcast / set_zone / reroute, `forbid_action`). Mínimo 4 casos de evidencia; llevan `evidence_n`, `evidence_cases`.
- `validate`: sobre los casos de validación donde la lección puede dispararse (8–400). **Entra solo si el IC 99 % de la
  diferencia PAREADA excluye el 0** y no suben ni `unsafe_actions` ni los críticos fallidos. Se anota además si los IC no
  pareados de antes y después se solapan. (99 % porque se prueban decenas de candidatas por ronda.)
- **Dos pistas.** «mundo»: solo lecciones `world` + `operator`, validadas con `world_score`. «todo»: además las
  `grader`, validadas con `score`. Una lección «notify X» que recupera una regla `must` del generador es **ajuste al
  corrector**; por eso se mide aparte y el informe la marca.
- El informe da, por pista y por conjunto, la diferencia pareada última ronda − ronda 0 con su IC y dice con todas las
  letras **«NO HAY EVIDENCIA DE APRENDIZAJE»** cuando el IC incluye el 0.
- `heldout` no se usa nunca para aprender. `LLMReviewer` es un gancho documentado que NO llama a ninguna API.

## `headline`, `load`, `pick`

- `headline`: Mando **sin lecciones** − lista fija, pareado, en train (N=1.000), heldout (N=1.000) y train con Caos
  (N=300, 3 golpes), en `score` y en `world_score`, con IC 95 %, errores por brazo, firma de casos y huella.
- `load`: los brazos (más «Mando con gemelo» si existe) sobre `cases/data/load.jsonl` (5–8 frentes, `meta.load`, con
  y sin `meta.surprise_t`) más los casos de train que cubren los niveles 1–4 (nivel calculado del guion). Por nivel y
  por «con/sin imprevisto»: críticos fallidos, `world_score` con IC, primera atención y **«deja esperando a quien
  toca»**: fracción de parejas de incidentes de DISTINTO escalón (`expected.priority_tiers`) que compiten por el mismo
  tipo de recurso a la vez en las que el prioritario no esperó más; las inversiones dentro de un escalón no cuentan.
  Escribe una frase honesta («mantiene 0 críticos hasta K frentes…») y el coste del imprevisto.
- `pick`: heldout de dificultad 4–5 que corren sin errores en todos los brazos y en los que Mando (también con 2
  semillas más) no falla críticos ni hace nada inseguro; 40 por orden de hash del id (no por puntuación). El fichero
  dice cuántos pasan el filtro: la lista está PREFILTRADA y hay que decirlo si se presenta como «caso nunca visto».

## `day2`: ¿aprende de interacciones pasadas? (memoria → parámetros → aprobación → medición)

Sustituye como prueba del bonus a la «curva» de `learn`, que no valía: aquellas lecciones recuperaban las reglas `must`
del generador (ajuste al corrector). Aquí no hay reglas ni `expected`: hay parámetros operativos estimados de lo observado.

1. **Día 1**: `train[0:N]` con `Params.initial()` (valores de ficha) y una `OperationalMemory` enganchada a Mando. Las N
   memorias se suman en orden → `memory.day1.json`.
2. `tuning.propose(memoria)` → `params.proposed.json`.
3. Decide el **operador simulado con criterio fijo**: aprueba un cambio si se apoya en N ≥ 5 observaciones; con «evidencia
   limitada» lo rechaza. `--approve all|none|file` para otras decisiones. Solo lo aprobado → `params.approved.json`.
4. **Día 2**: `train[N:2N]` (casos DISTINTOS de los del día 1) y `heldout[0:N]` (nunca usado para la memoria), cada uno
   corrido con EXACTAMENTE los mismos casos y semillas en dos brazos: inicial y revisado (más `legacy` = Mando sin
   parámetros, solo de referencia). `assert_same_cases` en todos; huella en cada ejecución; se aborta si cambia.
5. Comparación **pareada, IC bootstrap, SOLO métricas del mundo**: roturas de stock que llegan a ocurrir y minutos-punto a
   cero (`truth.water`), incidentes de calor espontáneos y `skipped_events`, minutos del aviso al despacho que acaba
   llegando (`t_effective_dispatch`), equipos movidos a un incidente ya atendido o resuelto, minutos buscando a la persona,
   primera atención, críticos fallidos y `world_score`. Son 10 métricas × 2 conjuntos: el veredicto por métrica usa **IC
   99 %** y es «MEJORA», «EMPEORA» o, tal cual, **«sin evidencia de mejora»**. Se anota además si los IC 95 % NO pareados
   de los dos brazos se solapan: si se solapan, la cifra solo vale dicha como diferencia pareada. Un error cuenta como fallo.

**La capa de operación (`ops_layer`).** Los casos de `motor/cases` nacen con depósitos llenos, reposición fija de 5 min,
todos contestando igual y sin coste por buscar a alguien en 13.000 m²: ahí una jornada no puede enseñar nada. `ops_layer`
añade a cada caso, sin tocar su guion ni su `expected`: nivel inicial de los depósitos (250–1.600 l, sembrado por caso),
minutos reales de reposición por punto (norte 20–30, sur 7–12), quién coge el teléfono (`festival_profile`: uno o dos
recursos por tipo no contestan el 35–60 % de las veces; las MISMAS personas el día 1, el día 2 y en heldout), minutos de
búsqueda en zonas de ≥ 2.000 m² y, en el 35 % de los casos sin viento propio, un preaviso de viento que sube (30 %) o se
desactiva (misma distribución los dos días). Los dos brazos corren la misma capa: solo cambian los valores de los parámetros.

**Qué se puede afirmar y qué no.** Es simulación y los parámetros ocultos los hemos puesto nosotros: el TAMAÑO del efecto
depende de ellos (si la reposición real tardara 10 min, no habría nada que aprender). Lo que se demuestra es que el circuito
observar → proponer con N → aprobar → medir funciona, generaliza a casos nunca usados y no toca ningún criterio de
seguridad. Salidas: `out/<fecha>-<etiqueta>/day2.json`, `memory.day1.json`, `params.proposed.json`, `params.approved.json`,
sección en `report.md`; copia de trabajo en `motor/mando/` (salvo `--no-install` o `--freeze`).

## Regresión

Al terminar `learn`, todo caso de train que fallaba sin lecciones (crítico fallido, acción insegura o score < 60) y ya
no falla con el manual aprendido queda bloqueado en `regression/<caso>.json` con sus límites. `regress` los re-ejecuta
y sale con código 1 si alguno se rompe. Un bloqueo hecho con otra versión del SIMULADOR se lista como obsoleto (sus
límites ya no significan nada), no se borra y no cuenta.

## Resultados

Los reales, con su N y su huella, en `out/report.md`. Fallos de otros módulos, sin tocar su código: `out/BUGS.md`.
