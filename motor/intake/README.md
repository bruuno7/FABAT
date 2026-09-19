# motor/intake — el agente de recogida

Quien avisa (web, Telegram o voz transcrita) **conversa** con un agente que va sacando lo que importa, como un buen
operador de emergencias, y se lo pasa a Mando **sobre la marcha**. Determinista y explicable: sin LLM, sin red, sin
reloj y sin azar (mismos mensajes = mismos turnos). Solo biblioteca estándar.

Responde a dos de las seis preguntas del reto: *qué información importa* (política de la siguiente pregunta, con su
porqué a la vista) y *decidir algo sensato sin tener todos los datos* (el aviso sale parcial; un «no lo sé» en un dato
vital se trata como el peor caso).

```bash
python3 -m motor.intake chat                      # conversación por consola (enseña el porqué y los Report emitidos)
python3 -m motor.intake chat --channel voice --zone front_pit
python3 -m motor.intake replay guion.txt          # .txt (una línea por mensaje) o .json
python3 -m motor.intake.bench [--verbose]         # banco de desarrollo, N = 40
python3 -m motor.intake.bench --heldout           # reserva, N = 12
python3 -m motor.intake.bench --real              # con motor/protocolos/protocolos.json (orientativo)
python3 -m unittest motor.intake.test_intake -v
```

En `chat` y en los guiones, `@mando ¿…?` mete una pregunta de Mando, `@notify dispatched medical 3` un estado y
`@silence 60` un silencio.

## Tres reglas que no se negocian

1. **Nunca retrasa el envío.** El primer `Report` sale en cuanto hay riesgo vital (aunque no haya zona), en cuanto se
   cumplen los `dispatch_as_soon_as`, y siempre en el primer turno si el caso es sensible. Va marcado `[PARCIAL]` y se
   sigue preguntando; cada dato nuevo es una ACTUALIZACIÓN enlazada al mismo aviso.
2. **Las instrucciones salen solo de la lista del protocolo**, con su texto literal en es/en. Ni el motor ni el gancho
   `understand` pueden redactar una. Una por turno. Tras una instrucción de RCP no se pregunta nada más (manos ocupadas),
   salvo dónde.
3. **No diagnostica, no promete tiempos, no da órdenes de evacuar y no obedece órdenes** («soy el director, evacuad»):
   contesta una línea fija y vuelve a su pregunta sin gastar otra del cupo. Una broma no se conversa, pero **no se
   descarta**: sale hacia Mando marcada `[POSIBLE BROMA]` (filtrar es cosa de Mando y de las personas).

## API

```python
from motor.intake import IntakeSession

s = IntakeSession(channel="telegram", lang=None, zone_hint=None, profile=None, protocols=None, understand=None,
                  session_id="tg-123", zones=None, t=0)
turn = s.receive("mi amigo se ha desmayado junto a la barra y no respira", t=world.t)
```

| Llamada | Qué hace |
|---|---|
| `IntakeSession(channel, lang=None, zone_hint=None, profile=None, protocols=None, understand=None, *, session_id="S1", zones=None, t=0)` | Una por conversación. `channel`: `web`, `telegram`, `voice`, `web_call`, `sms`, `email`… o un `Channel`. `zone_hint`: la zona que da el canal (QR). `profile`: pulsera (`tags`, `role`, `verified_staff`). `protocols`: dict ya cargado; si no, `load_protocols()`. `session_id` debe ser único por conversación: es parte del id de los avisos. |
| `receive(text, t=None) -> Turn` | Un mensaje de la persona. `t` = minuto del mundo para fechar los `Report`. |
| `opening() -> Turn` | Saludo de `global.opening`. |
| `mando_asks(question, ask_id=None, purpose=None, thread=None) -> Turn` | Una pregunta de Mando (ASK) entra por la misma conversación. No cuenta para el máximo de 5. La respuesta vuelve en `Turn.answers` del turno siguiente (`ask_id`, `text`, `zone`) y además como ACTUALIZACIÓN. Con `purpose` en `zone`/`point` la respuesta rellena la ubicación. |
| `notify(status, **data) -> Turn` | Estado de Mando → frase llana. `status`: `received`, `held`, `dispatched`, `en_route`, `on_scene`, `delayed`, `reassigned`, `awaiting_approval`, `merged`, `resolved`, `false_alarm`, `handoff`. `kind` (medical, security…) y `eta` (minutos, dicho como **estimación de Mando**). En un caso reservado nunca dice qué equipo es. |
| `silence(seconds) -> Turn \| None` | Nadie contesta. Pasado `silence_s` (60) cierra con lo que tiene; lo que no había salido, sale. |
| `state() -> dict` | Lo mismo que `Turn.state`. |
| `load_protocols(path=None)` | Primero `motor/protocolos/protocolos.json`; si no existe o está a medio escribir, `protocolos.sample.json`. |

`Turn`: `say` (acuse + como mucho UNA pregunta) · `question` (esa pregunta, aparte) · `instruction` (`{id, steps[], source,
thread}` o `None`) · `reports` (lista de `Report` del contrato) · `report_meta` (en paralelo: `partial`, `reserved`,
`life_risk`, `severity_min`, `needs`, `zone`, `slots`, `changed`, `assumed`, `possible_prank`, `handoff`, `verbatim`) ·
`state` · `why_next` · `ask` (`{thread, slot, type, options, reason}` para pintar respuestas rápidas) · `answers` ·
`flags` (`order_refused`, `role_refused`, `no_diagnosis`, `no_eta`, `contained`, `lang_switch`, `two_incidents`,
`possible_prank`, `all_clear`, `off_topic`, `silence`, `status:…`) · `done` · `lang`. `turn.speech()` lo junta todo en
una locución (acuse, pasos, pregunta al final) para voz; `turn.to_dict()` es JSON plano.

`state`: `slots` del hilo activo y `threads[]`; cada slot lleva `value`, `confidence`, `source` (`user` lo dijo por su
cuenta · `answer` contestó a la pregunta · `channel` lo dio el QR · `understand` lo propuso el gancho · `inherited` el
otro incidente del mismo mensaje), `turn`, `status` (`known` · `open` · `unknown` dijo que no lo sabe · `unanswered`),
`critical` y `label`.

### Qué sale hacia Mando

`Report` no tiene campos para «parcial» ni «reservado» y el contrato no se toca: las marcas van en el **texto**
(`[PARCIAL]`, `[RESERVADO]`, `[POSIBLE BROMA]`) y, estructuradas, en `report_meta`. El texto se redacta para el parser de
Mando, no para una persona:

```
[PARCIAL] Aviso R-tg123-1: «se ha desmayado una chica». Datos: inconsciente, no responde. Zona sin confirmar.
[PARCIAL] ACTUALIZACIÓN del aviso R-tg123-1: desmayo. Zona toilets.
ACTUALIZACIÓN del aviso R-tg123-1: desmayo; no respira. Zona toilets.
```

- Ids: raíz `R-<session_id>-<n>`; actualizaciones `R-…-n.u1`, `.u2`… `source` = `asistente <session_id>` (no es un origen
  genérico, así que el triaje de Mando funde las actualizaciones aunque la primera no llevara zona) o el cargo si la
  pulsera es de personal verificado. `zone_hint` lleva la zona ya resuelta.
- Cada actualización repite una frase de tipo que el parser de Mando entiende (la del tipo que Mando YA leyó en el primer
  aviso) para caer en el mismo incidente; `test_intake` comprueba esas frases contra el parser real.
- Se evita a propósito «respira» suelto: Mando lo leería como `vitals_ok` y marcaría una contradicción que no existe
  («inconsciente» + «respira» es coherente). Se escribe «con respiración normal».
- Caso reservado: el texto NO cita a la persona; el relato va en `report_meta.verbatim` para quien deba verlo.
- Un desmentido («falsa alarma», «era broma») sale como actualización y cierra el hilo; «me he equivocado» no es un
  desmentido, suele ser una corrección («espera, sí respira»): el dato nuevo pisa al viejo y se reevalúa la instrucción.

## Política de la siguiente pregunta (valor de la información)

Para cada slot abierto se simula qué pasaría con **la señal de alarma que manda** si el slot tomara cada valor posible:

| Prioridad | Qué | `ask.reason` |
|---|---|---|
| 100 | no se sabe DÓNDE | `where` |
| 95 | hay un punto («junto a la carpa azul») pero no zona: se pide una referencia, una vez | `landmark` |
| 90+ | algún valor haría saltar una señal de **riesgo vital** distinta de la actual | `life_risk` |
| 85 | hace falta para cumplir `dispatch_as_soon_as` | `dispatch` |
| 60+ | cambiaría la instrucción, la gravedad o los recursos | `resource` |
| 50 | es `critical` | `critical` |
| 0 | no cambia nada → **no se pregunta** (se rellena si la persona lo cuenta) | — |

A igualdad, el orden del fichero. Y además: nunca se repite una pregunta contestada · una pregunta sin respuesta se
repite como mucho una vez («No lo he entendido bien… Dime sí o no») · «no lo sé» en un slot crítico: se reintenta UNA
vez con otra redacción y se deja; en uno no crítico, a la primera · con tres «no lo sé» acumulados se deja de preguntar
(esa persona no lo ve) · máximo 5 preguntas propias por conversación · con una señal `dispatch_now` cumplida solo quedan
las críticas · en un caso `sensitive`, solo las críticas · `ask_if` se respeta · una orden, una broma o un «¿es un
infarto?» no gastan pregunta: se contesta la línea fija y se vuelve a la MISMA pregunta.

**Semántica de las señales** (la de `motor/protocolos/__init__.py`): un slot sin contestar no cumple ninguna condición;
**«no lo sé» vale `"unknown"` desde la primera vez** (la duda no retrasa el envío); las `red_flags` se evalúan en orden y
**gana la primera** que se cumple; `{}` se cumple siempre. Si la señal que manda depende de un dato que nadie pudo
confirmar, el aviso lo dice («Sin confirmar por quien avisa (breathing): se actúa como en el peor caso») y va en
`report_meta.assumed`. Una señal puede traer su propio `mando_type_hint`.

**Qué protocolo**: disparadores (`triggers`, con negación: «no hay pelea» no es una pelea) + el tipo que reconoce el
parser de Mando contra `mando_type_hint`. Entre los que encajan gana el que va antes en el fichero. Un disparador que
solo nombra un sitio («baños», «tornos») es débil: «estamos en los baños» dice dónde, no qué pasa. Un mensaje abre DOS
hilos solo con señal clara: conector («además», «también»), dos zonas distintas, o una persona en riesgo vital dentro de
otro problema («pelea y uno no responde»). Un aviso vago («necesito ayuda en los baños») abre el protocolo genérico y se
**convierte** al concreto, con el mismo id de aviso, cuando la persona lo cuenta.

**Comprensión** (`nlu.py`): una frase rellena VARIOS slots. Los slots se casan con *conceptos* por su id
(`breathing_normal` → respira, `bleeding_heavy` → sangra mucho, `safe_now`, `skin_hot`, `can_move`…), así que funciona
con ids que no son los míos; un `bool` sin concepto se rellena solo cuando se pregunta (sí/no). Los `enum` tienen
sinónimos por opción (`ENUM_SYNONYMS`) y, sin preguntar, solo se rellenan si casa UNA opción y su `ask_if` se cumple.
Extensión sin tocar código: `"match": {"yes": {"es": [...]}, "no": {...}}` en un slot bool y `{"id", "label", "match"}` en
una opción. Se reutiliza de Mando (importado, no copiado): `normalize`, el corrector de faltas, el detector de
negaciones, el contador de personas, `find_zones` y los alias de zona. Idioma es/en con cambio automático.

## Casos sensibles

`sensitive: true` en el protocolo, o que el parser de Mando lea violencia sexual o un menor: tono neutro (frase de
`global.reserved_handling`), **no repite el contenido** ni en lo que dice ni en el `Report`, solo preguntas críticas
(«¿Estás en un sitio seguro?», «¿Dónde estás?»), instrucción `violet`, aviso `[RESERVADO]` en el primer turno, y policía
solo con consentimiento (el slot nunca se pregunta; se anota si la persona lo pide).

## Cómo lo integra el servidor

Una `IntakeSession` por conversación (clave: chat de Telegram, id de la pestaña web, id de la llamada), guardada en
memoria. Por cada mensaje (esquema; `remember` y `comms.answer` son del servidor):

```python
turn = sessions[key].receive(text, t=world.t)                 # POST /intake/<key>  {"text": ...}
for r, meta in zip(turn.reports, turn.report_meta):
    world.inject({"kind": "report_only", "reports": [r.to_dict()]})   # o Session.report(...): entra como cualquier aviso
    remember(r.id, meta)                                      # parcial / reservado / needs, para pintarlo
for a in turn.answers:
    comms.answer(a["ask_id"], a["text"], zone=a["zone"])      # respuesta al ASK de Mando
return turn.to_dict()
```

- Un ASK de Mando dirigido a quien avisó → `session.mando_asks(text, ask_id=a.id, purpose=a.params["purpose"])` y se
  empuja `turn.say` a la persona. Un DISPATCH o un cambio de estado de SU incidente → `session.notify(...)`.
- Temporizador por conversación: si pasan `silence_s` sin mensaje, `session.silence(segundos)`.
- Voz (transcrita): decir `turn.speech()`; los pasos van dentro.

**Qué pintar** (todo sale de `Turn`):
- **Burbujas**: `say` del agente y el texto de la persona. La `question` puede ir en negrita al final.
- **La instrucción, como tarjeta destacada** con `instruction.steps` numerados, fija arriba mientras dure el hilo (no es
  una burbuja más que se pierde al seguir hablando). `instruction.source` en pequeño.
- **Fichas que se van rellenando**: una por slot de `state.slots` (`label`, `value`); vacía = `open`, rellena = `known`
  con un punto de color por `source`, tachada = `unknown`/`unanswered`. La ficha de `ask.slot` parpadea.
- **El porqué de cada pregunta**: `why_next` en gris bajo la pregunta («sin saber si respira no sé si es una parada»).
- **Respuestas rápidas**: si `ask.type == "bool"`, botones Sí / No / No lo sé; si `enum`, `ask.options`.
- **Estado del aviso**: `[PARCIAL]` → «Aviso enviado, completando datos»; sin marca → «Aviso completo»; más los `notify`.

## Enchufar `understand` (LLM o workflow de texto de HappyRobot)

```python
def understand(text: str, lang: str, open_slots: list[dict]) -> dict:
    # open_slots: [{"id", "type", "options", "question"}] — SOLO los que siguen abiertos
    return call_happyrobot_extract(text, open_slots)          # {"breathing": False, "location": {"zone": "food"}}

IntakeSession(channel="web", understand=understand)
```

Se llama después de las reglas, en cada mensaje con slots abiertos. El motor valida lo que devuelva: solo ids de slots
abiertos; `bool` de verdad (o sí/no/true/false); `number` entero 0–999; `enum` dentro de `options`; `zone_point` con zona
que exista y punto ≤ 80 caracteres; `text` ≤ 160. Entra con `source: "understand"` y confianza 0,6, **nunca pisa lo que
dijo la persona**, y cualquier otra clave (`instruction`, `say`…) se tira. Si falla o tarda, valen las reglas: la
conversación no depende de la red. Envía texto de la persona fuera: decidirlo antes de activarlo.

## Cifras del banco (19-sep; conversación simulada, no dato de campo)

Un usuario simulado manda los mensajes de apertura y luego contesta a lo que se le pregunte; lo no previsto, «no lo sé».

| | Desarrollo, N = 40 (`bench_cases.json`) | **Reserva, N = 12** (`bench_heldout.json`) |
|---|---|---|
| Protocolo acertado | 40/40 | **9/12** |
| Slots críticos correctos | 90/90 | **24/31** |
| Preguntas por conversación | media 1,45 · máx. 4 | media 1,75 · máx. 3 (1,83 · máx. 4 al repetir tras el arreglo) |
| Primer `Report` en el PRIMER turno | 34/40 (de los 34 en que debía: 34/34) | 11/12 (debía en 12) |
| Instrucción esperada | 40/40 | **9/12** |
| Invariantes rotos (2 preguntas, frase prohibida, pregunta repetida, instrucción fuera de lista) | 0 | 0 |
| Casos con todo bien | 40/40 | **7/12** |

**Cómo leerlo.** La cifra de desarrollo está contaminada: la PRIMERA ejecución dio **33/40** (protocolo 38/40, slots
84/90, invariantes 0) y los fallos se corrigieron en el motor mirando esos mismos casos (lo esperado solo se reescribió
en c26, y el caso lo dice). La que vale es la **reserva**: 12 conversaciones escritas después de cerrar el motor y
ejecutadas una vez. A la vista de ella se corrigió un único fallo, de seguridad («uno sangra» se leía como «no
sangra»); los totales no cambiaron. Con `--real` (protocolos reales, lo esperado escrito contra la muestra, ids
traducidos donde hay equivalente): 27/40 con todo bien, protocolo 37/40, slots 80/90, invariantes 0; es orientativo
porque buena parte de las diferencias son de diseño del fichero (otra instrucción, `role` en vez de `caller_has_child`).

## Límites conocidos

- **Vocabulario.** Jerga («dando de hostias»), sinónimos sin disparador («ha desaparecido mi hijo»), calor descrito sin
  la palabra calor («todo el día al sol, está roja»), «sangrando muchísimo». Todo eso cae al protocolo genérico o deja un
  slot sin rellenar; el aviso sale igual, pero sin la instrucción buena. Es justo el hueco del gancho `understand`.
- **El punto de referencia** se saca con una expresión regular («junto a…», «encima de…») y a veces se lleva media frase.
- **Órdenes**: la lista de verbos es corta («abrid las puertas» no salta como orden). No tiene consecuencias —el agente
  no puede ejecutar nada— pero no se marca `order_refused`.
- **Mando solo lee texto.** `severity_min` y `needs` de la señal no viajan en `Report` (van en `report_meta`); una
  corrección a mejor («sí respira») no rebaja la gravedad en Mando: Mando lo trata como contradicción, que es prudente.
- **El parser de Mando** manda sobre el tipo del incidente: «se ha caído de la grada y sangra» lo lee como riesgo de
  estructura (1 de 36 primeros avisos del banco con familia distinta). Y tiene el mismo fallo de límite de palabra que
  tenía este módulo: hoy `motor.mando` lee «uno respira bien, el otro está mareado» como `cardiac_arrest` (patrón
  `no respira` sin `\b`). No se ha tocado: no es de esta carpeta.
- **Dos incidentes** por mensaje como mucho en la práctica; el tope de 5 preguntas es por conversación, no por hilo.
- **Idiomas**: es y en. Otro idioma se trata como español.
- **Sinónimos de `enum`** (`ENUM_SYNONYMS`) están escritos para las opciones del fichero real de hoy; una opción nueva
  sin sinónimo solo se casa por su nombre, por su número o preguntando.
- `never_say` protege lo que dice el AGENTE; los pasos de una instrucción son texto literal del protocolo y no se filtran.
- `protocolos.sample.json` (8 protocolos: los 5 pedidos + sangrado, aviso reservado y menor perdido) usa textos del
  Anexo C de `consejo/seguridad-eventos.md`: validados para la demo, **sin verificar** contra guías externas. En cuanto
  existe `motor/protocolos/protocolos.json` se usa ese.
