# motor/baseline — el agente de lista fija

Carpeta privada. Solo biblioteca estándar. Implementa `AgentAPI` (mismo contrato que Mando) para poder
compararlos sobre los mismos casos y semillas.

```python
from motor.baseline import Baseline, BaselinePlus, BaselineReroute
agent = Baseline(comms=comms)        # misma firma que Mando(playbook=None, comms=None, parser=None)
```

## Qué hace `Baseline` (el protocolo en papel, hecho con honestidad)

- **Parser por palabras clave** (`KeywordParser`, es/en, sin acentos): zona por `zone_hint` o por nombre
  («puerta b», «foso», «food truck»…), tipo de recurso por vocabulario (médico, seguridad, técnico,
  logística; «no respira» → ambulancia) y una gravedad tosca (8 si hay palabra grave, 5 si no).
  Medido contra la verdad de los primeros 1.500 casos de train (N = 5.215 avisos de incidentes verdaderos): acierta
  el tipo de recurso en el 86,7 % y la zona en el 73,4 % (en el 24,8 % no reconoce ninguna zona y el aviso se queda
  sin atender). Gana el tipo con más palabras encontradas; a igualdad, el más grave.
- **Un aviso → un despacho** al recurso LIBRE más cercano del tipo adecuado (distancia del plano, sin mirar
  densidad), **por orden de llegada**. Si no hay nadie libre de ese tipo, el aviso espera su turno.
- «Si no contesta, llama al siguiente»: ante `no_answer`, `rejected`, `resource_offline`, `resource_busy`,
  `comms_down` o `route_blocked` reintenta con otro recurso, hasta 2 veces más. Es lo único que reintenta.
- **Respeta la aprobación humana**: «fuego» → pide bomberos; «arma/bomba» → pide policía; «parada cardiaca /
  no respira» → pide ambulancia externa. Todo eso sale en `AWAITING_APPROVAL` y solo se ejecuta tras `approve(ok=True)`.
- Avisos de SENSOR de zona saturada → manda seguridad a mirar.

## Qué NO hace (y es justo lo que pide el reto)

No fusiona duplicados (dos avisos del mismo desmayo = dos equipos), no ordena por gravedad, no escribe
supuestos, no replanifica cuando el mundo cambia (si un recurso cae a mitad de camino, no se entera), no
pregunta nunca, no mira densidades ni toca zonas, desvíos o megafonía, y solo cubre UNA unidad por aviso
aunque el incidente necesite dos. Un aviso sin zona reconocible se queda sin atender (queda en el log).

## `BaselinePlus` (segundo escalón)

Igual, pero **fusiona** avisos del mismo sitio y tipo de recurso en 15 min (emite `MERGE`) y atiende la cola
**por gravedad** estimada en vez de por llegada. Sirve para ver cuánto de la ventaja de Mando se explica solo
con esas dos ideas.

## `BaselineReroute` (tercer agente de referencia)

Firma pública: `BaselineReroute(playbook=None, comms=None, parser=None)`, con `tick(obs)`,
`approve(action_id, ok, note="")` y `snapshot()` heredados. Su nombre es `baseline_reroute`.
Conserva los despachos de `Baseline`: uno por aviso al recurso libre más cercano, por orden de
llegada, sin fusionar duplicados, sin supuestos ni replanificación. Mantiene las aprobaciones
humanas para `ALWAYS_APPROVE`.

Ante un aviso textual de atasco o saturación (por ejemplo, «puerta B atascada», «puerta saturada»,
«no avanza» o «overcrowded»), reconoce la zona con el mismo parser y aplica una única vez por
origen el desvío del manual: **gate_b → gate_a, gate_a → gate_b, gate_c → gate_b**. Emite
`REROUTE` con `zone=origen` y `params={"to": destino, "fraction": 0.6}`. No comprueba la ocupación
del destino, no ensaya, no pone caducidad y nunca retira el desvío. Las lecturas numéricas de los
contadores siguen generando despachos como en `Baseline`; no activan una revisión del desvío.

Sirve como referencia para la pantalla partida `/duelo`: el procedimiento fijo satura la puerta A
con su propio desvío, mientras el agente de verdad lo ensaya antes. Este módulo proporciona el
agente; seleccionarlo en la pantalla corresponde al servidor.

```bash
python3 -m unittest motor.baseline.test_baseline -v
```

El test de integración usa `demo_case.json`, `World` y `SimComms` reales, y comprueba en
`world.truth()` que el pico de A supera 5 personas/m² con el desvío (N = 1 caso, semilla 7),
frente a `Baseline` sin desvío. También verifica determinismo, los tres destinos, despachos sin
fusión y el ciclo de aprobación, espera y veto.

`snapshot()` devuelve `incidents` (un «ticket» por aviso o grupo, con sus `reports`), `plans: []`, `actions`,
`log`, `lessons: []`. No usa `comms`: el resultado de cada despacho le llega por `obs.action_results`.
