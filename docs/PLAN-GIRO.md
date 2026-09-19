# Plan del giro — HappyRobot decide, MANDO es su mundo y sus manos (rama `ana`, sáb 19-sep 15:40)

## El problema del diseño anterior (dicho sin paños calientes)
- **Quien decidía era un backend con reglas; HappyRobot era la boca y el oído.** Para un reto del propio HappyRobot que puntúa
  «decide y actúa por su cuenta» y «aprende», eso es ir a contrapelo: fiable, pero poco agéntico y con el patrocinador de adorno.
- **Anchura en vez de profundidad:** tres interfaces (Sala, centro, clásica… y `web/`), dos bases de datos (`db.py` y `ledger.py`),
  más de veinte workflows en borrador y **ninguna interacción real demostrada de punta a punta**. El requisito obligatorio
  «interacción de verdad» sigue sin cerrarse.
- **El equipo no puede explicar lo que no ha escrito:** decenas de miles de líneas hechas por agentes en paralelo. Si un juez
  pregunta «¿cómo decide?», la respuesta tiene que caber en una frase y verse en la plataforma.
- Lo que SÍ vale y se queda: el recinto simulado que se mueve (es «el escenario que cambia»), el gemelo (ensayar y prever), la
  Sala (ver e intervenir), el ledger (memoria), el espejo de Telegram y los evals (prueba de fiabilidad).

## El diseño nuevo en una frase
**Un agente de HappyRobot recibe todo, decide la prioridad, reparte el trabajo, avisa, vigila su plan y lo rehace cuando algo
cambia; aprende lecciones de lo que pasó; una persona ve su razonamiento y manda en lo grave.** MANDO (este repo) es el mundo
que el agente observa, las herramientas que usa y la pantalla donde se le supervisa.

## Piezas (pocas)
| Pieza | Dónde vive | Qué hace |
|---|---|---|
| Entradas por canal | HappyRobot (`fa-entrada-tg` de Telegram; voz/Web call; email; SMS) | Normalizan y llaman al cerebro. Nada de lógica. |
| **`mando-cerebro`** (Workflow Function) | HappyRobot | Entiende → pide contexto → **razona** (¿nuevo o se fusiona?, prioridad y porqué, a quién se avisa y qué se le dice, qué recurso va y a quién se deja esperando, plan con supuestos y qué vigilar) → entrega la decisión → actúa → guarda el episodio. |
| Despacho | HappyRobot (`fa-despacho-tg` con botones; voz por oficio como escalada) | Pregunta a personas reales, recoge acepta / rechaza / silencio / ETA. |
| **`mando-reevalua`** | HappyRobot | Se dispara con CUALQUIER cambio (rechazo, silencio, dato nuevo, sensor, previsión, golpe del jurado): «¿sigue valiendo el plan?» → plan nuevo y reasignación. Es la adaptación. |
| **`mando-aprende`** | HappyRobot | Al cerrar incidentes y al final del día: compara decisión y resultado, propone lecciones con evidencia; una persona las aprueba; entran en el contexto la próxima vez. |
| Herramientas | este repo (`/hr/tools/*`) | `contexto`, `ensayar` (gemelo), `decidir` (aplica barandillas y ejecuta), `memoria/*`. |
| Barandillas | este repo (deterministas, a propósito) | Evacuar / parar / ayuda externa → SIEMPRE persona. Riesgo vital → se despacha ANTES de razonar. Solo destinos de la lista blanca. |
| Mundo | este repo (simulador + gemelo) | El recinto que se mueve; el jurado lo golpea. |
| Sala de control | este repo | Ver la situación, **leer el razonamiento del agente**, aprobar / vetar / corregir, aprobar lecciones. |
| Plan B y vara de medir | este repo (planificador de reglas) | Si la plataforma no contesta en N segundos, deciden las reglas. Mismo banco, tres brazos (lista fija · reglas · agente) con su N. |

## Cómo cubre el enunciado (esto manda SIEMPRE)
| Requisito / criterio | Cómo queda cubierto | Cómo se demuestra |
|---|---|---|
| Sistema agéntico (OBLIGATORIO) | El agente decide y actúa sin que nadie le diga el siguiente paso | Un aviso por Telegram desencadena solo: prioridad → reparto → avisos → seguimiento |
| Escenario que se mueve (OBLIGATORIO) | Recinto simulado + golpes del jurado + rechazos reales del staff | El jurado cierra una puerta desde su móvil |
| Respuesta de varios pasos (OBLIGATORIO) | Entender → contexto → decidir → avisar → esperar respuesta → reasignar → cerrar → aprender | La cronología del incidente en la Sala |
| Interacción de verdad (OBLIGATORIO) | Telegram real con botones; llamada de voz real a un móvil de la lista blanca; filas en Twin / ledger | Suena un móvil en la sala |
| Interfaz para la persona (OBLIGATORIO) | Sala: situación, razonamiento del agente, aprobar / vetar | Veto en directo y plan alternativo |
| Aprende (BONUS) | Episodios → lecciones con evidencia → aprobación humana → cambian la decisión siguiente | Mismo incidente, día 1 y día 2, con la lección aprobada entre medias |
| DECIDE · decisión sin todos los datos | El agente decide con confianza declarada y pregunta UNA cosa si falta algo vital | Aviso sin zona |
| DECIDE · prioridad | El agente ordena la cola con su porqué, contando con los medios que quedan | Tres avisos a la vez, dos equipos libres |
| DECIDE · adaptación | `mando-reevalua` ante cada cambio; plan con supuestos y «qué vigilar» | Rechazo + puerta cerrada → plan nuevo |
| ACTÚA · coordinación | Gente (staff por Telegram/voz), información (informante, organizador) y medios (recursos) a la vez | Panel de asignaciones vivo |
| ACTÚA · ejecución | Mensajes, llamadas, escrituras en Twin/ledger, webhooks | Pestaña Runs de HappyRobot |
| SUPERVISA · control | Razonamiento legible, barandillas, aprobar / vetar, regla de dos personas | Tarjeta de decisión |
| SUPERVISA · creatividad | El jurado ataca el mundo; el agente ensaya en un gemelo antes de decidir; enseña sus propios fallos (evals) | `/fiabilidad` si da tiempo |
| SUPERVISA · aprendizaje | Lecciones aprobadas por persona, reversibles, con su N | Pantalla de lecciones |

## Fases (con guillotinas)
- **F0 · hasta las 17:30 — la rebanada REAL.** Telegram → `fa-entrada-tg` → `mando-cerebro` → decisión (prioridad + reparto) →
  botones al staff → «Acudo» → se ve en la Sala → episodio guardado. Túnel abierto, workflows publicados en development.
  *Guillotina 18:00:* si el razonador dentro de la plataforma no va, el MISMO prompt corre en `cerebro_llm.py` (backend) y
  HappyRobot lo llama por webhook: sigue orquestando HappyRobot y sigue decidiendo un LLM.
- **F1 · 17:30–19:30 — adaptación.** `mando-reevalua` con rechazo, silencio, dato nuevo, golpe del jurado y previsión del gemelo.
  La Sala enseña el razonamiento («por qué», supuestos, qué vigila).
- **F2 · 19:30–21:00 — aprendizaje.** Episodios → `mando-aprende` → lecciones → aprobar en la Sala → cambian la decisión. Demo
  día 1 → día 2.
- **F3 · en paralelo, una persona — voz real.** Primera llamada a un móvil propio (ojo: SIP 403 con número de EE. UU.; plan B
  Web call con datos del móvil). Entradas de email y SMS apuntando al cerebro.
- **F4 · 21:00–23:00 — limpieza y medida.** PR de limpieza (abajo). Evals del agente con el cerebro local: tres brazos, N pequeño
  pero honesto. README, GUIA y COMO-DECIDE reescritos para el diseño nuevo.
- **F5 · 23:00–03:00 — vídeo, ensayo, entrega.** Congelación de código a las 23:00.

## Limpieza del repo (en una rama aparte, por PR, nada se borra sin acuerdo: se mueve a `archivo/`)
1. **Una interfaz:** Sala de control. `/centro`, `/clasico`, `/duelo`, `/curva`, `/caos` y `web/` → decidir con el equipo cuál
   vive; el resto a `archivo/`.
2. **Una memoria:** `ledger.py` (SQLite, de Aibo) + Twin en la plataforma. `db.py`/`historial_*` se fusionan o se archivan.
3. **Workflows:** lista corta y viva (entradas, cerebro, despacho, reevalúa, aprende, voz). Los borradores que no se usen, fuera
   del mapa.
4. **Documentos:** README (qué es), GUIA (cómo se usa), COMO-DECIDE (cómo razona el agente + barandillas), COBERTURA-RETO. Lo
   demás, a `docs/archivo/`.
5. **Generados fuera de git:** `motor/harness/out/2026*`, `_frozen`, `*.db`, `dist/`.
6. **Estructura objetivo:** `hr/` (workflows, prompts, contrato de herramientas) · `motor/` (mundo, gemelo, reglas-plan-B,
   herramientas, Sala) · `puente/` (Telegram) · `evals/` · `docs/`.

## Qué necesito del equipo
- Un dueño por pieza: Bruno = Telegram y `fa-*`; Aibo = ledger/memoria y llamada real; Talía y Firdaous = Sala (razonamiento y
  lecciones a la vista) y vídeo; Ana = cerebro, herramientas, reevalúa, aprende, evals y limpieza.
- ¿Twin está aprovisionado? ¿Hay API key de HappyRobot con rol de edición y túnel estable?
- Decidir hoy la interfaz única.
