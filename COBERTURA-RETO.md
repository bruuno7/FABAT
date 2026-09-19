# Cobertura del reto HappyRobot (HackSpain 2026)

Texto del enunciado: `analisis/ENUNCIADO-RETO.md`. Verificado contra el servidor vivo
`TELEGRAM_MODE=off MANDO_DB=off … python -m motor.server demo --case demo-1 --port 8851`
el 19-sep-2026: tres `reset` + `step n=25` idénticos (huella
`d578d9cba10879656e77479196daf3912e3c127799032f8b493f4ce8fd7a40cf`). Simulación N=3.

Leyenda: **CUBIERTO** / **PARCIAL** / **FALTA**. «Real» = mueve un sistema de fuera (llamada, Telegram, ticket). «Simulado» = recinto, tiempo o interlocutor ficticio.

---

## Las seis preguntas

| # | Enunciado (cita) | Cómo lo cubre MANDO | Demo 30 s | Test / eval | Estado |
|---|---|---|---|---|---|
| 1 | «Llegan cien mensajes y solo tres cambian algo» | Triaje `motor/mando/triage.py` (`ingest`, `MERGE_WINDOW=15`). Embudo en `/api/state` → `funnel`. Frases en `GET /api/explica` pregunta `informacion` y pantalla `/porque`. | Abrir `/porque`, iniciar, leer la cartela: avisos / fusionados / falsas. En t=25: 7 avisos, 6 cambiaron algo, 1 fusionado, 0 falsas. | `motor.server.test_explica.test_seis_preguntas_demo_1`; `funnel` en `app.py` `_funnel` | **CUBIERTO** · simulado (los avisos del caso) + real si llegan por Telegram/web |
| 2 | «El sistema tiene que decir por dónde se empieza ahora» | `motor/mando/priority.py` `compute` / `sort_key`. Cola descompuesta en `/api/explica` `prioridad.detalle.cola` (gravedad, plazo, densidad, confianza). | `/porque`: primera tarjeta «Qué va primero». En t=25 van tres paradas (M-003/004/005) a 10,0. | `test_explica` (producto de factores = prioridad del estado); `motor.mando.test_mando.TestPriority` | **CUBIERTO** · simulado |
| 3 | «A quién se llama, qué se le cuenta y en qué orden» | `hr_routing.workflow_slot` + `comms_happyrobot.send`. Telegram `fa-despacho-tg` (espejo). `/api/explica` `aviso`. Lo reservado no va por voz ni megafonía. | `/porque` cartela 3: cargo, canal, workflow. En t=25: 36 comunicaciones, 5 pendientes; 17 llamadas modo sim. | `test_explica`; `test_enrutado`; `test_espejo_telegram` | **PARCIAL** · en este arranque **simulado** (`presentation.voice=simulada`, workflows `configured: false`). Real si hay HR + lista blanca |
| 4 | «Mandarlas a un lado es dejar el otro esperando» | `planner.py` `_options` / `_recall`. `/api/explica` `recursos`: asignaciones, candidatos libres, `esperando[].por_que`. | `/porque` cartela 4. t=25: 3 asignados, 5 esperan (ambulancia offline; paradas piden persona para el 112). | `test_mando.test_six_fronts_five_resources_lowest_priority_waits_and_is_explained`; `test_explica` | **CUBIERTO** · simulado (recursos del recinto) |
| 5 | «La siguiente acción concreta y quién la hace» | Acciones AUTO vs APPROVE (`autonomy.gate`). `/api/explica` `accion` + tarjetas en `/centro` y `/sala`. | `/porque` cartela 5. t=25: megafonía del frente espera al Director; 7 aprobaciones pendientes. | `test_explica`; `test_sala.DecisionesTest` | **CUBIERTO** · simulado + persona real al pulsar Aprobar |
| 6 | «¿Se da cuenta el sistema, o sigue como si nada?» | `assumptions.holds`; log `assumption_broken`; plan `invalidated_by` / `supersedes`. `/api/explica` `plan`. | `/porque` cartela 6. t=25: supuesto roto en t=17 en M-002; sustituye P-015. Log: «Ambulancia interna sigue operativo» se rompe. | `test_server` (demo-gates rompe supuesto); `test_explica` | **CUBIERTO** · simulado |

---

## Las cuatro capacidades

| # | Enunciado (cita) | Cómo lo cubre MANDO | Demo 30 s | Test / eval | Estado |
|---|---|---|---|---|---|
| Enterarse | «recoge lo que va llegando… pantalla donde se vea en dos segundos» | Canales: `/api/report`, `/hr/events`, bot Telegram, chat `/asistente`, sensores del caso. Parser `HeuristicParser.parse`. Pantallas `/sala`, `/centro`, `/porque`. | Móvil en `/asistente` o aviso en `/api/report`; en `/porque` sube el contador de avisos. | `test_hardening` (ingesta); `test_explica` | **PARCIAL** · texto web **real**; sensores y aforo **simulados**; HappyRobot intake `configured: false` en este arranque |
| Priorizar | «qué se atiende primero y por qué… con los medios que quedan» | `priority.compute` + `waiting` / `why_waiting`. `/api/explica` desglosa pesos. | Cartela 2 + barras por factor en el detalle del incidente. | `test_explica.test_incidente_vivo_descompone_prioridad` | **CUBIERTO** · simulado |
| Coordinar | «Avisa… reparte tareas y sigue quién ha cogido qué» | Despacho voz/Telegram, `calls[]`, `telegram.asignaciones`, `fronts[].team`. | `/centro` o `/sala`: ACEPTA/RECHAZA. t=25: 17 llamadas modo `sim`. | `test_espejo_telegram`; `test_phase3` | **PARCIAL** · bucle Telegram **real** cuando el bot está on; aquí `telegram.status=off`. Voz **simulada** en este proceso |
| Adaptarse | «a mitad… rehacer el plan» | Supuesto roto → replan; golpes `POST /api/strike`; gemelo `rehearsal.py`; previsión `forecast.py`. | Tras el paso a t=25, cartela 6 muestra el plan tirado. Tecla de golpe del jurado en `/sala`. | `test_forecast.py`; `test_centro_integration`; `test_explica` | **CUBIERTO** · recinto **simulado**; la decisión de tirar el plan es **real** (reglas) |

---

## Los seis requisitos de la entrega

| # | Enunciado (cita) | Cómo lo cubre MANDO | Demo 30 s | Test / eval | Estado |
|---|---|---|---|---|---|
| Sistema agéntico | «Decide y actúa por su cuenta. Un chatbot que contesta preguntas no entra.» | Bucle `Mando.tick`: triaje → plan → AUTO ejecuta. No espera una pregunta para despachar una parada. | Play en `/centro`: salen despachos solos; lo grave se queda en la tarjeta. | `test_mando`; `test_explica` (despacho_no_espera) | **CUBIERTO** |
| Escenario que se mueve | «La situación cambia mientras el sistema corre» | `world.step` 1 min; eventos del caso; `POST /api/strike`; recursos que se caen (ambulancia offline en demo-1 t=8). | Iniciar demo-1: a los pocos minutos la ambulancia queda atrapada y el plan sanitario se tira. | `test_server` demo-1 signal; caso `c-d000001` | **CUBIERTO** · mundo **simulado** |
| Varios pasos | «Una cadena de acciones con un objetivo, no una acción suelta» | `Plan.steps` + supuestos. t=25: 15 planes, varios con `supersedes`. | `/centro` ficha: plan actual tachado / plan nuevo. `/porque` cartela 6. | `test_explica`; snapshot `plans` | **CUBIERTO** |
| Interacción de verdad | «Llama, escribe, crea tickets o mueve datos en un sistema real» | HappyRobot (voz, web call, email, SMS) y Telegram. En **este** proceso: `happyrobot.*.configured=false`, `calls.mode=sim`, Telegram off. | Con `.env` real: una web call al cargo. Aquí: 17 llamadas simuladas en t=25. | `test_connection`; `test_phase3`; doctor | **PARCIAL** · **simulado** en el arranque de cobertura; **real** solo con HR_API_KEY + lista blanca + túnel |
| Interfaz para la persona | «entender… ver qué está haciendo… intervenir» | `/sala`, `/centro`, `/porque`, `/asistente`, `POST /api/approve`. | Abrir `/porque` y `/centro`; pulsar Aprobar en una de las 7 tarjetas. | `test_explica.test_pagina_porque_y_enlaces`; `test_server.test_pages` | **CUBIERTO** · la Sala aún no pinta `/api/explica` (contrato escrito para el equipo) |
| Aprende (bonus) | «Revisa las llamadas y las decisiones… ajusta cómo actúa la próxima vez» | Lecciones y parámetros con aprobación (`memory.py`, `/memoria`). No se entrena un modelo. | `/memoria`: candidata + Aprobar. | `motor.mando` tests de lecciones; harness de memoria en `MVP.md` | **PARCIAL** · bonus; efecto medido en simulación, no en este minuto de demo |

---

## Los ocho criterios de evaluación

Tres bloques de igual peso: cómo decide · cómo actúa · cómo se supervisa.

| Criterio | Enunciado (cita) | Cómo lo cubre MANDO | Demo 30 s | Test / eval | Estado |
|---|---|---|---|---|---|
| Decisión | «¿Decide algo sensato sin tener todos los datos?» | Parser conservador si el tipo no se reconoce; riesgo vital despacha sin zona confirmada; hold si confianza < 0,5. | demo-1: parada por WhatsApp con sitio vago → equipo sale, se pregunta en paralelo. | `planner._ask_first`; `test_mando` | **CUBIERTO** · simulado |
| Prioridad | «¿Sabe qué va primero cuando todo parece urgente?» | Fórmula pública + desempate. `/porque` barras. | Tres paradas a 10,0 (suelo vital) en t=25. | `test_explica`; `priority.py` | **CUBIERTO** |
| Adaptación | «¿Hace algo distinto cuando la situación cambia?» | Replan al romperse un supuesto; recall; golpe del jurado. | Ver P-002 tirado cuando seguridad no contesta; ambulancia offline tira P-004. | log `assumption_broken` en 8851 | **CUBIERTO** |
| Coordinación | «¿Lleva a la vez a la gente, la información y los medios?» | Frentes, llamadas, Telegram, recursos. | `/centro` plano + frentes + servicios. | `test_centro_integration`; `test_espejo_telegram` | **PARCIAL** · Telegram apagado y voz simulada en este proceso |
| Ejecución | «¿Ejecuta acciones fuera del sistema o solo las propone?» | `comms.send` → hook/runs o sim. t=25: 17 llamadas **sim**. | Con plataforma: descolgar web call. Aquí se ve el estado «llamando» simulado. | `test_phase3`; `presentation.channels` | **PARCIAL** · **simulado** ahora; el cable real existe |
| Control | «¿Se entiende qué está haciendo y se puede intervenir?» | `/porque`, tarjetas Aprobar/Vetar, doble firma opcional, enmascarado. | Abrir `/porque`; vetar megafonía. | `test_explica` (404, reservado, sin teléfonos); `test_auditoria_dinamica` | **CUBIERTO** · falta el botón en `sala.js` (no se toca: lo pinta el equipo) |
| Creatividad | «¿El escenario y la forma de gestionarlo tienen algo propio?» | Gemelo que ensaya el desvío; supuestos escritos; adversario sobre el mundo (no sobre la frase); capa de explicación sin LLM. | `/porque` + ensayo de puerta; no es un mapa con chinchetas fijas. | `rehearsal.py`; `/duelo` | **CUBIERTO** · recinto ficticio |
| Aprendizaje | «Puntos extra si aprende de las ejecuciones anteriores» | Manual de lecciones + parámetros (`contact_order`, ventana de duplicados) con sí humano. | `/memoria` si hay candidata. | harness memoria (simulación) | **PARCIAL** · bonus; no mejora la puntuación global (lo dice el propio MVP) |

---

## Huecos

Ordenados por cuánto puntúan (bloques de evaluación de igual peso; el bonus vale menos).

1. **Ejecución / coordinación reales** — PARCIAL. Este proceso corre en `sim`. Sin `HR_API_KEY`, túnel (`MANDO_PUBLIC_URL`) y lista blanca no hay llamada ni Telegram de verdad. Es el bloque «cómo actúa».
2. **Aprendizaje** — PARCIAL (bonus). Hay memoria con aprobación; no hay evidencia de que suba la nota global.
3. **Sala de control sin «¿Por qué?»** — PARCIAL en control. La API y `/porque` existen; `static/sala*` no se ha tocado (equipo). Contrato en `motor/server/CONTRATO-INTERFAZ.md`.
4. **Intake HappyRobot apagado** — PARCIAL en «enterarse». El texto se entiende en local. Con `HR_HOOK_INTAKE` el entendimiento pasa por la plataforma.
5. **Previsiones vacías en t=25 de demo-1** — PARCIAL visual. El código (`forecast.py`, `test_forecast.py`) está; en este minuto `forecasts=[]` (varios umbrales ya cruzados; el worker publica cruces *futuros*).
6. **Sensores y recinto** — simulados siempre (el enunciado lo permite; hay que decirlo).

Detalle de cierre y tiempos: `analisis/COBERTURA-HUECOS.md` (privado).
