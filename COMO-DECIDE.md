# Cómo decide MANDO

MANDO coordina los incidentes de un evento masivo. No es un chatbot: en cada minuto mira el recinto, ordena lo abierto, manda equipos, escribe un plan con supuestos y tira ese plan cuando un supuesto deja de ser cierto. El núcleo que decide es un planificador de reglas, determinista (misma entrada → misma salida). Los modelos de lenguaje, si están, entienden texto libre y hablan; no puntúan la cola.

Pantalla donde se ve el «por qué» de ahora: `/porque` (API: `GET /api/explica` y `GET /api/explica/{id}`).

## El bucle (cada minuto)

```
avisos (voz, Telegram, SMS, web, radio, sensor)
        │
        ▼
  entender el texto     motor/mando/parser.py  HeuristicParser.parse
        │
        ▼
  fusionar o abrir      motor/mando/triage.py  Triage.ingest
        │
        ▼
  número de prioridad   motor/mando/priority.py  compute
        │
        ▼
  ensayar en el gemelo  motor/mando/rehearsal.py  Rehearsal.run / choose
        │               (copia del recinto AHORA, sin el futuro del caso)
        ▼
  plan con supuestos    motor/mando/planner.py  Planner.build
        │
        ▼
  ¿lo ejecuta solo?     motor/mando/autonomy.py  level / gate
        │                 AUTO → sale   APPROVE → tarjeta a una persona
        ▼
  avisar / llamar       motor/server/comms_happyrobot.py + hr_routing.py
        │                 Telegram (fa-despacho-tg) o voz (mando-despacho-*)
        ▼
  el recinto avanza 1 min
        │
        ▼
  ¿siguen en pie los supuestos?   motor/mando/assumptions.py  holds
        │ no → se tira el plan y se vuelve a priorizar
        ▼
  previsión 15 min      motor/server/forecast.py  forecast
```

## Cómo se entiende un aviso

`motor/mando/parser.py` · `HeuristicParser.parse`

El aviso entra como texto (o lectura de sensor). Se normaliza (minúsculas, sin tildes) y se cruza con el léxico de `motor/mando/lexicon.py`. Sale un dict: tipo, familia, zona, gravedad 1–10, recursos que hacen falta, confianza, si es riesgo vital, si es caso reservado.

Confianza de partida según el canal (`parser.py`, `parse`):

| Canal | Base |
|---|---|
| sensor, operador | 0,95 |
| radio | 0,85 |
| voz | 0,80 |
| SMS | 0,60 |
| WhatsApp | 0,55 |

Suma o resta: personal conocido +0,10; dos señales de tipo +0,10; «creo / parece / me han dicho» −0,25; tipo no reconocido −0,15; sin zona −0,10. Queda entre 0,05 y 0,99.

Si no hay tipo en el léxico no se adivina: familia genérica `unknown_<familia>`, se pregunta, y un riesgo vital despacha igual.

Caso reservado (agresión sexual, menores, amenaza): ni megafonía ni detalle en pantalla pública.

## Cómo se fusionan

`motor/mando/triage.py` · `Triage._find` / `ingest`

Ventana: 15 min (`MERGE_WINDOW`). Mismo tipo o grupo + misma zona → un solo incidente (sube la confianza). Informante del personal (no «asistente» genérico) también fusiona. Zona vecina, solo en familias de flujo/infra, ventana 6 min.

No se fusionan dos riesgos vitales sin zona: pueden ser dos personas.

Un aviso único con confianza < 0,5 se retiene 8 min (`CONFIRM_BELOW`, `HOLD_MAX`) salvo riesgo vital. Un desmentido creíble cierra; uno débil del público solo baja la confianza.

Contradicción (gravedades que distan 4 o más, o «no respira» frente a «está de pie»): baja la confianza ×0,6 y se pregunta; manda la versión grave.

## Cómo se calcula la prioridad

`motor/mando/priority.py` · `compute` · `explain` · `sort_key`

```
prioridad = min(10, gravedad × f_plazo × f_densidad × f_vulnerable × f_tendencia × f_confianza) + ajuste_manual
```

| Factor | Fórmula | Dónde |
|---|---|---|
| gravedad | 1..10 del incidente | `Incident.severity` |
| f_plazo | 0,6 + 0,6·u ; u = 1 − minutos_restantes/30, acotado a [0,1]. Sin plazo, u = 0,5 → ×0,90 | `HORIZON_MIN = 30` |
| f_densidad | 1 + k·d ; d = (densidad − 2)/(7 − 2) en [0,1]; k = 0,3 en aglomeración, 0,1 en el resto | 2/m² planificación, ~7/m² aplastamiento |
| f_vulnerable | ×1,1 zona PMR y/o ×1,1 menores | `Zone.kind == "pmr"` |
| f_tendencia | 1 + 0,1·s ; s = variación de densidad por minuto / 0,2, en [−1,1] | |
| f_confianza | 0,5 + 0,5·confianza ; en riesgo vital la confianza no cuenta por debajo de 0,8 | |
| ajuste_manual | suma de `priority_boost` del manual, acotada a ±2 | |
| suelo | un riesgo vital nunca baja de 9,0 | `LIFE_FLOOR` |

Desempate (`sort_key`): más gravedad, menos plazo, id más antiguo.

### Ejemplo (caso demo-1, minuto 20, incidente de embudo)

Del estado vivo, no inventado:

```
prioridad 7,48 = gravedad 6 × plazo 3 min (×1,14) × densidad 4,5/m² (×1,15) × confianza 90 % (×0,95)
               = 6 × 1,14 × 1,15 × 0,95 = 7,47  →  7,48
```

La línea pública redondea a «prioridad 7,5». Una posible parada en el mismo minuto: gravedad 10 × plazo vencido (×1,20) × confianza 90 % (×0,95) = 11,4, tope 10,0. Por eso va delante.

## Cómo se elige el recurso

`motor/mando/planner.py` · `_Build._options` / `dispatch` / `_recall`

Entre los libres del tipo pedido, gana el de mejor ETA (Dijkstra sobre `festival.json`, más lento si la zona está densa). La ambulancia no cruza público por encima de `amb_max_density` (por defecto 1,5/m²). Si hay varios, el `why` del despacho nombra al siguiente.

Si no queda nadie libre y este incidente supera al que tiene el recurso por un margen de 1,5 (`RECALL_MARGIN`), se le retira (`RECALL`). Lo vital no se suelta; lo vital sí quita a lo que no es vital, sin ese margen.

El que espera queda escrito (`why_waiting`): falta tipo X, todos ocupados en algo más prioritario.

## A quién se llama y por qué canal

`motor/server/hr_routing.py` · `workflow_slot` · `WORKFLOW_NAMES`  
`motor/server/comms_happyrobot.py` · `send`

| Oficio / acción | Workflow |
|---|---|
| médico, ambulancia | `mando-despacho-sanitario` |
| seguridad | `mando-despacho-seguridad` |
| técnico | `mando-despacho-tecnico` |
| logística | `mando-despacho-logistica` |
| evacuación / parar / director | `mando-escalada-director` |
| 112 y servicios | `mando-aviso-servicios-externos` |
| megafonía | `mando-difusion-publico` |
| despacho por Telegram | `fa-despacho-tg` (la plataforma decide el rol; MANDO solo lo refleja) |

Canal: personal de campo por voz o radio; público por Telegram / web / SMS. Web call no marca un teléfono: deja un enlace para que descuelgue el cargo. Lista blanca obligatoria para marcar (`MANDO_ALLOWED_NUMBERS`). Nunca 112/061 reales. Lo reservado no sale por megafonía ni por voz al público.

Si el hook no contesta, la orden cae a simulación y queda en el log: la demo no se cuelga.

## Qué es un supuesto y cuándo se rompe

`motor/mando/assumptions.py` · `holds`  
Cada plan escribe supuestos comprobables (`Assumption.check`). Ejemplos:

| kind | Qué tiene que seguir siendo cierto |
|---|---|
| `zone_density_below` | personas/m² en esa zona < umbral |
| `route_clear` | el camino por debajo de esa densidad y no cerrado |
| `action_accepted_within` | el equipo aceptó antes de N minutos |
| `resource_status_is` | el recurso sigue available / en_route / busy |
| `incident_improving` | pasado el plazo, la métrica ha bajado (o ya es segura) |
| `weather_below` | p. ej. viento < 60 km/h |

Si `holds` es falso, el plan se invalida (`invalidated_by`), se cancelan los pasos que dependían de eso y se construye otro (`supersedes`). Queda en el log como `assumption_broken`.

## Cómo se ensaya en el gemelo

`motor/mando/rehearsal.py` · `Rehearsal.run` / `choose`

Antes de un desvío o de una ruta sanitaria se copia el recinto **tal como está** (sin leer el futuro del caso: no se llama a `truth()`). Se aplican las acciones, se avanzan 12 min (`HORIZON_MIN`) y se mira densidad por zona. Criterio, en este orden: (1) nadie por encima de 6,5/m²; (2) menos minutos por encima de 4/m²; (3) pico más bajo; (4) la opción menos intrusiva. Si el destino del desvío queda ≥ 4/m², la acción pasa a APPROVE (`autonomy.py`, `SAFE_DENSITY`).

## Qué decide una persona y qué nunca espera

`motor/mando/autonomy.py` · `level` · `gate` · `decision_card`  
`motor/contracts.py` · `ALWAYS_APPROVE`

Siempre persona: evacuar, parar el espectáculo, pedir ayuda externa. También cerrar una zona, megafonía general (pista / frente / recinto) y un desvío cuyo ensayo no deje el destino bajo 4/m².

Nunca espera: un despacho. Una posible parada cardiaca no se queda en la tarjeta.

La tarjeta lleva cargo (Director del Plan de Actuación o Coordinador sanitario), suplente, las dos ramas ensayadas y una ventana (3 min si es vital, si no 10, acotada 2–15).

## Cómo se prevé

`motor/server/forecast.py` · `forecast` / `ForecastTracker`

Gemelo a 15 min **sin órdenes nuevas**. Avisa el primer cruce de: densidad 4 y 5 /m², agua a 0, unidades críticas libres a 0, ruta de ambulancia bloqueada. «Evitado» exige intervención registrada en la ventana; la atribución es temporal, no causal.

## Qué hace el sistema cuando algo cae

| Qué cae | Qué hace |
|---|---|
| Un supuesto | Tira el plan, replanifica, sube de escalón si no mejora |
| El equipo no contesta o rechaza | Queda excluido; se llama al siguiente; se avisa al coordinador |
| HappyRobot no responde | Fallback a simulación / SMS; queda escrito |
| Canal caído | Se reintenta por otro canal |
| Recurso offline (p. ej. ambulancia atrapada) | Nuevo incidente de recurso + replan de lo que dependía |
| La persona veta | Se propone la alternativa (`autonomy.ALTERNATIVE`); no se ejecuta lo vetado |
| Integración Telegram cae | El espejo se apaga; el despacho por voz sigue siendo la escalada |

Nada de esto se inventa en `/api/explica`: si el dato no está en el estado, la frase dice que no está.
