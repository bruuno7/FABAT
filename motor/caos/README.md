# motor/caos — el adversario del mundo

Carpeta privada. Solo biblioteca estándar. HappyRobot vende «adversarial agents» que atacan la
**conversación**; Caos ataca el **mundo**: escenario, recursos y los supuestos escritos del plan.

```python
from motor.caos import Chaos, RandomChaos
chaos = Chaos(budget=3, lookahead=15)
chaos.start(case, seed)                  # reinicia presupuesto y registro
...
chaos.maybe_strike(world, agent)         # en cada tick, después de aplicar las acciones del agente
chaos.strikes                            # [{t, effect, label, why, damage_est, assumption, alternatives, budget_left}]
chaos.log                                # LogEntry(kind="chaos") con el porqué en una frase
```

## Consola del adversario (para la pantalla: el JURADO elige el golpe)

```python
ranked = Chaos().suggest(world, agent, top=6)
# [{"label": "med_2 fuera de servicio", "why": "dejo fuera a med_2 porque el plan P-003 depende de «…»",
#   "damage": 31.5, "assumption": "S-0007", "effect": {"kind": "resource_offline", ...}, "rank": 0}, ...]
Chaos().strike(world, ranked[0])         # aplica el elegido (world.inject) sin gastar presupuesto
```

`suggest()` no toca ni el mundo ni el agente reales: trabaja sobre clones. Con Mando tarda ~20–30 ms.

## Cómo decide

1. **Catálogo** (`catalogue(world, snapshot)`): golpes candidatos con el formato de efectos `world` de
   `INTERFACES.md`, de más a menos dirigidos:
   - `rank 0` — **supuestos vivos** de los planes (`snapshot["plans"][].assumptions` con `holds`):
     `zone_occupancy_below`/`zone_density_below` → `zone_inflow` en esa zona · `zone_state_is` → `zone_state closed` ·
     `resource_status_is` → `resource_offline` · `route_clear` → `zone_inflow` en la ruta · `weather_below` → `weather` ·
     `supply_above` → `zone_flag` a 0 · `action_accepted_within` → `resource_no_answer`.
   - recursos que están de camino o atendiendo (`resource_offline`; «es el único que lo cubre» si no quedan libres
     de su tipo), último recurso libre de un tipo (`resource_rejects`, `resource_no_answer`), cierre de `corridor_s`
     con la ambulancia en ruta.
   - incidente grave nuevo (`incident`: parada cardiaca en la zona más densa; arma blanca si queda ≤ 1 de seguridad).
   - `zone_inflow` en las dos puertas/foso más llenos, agua a cero con calor, apagón en restauración, tormenta,
     41 °C, `comms_down` de voz o radio, `transport_cut` en salida.
2. **Daño estimado**: para cada candidato (máx. 12) clona mundo (`world.clone()`) y agente (`copy.deepcopy` con el
   mundo clonado en el `memo`, para que su `SimComms` apunte al clon), aplica el golpe y simula `lookahead` minutos con
   un operador que aprueba a los 2 min. `daño = harm(con golpe) − harm(sin golpe)`. `harm()` pesa fallidos
   (×2,5 si gravedad ≥ 8), incidentes sin atender según el plazo gastado, minutos por encima de 5/m² y pico de densidad.
   Si el agente no se puede copiar, simula solo el mundo (re-simulación barata).
3. **Momento**: golpea si el mejor daño supera un listón que empieza en ≈ «provocar un fallo» (14) y baja
   linealmente con el tiempo; cuando el tiempo que queda solo da para gastar el presupuesto, golpea con cualquier
   daño > 0,5. Mínimo 4 min entre golpes; evalúa cada 2 min.

Caos ve el guion futuro del caso (los clones comparten los eventos programados): es el autor del escenario.
El agente nunca ve nada de Caos.

`RandomChaos(budget)`: mismo catálogo (sin supuestos) y mismo presupuesto, pero momento y golpe al azar con
semilla. Es el control: en `test_harness` el inteligente hace más daño medio que el aleatorio.

## Nota sobre Mando

`Mando.triage` guarda `lambda: self.new_id("M")`; `deepcopy` no copia funciones, así que el clon gastaría los
ids del agente real (en la demo aparecerían `M-371`). `rollout()` reengancha ese generador al clon. Está
apuntado en `motor/harness/out/BUGS.md`.
