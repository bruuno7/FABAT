# Motor — interfaces entre módulos (leer antes de escribir una línea)

Carpeta privada. **Nada de esto se sube a ningún repo ni servicio externo.** Python 3.14, solo
biblioteca estándar en el núcleo (`world`, `cases`, `mando`, `baseline`, `caos`, `harness`). Solo
`server/` puede usar dependencias, vía `uv`. Código y comentarios en español, identificadores en
inglés. Los tipos viven en `motor/contracts.py` y **no se redefinen ni se modifican**: si te falta un
campo, usa `params`, `flags` o `data` (son dict libres) y apúntalo en tu README.

Se ejecuta siempre desde la raíz del proyecto: `python3 -m motor.<paquete>...`.

## Reparto de carpetas (cada agente toca solo la suya)

| Carpeta | Qué es |
|---|---|
| `motor/world/` | Simulador determinista del festival. Implementa `WorldAPI`. |
| `motor/cases/` | Taxonomía de crisis y generador combinatorio de miles de casos. |
| `motor/mando/` | El agente: triaje, prioridad, plan con supuestos, replanificación. `AgentAPI`. |
| `motor/baseline/` | El «agente de lista fija» contra el que se compara. `AgentAPI`. Lo escribe el agente de `harness`. |
| `motor/caos/` | Adversario con presupuesto de golpes. |
| `motor/harness/` | Banco de pruebas: N ejecuciones sin pantalla, métricas, lecciones, regresión. |
| `motor/server/` | API + pantalla de mando + página del jurado + adaptador HappyRobot. |
| `motor/happyrobot/` | Especificación de los workflows a montar en la plataforma (documentos, no código). |

## El escenario: «Festival Abierto»

40.000 asistentes, 30.000 m², dos escenarios, tres días (día 1: incidencias menores; día 2: una
incidencia mayor; día 3: salida). Zonas (ids fijos, los usa todo el mundo):

`gate_a`, `gate_b`, `gate_c` (accesos) · `front_pit` (escenario 1, frente) · `stage_2` (escenario 2) · `general` · `vip` ·
`pmr` (plataforma de movilidad reducida) · `food` (restauración) · `toilets` · `water_n`, `water_s`
(puntos de agua) · `medical_1`, `medical_2` (puestos médicos) · `corridor_n`, `corridor_s` (pasillos,
`corridor_s` es además la ruta de ambulancia) · `backstage` · `exit_transport` (salida a lanzaderas y
metro). `camping` queda previsto pero desactivado.

Recursos (ids fijos): `sec_1`..`sec_5` (seguridad), `med_1`..`med_3` (equipos médicos a pie),
`amb_1` (ambulancia interna), `tech_1`, `tech_2`, `log_1` (logística), `vol_1`..`vol_3`.

`motor/world/festival.json` es la fuente de verdad de áreas, capacidades, vecinos y posiciones
iniciales. Referencias de densidad: 2 personas/m² = criterio de planificación; 5/m² = límite superior
de pie; ~7/m² = riesgo de aplastamiento (Fruin / Keith Still).

## Formato de un caso (`motor/cases/`, JSONL, un caso por línea)

```json
{
  "id": "c-000123", "seed": 123, "split": "train|heldout|demo",
  "day": 2, "start_hhmm": "21:30", "duration_min": 90,
  "families": ["crowd", "medical"], "difficulty": 1-5,
  "initial": {"occupancy": {"gate_b": 900, "...": 0}, "weather": {"temp_c": 36}, "resources_offline": ["sec_4"]},
  "events": [
    {"t": 3, "kind": "incident", "incident": {"id": "i1", "family": "crowd", "type": "gate_saturation",
       "zone": "gate_b", "severity": 7, "deadline": 25, "needs": {"security": 1}},
     "reports": [{"channel": "voice", "source": "jefe seguridad 2", "lang": "es",
                  "text": "La puerta B está atascada, un torno no funciona y sigue llegando gente"}]},
    {"t": 9, "kind": "report_only", "reports": [...]},        // duplicados, falsos, contradictorios
    {"t": 14, "kind": "world", "effect": {"kind": "resource_offline", "resource": "amb_1", "reason": "bloqueada por la multitud"}},
    {"t": 20, "kind": "world", "effect": {"kind": "weather", "temp_c": 39}}
  ],
  "expected": {"must": ["dispatch medical to i2 within 3 min"], "must_not": ["evacuate without approval"]}
}
```

`events[].kind`: `incident` (nace un incidente verdadero y sus avisos) · `report_only` (avisos sin
incidente nuevo: duplicado, falso, contradictorio, ambiguo) · `world` (efecto directo). Efectos
`world` admitidos, que son también el formato de `WorldAPI.inject()` y los golpes de Caos:
`resource_offline`, `resource_online`, `resource_no_answer` (n ticks), `resource_rejects`,
`zone_state`, `zone_inflow` (personas/min extra), `zone_flag` (power, water_l, structure_ok),
`weather`, `comms_down` (canal caído n ticks), `incident` (uno nuevo completo), `transport_cut`.

## Ciclo de una ejecución (lo usa harness y server, idéntico)

```python
world = World.from_case(case, seed)          # motor.world
comms = SimComms(world, seed)                # motor.world.comms  (o HappyRobotComms en server)
agent = Mando(playbook=..., comms=comms)     # motor.mando   (o Baseline)
while not world.done():
    obs = world.observe()
    for a in agent.tick(obs):                # Mando propone y ejecuta lo AUTO; lo APPROVE espera
        if a.status != ActionStatus.AWAITING_APPROVAL:
            world.apply(a)
    chaos.maybe_strike(world, agent)         # opcional
    world.step()
metrics = score(world.truth(), agent.snapshot())
```

En el banco de pruebas las aprobaciones las da un «operador simulado» (aprueba lo razonable tras
1–3 min). En el servidor las da una persona con un botón.

## Métricas (las calcula `harness`, las pinta `server`)

`critical_failed` (incidentes de severidad ≥ 8 que llegaron a FAILED) · `time_to_first_action` por
incidente · `time_to_resolve` · `wasted_dispatches` (recursos mandados a falsas alarmas o duplicados)
· `replans` · `approvals_requested` · `unsafe_actions` (acciones ALWAYS_APPROVE ejecutadas sin
aprobación: debe ser 0) · `peak_density` por zona · `score` 0–100. Toda cifra va con su N.
