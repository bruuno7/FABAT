# Fallos encontrados por el banco de pruebas en otros módulos

No se ha tocado nada de `motor/mando/`, `motor/world/` ni `motor/cases/`. Cada entrada dice con qué huella de código
se vio; como esos módulos siguen cambiando, algunas pueden estar ya arregladas: reproducir antes de trabajar en ellas.

## Proceso (afecta a todas las cifras)

**P1 · Los ficheros de casos se regeneran en el sitio con los mismos ids y semillas.**
`motor/cases/data/{train,heldout,demo}.jsonl` se reescribieron el 19-sep a las 00:01:47 mientras corría una medición.
Misma lista de (id, semilla), contenido distinto: la misma orden dio «lista fija 74,31 con 190 críticos» (antes) y
«70,03 con 276 críticos» (después) sobre «los mismos» 120 casos. Qué debería pasar: cada generación con su versión
(nombre de fichero o campo `dataset` dentro de cada caso). Mitigación en el banco: `--freeze` copia también los casos
y `case_signature` es un hash del CONTENIDO.

**P2 · Mando se edita mientras se mide.** Una copia congelada hecha a las 00:04:48 tenía `mando.py` llamando a
`self._escalate_cards()`, que aún no existía: 1.000 de 1.000 ejecuciones de Mando reventaron (`AttributeError`). El
banco las contó como score 0 (no las escondió), pero llegó a escribir ese `headline.json`. Mitigación: comprobación
previa que aborta sin escribir nada y `--wait-stable N`.

## motor/mando

**M1 · El generador de ids del triaje es una clausura sobre `self` y no sobrevive a `copy.deepcopy`.**
`mando.py`: `self.triage = Triage(self.incidents, self.meta, lambda: self.new_id("M"))`. `deepcopy` no copia
funciones: el triaje del clon sigue llamando al `new_id` del Mando ORIGINAL. Visto (huella de las 23:31, caso de train
n.º 6, Caos inteligente): tras los ensayos de Caos el Mando real numeraba sus incidentes `M-371`. Qué debería pasar:
un clon no debe tocar el estado del original (pasar `self.new_id` enlazado o un contador propio del triaje). Caos lo
esquiva reenganchando `triage.new_id` en el clon (`motor/caos/chaos.py`, `rollout`). Vale igual para el ensayo con gemelo.

**M2 · Las aprobaciones y vetos se registran con el minuto anterior.** `approve()` usa `self.t`, que es el del último
`tick`; el operador decide al principio del minuto siguiente. En el log sale «PIDE APROBACIÓN» y «La persona APRUEBA»
en el mismo minuto aunque hayan pasado 1–3. Cosmético, pero en pantalla parece que la persona contesta al instante.

**M3 · (visto con la huella de las 23:37; reproducir) Dato enterrado en un mensaje largo.** Caso de train con
`weapon_seen` (gravedad 9, plazo 10 min) cuyo único aviso era un WhatsApp que empieza preguntando por el último bus y
en mitad dice «un tío ha sacado una navaja… en la entrada pequeña, la C». Mando no abrió incidente: nunca se despachó y
el crítico falló. Era el patrón de crítico fallido más repetido (`never dispatched`). Qué debería pasar: una palabra de
amenaza vital en cualquier parte del texto abre incidente aunque la intención dominante sea otra.

**M4 · (huella de las 23:37; reproducir) Un aviso contradictorio cierra un crítico como falsa alarma.** Caso con
`chemical_submission` (gravedad 9): a los 2 min llega por radio «está controlado, no mandéis más gente» de otro
indicativo y Mando emite `DISMISS` («jefe de seguridad 3 dice que no pasa nada»); el incidente verdadero acaba FAILED.
Regla del caso violada: `must_not: dismiss i1`. Qué debería pasar: con gravedad ≥ 8 una negación de un tercero baja la
confianza y dispara un ASK a quien está en el sitio, no un cierre.

## motor/cases ↔ motor/world

**C1 · `request_external 112 for iN with approval`.** El servicio «112» no existe para el mundo
(`external_eta_min`: ambulance, medical, police, fire y, desde la fase 2, transport): un agente que pidiera literalmente
`kind="112"` recibiría `unknown_external`. El puntuador acepta cualquier REQUEST_EXTERNAL aprobado para esa regla.
Qué debería pasar: que la regla nombre un servicio que el mundo conozca.

**C2 · Reglas no evaluables con la información del caso.** `dispatch to iN before location known` y `wait for approval
before dispatch to iN` no se pueden comprobar sin saber en qué aviso «se conoce» la zona. El banco las deja como no
evaluables (no puntúan); si importan, el caso debería marcar el aviso que trae la zona.
