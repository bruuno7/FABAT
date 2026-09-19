# motor/mando — el agente

Carpeta privada: nada de esto se sube a ningún repo. Python 3.14, solo biblioteca estándar. Determinista: mismas
observaciones, mismas decisiones (sin reloj ni azar). Se ejecuta desde la raíz del proyecto:

```
python3 -m unittest motor.mando.test_mando -v     # 49 tests, incluido el de integración con el simulador real
python3 -m motor.mando.free_text_bench            # avisos libres escritos a mano: familia, tipo y zona
```

**Qué es y qué no es.** Mando es un planificador de bucle cerrado con REGLAS: cero LLM en el núcleo. El parser de
avisos (`parser.py` + `lexicon.py`) son expresiones regulares y tablas escritas a mano; no es «IA» y no se vende como
tal. La vía prevista para los textos que las reglas no reconocen es `LLMParser` (mismo contrato, sin llamar a ninguna
API todavía). Lo propio de Mando es otra cosa: el plan lleva ESCRITOS sus supuestos, se ENSAYA en un gemelo del
recinto antes de ejecutarse y se tira solo cuando un supuesto se rompe.

Mando recibe `Observation`, devuelve `Action` y habla con personas por `CommsAPI`. **No importa, lee ni copia nada de
`motor/cases/`** (lo vigila `TestNoHeldoutLeak`). De `motor/world/festival.json`, si existe, lee lo que sabría
cualquier centro de control por el plan de aforo: minutos por arista (incluidas las vías de servicio), descarga de
los tornos de cada puerta, zonas que la ambulancia no cruza, densidad máxima para la ambulancia y el cargo de cada
recurso. Si no existe, usa saltos por `Zone.neighbors` (2 min por salto).

## API pública

```python
from motor.mando import Mando, Playbook, HeuristicParser, LLMParser, CascadeParser, report

agent = Mando(playbook=None, comms=None, parser=None, *, twin=None, watch_zones=True, festival=None,
              params=None, memory=None)               # ver «Memoria operativa y parámetros aprobados»
agent.tick(obs: Observation) -> list[Action]      # acciones NUEVAS de este tick (y las aprobadas desde el anterior)
agent.approve(action_id, ok, note="") -> None     # sí o veto de la persona con cargo
agent.snapshot(full=False) -> dict                # vista PÚBLICA por defecto; full=True = centro de control
text, data = report(agent)                        # informe posterior (texto en español + dict)
```

- `twin`: callable sin argumentos que devuelve un gemelo del mundo actual (`world.twin`). De él Mando usa solo
  `apply`, `step` y `observe`; nunca `truth()`. Con `twin=None` todo funciona con la proyección analítica.
- `playbook=None` → manual vacío. `Playbook.load()` sin ruta carga `playbook.seed.json` (3 lecciones de ejemplo).
- `comms=None` → Mando no llama a nadie y solo se entera de rechazos por `obs.action_results`.
- `tick` devuelve las acciones ya con estado: `EXECUTING` (AUTO: aplicar al mundo), `AWAITING_APPROVAL` (no aplicar),
  `DONE` (MERGE y DISMISS: contabilidad). **Una acción aprobada vuelve a salir en el `tick` siguiente** con
  `EXECUTING`, para que el bucle de `INTERFACES.md` la aplique sin código especial.

`snapshot()`: `t` · `incidents` (por prioridad; cada uno con `explain`, `label`, `origin` report|watch|pattern,
`life_threat`, `reserved`, `hold`, `plan`, `replans`, `level`, `waiting`…) · **`fronts`** (tablero: por incidente vivo,
estado, equipo con su ETA, prioridad, `waiting` y `why_waiting`) · `plans` (vivos e invalidados, con supuestos y su
estado, `supersedes`, `invalidated_by`, `why`) · `actions` (las que esperan llevan `params.decision_card`) ·
`pending_approvals` · `resources` (+ `assigned_to`, `role`) · `log` · `counters` (… `rehearsals`, `escalations`,
`human_decision_latency` = {acción: minutos entre la propuesta y la respuesta}, `human_decision_latency_mean`) · `lessons`.

## Qué hace en cada tick

avisos → triaje → prioridades → **supuestos de los planes vivos** → resultados de acciones y de comunicaciones →
reparto global de recursos → (re)planificación con ensayo → escalada de tarjetas sin contestar.

Si un supuesto se rompe: `Assumption.holds=False`, `Plan.invalidated_by`, se cancelan las acciones pendientes que
dependían de él y el plan nuevo lleva `supersedes` y un `why` que nombra el supuesto roto. Si lo rompió una decisión
propia (nuestro desvío), el log lo dice. Las revisiones repetidas de un mismo incidente («reevaluar en 5 min») que no
cambian nada se agrupan en UNA línea de log que se va actualizando.

| Fichero | Qué es |
|---|---|
| `lexicon.py` | REGLAS: tipos de incidente (cómo se reconocen y qué pide el protocolo), señales genéricas, alias de zonas. |
| `parser.py` | `Parser` (Protocol), `HeuristicParser` (reglas), `LLMParser` y `CascadeParser` (enchufe para un modelo). |
| `triage.py` | Correlación (MERGE), contradicciones (ASK), retención de avisos poco fiables, patrones. |
| `priority.py` | El número de prioridad y su explicación en una línea. |
| `assumptions.py` | Evaluación de los `check` de los supuestos. |
| `rehearsal.py` | Ensayo previo en el gemelo: alternativas, criterio de elección, resultado con números. |
| `planner.py` | Plan con pasos y supuestos: recursos por ETA, RECALL, REROUTE ensayado, ASK primero. |
| `autonomy.py` | AUTO frente a APPROVE, tarjeta de decisión, lección candidata de un veto. |
| `playbook.py` + `playbook.seed.json` | El manual que aprende. |
| `memory.py` → `memory.day1.json` | Memoria operativa: RESULTADOS OBSERVADOS de la jornada, con su N. Nunca lee la verdad del mundo. |
| `tuning.py` → `params.proposed.json`, `params.approved.json` | De la memoria a cambios de PARÁMETROS que una persona aprueba o rechaza; `Params` es lo que lee Mando. |
| `mando.py` | El bucle, el reparto global, el registro y `snapshot()`. |
| `report.py` | Informe posterior: qué pasó, qué decidió, supuestos rotos, qué hizo mal, qué cambiaría. |
| `free_text_bench.py` | 60 avisos libres escritos a mano para medir el parser. |

## Lo que el parser no reconoce (partición «nunca vista»)

El léxico cubre vocabulario general de emergencias escrito a mano. Ante un aviso cuyo tipo no reconoce, Mando
**generaliza, no memoriza**: `lexicon.generic_family()` da familia + señales (¿riesgo vital?, ¿amenaza?, ¿cuántos?,
¿zona?), el tipo queda `unknown_<familia>`, la confianza baja 0,15 y la política es conservadora y explicable:

- riesgo vital → sale ya el recurso genérico adecuado (equipo médico) y se pregunta mientras llega;
- amenaza o sospecha → se ESCALA a la persona (`NOTIFY` a `operator` con `escalate`) y se pregunta; Mando no despacha,
  no radia y no propone nada: no decide;
- el resto → ASK para obtener lo que falta; cuando contesta quien está en el sitio (con `data.type/needs` o con
  texto) se actúa por familia con lo que él pide. El nombre del tipo lo da esa persona, no el léxico.

Queda en el log: «M-007: tipo no reconocido: actúo por familia y señales (…)». Procedencia del léxico: una versión
anterior copiaba patrones de `motor/cases/phrasing.py` e incluía 12 de los 13 tipos solo-heldout. Se retiró entera; la
actual parte de la primera versión (anterior a leer `motor/cases`) más alias de zona generales. Reservas que
conviene saber: los nombres de rol de NOTIFY (`security_lead`, `violet_point`…) coinciden con los del generador, y las
fichas de protocolo de los tipos de TRAIN se escribieron después de haber leído sus reglas `must`.

## Ensayo previo (`rehearsal.py`)

Antes de ejecutar una decisión con efectos de flujo o de ruta, Mando genera 2–4 alternativas, las ensaya 12 min en un
gemelo (15 min para rutas) y elige con este criterio, en orden: nadie por encima de 6,5/m² · menos minutos por encima
de 4/m² en las zonas vigiladas · pico de densidad más bajo · la menos intrusiva. Como mucho 20 ensayos por tick.

- **REROUTE** (con el SET_ZONE y los despachos que el mismo plan ya lanza, como contexto): «X % al mejor destino»,
  «todo lo desviable (60 %) al mejor», «Y % al segundo destino», «sin desvío». Si gana «sin desvío», no se desvía.
- **Ambulancia**: se ensaya si llega y cuándo con las dos mejores opciones (no cruza público por encima de 1,5/m²
  ni zonas sin tránsito de vehículos; usa las vías de servicio). Si no llega en 15 min, va el equipo a pie.
- **STOP_SHOW, EVACUATE, cerrar zona, megafonía general, REROUTE que pide aprobación**: se ensayan las DOS ramas
  (si se aprueba / si no) para la tarjeta de decisión.

El resultado ESCRIBE los supuestos con números («ensayado: Puerta A (norte) llega al 53 % en 12 min; supuesto: Puerta A
sigue por debajo del 85 %») y queda en una línea de log: «ENSAYO (12 min) para Puerta B: 60 % a Puerta A → Puerta A
2,1/m² en 12 min ✓ · 52 % a Puerta C → Puerta C 3,1/m² ✓ · sin desvío → Puerta B 5,4/m² ✗». El horizonte es corto a
propósito: el gemelo supone que una oleada sigue al ritmo actual y a 30 min sobreestima; al reevaluar se reensaya.
Repartir un desvío entre dos destinos está escrito (`planner.ALLOW_SPLIT`) pero apagado: el simulador guarda un solo
desvío por origen (`World.reroutes[src]`); hace falta que admita varios para activarlo.

## Autonomía y tarjeta de decisión (`autonomy.py`)

APPROVE: `EVACUATE`, `STOP_SHOW`, `REQUEST_EXTERNAL`, cerrar una zona, **megafonía general** (zona `general`,
`stage_front` o todo el recinto) y todo **REROUTE cuyo ensayo (o, sin gemelo, su proyección) no deje el destino por
debajo de 4/m²**. AUTO: despachar (una posible parada nunca espera), avisar, preguntar, restringir, reabastecer,
megafonía de zona pequeña y REROUTE ensayado con el destino < 4/m². Ninguna lección puede cambiar esto.

Toda acción que espera lleva `params["decision_card"]`: `addressee` (el cargo que decide: «Director del Plan de
Actuación»; «Coordinador sanitario» para ambulancia externa; «Responsable del punto violeta (con el consentimiento
de la víctima)» para la policía en una agresión sexual), `deputy`, `if_approved` e `if_vetoed` (pico de densidad,
minutos por encima de 4/m², minuto de aplastamiento, por zona; `null` si no hay gemelo), `rehearsed`, `window_min`
(sale del ensayo: minutos hasta el aplastamiento o el pico si no se hace nada), `asked_at`, `escalate_at`,
`escalated_at`, `answered_at`. Si nadie contesta en `escalate_at`, Mando emite un NOTIFY al suplente
(`params.about` = la acción, `escalate=true`) y lo deja en el log. La latencia de cada decisión queda en
`counters.human_decision_latency`. Una evacuación **preparada** ante una amenaza (`params.prepared=true`) no la
ejecuta un aprobador automático: `approve(id, True, note)` exige que `note` empiece por «EVACUAR». Veto → lección
candidata y el plan nuevo propone el escalón menos drástico (`autonomy.ALTERNATIVE`).

## Casos reservados

Violencia sexual, menores y amenazas (`TypeSpec.reserved`, o la señal de amenaza): nunca BROADCAST, no se repite el
contenido al informante (las preguntas son neutras), se avisa al punto violeta o al responsable y la policía solo con
aprobación. En `snapshot()` (vista pública) el incidente sale con `reserved: true`, `label: "incidente reservado"`,
sin tipo ni zona ni notas; sus planes, acciones, recursos y líneas de log salen enmascarados. `snapshot(full=True)`
es la vista del centro de control.

## Memoria operativa y parámetros aprobados (el bonus «aprende de interacciones pasadas»)

La forma es la de `IDEA-bruno.md`: **resultados observados → propuesta de cambio de PARÁMETROS → aprobación de una
persona → medición con la misma secuencia y las dos configuraciones** (`python3 -m motor.harness day2`). No son lecciones
ni reglas y nada depende de `expected.must`: es estimar, con su N, cómo funciona de verdad ESTE recinto.

```python
from motor.mando.memory import OperationalMemory
from motor.mando.tuning import Params, propose

agent = Mando(comms=comms, params=Params.initial(), memory=OperationalMemory())    # día 1: valores de ficha + memoria
proposals = propose(agent.memory, names={"water_n": "Agua Norte"})                  # lista de Change con su N y su texto
proposals.approve("C-01", by="Ana"); proposals.reject("C-04", note="pocos datos")   # lo decide una PERSONA
proposals.write_approved()                                                          # → motor/mando/params.approved.json
agent = Mando(comms=comms, params="approved")                                       # día 2 (= Params.load())
```

- **`params=None` es el Mando de siempre** (no anticipa nada; las cifras anteriores del banco no cambian: comprobado byte a
  byte). `Params.initial()` = valores de ficha. Lo propuesto y no aprobado, o rechazado, **no entra** (hay test).
- **La memoria solo apunta lo que Mando observa**: la `Observation` de cada minuto, sus acciones y lo que contestan por
  `CommsAPI`. `memory.py` no importa el simulador ni los casos, y hay un test que hace reventar `world.truth()` mientras
  se construye. Guarda: (a) minutos reales de cada reposición (pedida → DONE) por punto, consumo observado (`water_l` minuto
  a minuto) y depósitos vistos a cero; (b) por recurso y canal: aceptó / rechazó / no contestó, minutos hasta aceptar y
  minutos perdidos en cada intento fallido; (c) avisos sin zona y minutos hasta saberla (ASK → respuesta), y minutos que el
  equipo tardó en dar con la persona en cada zona (`params.search_min`, lo cuenta el equipo); (d) avisos por incidente,
  minutos entre avisos repetidos y equipos que llegaron para nada donde ya había otro incidente igual, confirmado y
  abierto; (e) alertas de viento: aviso, preparativos y desenlace (llegó / no llegó, minutos hasta desactivarse).
  `n_by_parameter()` da el N detrás de cada parámetro.

| Parámetro | Valor de ficha | Qué propone `tuning.py` | Qué hace Mando con él |
|---|---|---|---|
| `resupply_lead_min[punto]` | 10 min | p80 de los minutos observados (N ≥ 5); nunca MENOS que la ficha | cada minuto estima litros ÷ consumo observado; si quedan menos minutos que `lead + 3`, abre `water_low` y pide el RESUPPLY ya |
| `contact_order[tipo]` | el más rápido | tasa de respuesta por recurso, suavizada hacia la media del tipo (5 llamadas de prior); solo si la diferencia ≥ 15 puntos; recursos con < 5 llamadas no entran | al ETA de cada candidato se le suman los minutos ESPERADOS que se pierden si no contesta: (1 − tasa) × minutos observados por intento fallido |
| `require_precise_location[zona]` | no | zonas donde dar con la persona costó ≥ 3 min de media | sale el equipo Y A LA VEZ un ASK `purpose="point"` («¿junto a qué torre, puesto o acceso numerado?»); el punto se pasa por NOTIFY al equipo en camino. Nunca retrasa el despacho. De esa respuesta solo se usa el punto |
| `duplicate_window_min` | 15 | solo se ALARGA, y solo si hubo equipos movidos por un probable duplicado fuera de ventana | ventana de fusión del triaje; **nunca se aplica a un riesgo vital** (a los 20 min puede ser otra persona) |
| `weather_followup_min` | 5 | 3 si el viento pasó de preaviso a riesgo en < 5 min | cada cuánto se revisa un aviso meteorológico abierto |
| `weather_standdown_min` | — | 10 (mínimo) si hubo alertas que no llegaron a más | tras N min seguidos en calma y sin avisos nuevos, cancela los PREPARATIVOS y libera equipos |

Cada propuesta lleva valor anterior, valor nuevo, evidencia con N y una línea para la pantalla («Reposición en Punto de
agua norte: tardó 28,7 min de media (N=50; 46 veces el depósito llegó a 0 antes); propongo pedirla 22 min antes»). Con
N < 5 dice **«EVIDENCIA LIMITADA»** y el cambio es conservador (viejo + (observado − viejo)·N/(N+3)). Lo mirado y NO
cambiado también sale, con su porqué (`Proposals.unchanged`).

**Lo que nunca se ajusta.** Que la tormenta no llegara el día 1 NO enseña a ignorar el aviso del día 2. `TUNABLE` es una
lista cerrada; `SAFETY_LOCKED` (viento de parada, escalones de viento, densidades, qué exige aprobación…) no está en ella;
`Params` rechaza con `ValueError` un fichero que los traiga, y tampoco deja pedir el agua más tarde que la ficha, acortar
la ventana de duplicados ni bajar de 10 min de calma. Test: con ocho alertas fallidas el día 1 y todo aprobado, el día 2
el preaviso se atiende igual y la parada se propone en el mismo minuto y con aprobación humana.

**Cada vez que un parámetro aprendido cambia una decisión queda en el log** (`kind = "param"`): «Parámetro aprendido
resupply_lead_min[water_n] (N=50): reposición de Punto de agua norte pedida con ~34 min de agua; con el valor de ficha (10
min) se habría esperado ~21 min más». `snapshot()["params"]` = `{active, values, evidence, applied}` y
`counters.params_applied`. El tipo `water_low` («agua a punto de agotarse») es observación propia de Mando, del mismo grupo
que `water_out`: si el sensor acaba diciendo «0 litros», es el mismo incidente y no sale otra cisterna.

Límites que conviene saber: el consumo se estima con los últimos 6 minutos, así que con el público aún entrando se queda
corto; hay UNA sola logística para dos puntos de agua; el orden de contacto apenas cambia nada mientras no contestar
cueste solo ~2 min (así salió medido).

## Muchos frentes a la vez

Antes de planificar, `_allocate` reparte los recursos LIBRES entre todos los incidentes que piden el mismo tipo: se
sirve primero a los de riesgo vital y luego por prioridad, y entre los servidos se minimiza la suma de prioridad ×
minutos de llegada (no gana el primero que llega). Si no alcanza, un incidente más prioritario puede quitarle el
recurso al de MENOR prioridad (RECALL, con margen de 1,5 puntos y 5 min de enfriamiento; nunca a un riesgo vital). El
que espera queda explicado en `fronts[].why_waiting` y en el log: «M-004 espera seguridad: prioridad 1,4, sin riesgo
vital; le llega Seguridad 3 en ~11 min, cuando acabe M-005». Al entrar un imprevisto solo se toca el plan del
incidente que pierde el recurso; los demás siguen vivos.

## Prioridad

```
prioridad = min(10, gravedad × f_plazo × f_densidad × f_vulnerable × f_tendencia × f_confianza) + ajuste_del_manual

f_plazo       0,6 + 0,6·u        u = 1 − minutos_restantes/30 en [0,1]; sin plazo u = 0,5 (×0,90)
f_densidad    1 + k·d            d = (densidad − 2)/(7 − 2) en [0,1]; k = 0,3 en aglomeraciones y 0,1 en el resto
f_vulnerable  1 · 1,1 · 1,2      zona PMR y/o menores
f_tendencia   1 + 0,1·s          s = variación de densidad por minuto / 0,2 en [−1,1]
f_confianza   0,5 + 0,5·c        en riesgo vital c nunca cuenta menos de 0,8
ajuste        suma de `priority_boost` de las lecciones que aplican, acotada a ±2
```

Resultado en [0, 10]. Suelo 9,0 para un riesgo vital. Desempate: más gravedad, menos plazo, id más antiguo. El plazo
es una estimación de Mando por tipo y se corrige si quien está en el sitio lo dice. En pantalla:
`prioridad 5,1 = gravedad 6 × plazo 25 min (×0,70) × densidad 5,8/m² (×1,23)`.

## Supuestos (`Assumption.check`)

| `kind` | Parámetros | Se rompe cuando |
|---|---|---|
| `zone_occupancy_below` | `zone`, `ratio` (+ `own_action` si nace de un desvío propio) | ocupación/capacidad ≥ ratio |
| `zone_density_below` | `zone`, `density` | personas/m² ≥ density |
| `zone_state_is` | `zone`, `state` | la zona cambia de estado |
| `resource_status_is` | `resource`, `status` | el recurso queda OFFLINE o desaparece |
| `route_clear` | `zones`, `density`, `resource` | alguna zona del camino supera la densidad o se cierra |
| `weather_below` | `key`, `value` | p. ej. `wind_kmh` ≥ 70 |
| `supply_above` | `zone`, `flag`, `value` | p. ej. `water_l` ≤ 200 en el punto de agua alternativo |
| `action_accepted_within` | `action`, `since`, `minutes` | el equipo rechaza, no contesta o pasan 3 min sin verlo moverse |
| `incident_improving` | `incident`, `since`, `minutes`, `baseline`, `safe` | «reevaluar en N min»: la métrica del incidente no ha mejorado; sube el escalón de respuesta |

Un `kind` desconocido no tira el plan. Tras 6 planes fallidos seguidos Mando deja de insistir y escala a la persona.

## Parámetros de las acciones

- Siempre `zone` e `incident` (el id de MANDO, `M-001`; el mundo no lo conoce) y, salvo en lo preventivo,
  `params["reports"]` con los ids de aviso, **el más reciente primero**.
- DISPATCH: `resource`, `channel=voice`, `params`: `need`, `eta`, `route`, `message`, `type`. RECALL: `from_incident`,
  `for_incident`. RESUPPLY: `zone` = punto de agua. REROUTE: `to`, `fraction`, `dest_peak_density`, `rehearsed`
  (resultado del ensayo o `null`), `projected_ratio`; o `cancel=true`. SET_ZONE: `state`. BROADCAST: `message`.
  STOP_SHOW: `minutes`. EVACUATE: `prepared`. REQUEST_EXTERNAL: `kind` = `service` ∈ ambulance | police | fire | transport.
- NOTIFY: `params.to` ∈ security_lead, medical_lead, production, violet_point, coordinator, gates, all_leads, operator,
  o el cargo suplente de una tarjeta. ASK: `params.purpose` ∈ zone | type | confirm | clarify | sitrep.
- Voz caída (`params.error == "comms_down"` o respuesta «canal caído») → misma acción por `channel=sms` (`retry_of`).

Respuestas de `CommsAPI.poll`: `action_id` (o `action`), `result`: accept | reject | no_answer | answer, `text`, `data`.
Cuando el primer equipo llega al sitio Mando le pregunta qué hace falta (`purpose="sitrep"`) y ajusta `needs`.

## El manual (`Playbook`)

```json
{"id": "L-014", "text": "frase corta para la pantalla",
 "when": {"type": "gate_saturation" | ["a","b"], "family": "crowd", "zone": "gate_b", "zone_kind": "gate",
          "severity_min": 7, "weather": {"temp_c_above": 35, "wind_kmh_above": 50, "rain": true},
          "state": {"show_phase": "headliner", "day": 2, "zone_density_above": 4.0, "zone_ratio_above": 0.8}},
 "then": {"priority_boost": 1.0, "prefer_resource": "ambulance" | "med_2",
          "pre_action": {"kind": "broadcast", "zone": "general", "params": {"message": "..."}},
          "forbid_action": {"kind": "reroute", "to": "gate_a"},
          "assumption_threshold": {"zone_occupancy_below": {"ratio": 0.7}}},
 "source": "run c-000123 | veto del operador", "evidence_n": 12}
```

Todas las claves son opcionales; un valor puede ser escalar o lista. `Playbook.load/save/add/apply`. Cada vez que una
lección cambia algo queda en el log: «Lección L-014 aplicada: no se desvía hacia Puerta A — …». Material para el
revisor: `snapshot()["lessons"]["candidates"]` (vetos) y `report(agent)[1]["would_change"]`.

## Enchufar un modelo para leer avisos

```python
def client(prompt: str) -> str: ...   # llama al modelo que sea y devuelve el JSON como texto
agent = Mando(parser=CascadeParser(HeuristicParser(), LLMParser(client=client)))   # el modelo solo ve lo no reconocido
agent = Mando(parser=LLMParser(client=client, fallback=HeuristicParser()))         # o el modelo lo lee todo
```

`LLMParser` sin `client` lanza `NotImplementedError`; el prompt está en `parser.LLM_PROMPT`. Contrato de
`parse(report, zones) -> dict`: `type`, `family`, `zone | None`, `severity` 1–10, `needs`, `confidence`, `missing` y, de
apoyo, `life_threat`, `threat`, `reserved`, `generic`, `zone_relative`, `sitewide`, `count`, `minors`, `all_clear`,
`vitals_ok`, `negated`, `secondary`, `sensor`, `informational`, `staff`, `zone_candidates`.

## Lo medido (cifras tal cual)

Avisos libres escritos a mano (`free_text_bench.py`, N = 60, nada de plantillas). Primera medición, antes de tocar
nada: zona 53/60 (DEV 20/20, HOLDOUT 20/20, «ubicaciones difíciles» 13/20). Tras añadir alias generales mirando los
fallos de la tanda difícil: 60/60, cifra optimista porque esa tanda ya no es independiente. Familia 54/60; tipo
28/32 en las filas con tipo esperado (DEV 16/17, HOLDOUT 12/15). Las frases las escribió quien escribió los alias:
un revisor externo midió 6/12 de zona con la tabla anterior, y esa es la cifra a batir con frases ajenas.
