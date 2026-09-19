# motor/cases — taxonomía de crisis y generador de casos

Carpeta privada: nada de esto se sube a ningún repo. Solo biblioteca estándar. Se ejecuta desde la raíz:

```
python3 -m motor.cases generate --n 3000 --seed 1 --out motor/cases/data/train.jsonl --split train
python3 -m motor.cases generate --n 1000 --seed 1 --out motor/cases/data/heldout.jsonl --split heldout
python3 -m motor.cases generate --out motor/cases/data/demo.jsonl --split demo
python3 -m motor.cases generate --n 600 --seed 1 --out motor/cases/data/load.jsonl --split load   # 150 por carga 5/6/7/8
python3 -m motor.cases stats motor/cases/data/load.jsonl [--all]
python3 -m motor.cases show motor/cases/data/demo.jsonl c-d000011
python3 -m motor.cases check-world motor/cases/data/train.jsonl   # corre cada caso en motor.world.World
python3 -m motor.cases space
python3 -m unittest motor.cases.test_cases -v
```

| Fichero | Qué es |
|---|---|
| `taxonomy.py` | 79 tipos como datos (`TAXONOMY`), reglas `must`/`must_not` con gramática fija (`parse_rule`), partición (`allowed_perturbations`, `combo_universe`). Zonas, vecinos, recursos y programa se LEEN de `motor/world/festival.json` (`ZONES`, `NEIGHBORS`, `RESOURCES`, `program_windows`, `phase_at`). |
| `phrasing.py` | Textos de los avisos con plantillas y semilla: radio, llamada, operador, sensor, WhatsApp/SMS con faltas y emojis; es, en, fr, de, pt; ambiguos, duplicados, contradictorios, bromas, dato enterrado. |
| `generator.py` | `generate(n, seed, split)`, `iter_cases(seed, split, start, n)`, `build_case(index, seed, split)`, `build_load_case(index, seed, split, load, surprise)`, `iter_load_cases(seed, per_level)`, `generate_load(per_level, seed)`, `priority_order(case)`, `max_concurrent(case)`, `compute_difficulty(case)`, `space_size(split)`. |
| `demo_cases.py` | 12 casos escritos a mano (`demo_cases()`): el «nunca visto» `c-d000009` y los dos de carga `c-d000011` y `c-d000012`. |
| `validate.py` | `validate_case(case) -> list[str]`, `validate_file(path)`. El CLI valida cada caso antes de escribirlo. |
| `test_cases.py` | 26 pruebas: determinismo, validación, partición disjunta, cobertura, dificultad, coherencia con el programa, contenido de demo, carga simultánea, ejecución en `motor.world.World`. |
| `data/` | `train.jsonl` (3.000), `heldout.jsonl` (1.000), `demo.jsonl` (12), `load.jsonl` (600). Semilla 1. |

## Cómo se generan

El tipo principal recorre **en rueda** todos los tipos de la partición y su perturbación recorre en rueda
las que esa partición le permite: la cobertura de combinaciones es sistemática, no fruto del azar. El resto
se sortea con la semilla del caso: día (1–3) y fase (`doors`, `concerts`, `headliner`, `egress`: los nombres
del programa de `festival.json`) × meteorología (`normal`, `heat` 36–41 °C, `wind`, `storm`) × 1–4
incidentes verdaderos (65 % de los acompañantes se solapan con el anterior) × calidad de la información
(`clean`, `ambiguous`, `duplicated`, `contradictory`, `false_alarms`, `buried`) × estado de los recursos
(`full`, `one_offline`, `shift_end`, `no_answer`, `rejects`, `all_busy`) × 1–2 perturbaciones `world`
(`resource_offline`, `resource_online`, `resource_no_answer`, `resource_rejects`, `zone_closed`,
`zone_inflow`, `zone_flag`, `weather_shift`, `comms_down`, `transport_cut`, `second_wave`) ×
encadenamientos de hasta dos eslabones.

**Coherencia con el simulador.** La hora de inicio se elige dentro de la ventana que esa fase tiene ese día
en el programa (si cabe, el caso entero). `validate.py` rechaza un caso cuya `meta.phase` no sea la que da el
reloj del simulador, que empiece o abra incidentes con el recinto `closed`, o que exija `stop_show` a un
incidente que nace fuera de `concerts`/`headliner` (el generador quita esa regla: no hay concierto que
parar). `initial.occupancy` ya no pisa todo el recinto: solo las zonas cuyo incidente exige una densidad
(siempre por debajo de 6,5 p/m² para no disparar el `crush_risk` automático); el resto sale del programa.

**Dificultad 1–5, calculada** (`compute_difficulty`): nº de incidentes, severidad máxima, solapes que
compiten por el mismo tipo de recurso, demanda simultánea por encima de las unidades en servicio, calidad
de la información, estado de los recursos, perturbaciones, eslabones, meteorología, fase, acciones que
exigen aprobación e idioma del primer aviso. Cortes en 2,8 / 4,4 / 6,2 / 8,2 puntos.

**Prioridad esperada** (`expected.priority`, en TODOS los casos): orden razonable entre los incidentes
seguros, por escalones de severidad (≥9 · 7–8 · 5–6 · ≤4) y, dentro, severidad, plazo más corto y familia.
`expected.priority_tiers` da los escalones y `expected.may_wait` los del último escalón (severidad ≤ 6): a
quién es razonable dejar esperando. Para puntuar: penalizar solo las inversiones ENTRE escalones.

**Partición estricta.** Cada combinación (familia × tipo × perturbación) es de train o de heldout, nunca de
las dos: a cada tipo compartido se le reservan 3 de las 11 perturbaciones para heldout (rotando por índice);
los 13 tipos **[H]** de la tabla solo existen en heldout; también estos encadenamientos entre tipos
compartidos: `anaphylaxis` → `cardiac_arrest`; `corridor_bottleneck` → `ambulance_blocked_by_crowd`; `intoxication_overdose` → `cardiac_arrest`; `lighting_failure` → `counterflow_exit`; `power_outage_food` → `fight`; `suspicious_object` → `rumor_panic`; y todo encadenamiento que toque un tipo [H]. En train nunca coinciden en un caso
las familias: aggression × weather, external × supply, external × weather. `demo` va aparte y `c-d000009` junta justo esas familias.

**Tipos sensibles [S]** (`bomb_threat_call`, `chemical_submission`, `lost_child`, `sexual_assault_report`, `weapon_seen`): llevan `sensitive=True` y, además de sus reglas, `must` avisar al punto
violeta o al jefe de seguridad y `must_not`: `broadcast for <i>`, `echo report_content of <i> to informant`
(no repetir al informante lo que ha contado) y `request_external police for <i> without approval`. En
`sexual_assault_report` va primero el punto violeta, seguridad localiza con discreción y ya no se exige
sanitario. **Siguen en train/heldout; jamás en demo**: `validate.py` rechaza en el split `demo` esos tipos,
`crowd_collapse` (atrapados, decisión D4) y cualquier aviso con vocabulario vetado (`DEMO_FORBIDDEN_WORDS`).

## Carga simultánea (`load.jsonl`)

`build_load_case`: 5, 6, 7 u 8 incidentes verdaderos **activos a la vez**. Todos se abren dentro de una
ventana de 10–15 min (`meta.window`) y siguen dentro de plazo en su último minuto; el primero es una tarea
menor (severidad ≤ 5) que se queda con un equipo, lo grave (≥ 8) tiende a entrar tarde; familias distintas
mientras queden (en train las parejas vetadas lo limitan a 7); y la demanda de al menos un tipo de recurso
supera las unidades del recinto (`meta.demand`, `meta.supply`, `meta.scarce_kinds`). `expected` añade
`recall lower_priority for <el más prioritario> within 3 min` y `queue ... behind lower_priority` en
`must_not`, además de `priority`/`priority_tiers`/`may_wait`. Con sorpresa (`meta.surprise_t`,
`meta.surprise_kind` = `incident` | `world`), en los dos últimos minutos de la ventana entra un incidente
grave nuevo (efecto `incident`, perturbación `second_wave`) o un golpe `world` (evento con
`tag: "surprise"`). Sin sorpresa, la perturbación es una condición conocida desde el minuto 0–2. La partición
se respeta: cada caso lleva `split` train o heldout y sus combinaciones salen del universo de su partición.

| Carga | Casos | train / heldout | Sin sorpresa | Sorpresa: incidente | Sorpresa: golpe world | Familias distintas (media) |
|---|---|---|---|---|---|---|
| 5 | 150 | 100 / 50 | 75 | 38 | 37 | 5.0 |
| 6 | 150 | 100 / 50 | 75 | 38 | 37 | 5.8 |
| 7 | 150 | 100 / 50 | 75 | 38 | 37 | 6.9 |
| 8 | 150 | 100 / 50 | 75 | 38 | 37 | 7.3 |

Recurso escaso (N = 600; un caso cuenta en todos los suyos): security 488 · logistics 93 · medical 92 · tech 72 · ambulance 28 · volunteer 9.

Casos demo de carga: `c-d000011` «Seis frentes a la vez» (seis familias, un técnico de baja, viento 42 → 52
km/h, persona que no responde en el foso) y `c-d000012` «Seis frentes y el imprevisto del jurado» (siete
parejas de seguridad pedidas, cinco en el recinto). En este último la sorpresa **no va en el caso**:
`meta.surprise_kind = "injected_by_person"` y `meta.surprise_menu` trae cinco golpes listos para
`WorldAPI.inject` (en el incidente del menú, `deadline: 6` es relativo si se inyecta pasado el minuto 6).

## Añadidos al formato de `INTERFACES.md` (todos opcionales para quien lee)

- `meta`: `phase`, `weather`, `info_quality`, `resource_state`, `perturbations`, `chain`, `primary`,
  `primary_type`, `types`, `combos` (familia, tipo, perturbación), `difficulty_points`, `max_concurrent`; en
  carga, `load`, `window`, `demand`, `supply`, `scarce_kinds`, `distinct_families`, `surprise_t`,
  `surprise_kind`; en demo, `title`, `story`, `never_seen`, `surprise_menu`.
- `expected.priority`, `expected.priority_tiers`, `expected.may_wait`.
- `events[].cond = {"unless_resolved": "i1"}`: el simulador descarta el evento si `i1` ya está resuelto. Sus
  reglas en `expected.must` acaban en `if spawned`.
- `events[].tag` / `ref` / `subtag`: `duplicate`, `contradictory`, `clarification`, `false_alarm` (`ref` =
  `fa1`...), `perturbation`, `surprise`. Los avisos solo llevan campos de `contracts.Report`.
- `initial.shift_ends = {"sec_2": 9}` es informativo (el simulador no lo lee); el `resource_offline` de ese
  minuto es lo que cuenta.
- Efectos, con los nombres que entiende `motor/world`: `resource_no_answer {resource, n}`,
  `resource_rejects {resource, reason}`, `zone_state {zone, state, reason}`, `zone_inflow {zone, per_min, n}`,
  `zone_flag {zone, flag, value}`, `weather {temp_c?, wind_kmh?, rain?, alert?}`, `comms_down {channel, n}`,
  `transport_cut {mode, n}`, `incident {incident, reports}`. La duración es siempre `n` (el validador rechaza
  `minutes`, que el simulador ignoraría dejando el efecto sin fin).
- `deadline` es el minuto absoluto del caso.
- Reglas de `expected`: `dispatch <tipo> to <i> within <n> min`, `request_external <servicio> for <i> with approval`,
  `stop_show|evacuate <zona> for <i> with approval`, `set_zone <zona> restricted|closed for <i>`,
  `reroute <zona> to <zona> for <i>`, `broadcast for <i>`, `notify <rol> about <i|recurso>`,
  `resupply <zona> for <i> within <n> min`, `recall lower_priority for <i>`, `merge reports of <i>`,
  `ask about <i>`, `dismiss <fa>`, `echo ...` (solo en `must_not`); en todos los casos van
  `evacuate|stop_show|request_external without approval` en `must_not`.

## Cifras reales (salida de `stats`, `space` y `check-world`, semilla 1)

| | train | heldout | demo | load |
|---|---|---|---|---|
| Casos (N) | 3.000 | 1.000 | 12 | 600 |
| Firmas estructurales distintas | 2.999 | 1.000 | 12 | 600 |
| Incidentes verdaderos (condicionales) | 7.902 (810) | 2.625 (281) | 45 (8) | 4.052 (0) |
| Avisos | 13.516 | 4.406 | 70 | 5.817 |
| Tipos de la taxonomía presentes | 66 de 79 | 79 de 79 | 41 de 79 | 79 de 79 |
| Combinaciones familia×tipo×perturbación cubiertas | train 504 de 504 | heldout 312 de 312 | — | train 443 de 504 · heldout 264 de 312 |
| Casos con encadenamiento (eslabones distintos) | 741 (37) | 248 (33) | 7 (9) | 0 (0) |
| Dificultad 1 / 2 / 3 / 4 / 5 | 367 / 653 / 859 / 617 / 504 | 91 / 236 / 278 / 218 / 177 | 0 / 2 / 3 / 2 / 5 | 0 / 0 / 0 / 2 / 598 |
| Máx. incidentes activos a la vez 1 / 2 / 3 / 4 / 5 / 6 / 7 / 8 / 9 | 874 / 1.153 / 623 / 350 / 0 / 0 / 0 / 0 / 0 | 337 / 385 / 183 / 95 / 0 / 0 / 0 / 0 / 0 | 1 / 5 / 2 / 2 / 0 / 2 / 0 / 0 / 0 | 0 / 0 / 0 / 0 / 112 / 150 / 150 / 150 / 38 |
| Canal: whatsapp / radio / voice / sensor / sms / operator | 5.885 / 3.184 / 1.531 / 1.284 / 842 / 790 | 1.904 / 1.131 / 524 / 328 / 261 / 258 | 28 / 25 / 5 / 12 / 0 / 0 | 2.142 / 1.619 / 871 / 386 / 334 / 465 |
| Idioma: es / en / fr / de / pt | 11.788 / 1.127 / 198 / 200 / 203 | 3.816 / 369 / 77 / 81 / 63 | 58 / 7 / 2 / 2 / 1 | 5.098 / 458 / 73 / 91 / 97 |
| Parejas de familias que coinciden (de 36) | 33 | 36 | 36 | 36 |

Combinaciones compartidas entre `train.jsonl` y `heldout.jsonl`: 0. En `load.jsonl` ninguna combinación cae fuera
del universo de su partición. Casos de train por familia (N = 3.000; un caso cuenta en todas las suyas): crowd 1.121 · medical 1.078 · weather 315 · aggression 940 · supply 635 · infra 1.154 · resource 2.220 · info 2.224 · external 490.

`check-world`: los 4.612 casos (3.000 + 1.000 + 12 + 600) corren en `motor.world.World` hasta el final, sin agente,
con 0 excepciones, 0 efectos rechazados, la fase del reloj del simulador igual a la declarada y todos los
incidentes seguros abiertos por el mundo.

**Tamaño del espacio** (`space_size`, cota inferior): se enumeran los conjuntos de 1–4 tipos compatibles
entre sí (meteorología y fase comunes, perturbaciones permitidas comunes y, en train, sin parejas de
familias vetadas) y cada uno se multiplica por meteorologías comunes × fases comunes × 3 días × subconjuntos
de 1–2 perturbaciones comunes × 6 calidades de información × 5 estados de recursos (`all_busy` se deja
fuera porque fija los acompañantes). **Train: 1.889.046.900** (56 tipos; conjuntos por tamaño
{1: 56, 2: 1433, 3: 22878, 4: 259614}). **Heldout: 260.876.880** (68 tipos). No cuenta zonas, severidades,
tiempos, encadenamientos, segunda oleada, idiomas, textos ni los casos de carga (5–8 incidentes).

## Taxonomía (79 tipos: crowd 10  ·  medical 11  ·  weather 6  ·  aggression 8  ·  supply 7  ·  infra 11  ·  resource 9  ·  info 10  ·  external 7)

Severidad 1–10; «Plazo» en minutos desde que nace; [H] = solo heldout; [S] = sensible (nunca en demo).
`must`/`must_not` completos en `taxonomy.py`.

| Familia | Tipo | Qué es | Sev. | Necesita | Plazo | Aprobación | Degenera en |
|---|---|---|---|---|---|---|---|
| crowd | `gate_saturation` | Puerta saturada | 5–7 | security 1, volunteer 1 | 20–30 | — | gate_crush_risk |
| crowd | `gate_crush_risk` | Riesgo de aplastamiento en puerta | 8–9 | security 2, medical 1 | 8–12 | — | crowd_collapse |
| crowd | `front_pit_critical_density` | Densidad crítica en frente de escenario | 9–10 | security 2, medical 1 | 8–12 | sí | crowd_collapse |
| crowd | `crowd_collapse` **[H]** | Caída en cadena con atrapados | 10–10 | medical 2, security 2, ambulance 1 | 5–8 | sí | medical_post_saturated |
| crowd | `corridor_bottleneck` | Embudo en pasillo | 5–7 | security 1, volunteer 1 | 15–25 | — | ambulance_blocked_by_crowd |
| crowd | `mass_entry_attempt` | Intento de entrada masiva | 7–9 | security 3 | 8–12 | sí | gate_crush_risk |
| crowd | `counterflow_exit` | Contraflujo en la salida | 6–8 | security 2, volunteer 1 | 12–18 | — | crowd_collapse |
| crowd | `pmr_platform_overcrowded` | Plataforma PMR desbordada | 5–7 | security 1, volunteer 1 | 15–20 | — | trauma_fall |
| crowd | `crowd_surge_general` | Avalancha o estampida en pista | 7–9 | security 2, medical 1 | 8–12 | — | crowd_collapse |
| crowd | `stage_invasion` **[H]** | Invasión de escenario | 6–8 | security 2 | 8–12 | — | fight |
| medical | `cardiac_arrest` | Parada cardiaca | 10–10 | medical 1, ambulance 1 | 4–6 | — | — |
| medical | `heat_stroke` | Golpe de calor | 7–8 | medical 1 | 10–15 | — | multiple_heat_strokes |
| medical | `multiple_heat_strokes` | Golpes de calor múltiples | 8–9 | medical 2, logistics 1 | 10–15 | — | medical_post_saturated |
| medical | `intoxication_overdose` | Intoxicación o sobredosis | 6–8 | medical 1 | 10–15 | — | cardiac_arrest |
| medical | `anaphylaxis` | Reacción alérgica grave | 8–9 | medical 1, ambulance 1 | 6–8 | — | cardiac_arrest |
| medical | `trauma_fall` | Caída con traumatismo | 5–7 | medical 1 | 15–20 | — | — |
| medical | `seizure` | Crisis convulsiva | 7–8 | medical 1 | 8–12 | — | — |
| medical | `medical_post_saturated` | Puesto médico saturado | 7–9 | medical 1, ambulance 1 | 15–20 | sí | — |
| medical | `minor_injury` | Lesión leve | 2–3 | medical 1 | 30–45 | — | — |
| medical | `diabetic_emergency` **[H]** | Urgencia diabética | 7–8 | medical 1 | 8–12 | — | — |
| medical | `mass_food_poisoning` **[H]** | Intoxicación alimentaria múltiple | 7–9 | medical 2, logistics 1 | 12–18 | sí | medical_post_saturated |
| weather | `extreme_heat_alert` | Alerta por calor extremo | 6–7 | logistics 1, volunteer 1 | 25–35 | — | water_out, multiple_heat_strokes |
| weather | `strong_wind_gusts` | Rachas de viento fuertes | 6–8 | tech 1, security 1 | 12–18 | — | structure_damage, storm_structures |
| weather | `storm_structures` | Tormenta con estructuras en riesgo | 9–10 | tech 1, security 2 | 8–12 | sí | structure_damage, crowd_surge_general |
| weather | `lightning_nearby` | Rayos a menos de 10 km | 8–9 | security 2 | 10–15 | sí | crowd_surge_general |
| weather | `heavy_rain_flooding` | Lluvia intensa y encharcamiento | 5–7 | tech 1, logistics 1 | 20–30 | — | trauma_fall, power_outage_food |
| weather | `hail_shelter_rush` **[H]** | Granizo: carrera a refugiarse | 7–8 | security 2, medical 1 | 8–12 | — | crowd_collapse |
| aggression | `fight` | Pelea | 5–7 | security 2 | 8–12 | — | weapon_seen |
| aggression | `chemical_submission` **[S]** | Posible sumisión química (punto violeta) | 8–9 | medical 1, security 1 | 8–12 | sí | — |
| aggression | `sexual_assault_report` **[S]** | Agresión sexual (punto violeta) | 9–9 | security 1 | 8–12 | sí | — |
| aggression | `weapon_seen` **[S]** | Arma blanca vista | 9–9 | security 2 | 6–10 | sí | crowd_surge_general |
| aggression | `theft_gang` | Robos de móviles en cadena | 3–5 | security 1 | 25–40 | — | — |
| aggression | `staff_assaulted` | Agresión a personal | 6–7 | security 2, medical 1 | 8–12 | — | injured_staff |
| aggression | `harassment_group` | Acoso de un grupo | 5–6 | security 1 | 10–15 | — | — |
| aggression | `hate_incident` **[H]** | Incidente de odio | 6–7 | security 2 | 8–12 | sí | — |
| supply | `water_out` | Agua agotada | 6–8 | logistics 1, volunteer 1 | 15–25 | — | multiple_heat_strokes, fight |
| supply | `food_shortage` | Comida agotada en barras | 3–4 | logistics 1 | 40–60 | — | — |
| supply | `generator_fuel_low` | Generador sin combustible | 6–7 | logistics 1, tech 1 | 20–30 | — | power_outage_food, stage_power_failure |
| supply | `medical_supplies_low` | Material médico bajo mínimos | 6–7 | logistics 1 | 15–25 | — | medical_post_saturated |
| supply | `wristbands_out` | Pulseras agotadas en acceso | 4–6 | logistics 1, volunteer 1 | 20–30 | — | gate_saturation |
| supply | `radio_batteries_low` | Baterías de radio agotándose | 4–5 | logistics 1 | 25–40 | — | comms_network_down |
| supply | `ice_cooling_out` **[H]** | Hielo y mantas frías agotados | 6–7 | logistics 1 | 15–20 | — | multiple_heat_strokes |
| infra | `power_outage_food` | Apagón en restauración | 6–7 | tech 1, security 1 | 15–20 | — | cashless_down, fight |
| infra | `cashless_down` | Caída del pago cashless | 5–7 | tech 1 | 20–30 | — | fight |
| infra | `stage_power_failure` | Corte de corriente en escenario | 6–8 | tech 2 | 10–15 | — | crowd_surge_general |
| infra | `toilets_blocked` | Baños inutilizados | 3–5 | tech 1 | 40–60 | — | — |
| infra | `barrier_failure` | Valla cedida | 8–9 | tech 1, security 2 | 8–12 | — | gate_crush_risk, crowd_collapse |
| infra | `structure_damage` | Estructura dañada | 8–9 | tech 1, security 1 | 8–12 | sí | trauma_fall |
| infra | `lighting_failure` | Fallo de alumbrado | 6–7 | tech 1, volunteer 1 | 12–18 | — | trauma_fall, counterflow_exit |
| infra | `comms_network_down` | Red de comunicaciones caída | 6–7 | tech 1 | 15–20 | — | — |
| infra | `turnstile_failure` | Tornos averiados | 4–6 | tech 1, volunteer 1 | 20–30 | — | gate_saturation |
| infra | `gas_leak_food` **[H]** | Fuga de gas en cocinas | 9–9 | security 2, tech 1 | 6–10 | sí | small_fire |
| infra | `small_fire` | Conato de incendio | 8–9 | security 2, tech 1 | 6–10 | sí | crowd_surge_general |
| resource | `ambulance_blocked_by_crowd` | Ambulancia bloqueada por la multitud | 8–9 | security 2 | 6–10 | sí | — |
| resource | `injured_staff` | Personal propio lesionado | 6–7 | medical 1 | 10–15 | — | — |
| resource | `vehicle_breakdown` | Ambulancia interna averiada | 6–7 | tech 1 | 15–20 | sí | — |
| resource | `medical_team_overwhelmed` **[H]** | Equipo médico pide refuerzo | 7–8 | medical 1 | 8–12 | — | — |
| resource | `resource_offline_start` | Un recurso fuera de servicio desde el inicio (estado de recursos) | — | — | — | — | — |
| resource | `shift_end_no_relief` | Fin de turno sin relevo (estado de recursos) | — | — | — | — | — |
| resource | `team_no_answer` | Equipo que no contesta (estado de recursos) | — | — | — | — | — |
| resource | `team_rejects` | Equipo que rechaza la orden (estado de recursos) | — | — | — | — | — |
| resource | `all_busy_higher_priority` | Todo ocupado cuando entra algo más grave (estado de recursos) | — | — | — | — | — |
| info | `lost_child` **[S]** | Menor perdido | 7–8 | security 1, volunteer 1 | 15–20 | — | — |
| info | `lost_vulnerable_adult` | Adulto vulnerable desorientado | 6–7 | volunteer 1, security 1 | 20–30 | — | — |
| info | `rumor_panic` | Bulo que provoca carreras | 6–8 | security 2 | 8–12 | — | crowd_surge_general, counterflow_exit |
| info | `fake_staff_instructions` **[H]** | Falso personal dando órdenes de evacuar | 7–8 | security 2 | 8–12 | — | counterflow_exit |
| info | `ambiguous_report` | Aviso ambiguo (solo avisos) | — | — | — | — | — |
| info | `duplicate_reports` | Avisos duplicados con detalles distintos (solo avisos) | — | — | — | — | — |
| info | `contradictory_reports` | Avisos contradictorios (solo avisos) | — | — | — | — | — |
| info | `false_alarm_prank` | Broma o falsa alarma (solo avisos) | — | — | — | — | — |
| info | `buried_key_fact` | Dato clave enterrado en el mensaje (solo avisos) | — | — | — | — | — |
| info | `sensor_glitch` **[H]** | Lectura de sensor espuria (solo avisos) | — | — | — | — | — |
| external | `transport_cut_exit` | Corte de transporte a la salida | 7–8 | security 2, volunteer 2 | 15–25 | sí | counterflow_exit |
| external | `suspicious_object` | Objeto sospechoso | 9–9 | security 2 | 6–10 | sí | rumor_panic |
| external | `bomb_threat_call` **[H]** **[S]** | Amenaza de bomba por teléfono | 9–10 | security 2 | 6–10 | sí | rumor_panic |
| external | `artist_delay_cancel` | Retraso o cancelación del cabeza de cartel | 5–7 | security 2 | 12–18 | — | fight, crowd_surge_general |
| external | `drone_intrusion` | Dron no autorizado sobre el público | 5–6 | security 1 | 15–20 | sí | — |
| external | `nearby_wildfire_smoke` **[H]** | Humo de incendio cercano | 8–8 | security 1, medical 1 | 12–18 | sí | — |
| external | `road_access_blocked` | Acceso rodado cortado (ambulancias externas) | 6–7 | security 1 | 15–25 | sí | — |
