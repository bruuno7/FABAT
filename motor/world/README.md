# motor/world — simulador del «Festival Abierto»

Determinista (mismo caso + misma semilla = misma ejecución), tick de 1 minuto, solo biblioteca estándar.
Un caso de 90 min con `observe()` en cada tick tarda ~3,3 ms; los tres días enteros, ~0,1 s.

```python
from motor.world import World, SimComms, load_festival

world = World.from_case(case, seed)        # case: dict con el formato de INTERFACES.md
comms = SimComms(world, seed)
while not world.done():
    obs = world.observe()
    for a in agent.tick(obs):
        if a.status != ActionStatus.AWAITING_APPROVAL:
            world.apply(a)                 # muta y devuelve la MISMA acción; nunca lanza
    world.step()
truth = world.truth()
```

```
python3 -m unittest motor.world.test_world -v
python3 -m motor.world.demo                # demo_case.json con un agente trivial, puertas minuto a minuto
python3 -m motor.world.demo --reroute 6    # igual, desviando gate_b -> gate_a en t=6: gate_a pasa de 6,5/m²
python3 -m motor.world.demo --bench 200    # ms por ejecución
```

## API pública

- `load_festival(path=None) -> dict` — `festival.json` cacheado. **No mutarlo.** Aristas con `minutes` y `staff_only`.
- `World.from_case(case, seed=None, festival=None) -> World` (`seed=None` usa `case["seed"]`).
- `WorldAPI`: `t`, `observe()`, `apply(action)`, `inject(event)`, `step()`, `truth()`, `clone()`, `done()`.
- `World.twin(seed: int | None = None) -> World` — gemelo para que el AGENTE ensaye (ver «Gemelo»). `clone()` es la
  copia exacta con futuro y mismo RNG: es la del adversario, Mando no debe usarla.
- Ayudas de solo lectura (no son verdad oculta): `travel_time(from_zone, to_zone, resource_id=None) -> int | None`
  (None = sin ruta, p. ej. ambulancia bloqueada), `density(zone)`, `clock()`.
- Para `SimComms`/adaptadores: `contact_state(resource_id) -> ok|offline|no_answer|rejects`,
  `channel_down(channel) -> bool`, `answer_for(action) -> (texto, data)`.
- `SimComms(world, seed=0, p_reject=0.04, p_no_answer=0.03)`: `send(action, resource=None)`, `poll(t)` →
  `{"action_id", "result": accept|reject|no_answer|answer, "text", "t", "data"}`. `data` es extra: en un `ASK`
  trae `{"exists": True, "zone", "type", "family", "severity", "needs", "deadline"}`, `{"exists": False}` (falsa
  alarma) o `{"exists": None}`. Un `ASK` localiza el incidente por `action.incident` (id verdadero),
  `params["report"]`/`params["reports"]` (ids de aviso) o `action.zone`. RNG propio: no toca el del mundo.

## Gemelo para ensayar (`twin`)

```python
tw = world.twin()                       # ~15 µs, igual de barato que clone()
tw.apply(Action("e1", ActionKind.REROUTE, tw.t, zone="gate_b", params={"to": "gate_a"}))
for _ in range(15):
    tw.step()
tw.density("gate_a"); tw.travel_time("medical_1", "front_pit", "amb_1"); tw.observe()
```

Copia el estado de AHORA (ocupaciones, estados y flags de zona, recursos y sus trayectos, acciones vivas, desvíos,
megafonías, evacuaciones, externos ya pedidos, meteorología, reloj y programa) y le quita el futuro: ningún evento
del caso posterior a `t`, ningún incidente espontáneo (calor, viento, agua), ningún aviso retenido. RNG propio:
por defecto sale de `(seed del mundo, t)`, así que dos gemelos del mismo minuto son iguales; con `seed` se fija.
No comparte estado con el mundo real ni toca las acciones del agente. `done()` nunca es cierto: el agente decide
cuántos minutos avanza. `truth()["twin"]` vale `True`.

Lo único del presente que el gemelo no puede saber es cuándo ACABA una oleada (`zone_inflow`) en curso: supone que
sigue indefinidamente al ritmo actual. Es una previsión por persistencia, conservadora. En `demo_case.json`, con el
desvío gate_b→gate_a aplicado en t=6, el gemelo clava la densidad de gate_a minuto a minuto (4 /m² en t≈19, 6,5 en
t≈33, error 0) hasta t=47, que es cuando la oleada real se acaba; a partir de ahí el gemelo sobreestima.
Sí genera `crush_risk` y avisos SENSOR, porque son consecuencia de la densidad que se está ensayando. El gemelo
conserva los incidentes verdaderos abiertos (hacen falta para que los recursos en camino trabajen): Mando debe leer
de él solo `observe()`, `density()`, `travel_time()` y el estado de sus propias acciones, nunca `truth()`.

## Tiempo

`t` = minutos desde el inicio del caso. `day` + `start_hhmm` sitúan el caso en el programa; una hora anterior a
las 06:00 cuenta como la madrugada de ese mismo día de festival. La ocupación inicial sale del programa (cuánta
gente ha llegado ya y dónde está) y `initial.occupancy` pisa zonas sueltas. `events[].t == k` se ve en el
`observe()` de `t == k`. `new_reports` y `action_results` son los del último tick (repetir `observe()` no los pierde).

Además de `occupancy`, `weather` y `resources_offline`, `initial` admite: `flags` (`{"water_n": {"water_l": 500}}`),
`zone_state` (`{"gate_c": "closed"}`) y `spontaneous` (`false` apaga los incidentes que el mundo genera solo por
calor, viento o agua; los de densidad crítica salen siempre).

## Modelo

- **Multitud.** Cada fase del programa da a cada zona un peso; `deseado = peso × gente dentro`. Pasillos y pista son
  zonas de paso (difunden su exceso); el resto son destinos (se llenan hasta lo deseado y sueltan lo que les sobra).
  Cada arista tiene tope de personas/min. La entrada voluntaria se frena cuando la zona pasa de su `comfort_d`
  (a cero en `comfort_d + 1,5`); la forzada (llegadas de fuera, `zone_inflow`, desvíos) solo se frena cerca de
  `hard_density`. `restricted` multiplica la entrada por 0,4 y `closed` por 0.
- **Puertas.** Son colas: entra lo que llega de fuera (programa × `gate_share`), sale hacia dentro lo que dan los
  tornos (`entry_per_min × flags.flow_factor`, ×1,3 si hay seguridad trabajando en la puerta). La gente rechazada
  queda fuera como rezagada y lo reintenta. En salida descargan `exit_per_min`.
- **REROUTE A→B**: la fracción (`params.fraction`, 0,6 por defecto) de todo lo que iba a entrar en A entra en B; si
  A y B son puertas, además se va andando a B un 5 %/min de la cola de A. B no elige: se puede saturar.
- **Conservación**: `outside + sum(occupancy) + exited == population` en todo momento. `zone_inflow` en una puerta
  tira primero de los de fuera; si no quedan, crece `population` (queda en `truth()["population"]["injected"]`).
  En una zona interior, `zone_inflow` saca la gente de las zonas vecinas.
- **Recursos.** Dijkstra sobre todas las aristas (también `staff_only`); entrar en una zona cuesta
  `minutes × {<2/m²: 1 · <4: 1,5 · <5,5: 2,5 · más: 3}`.
- **Ambulancia: no cruza público.** Un AMBULANCE no atraviesa zonas por encima de `amb_max_density` (1,5 /m²) ni
  zonas con `vehicle_transit: false` (foso, VIP, PMR, restauración, baños, puntos de agua). Al DESTINO sí entra
  aunque esté lleno: el último tramo se hace a pie con la camilla, al ritmo de un equipo a pie. Hay dos rutas
  sanitarias: el vial que cruza `corridor_s` y los viales de servicio (`service_road` en `festival.json`):
  `backstage–gate_c` (sur, 4 min) y `backstage–medical_2` (norte, 5 min), además de `backstage–medical_1`,
  `backstage–front_pit` y `gate_c–exit_transport`. Si `corridor_s` se llena (salida, desvío), rodea por backstage;
  sin ruta, la acción falla con `route_blocked`; si se bloquea a medio camino, espera y recalcula. Los recursos
  externos entran por `backstage` (acceso de servicio), no entre el público.
- **Incidentes.** Al llegar un recurso que cubre una necesidad (`needs`; una ambulancia cubre también `medical`), el
  incidente pasa a IN_PROGRESS (eso es lo que cuenta para el plazo) y avanza `cubierto/necesario` por minuto hasta
  `service_min` (número ±15 %, o rango `[mín, máx]`, con semilla). Una `cardiac_arrest` ocupa al equipo 30–60 min:
  en un caso de 90 min puede acabar IN_PROGRESS, y eso no es un fallo.
  Familia `crowd`: no se resuelve mientras la zona siga por encima de su capacidad. Pasado `deadline` sin estar
  IN_PROGRESS → FAILED. `deadline` es minuto absoluto del caso; si viene ≤ `t` de apertura se toma como relativo.
  Incidentes sin `needs` nunca fallan por plazo (los juzga el banco de pruebas).
- **El mundo no conoce los ids de incidente de Mando.** `DISPATCH` busca el objetivo así: `action.incident` si es un
  id verdadero → `params["reports"]`/`params["report"]` → `action.zone` (o `params["zone"]`): al llegar atiende el
  incidente activo más grave de esa zona al que le falte ese tipo de recurso. Si no hay ninguno (falsa alarma,
  duplicado, tipo equivocado) el recurso pierde `check_min` minutos, la acción acaba DONE con
  `params["outcome"] = "nothing_found"` y se apunta en `truth()["wasted_dispatches"]`. **Mandar siempre `zone`.**
- **Cadenas.** Calor > 32 °C → incidentes médicos espontáneos (≈2 por 90 min a 36 °C, ≈4 a 39 °C, N=20) y más
  consumo de `water_l`; agua a 0 → aviso SENSOR + incidente `water_out`, la cola se va al otro punto y a los 30 min
  suben los desmayos; `power=false` en `food` → la gente se va a `general`/`front_pit`;
  fin de cabeza de cartel → pico en puertas y `exit_transport`; `transport_cut` → `exit_transport` se llena y los
  externos tardan 8 min más.
- **Viento por escalones** (`wind_steps_kmh`: 40 / 50 / 60). Escalón 1, preaviso: aviso SENSOR de la «estación
  meteorológica» al subir de escalón, sin daños. Escalón 2, riesgo en estructuras: el aviso se repite cada 15 min y
  cada zona con estructura puede pasar a `structure_ok=false` + incidente `structure_risk`
  (`wind_rate × (viento − 49)` por minuto, ×1,5 con lluvia). Escalón 3, riesgo grave: esa probabilidad ×2 y el texto
  dice que parar es decisión del Director del Plan. `observe().weather["wind_level"]` = 0..3. Los avisos salen
  siempre; las roturas solo con `spontaneous` activo (nunca en el gemelo).
- **Sensores de aforo.** Tres niveles: (1) **tendencia**: por debajo del umbral, pero subiendo ≥ 0,15 /m² por minuto
  (media de 3 min), con ≥ 2 /m², y que a ese ritmo llegaría a 6,5 en ≤ 15 min → «Tendencia en Puerta B: 2,4/m² y
  subiendo 0,29/m² por minuto; a este ritmo, 6,5/m² en 14 min»; (2) **umbral**: por encima de capacidad o de
  `sensor_density` (4 /m² en zonas estáticas; 3,5 en puertas, pasillos y salida; 4,5 en el foso, cuyo aforo de
  diseño es 4,6) → aviso cada 5 min, con la tendencia en el texto si sigue subiendo; (3) **crítica**: `front_pit`
  o puerta por encima de 6,5 /m² → incidente `crush_risk` (severidad 9, plazo 10 min, 2 de seguridad), ids `x<n>`.
  Una salida NORMAL también genera 4–5 avisos (tendencia en `corridor_n` y `gate_b`, umbral en `gate_b` a 3,5–3,7):
  son reales y no llevan incidente detrás (`truth_incident=None`). `minutes_over_5` sigue contando minutos > 5 /m².

## Acciones (`apply`)

| Acción | Campos | Efecto y estado |
|---|---|---|
| DISPATCH | `resource`, `zone` y/o `incident` | EXECUTING (`params.eta`, `params.path`) → DONE al llegar (`params.outcome`: `on_scene`/`nothing_found`). FAILED: `unknown_resource`, `resource_offline`, `resource_busy`, `no_answer`, `unknown_target`, `route_blocked`, `incident_closed`, `comms_down` (si `action.channel` está caído). REJECTED: `rejected`. CANCELLED si el incidente se cierra antes o hay RECALL |
| RECALL | `resource` | lo deja AVAILABLE donde esté; el incidente vuelve a OPEN/ASSIGNED |
| SET_ZONE | `zone`, `params.state` | `open`/`restricted`/`closed`; reabrir cancela una evacuación |
| REROUTE | `zone` (origen), `params.to`, `fraction`, `minutes` | `params.cancel=true` o `fraction=0` lo quita |
| BROADCAST | `zone`, `params.minutes` (15) | entrada a la zona ×0,75 |
| RESUPPLY | `zone` (punto de agua), `resource` (`log_1`), `params.litres` | viaja, 5 min, rellena `water_l` y cierra el `water_out` |
| EVACUATE | `zone` (o `None`/`"all"` = recinto) | zona sin entrada y vaciándose; EXECUTING → DONE al quedar < 2 % |
| STOP_SHOW | `params.resume` | peso de `front_pit` ×0,4 y corta las oleadas hacia el foso; `clock.show_phase = "stopped"` |
| REQUEST_EXTERNAL | `params.kind`: `ambulance`/`medical`/`police`/`fire`, `zone` o `incident` | EXECUTING (`params.eta`) → DONE con `params.resource` = id nuevo (`ext_<kind>_<n>`), que entra por `backstage` y va solo al destino |
| REQUEST_EXTERNAL | `params.kind = "transport"` (refuerzo de lanzaderas) | EXECUTING (`params.eta` ≈ 15–18 min) → DONE con `params.outcome = "transport_reinforced"`: caudal de `exit_transport` ×1,5 y, si hay `transport_cut`, el corte pasa a dejar salir el 60 %. No crea recurso |
| NOTIFY, ASK, MERGE, DISMISS | — | DONE, sin efecto físico (quedan en `truth()["actions"]`). Única excepción, con la capa `ops`: un NOTIFY con `resource` y `params.point` le da al equipo el punto concreto |

El mundo ignora acciones en AWAITING_APPROVAL o ya terminadas. No juzga si algo estaba aprobado: eso es de `harness`.

## Efectos (`inject` y `events[].kind == "world"`)

`inject` acepta el efecto suelto o el evento entero (`{"kind": "world", "effect": {...}}`, `report_only`, `incident`).
Un efecto desconocido o con id inexistente no lanza: queda en `truth()["injected"]` con `error`.

`resource_offline {resource, n?}` · `resource_online {resource}` · `resource_no_answer {resource, n=5}` ·
`resource_rejects {resource, n=10}` · `zone_state {zone, state}` · `zone_inflow {zone, per_min, n?}` (también `rate`,
`people_per_min`, `value`) · `zone_flag {zone, flag, value}` o `{zone, power: false}` · `weather {temp_c, wind_kmh,
rain, alert}` · `comms_down {channel?, n=10}` (sin canal = todos; los avisos de ese canal llegan cuando vuelve) ·
`incident {incident, reports}` · `transport_cut {n?, factor=0}`. `n` admite también `ticks` o `duration`.

## Capa de «operación real» (`initial.ops`, OPCIONAL)

Sin `initial.ops` el mundo es exactamente el de siempre (comprobado: mismas métricas, byte a byte, en 712 casos de train,
heldout, load y demo con Mando y con la lista fija). Con ella, el recinto tiene parámetros que el agente NO conoce de
antemano y solo puede estimar observando; la usa `python3 -m motor.harness day2`.

```json
"initial": {"flags": {"water_n": {"water_l": 900}},
            "ops": {"resupply_min": {"water_n": [20, 30], "water_s": [7, 12]},
                    "contact": {"sec_4": {"p_no_answer": 0.48, "p_reject": 0.04}},
                    "locate": {"zones": {"general": [4, 9]}, "p_point": 0.8}}}
```

- `resupply_min[punto] = [mín, máx]`: minutos de descarga y llenado de un RESUPPLY en ese punto (sin la clave, los 5 min de
  `params.resupply_min`). RNG propio por reposición: no altera el del mundo. El consumo ya era observable: `flags.water_l`
  baja minuto a minuto en `observe()` y `initial.flags` fija el nivel de partida.
- `contact[recurso]`: probabilidad de que esa persona no conteste o rechace una llamada de DISPATCH (la lee `SimComms`).
- `locate.zones[zona] = [mín, máx]`: en una zona amplia, un equipo enviado a un incidente de PERSONA (familias `medical` y
  `aggression`) tarda esos minutos de más en dar con ella: sigue EN_ROUTE con su `eta`, el incidente no pasa a IN_PROGRESS
  y el plazo corre. No hay búsqueda si el DISPATCH lleva `params.point`, y se corta al minuto siguiente si llega un
  `NOTIFY` con `resource` = el equipo y `params.point`. Al llegar, la acción lleva `params.search_min` (lo cuenta el equipo:
  es observable) y, si lo había, `params.point`. Un `ASK` con `params.precise = true` devuelve además `data["point"]`
  («la torre de sonido», «el puesto 7»…) si quien avisó sabe darlo (`p_point`, determinista por incidente).
- `truth()` gana `water` = `{"dry_minutes": {punto: minutos a cero}, "stockouts": [{"t", "zone"}]}` (siempre presente) y,
  por incidente, `t_effective_dispatch` (minuto en que salió el despacho que de verdad ACABÓ llegando) y `search_min`.
  El gemelo copia también una búsqueda en curso sin compartir estado (hay test).

## Eventos condicionales (`events[].cond`)

`{"cond": {"unless_resolved": "i1"}}` en cualquier evento (`incident`, `world`, `report_only`, también vía
`inject`): si en el minuto `t` del evento el incidente verdadero `i1` está RESOLVED o FALSE_ALARM, el evento se
descarta entero (ni incidente, ni avisos, ni efecto) y queda en `truth()["skipped_events"]` como
`{t, origin, kind, what, cond, reason}` (`what` = id del incidente derivado o tipo de efecto). Si el origen está
abierto, en curso o FAILED, o el id no existe, el evento ocurre igual. Las reglas `... if spawned` de `expected.must`
se comprueban mirando si el id derivado está en `truth()["incidents"]`.

## Campos propios en dict libres

- `Zone.flags`: `power`, `water_l`, `water_capacity_l`, `shade`, `structure_ok`, `flow_factor` (puertas: fracción de
  tornos que funciona), `ambulance_route`; y, solo en `observe()`: `reroute_to`, `evacuating`, `broadcast_until`,
  **`flow_out`** = `{zona_destino: personas que pasaron en el último minuto}` (siempre presente, vacío si nada se
  movió; la clave `"outside"` es gente que salió del recinto; un desvío puede apuntar a una zona no vecina) y
  **`arrivals`** = personas que entraron de fuera a esa puerta en el último minuto. La variación de ocupación de
  cada zona entre dos `observe()` es exactamente entradas − salidas de esos dos campos (hay un test).
- `Observation.weather["wind_level"]`: 0 normal · 1 preaviso · 2 riesgo en estructuras · 3 riesgo grave.
- `festival.json`, por recurso: `role` = el CARGO de quien contesta («Jefe de seguridad de sector (foso)»), para
  pantalla y llamadas; `name` no cambia porque casos y regresiones lo citan.
- `Action.params`: los de la tabla, más `error`, `eta`, `path`, `outcome`, `resource`.
- `Observation.clock`: `day`, `hhmm`, `show_phase` (`closed|doors|concerts|headliner|egress|stopped`).
- `Resource.task` lleva el `action.incident` que mandó el agente (su id, no el verdadero).
- `truth()`: `incidents[id]` = Incident + `origin` (`case|inject|auto`), `t_first_dispatch`, `t_first_attention`,
  `t_resolved`, `t_failed`, `progress`, `service_min` · `peak_density[zone]` = `{density, occupancy, t}` ·
  `minutes_over_5`, `minutes_over_capacity` · `wasted_dispatches` · `skipped_events` · `actions` (todas las aplicadas, con estado
  final) · `injected` · `reports` (id de aviso → incidente verdadero o `None` si es falso) · `population` ·
  `occupancy`, `zone_state`, `resources`, `weather`, `clock`.

## Parámetros ajustables (`festival.json`)

Por zona: `area_m2`, `capacity`, `comfort_d`, `entry_per_min`, `exit_per_min`, `gate_share`, `flags`. Por arista:
`minutes`, `flow_per_min`, `staff_only`. `profiles` (reparto por fase) y `program.days[].phases` (`start`,
`arrive_share`, `leaving`). Por zona también `sensor_d` y `vehicle_transit`; por arista `service_road`.
En `params`: umbrales (`sensor_density`, `sensor_density_by_kind`, `sensor_trend_per_min`,
`sensor_trend_window_min`, `sensor_trend_horizon_min`, `sensor_trend_min_density`, `crush_density`, `hard_density`,
`amb_max_density`), viento (`wind_steps_kmh`, `wind_rate`, `wind_severe_factor`, `wind_repeat_min`), refuerzo de
transporte (`external_eta_min.transport`, `transport_boost`, `transport_relief_factor`), `state_inflow`, factores de cada acción (`broadcast_factor`, `reroute_fraction`,
`reroute_queue_frac`, `stop_show_factor`, `evac_boost`), cadenas (`heat_*`, `dry_*`, `water_*`, `wind_*`,
`power_off_food_factor`, `transport_cut_*`), `slow`, `service_min`, `external_eta_min`, plantillas de los incidentes
automáticos (`crush_incident`, `heat_incident`, `water_incident`, `structure_incident`).

## Límites conocidos

El agua empieza llena en cada caso (no se simulan las horas previas: usar `initial.flags`). Los recursos no ocupan
sitio. `clone()` y `twin()` copian el mundo, no `SimComms`. La ambulancia no sale a hospital: el supuesto «queda ≥ 1
ambulancia en el recinto» solo se rompe con `resource_offline`. El agente trivial de `demo.py` lee la verdad: solo prueba el mundo.
