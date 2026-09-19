# MANDO — el MVP

**Sabe cuándo su plan ha dejado de valer.** Un agente que coordina los incidentes de un evento masivo:
recoge avisos por todos los canales, decide qué va primero, llama de verdad a quien tiene que actuar,
ensaya cada decisión en un gemelo del recinto antes de ejecutarla, y tira el plan y lo rehace cuando un
supuesto se rompe. Lo grave lo decide una persona, con los dos futuros delante.

## Arrancarlo

```bash
./mvp.sh          # todo en local y simulado: http://127.0.0.1:8000  ·  app del asistente: /asistente
./mvp.sh lan      # accesible desde los móviles de la misma wifi (QR en la tecla Q)
./mvp.sh real     # con HappyRobot y Telegram reales (rellena antes .env a partir de .env.example)
./mvp.sh check    # tests de todos los módulos y comprobación de la configuración
./mvp.sh cifras   # recalcula el número titular del banco de pruebas, con N e intervalo
```

## Qué ve el jurado (dos perspectivas)

| Quién | Dónde | Qué hace |
|---|---|---|
| **Una persona del festival** (el jurado, con su móvil) | `/asistente`, bot de Telegram, llamada por Web call, email, SMS | Avisa de lo que pasa, por escrito o por voz; ve en directo qué hace Mando con SU aviso; puede provocar un imprevisto y ver cómo cambia el plan |
| **El centro de control** | `/` (modo escena: tecla E), `/duelo`, `/memoria`, `/informe` | Ve en dos segundos qué pasa y qué ha cambiado; prioridades con su porqué; plan con supuestos; llamadas con ACEPTA / RECHAZA; aprueba o veta lo grave con la tarjeta de decisión; ensaya un «¿y si…?» en el gemelo; aprueba lo que el sistema propone cambiar para mañana |

## Cómo está hecho

```
 avisos: voz · Telegram · email · SMS · web · sensores
        │
        ▼
 HappyRobot  ── entiende (AI Extract + AI Classify) ──►  /hr/events
        ▲                                                   │
        │  llama por teléfono: orden → ACEPTA / RECHAZA     ▼
        │  Signals: cambia la orden en plena llamada     MANDO (backend propio)
        └──────────────────────────────────────────────  triaje → prioridad → ENSAYO en el gemelo
                                                          → plan con SUPUESTOS → acciones
 persona del centro de control  ◄── tarjeta de decisión ──┘        │
        └── aprueba · veta · corrige · toma la llamada             ▼
                                                     simulador del recinto  ◄── CAOS (el jurado)
```

- **HappyRobot habla y entiende; Mando decide; una persona manda en lo grave.** Workflows montados por
  MCP en el workspace del equipo: despacho por teléfono, despacho por Web call, e ingesta por voz, email,
  SMS y texto (Telegram y sensores). Detalle en `motor/happyrobot/PLATAFORMA_REAL.md`.
- **El núcleo que decide es un planificador de bucle cerrado con reglas, determinista y explicable**, no
  un LLM: cada decisión tiene su número y su porqué, y se puede reproducir con la misma semilla. Los
  modelos de lenguaje están donde aportan: en la conversación y en entender texto libre.
- **Seguridad por diseño:** evacuar, parar el espectáculo o pedir ayuda externa NUNCA se ejecutan sin una
  persona; una parada cardiaca nunca espera a nadie; lo sensible (agresiones, menores) va enmascarado;
  no se marca ningún número fuera de la lista blanca; ningún número de emergencias real.

## Qué es real y qué es simulado

| Real | Simulado |
|---|---|
| Llamadas de voz por HappyRobot a móviles de la lista blanca, con aceptación o rechazo | El recinto, la multitud, los recursos y el tiempo (simulador determinista, 1 tick = 1 min) |
| Bot de Telegram, Web call, email y SMS de entrada | Las personas al otro lado cuando no se usa HappyRobot (`--comms sim`) |
| Webhooks en los dos sentidos, servidor MCP propio, northstars y tests en la plataforma | Sensores de aforo y meteorología |
| Las decisiones, los ensayos en el gemelo y las aprobaciones humanas | — |

## Cómo se ha medido

Contra un agente de lista fija, en los MISMOS casos y semillas, con intervalos de confianza y sin excluir
ninguna ejecución. Es simulación, no dato de campo. Cifras vigentes en `motor/harness/out/report.md`
(se regeneran con `./mvp.sh cifras`): en **1.000 casos que el agente no había visto nunca**, Mando
mejora a la lista fija en **+8,9 puntos [7,7 – 10,1]** y baja los incidentes críticos fallidos del 18,6 %
al 13,2 %; **con un adversario que ataca el mundo** (3 golpes), **+15,5 [13,0 – 18,2]** (N = 300).

## Límites que decimos nosotros antes de que los pregunten

- **Falla menos, no llega antes**: el tiempo hasta la primera atención es parecido al de la lista fija
  (2,4 frente a 1,9 min); lo que el banco sostiene es que Mando deja menos incidentes críticos sin atender.
- **El ensayo en el gemelo no mueve la media** (−0,09 [−0,33 – 0,13], N = 1.200): su valor es de caso y de
  explicación (la puerta B, los dos futuros de la tarjeta de decisión), no es la fuente del +8,9.
- **Muchos frentes a la vez**: con 5 frentes Mando saca ventaja clara (70,0 frente a 63,8); con 6 y 7 los
  intervalos se solapan: se degrada como cualquiera cuando faltan recursos. Lo que sí hace siempre es decir
  a quién deja esperando y por qué.
- **«Aprende», con su letra pequeña.** Medido (N = 400 por brazo, mismos casos, IC 99 % pareado): tras
  observar el día 1 que reponer el agua tardaba 28,7 min y no los 10 de ficha (N = 50), proponerlo con su N
  y aprobarlo una persona, las **roturas de stock bajan de 0,33 a 0,18 por caso**, y de 0,38 a 0,25 en 400
  casos nunca usados para la memoria; la **búsqueda de la persona baja 1,4–1,8 min**. Lo que NO mejora: la
  puntuación global ni los críticos fallidos (sin evidencia). Se aprende PARÁMETROS con reglas, no se
  entrena un modelo; y los tiempos ocultos del recinto simulado los pusimos nosotros.

## De MVP a producto (qué haría falta para incorporarlo en un recinto de verdad)

1. **El recinto es un fichero** (`motor/world/festival.json`): zonas, aforos, vecinos, recursos y programa.
   Cambiar de festival, estadio o feria es cambiar ese fichero; el motor no se toca. El Plan de
   Autoprotección del evento (obligatorio por el RD 393/2007 desde 20.000 personas al aire libre) es la
   fuente natural de esos datos y de las reglas que no se pueden romper.
2. **Sensores reales** en lugar del simulador: contadores de aforo por puerta, estación meteorológica y
   posición de equipos entran por el mismo contrato (`Observation`); el gemelo se alimenta de ellos.
3. **Telefonía local** (número español, SIP del recinto) y, donde el mando es por radio, el agente se queda
   con el teléfono del centro de control: proveedores, transporte, relevos, servicios externos.
4. **Identidad y permisos**: quién puede avisar, quién puede aprobar y quién puede tomar una llamada;
   registro auditable de cada decisión con su porqué (ya existe el log; falta firmarlo y conservarlo).
5. **El simulacro anual que exige la norma, cada noche**: el mismo banco de pruebas y el mismo adversario,
   sobre el plan real del evento, con informe de por dónde se rompe.
6. **Despliegue**: `Dockerfile` en la raíz; un contenedor detrás de un proxy con TLS, secretos por
   variables de entorno (`.env.example`), `MANDO_OPERATOR_TOKEN` obligatorio si se expone a internet.

Segundo vertical con el mismo motor: **cuadrillas de avería de una eléctrica** (recibir el aviso,
despachar por voz, confirmar y cerrar el bucle), que es la operación que HappyRobot ya vende en Utilities.
