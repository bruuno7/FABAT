# Banco de pruebas de Mando — informe

Generado por `python3 -m motor.harness report`. Huellas del código medido: {'compare': '3b6e1c0ecdf4', 'learn': '3b6e1c0ecdf4', 'headline': '3b6e1c0ecdf4', 'load': '3b6e1c0ecdf4', 'day2': 'cc17622e1b13'}. Huella en disco al generar: cc17622e1b13.
Toda cifra lleva su N. Es simulación, no dato de campo. Todos los brazos de cada tabla corren EXACTAMENTE los mismos casos y semillas (se comprueba y se aborta si no). Una ejecución en la que revienta el agente o el puntuador no sale del N: cuenta con score 0 y aparece en «Errores».
`score`: fórmula completa (`metrics.py`, fijada antes de medir). `solo-mundo` (`world_score`): la misma sin nada que dependa de `expected.must`/`must_not` del generador de casos.

**AVISO: las secciones de este informe se midieron con huellas de código distintas; no mezclar cifras entre secciones.**

## Titular reproducible (`python3 -m motor.harness headline`, huella 3b6e1c0ecdf4)

| Conjunto | N | Mando | Lista fija | Diferencia pareada (score) | IC 95 % | Diferencia pareada (solo-mundo) | IC 95 % | Críticos fallidos Mando / lista | Errores |
|---|---|---|---|---|---|---|---|---|---|
| train, sin adversario | 1000 | 81,36 | 71,76 | **9,60** | [8,42 – 10,78] | 6,80 | [5,69 – 7,92] | 244 de 2136 / 387 de 2144 | 0 / 0 |
| heldout, sin adversario | 1000 | 78,71 | 69,82 | **8,89** | [7,71 – 10,12] | 6,91 | [5,78 – 8,12] | 309 de 2332 / 438 de 2355 | 0 / 0 |
| train, con Caos (3 golpes) | 300 | 47,64 | 32,13 | **15,50** | [12,95 – 18,20] | 13,19 | [10,71 – 15,79] | 488 de 1083 / 587 de 958 | 0 / 0 |

## Comparación · Train, sin adversario (N=1000, mismas semillas, huella 3b6e1c0ecdf4)

| Agente | N | Errores | Score | IC 95 % | Solo-mundo | IC 95 % | Críticos fallidos | Inseguras | 1.ª atención (min) | Min·zona > 5/m² | Desperdiciados | `must` |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Lista fija | 1000 | 0 | 71,76 | [70,52 – 72,96] | 77,77 | [76,55 – 78,98] | 387 de 2144 (18,1 %) | 0 | 2,21 | 10,40 | 2,88 | 28,4 % |
| Lista fija + (fusiona y ordena) | 1000 | 0 | 72,81 | [71,59 – 74,02] | 78,61 | [77,45 – 79,80] | 370 de 2145 (17,2 %) | 0 | 2,08 | 10,40 | 2,38 | 30,2 % |
| Mando (sin lecciones) | 1000 | 0 | 81,36 | [80,31 – 82,52] | 84,57 | [83,58 – 85,67] | 244 de 2136 (11,4 %) | 0 | 2,27 | 9,89 | 0,86 | 67,5 % |
| Mando (manual aprendido) | 1000 | 0 | 81,88 | [80,82 – 82,99] | 84,86 | [83,87 – 85,94] | 242 de 2135 (11,3 %) | 0 | 2,27 | 9,82 | 0,72 | 70,4 % |

- Mando (sin lecciones) − Lista fija, pareado: **9,60** IC 95 % [8,42 – 10,78]; solo-mundo 6,80 [5,69 – 7,92] (N=1000; mejor en 767, peor en 230).
- Mando (sin lecciones) − Lista fija + (fusiona y ordena), pareado: **8,56** IC 95 % [7,38 – 9,77]; solo-mundo 5,96 [4,84 – 7,05] (N=1000; mejor en 747, peor en 247).
- Mando (manual aprendido) − Mando (sin lecciones), pareado: **0,52** IC 95 % [0,36 – 0,69]; solo-mundo 0,29 [0,15 – 0,45] (N=1000; mejor en 235, peor en 24).
- Mando (manual aprendido) − Lista fija, pareado: **10,12** IC 95 % [8,96 – 11,29]; solo-mundo 7,09 [6,00 – 8,21] (N=1000; mejor en 783, peor en 214).
- Lista fija + (fusiona y ordena) − Lista fija, pareado: **1,04** IC 95 % [0,74 – 1,37]; solo-mundo 0,84 [0,55 – 1,17] (N=1000; mejor en 295, peor en 65).

## Comparación · HELDOUT (nunca visto), sin adversario (N=1000, mismas semillas, huella 3b6e1c0ecdf4)

| Agente | N | Errores | Score | IC 95 % | Solo-mundo | IC 95 % | Críticos fallidos | Inseguras | 1.ª atención (min) | Min·zona > 5/m² | Desperdiciados | `must` |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Lista fija | 1000 | 0 | 69,82 | [68,49 – 71,16] | 76,02 | [74,74 – 77,33] | 438 de 2355 (18,6 %) | 0 | 1,94 | 11,08 | 3,02 | 26,1 % |
| Lista fija + (fusiona y ordena) | 1000 | 0 | 70,61 | [69,33 – 71,88] | 76,62 | [75,39 – 77,85] | 429 de 2357 (18,2 %) | 0 | 1,87 | 11,08 | 2,48 | 27,5 % |
| Mando (sin lecciones) | 1000 | 0 | 78,71 | [77,43 – 80,00] | 82,93 | [81,73 – 84,10] | 309 de 2332 (13,2 %) | 0 | 2,36 | 10,26 | 0,83 | 59,8 % |
| Mando (manual aprendido) | 1000 | 0 | 78,96 | [77,69 – 80,27] | 83,02 | [81,82 – 84,22] | 310 de 2334 (13,3 %) | 0 | 2,36 | 10,20 | 0,74 | 62,0 % |

- Mando (sin lecciones) − Lista fija, pareado: **8,89** IC 95 % [7,71 – 10,12]; solo-mundo 6,91 [5,78 – 8,12] (N=1000; mejor en 736, peor en 262).
- Mando (sin lecciones) − Lista fija + (fusiona y ordena), pareado: **8,10** IC 95 % [6,89 – 9,34]; solo-mundo 6,31 [5,18 – 7,51] (N=1000; mejor en 724, peor en 272).
- Mando (manual aprendido) − Mando (sin lecciones), pareado: **0,24** IC 95 % [0,10 – 0,39]; solo-mundo 0,09 [-0,04 – 0,23] (N=1000; mejor en 186, peor en 38).
- Mando (manual aprendido) − Lista fija, pareado: **9,14** IC 95 % [7,95 – 10,37]; solo-mundo 7,00 [5,86 – 8,21] (N=1000; mejor en 740, peor en 257).
- Lista fija + (fusiona y ordena) − Lista fija, pareado: **0,79** IC 95 % [0,44 – 1,17]; solo-mundo 0,60 [0,26 – 0,96] (N=1000; mejor en 287, peor en 72).

## Comparación · Train, con adversario al azar (N=300, mismas semillas, presupuesto 3 golpes, huella 3b6e1c0ecdf4)

| Agente | N | Errores | Score | IC 95 % | Solo-mundo | IC 95 % | Críticos fallidos | Inseguras | 1.ª atención (min) | Min·zona > 5/m² | Desperdiciados | `must` |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Lista fija | 300 | 0 | 64,80 | [62,38 – 67,36] | 70,82 | [68,53 – 73,33] | 174 de 844 (20,6 %) | 0 | 2,51 | 12,82 | 3,76 | 27,7 % |
| Lista fija + (fusiona y ordena) | 300 | 0 | 64,88 | [62,43 – 67,43] | 70,72 | [68,33 – 73,18] | 177 de 833 (21,2 %) | 0 | 2,35 | 13,18 | 3,12 | 29,4 % |
| Mando (sin lecciones) | 300 | 0 | 77,83 | [75,76 – 79,91] | 81,33 | [79,38 – 83,27] | 99 de 791 (12,5 %) | 0 | 2,41 | 10,48 | 1,02 | 65,9 % |
| Mando (manual aprendido) | 300 | 0 | 78,64 | [76,53 – 80,85] | 81,95 | [79,95 – 84,04] | 97 de 798 (12,2 %) | 0 | 2,42 | 10,21 | 0,75 | 68,6 % |

- Mando (sin lecciones) − Lista fija, pareado: **13,03** IC 95 % [10,66 – 15,35]; solo-mundo 10,51 [8,21 – 12,80] (N=300; mejor en 232, peor en 68).
- Mando (sin lecciones) − Lista fija + (fusiona y ordena), pareado: **12,95** IC 95 % [10,61 – 15,30]; solo-mundo 10,61 [8,35 – 12,84] (N=300; mejor en 236, peor en 62).
- Mando (manual aprendido) − Mando (sin lecciones), pareado: **0,81** IC 95 % [0,27 – 1,40]; solo-mundo 0,62 [0,09 – 1,20] (N=300; mejor en 80, peor en 11).
- Mando (manual aprendido) − Lista fija, pareado: **13,84** IC 95 % [11,48 – 16,22]; solo-mundo 11,13 [8,86 – 13,45] (N=300; mejor en 236, peor en 64).
- Lista fija + (fusiona y ordena) − Lista fija, pareado: **0,07** IC 95 % [-0,85 – 0,97]; solo-mundo -0,10 [-1,01 – 0,79] (N=300; mejor en 93, peor en 55).

## Comparación · Train, con adversario inteligente (Caos) (N=300, mismas semillas, presupuesto 3 golpes, huella 3b6e1c0ecdf4)

| Agente | N | Errores | Score | IC 95 % | Solo-mundo | IC 95 % | Críticos fallidos | Inseguras | 1.ª atención (min) | Min·zona > 5/m² | Desperdiciados | `must` |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Lista fija | 300 | 0 | 32,13 | [29,57 – 34,56] | 38,22 | [35,82 – 40,65] | 587 de 958 (61,3 %) | 0 | 2,19 | 22,39 | 4,46 | 24,8 % |
| Lista fija + (fusiona y ordena) | 300 | 0 | 30,49 | [28,08 – 33,03] | 36,34 | [33,98 – 38,81] | 625 de 938 (66,6 %) | 0 | 2,00 | 22,80 | 3,75 | 26,7 % |
| Mando (sin lecciones) | 300 | 0 | 47,64 | [44,49 – 50,92] | 51,41 | [48,38 – 54,60] | 488 de 1083 (45,1 %) | 0 | 2,18 | 10,95 | 1,15 | 62,6 % |
| Mando (manual aprendido) | 300 | 0 | 48,21 | [45,03 – 51,48] | 51,79 | [48,78 – 54,98] | 488 de 1078 (45,3 %) | 0 | 2,18 | 10,92 | 0,98 | 65,2 % |

- Mando (sin lecciones) − Lista fija, pareado: **15,50** IC 95 % [12,95 – 18,20]; solo-mundo 13,19 [10,71 – 15,79] (N=300; mejor en 226, peor en 71).
- Mando (sin lecciones) − Lista fija + (fusiona y ordena), pareado: **17,15** IC 95 % [14,38 – 19,88]; solo-mundo 15,07 [12,40 – 17,70] (N=300; mejor en 224, peor en 72).
- Mando (manual aprendido) − Mando (sin lecciones), pareado: **0,57** IC 95 % [0,07 – 1,12]; solo-mundo 0,38 [-0,12 – 0,91] (N=300; mejor en 79, peor en 15).
- Mando (manual aprendido) − Lista fija, pareado: **16,07** IC 95 % [13,46 – 18,79]; solo-mundo 13,57 [11,11 – 16,20] (N=300; mejor en 232, peor en 65).
- Lista fija + (fusiona y ordena) − Lista fija, pareado: **-1,65** IC 95 % [-2,74 – -0,60]; solo-mundo -1,88 [-2,99 – -0,81] (N=300; mejor en 100, peor en 87).

## Por familia de crisis (score medio, train sin adversario; N entre paréntesis)

| Familia | Lista fija | Lista fija + (fusiona y ordena) | Mando (sin lecciones) | Mando (manual aprendido) |
|---|---|---|---|---|
| aggression | 74,46 (312) | 75,12 (312) | 81,39 (312) | 82,31 (312) |
| crowd | 70,81 (370) | 71,98 (370) | 77,72 (370) | 78,45 (370) |
| external | 74,83 (167) | 75,48 (167) | 82,67 (167) | 83,79 (167) |
| info | 70,84 (750) | 72,05 (750) | 81,18 (750) | 81,68 (750) |
| infra | 68,78 (394) | 70,01 (394) | 78,93 (394) | 79,29 (394) |
| medical | 68,49 (355) | 69,58 (355) | 81,69 (355) | 81,94 (355) |
| resource | 70,76 (727) | 71,86 (727) | 80,17 (727) | 80,76 (727) |
| supply | 69,41 (210) | 69,67 (210) | 81,26 (210) | 81,56 (210) |
| weather | 61,85 (105) | 62,64 (105) | 75,42 (105) | 75,83 (105) |

## Los fallos más frecuentes de Mando (sin lecciones)

| # | Patrón | Tipo (según Mando) | Detalle | Casos |
|---|---|---|---|---|
| 1 | must | payment_down | broadcast for # | 56 de 1000 (p. ej. c-t000001, c-t000015, c-t000018) |
| 2 | critical_failed | crush_risk | ["security"] | 43 de 1000 (p. ej. c-t000006, c-t000060, c-t000063) |
| 3 | must | crush_risk | dispatch security to # within N min | 43 de 1000 (p. ej. c-t000006, c-t000013, c-t000015) |
| 4 | must | bottleneck | dispatch security to # within N min | 42 de 1000 (p. ej. c-t000016, c-t000024, c-t000032) |
| 5 | must | structure_risk | broadcast for # | 40 de 1000 (p. ej. c-t000002, c-t000039, c-t000045) |
| 6 | critical_failed | structure_risk | ["security", "tech"] | 37 de 1000 (p. ej. c-t000006, c-t000045, c-t000049) |
| 7 | must | vehicle_breakdown | request_external ambulance for # with approval | 36 de 1000 (p. ej. c-t000013, c-t000018, c-t000074) |
| 8 | must | vehicle_breakdown | notify medical_lead about # | 36 de 1000 (p. ej. c-t000013, c-t000018, c-t000074) |
| 9 | must | road_access_blocked | request_external police for # with approval | 33 de 1000 (p. ej. c-t000016, c-t000032, c-t000144) |
| 10 | must | road_access_blocked | notify medical_lead about # | 33 de 1000 (p. ej. c-t000016, c-t000032, c-t000144) |

## Aprendizaje (train N=3000, heldout N=1000, huella 3b6e1c0ecdf4; heldout nunca se usa para aprender)

Dos pistas. **«mundo»**: solo lecciones que salen de resultados del mundo o de vetos de la persona, validadas con `solo-mundo`. **«todo»**: además, lecciones que recuperan reglas `must` del generador («notify X»): eso es AJUSTE AL CORRECTOR y se enseña aparte. Una lección entra solo si el IC 99 % de la diferencia pareada en validación excluye el 0.

### Pista «mundo» (valida con `world_score`)

| Ronda | Lecciones | Train score | Train solo-mundo | Heldout score | Heldout solo-mundo | Heldout − ronda 0, pareado (solo-mundo) | IC 95 % | Críticos fallidos train / heldout | Errores |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 0 | 80,54 | 83,78 | 78,71 | 82,93 | 0,00 | [0,00 – 0,00] | 760 de 6521 / 309 de 2332 | 0+0 |
| 1 | 3 | 80,83 | 84,08 | 79,00 | 83,22 | 0,29 | [0,17 – 0,43] | 759 de 6519 / 306 de 2328 | 0+0 |

- train, `world_score`, última ronda − ronda 0 (pareado, N=3000): 0,30 IC 95 % [0,22 – 0,39] → **hay evidencia de mejora**.
- train, `score`, última ronda − ronda 0 (pareado, N=3000): 0,29 IC 95 % [0,21 – 0,38] → **hay evidencia de mejora**.
- heldout, `world_score`, última ronda − ronda 0 (pareado, N=1000): 0,29 IC 95 % [0,17 – 0,43] → **hay evidencia de mejora**.
- heldout, `score`, última ronda − ronda 0 (pareado, N=1000): 0,29 IC 95 % [0,17 – 0,44] → **hay evidencia de mejora**.
- Intervalos NO pareados de heldout (solo-mundo): ronda 0 [81,73 – 84,10], última [82,05 – 84,38] → SE SOLAPAN.

| Id | Origen | Lección | Evidencia (N casos) | Validación |
|---|---|---|---|---|
| R1-006 | operator | el operador vetó «set_zone» en «structure_risk» 79 veces: no se vuelve a proponer | 79 | mejora la validación +0.12 en world_score, IC 99 % pareado [+0.00, +0.33] (N=400; 11 casos mejor, 7 peor) sin empeorar críticos ni seguridad |
| R1-007 | operator | el operador vetó «stop_show» en «bottleneck» 75 veces: no se vuelve a proponer | 75 | mejora la validación +0.21 en world_score, IC 99 % pareado [+0.06, +0.38] (N=400; 16 casos mejor, 3 peor) sin empeorar críticos ni seguridad |
| R1-040 | operator | el operador vetó «stop_show» en «heavy_rain_flooding» 14 veces: no se vuelve a proponer | 14 | mejora la validación +2.01 en world_score, IC 99 % pareado [+0.91, +3.40] (N=33; 18 casos mejor, 1 peor) sin empeorar críticos ni seguridad |

Aceptadas 3, rechazadas 77. Con decenas de candidatas por ronda, incluso con IC del 99 % cabe alguna aceptación por azar.

### Pista «todo» (valida con `score`)

| Ronda | Lecciones | Train score | Train solo-mundo | Heldout score | Heldout solo-mundo | Heldout − ronda 0, pareado (solo-mundo) | IC 95 % | Críticos fallidos train / heldout | Errores |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 0 | 80,54 | 83,78 | 78,71 | 82,93 | 0,00 | [0,00 – 0,00] | 760 de 6521 / 309 de 2332 | 0+0 |
| 1 | 8 | 81,03 | 84,05 | 78,96 | 83,02 | 0,09 | [-0,04 – 0,23] | 757 de 6521 / 310 de 2334 | 0+0 |

- train, `world_score`, última ronda − ronda 0 (pareado, N=3000): 0,27 IC 95 % [0,20 – 0,36] → **hay evidencia de mejora**.
- train, `score`, última ronda − ronda 0 (pareado, N=3000): 0,49 IC 95 % [0,41 – 0,58] → **hay evidencia de mejora**.
- heldout, `world_score`, última ronda − ronda 0 (pareado, N=1000): 0,09 IC 95 % [-0,04 – 0,23] → **NO HAY EVIDENCIA DE APRENDIZAJE (el IC incluye el 0)**.
- heldout, `score`, última ronda − ronda 0 (pareado, N=1000): 0,24 IC 95 % [0,10 – 0,39] → **hay evidencia de mejora**.
- Intervalos NO pareados de heldout (solo-mundo): ronda 0 [81,73 – 84,10], última [81,82 – 84,22] → SE SOLAPAN.

| Id | Origen | Lección | Evidencia (N casos) | Validación |
|---|---|---|---|---|
| R1-007 | grader (ajuste al corrector) | en «payment_down» faltó el aviso por megafonía en 78 casos: se avisa antes de planificar | 78 | mejora la validación +0.93 en score, IC 99 % pareado [+0.81, +1.06] (N=97; 86 casos mejor, 0 peor) sin empeorar críticos ni seguridad |
| R1-008 | operator | el operador vetó «stop_show» en «bottleneck» 75 veces: no se vuelve a proponer | 75 | mejora la validación +0.22 en score, IC 99 % pareado [+0.07, +0.40] (N=400; 16 casos mejor, 3 peor) sin empeorar críticos ni seguridad |
| R1-013 | grader (ajuste al corrector) | en «structure_risk» faltó el aviso por megafonía en 58 casos: se avisa antes de planificar | 58 | mejora la validación +0.16 en score, IC 99 % pareado [+0.03, +0.44] (N=400; 25 casos mejor, 6 peor) sin empeorar críticos ni seguridad |
| R1-018 | grader (ajuste al corrector) | en «road_access_blocked» no se avisó a medical_lead en 46 casos: se le avisa siempre | 46 | mejora la validación +0.69 en score, IC 99 % pareado [+0.33, +1.50] (N=143; 46 casos mejor, 0 peor) sin empeorar críticos ni seguridad |
| R1-021 | grader (ajuste al corrector) | en «harassment_group» no se avisó a violet_point en 44 casos: se le avisa siempre | 44 | mejora la validación +0.78 en score, IC 99 % pareado [+0.04, +1.91] (N=80; 28 casos mejor, 4 peor) sin empeorar críticos ni seguridad |
| R1-030 | grader (ajuste al corrector) | en «transport_cut» faltó desviar exit_transport → gate_a en 33 casos | 33 | mejora la validación +0.17 en score, IC 99 % pareado [+0.08, +0.27] (N=135; 23 casos mejor, 0 peor) sin empeorar críticos ni seguridad |
| R1-037 | grader (ajuste al corrector) | en «medical_post_saturated» faltó desviar medical_2 → medical_1 en 28 casos | 28 | mejora la validación +0.14 en score, IC 99 % pareado [+0.07, +0.21] (N=153; 23 casos mejor, 0 peor) sin empeorar críticos ni seguridad |
| R1-040 | grader (ajuste al corrector) | en «stage_power_failure» faltó el aviso por megafonía en 27 casos: se avisa antes de planificar | 27 | mejora la validación +0.21 en score, IC 99 % pareado [+0.12, +0.32] (N=178; 31 casos mejor, 0 peor) sin empeorar críticos ni seguridad |

Aceptadas 8, rechazadas 72. Con decenas de candidatas por ronda, incluso con IC del 99 % cabe alguna aceptación por azar.

Referencia: lista fija 70,70 (train) y 69,82 (heldout); lista fija + 71,76 y 70,61.

## Regresión

6 casos bloqueados (fallaban sin lecciones y el manual aprendido los arregla). `python3 -m motor.harness regress` los re-ejecuta y falla si alguno vuelve a romperse. Estado: todos pasan.

## Degradación con la carga (N=1200, huella 3b6e1c0ecdf4)

Mando ya falla críticos en el nivel más bajo medido (1 frentes); la lista fija ya falla críticos en el nivel más bajo medido (1 frentes) (N=1200, huella 3b6e1c0ecdf4).

### Lista fija

| Frentes | Imprevisto | N | Errores | Críticos fallidos | Solo-mundo | IC 95 % | 1.ª atención (min) | Deja esperando a quien toca |
|---|---|---|---|---|---|---|---|---|
| 1 | todos | 180 | 0 | 74 de 342 | 78,38 | [75,74 – 81,17] | 1,92 | — (N=0) |
| 1 | sin imprevisto | 180 | 0 | 74 de 342 | 78,38 | [75,74 – 81,17] | 1,92 | — (N=0) |
| 2 | todos | 212 | 0 | 81 de 508 | 78,38 | [75,94 – 81,35] | 2,08 | 0,73 (N=79) |
| 2 | sin imprevisto | 212 | 0 | 81 de 508 | 78,38 | [75,94 – 81,35] | 2,08 | 0,73 (N=79) |
| 3 | todos | 126 | 0 | 44 de 270 | 77,05 | [73,79 – 80,12] | 2,47 | 0,60 (N=87) |
| 3 | sin imprevisto | 126 | 0 | 44 de 270 | 77,05 | [73,79 – 80,12] | 2,47 | 0,60 (N=87) |
| 4 | todos | 82 | 0 | 34 de 175 | 75,06 | [70,81 – 79,09] | 2,29 | 0,56 (N=77) |
| 4 | sin imprevisto | 82 | 0 | 34 de 175 | 75,06 | [70,81 – 79,09] | 2,29 | 0,56 (N=77) |
| 5 | todos | 150 | 0 | 115 de 514 | 63,78 | [60,01 – 67,43] | 2,18 | 0,59 (N=148) |
| 5 | sin imprevisto | 75 | 0 | 54 de 247 | 64,23 | [59,02 – 68,83] | 2,25 | 0,59 (N=74) |
| 5 | con imprevisto | 75 | 0 | 61 de 267 | 63,34 | [58,10 – 68,48] | 2,11 | 0,59 (N=74) |
| 6 | todos | 150 | 0 | 125 de 539 | 59,12 | [55,13 – 62,90] | 2,31 | 0,57 (N=150) |
| 6 | sin imprevisto | 75 | 0 | 53 de 245 | 62,27 | [55,81 – 68,24] | 2,32 | 0,56 (N=75) |
| 6 | con imprevisto | 75 | 0 | 72 de 294 | 55,98 | [49,22 – 61,47] | 2,31 | 0,59 (N=75) |
| 7 | todos | 150 | 0 | 160 de 594 | 53,63 | [49,73 – 57,51] | 2,58 | 0,52 (N=150) |
| 7 | sin imprevisto | 75 | 0 | 88 de 288 | 51,33 | [45,21 – 57,47] | 2,56 | 0,50 (N=75) |
| 7 | con imprevisto | 75 | 0 | 72 de 306 | 55,93 | [50,06 – 61,92] | 2,59 | 0,54 (N=75) |
| 8 | todos | 150 | 0 | 223 de 691 | 46,52 | [41,62 – 50,81] | 2,53 | 0,56 (N=150) |
| 8 | sin imprevisto | 75 | 0 | 102 de 315 | 47,51 | [40,55 – 54,41] | 2,51 | 0,57 (N=75) |
| 8 | con imprevisto | 75 | 0 | 121 de 376 | 45,53 | [39,54 – 51,14] | 2,56 | 0,54 (N=75) |

### Lista fija + (fusiona y ordena)

| Frentes | Imprevisto | N | Errores | Críticos fallidos | Solo-mundo | IC 95 % | 1.ª atención (min) | Deja esperando a quien toca |
|---|---|---|---|---|---|---|---|---|
| 1 | todos | 180 | 0 | 73 de 343 | 79,28 | [76,71 – 81,92] | 1,92 | — (N=0) |
| 1 | sin imprevisto | 180 | 0 | 73 de 343 | 79,28 | [76,71 – 81,92] | 1,92 | — (N=0) |
| 2 | todos | 212 | 0 | 77 de 508 | 79,14 | [76,81 – 81,98] | 1,94 | 0,71 (N=79) |
| 2 | sin imprevisto | 212 | 0 | 77 de 508 | 79,14 | [76,81 – 81,98] | 1,94 | 0,71 (N=79) |
| 3 | todos | 126 | 0 | 40 de 271 | 78,12 | [74,98 – 81,24] | 2,16 | 0,60 (N=87) |
| 3 | sin imprevisto | 126 | 0 | 40 de 271 | 78,12 | [74,98 – 81,24] | 2,16 | 0,60 (N=87) |
| 4 | todos | 82 | 0 | 33 de 175 | 75,51 | [71,21 – 79,41] | 2,15 | 0,58 (N=77) |
| 4 | sin imprevisto | 82 | 0 | 33 de 175 | 75,51 | [71,21 – 79,41] | 2,15 | 0,58 (N=77) |
| 5 | todos | 150 | 0 | 112 de 513 | 64,16 | [60,96 – 67,64] | 2,02 | 0,60 (N=148) |
| 5 | sin imprevisto | 75 | 0 | 55 de 247 | 63,68 | [58,88 – 68,00] | 2,06 | 0,60 (N=74) |
| 5 | con imprevisto | 75 | 0 | 57 de 266 | 64,63 | [59,41 – 69,08] | 1,99 | 0,60 (N=74) |
| 6 | todos | 150 | 0 | 115 de 539 | 61,24 | [57,30 – 65,06] | 2,07 | 0,59 (N=150) |
| 6 | sin imprevisto | 75 | 0 | 51 de 245 | 63,39 | [57,15 – 68,99] | 1,98 | 0,59 (N=75) |
| 6 | con imprevisto | 75 | 0 | 64 de 294 | 59,09 | [53,34 – 64,80] | 2,16 | 0,59 (N=75) |
| 7 | todos | 150 | 0 | 145 de 594 | 55,71 | [51,45 – 59,82] | 2,36 | 0,54 (N=150) |
| 7 | sin imprevisto | 75 | 0 | 79 de 288 | 54,16 | [47,09 – 60,48] | 2,37 | 0,53 (N=75) |
| 7 | con imprevisto | 75 | 0 | 66 de 306 | 57,25 | [51,66 – 63,05] | 2,36 | 0,56 (N=75) |
| 8 | todos | 150 | 0 | 198 de 691 | 48,59 | [43,96 – 53,12] | 2,32 | 0,57 (N=150) |
| 8 | sin imprevisto | 75 | 0 | 90 de 315 | 50,26 | [44,26 – 56,47] | 2,34 | 0,58 (N=75) |
| 8 | con imprevisto | 75 | 0 | 108 de 376 | 46,92 | [40,72 – 52,93] | 2,31 | 0,56 (N=75) |

### Mando (sin lecciones)

| Frentes | Imprevisto | N | Errores | Críticos fallidos | Solo-mundo | IC 95 % | 1.ª atención (min) | Deja esperando a quien toca |
|---|---|---|---|---|---|---|---|---|
| 1 | todos | 180 | 0 | 41 de 343 | 87,31 | [84,62 – 89,73] | 1,92 | — (N=0) |
| 1 | sin imprevisto | 180 | 0 | 41 de 343 | 87,31 | [84,62 – 89,73] | 1,92 | — (N=0) |
| 2 | todos | 212 | 0 | 60 de 508 | 83,63 | [81,58 – 86,28] | 2,17 | 0,61 (N=79) |
| 2 | sin imprevisto | 212 | 0 | 60 de 508 | 83,63 | [81,58 – 86,28] | 2,17 | 0,61 (N=79) |
| 3 | todos | 126 | 0 | 36 de 268 | 80,60 | [77,56 – 83,79] | 2,49 | 0,74 (N=87) |
| 3 | sin imprevisto | 126 | 0 | 36 de 268 | 80,60 | [77,56 – 83,79] | 2,49 | 0,74 (N=87) |
| 4 | todos | 82 | 0 | 19 de 175 | 81,12 | [76,91 – 84,83] | 2,63 | 0,57 (N=77) |
| 4 | sin imprevisto | 82 | 0 | 19 de 175 | 81,12 | [76,91 – 84,83] | 2,63 | 0,57 (N=77) |
| 5 | todos | 150 | 0 | 96 de 518 | 69,99 | [66,77 – 73,09] | 2,58 | 0,50 (N=148) |
| 5 | sin imprevisto | 75 | 0 | 43 de 247 | 70,57 | [66,05 – 74,91] | 2,52 | 0,50 (N=74) |
| 5 | con imprevisto | 75 | 0 | 53 de 271 | 69,41 | [64,34 – 74,64] | 2,65 | 0,51 (N=74) |
| 6 | todos | 150 | 0 | 116 de 531 | 62,65 | [58,93 – 66,17] | 2,66 | 0,54 (N=150) |
| 6 | sin imprevisto | 75 | 0 | 41 de 238 | 68,16 | [63,45 – 72,65] | 2,59 | 0,54 (N=75) |
| 6 | con imprevisto | 75 | 0 | 75 de 293 | 57,13 | [51,39 – 62,69] | 2,74 | 0,55 (N=75) |
| 7 | todos | 150 | 0 | 157 de 596 | 55,40 | [51,12 – 59,10] | 2,64 | 0,54 (N=150) |
| 7 | sin imprevisto | 75 | 0 | 74 de 289 | 56,22 | [50,38 – 61,74] | 2,56 | 0,59 (N=75) |
| 7 | con imprevisto | 75 | 0 | 83 de 307 | 54,57 | [49,43 – 59,55] | 2,72 | 0,49 (N=75) |
| 8 | todos | 150 | 0 | 168 de 692 | 52,66 | [48,71 – 56,56] | 2,89 | 0,55 (N=150) |
| 8 | sin imprevisto | 75 | 0 | 74 de 318 | 54,58 | [49,10 – 60,39] | 2,88 | 0,56 (N=75) |
| 8 | con imprevisto | 75 | 0 | 94 de 374 | 50,74 | [45,57 – 55,67] | 2,90 | 0,54 (N=75) |

### Mando con ensayo previo (gemelo)

| Frentes | Imprevisto | N | Errores | Críticos fallidos | Solo-mundo | IC 95 % | 1.ª atención (min) | Deja esperando a quien toca |
|---|---|---|---|---|---|---|---|---|
| 1 | todos | 180 | 0 | 41 de 343 | 87,17 | [84,60 – 89,66] | 1,92 | — (N=0) |
| 1 | sin imprevisto | 180 | 0 | 41 de 343 | 87,17 | [84,60 – 89,66] | 1,92 | — (N=0) |
| 2 | todos | 212 | 0 | 60 de 508 | 83,61 | [81,53 – 86,22] | 2,18 | 0,61 (N=79) |
| 2 | sin imprevisto | 212 | 0 | 60 de 508 | 83,61 | [81,53 – 86,22] | 2,18 | 0,61 (N=79) |
| 3 | todos | 126 | 0 | 36 de 268 | 80,58 | [77,56 – 83,71] | 2,50 | 0,74 (N=87) |
| 3 | sin imprevisto | 126 | 0 | 36 de 268 | 80,58 | [77,56 – 83,71] | 2,50 | 0,74 (N=87) |
| 4 | todos | 82 | 0 | 18 de 175 | 81,52 | [77,29 – 85,19] | 2,64 | 0,57 (N=77) |
| 4 | sin imprevisto | 82 | 0 | 18 de 175 | 81,52 | [77,29 – 85,19] | 2,64 | 0,57 (N=77) |
| 5 | todos | 150 | 0 | 96 de 518 | 70,20 | [66,66 – 73,42] | 2,56 | 0,50 (N=148) |
| 5 | sin imprevisto | 75 | 0 | 43 de 247 | 70,75 | [66,16 – 74,69] | 2,50 | 0,51 (N=74) |
| 5 | con imprevisto | 75 | 0 | 53 de 271 | 69,65 | [64,52 – 74,94] | 2,63 | 0,50 (N=74) |
| 6 | todos | 150 | 0 | 117 de 531 | 62,27 | [58,59 – 65,81] | 2,69 | 0,54 (N=150) |
| 6 | sin imprevisto | 75 | 0 | 41 de 238 | 68,09 | [63,21 – 72,50] | 2,60 | 0,54 (N=75) |
| 6 | con imprevisto | 75 | 0 | 76 de 293 | 56,45 | [50,87 – 61,95] | 2,78 | 0,54 (N=75) |
| 7 | todos | 150 | 0 | 157 de 596 | 55,36 | [51,27 – 59,32] | 2,66 | 0,55 (N=150) |
| 7 | sin imprevisto | 75 | 0 | 72 de 289 | 56,28 | [50,55 – 62,28] | 2,58 | 0,61 (N=75) |
| 7 | con imprevisto | 75 | 0 | 85 de 307 | 54,45 | [49,30 – 59,22] | 2,74 | 0,49 (N=75) |
| 8 | todos | 150 | 0 | 167 de 692 | 52,41 | [48,25 – 56,44] | 2,89 | 0,56 (N=150) |
| 8 | sin imprevisto | 75 | 0 | 72 de 318 | 54,54 | [48,54 – 60,46] | 2,92 | 0,57 (N=75) |
| 8 | con imprevisto | 75 | 0 | 95 de 374 | 50,29 | [44,65 – 55,09] | 2,86 | 0,54 (N=75) |

Ensayo previo (gemelo sin futuro): Mando con gemelo − Mando sin gemelo, pareado: -0,09 IC 95 % [-0,33 – 0,13]; solo-mundo -0,06 [-0,28 – 0,17] (N=1200).

## Día 1 → día 2: memoria operativa y parámetros aprobados (`python3 -m motor.harness day2`, huella cc17622e1b13)

Simulación. Los parámetros ocultos del recinto (festival_profile) los hemos puesto nosotros: el tamaño del efecto depende de ellos. Se demuestra el circuito observar → proponer → aprobar → medir, no un dato de campo.

Día 1: N=400 casos de train con parámetros de ficha (errores: 0). Observaciones por parámetro: `{"resupply_lead_min": {"water_n": 50, "water_s": 70}, "contact_order": {"security": 2408, "tech": 648, "logistics": 290, "volunteer": 144, "medical": 699, "ambulance": 37}, "require_precise_location": {"general": 115, "food": 89, "gate_b": 2, "front_pit": 68, "toilets": 2, "corridor_s": 1}, "duplicate_window_min": 2497, "weather_followup": 247}`. Día 2: otros N=400 casos de train y N=400 de heldout (heldout nunca se usó para la memoria), corridos dos veces con exactamente los mismos casos y semillas.

| Cambio | Parámetro | Antes | Después | N | Decisión | Texto |
|---|---|---|---|---|---|---|
| C-01 | resupply_lead_min[water_n] | 10 | 32 | 50 | approved (N=50 ≥ 5) | Reposición en Punto de agua norte: tardó 28,7 min de media (N=50; 46 veces el depósito llegó a 0 antes); propongo pedirla 22 min antes (con 32 min de margen en vez de 10) |
| C-02 | resupply_lead_min[water_s] | 10 | 15 | 70 | approved (N=70 ≥ 5) | Reposición en Punto de agua sur: tardó 13,1 min de media (N=70; 44 veces el depósito llegó a 0 antes); propongo pedirla 5 min antes (con 15 min de margen en vez de 10) |
| C-03 | contact_order[medical] | None | orden: med_1 → med_2 → med_3 | 699 | approved (N=699 ≥ 5) | Contacto de medical: Equipo médico 3 (itinerante) aceptó 177 de 239 llamadas y Equipo médico 1 227 de 248 (N=699); propongo llamar primero a quien contesta, salvo que esté mucho más lejos |
| C-04 | contact_order[security] | None | orden: sec_5 → sec_2 → sec_3 → sec_1 → sec_4 | 2395 | approved (N=2395 ≥ 5) | Contacto de security: Seguridad 4 (pista) aceptó 382 de 590 llamadas y Seguridad 5 (Puerta C) 308 de 326 (N=2395); propongo llamar primero a quien contesta, salvo que esté mucho más lejos |
| C-05 | require_precise_location[corridor_s] | False | True | 1 | rejected (evidencia limitada (N=1 < 5): faltan datos) | En Pasillo sur (ruta de ambulancia) el equipo tardó 3,0 min de media en dar con la persona (N=1): «Pasillo sur (ruta de ambulancia)» es demasiado amplio; propongo que el ASK pida un punto concreto (torre, puesto o acceso numerado) mientras el equipo va de camino — EVIDENCIA LIMITADA, cambio conservador |
| C-06 | require_precise_location[general] | False | True | 115 | approved (N=115 ≥ 5) | En Pista general el equipo tardó 6,4 min de media en dar con la persona (N=115): «Pista general» es demasiado amplio; propongo que el ASK pida un punto concreto (torre, puesto o acceso numerado) mientras el equipo va de camino |
| C-07 | require_precise_location[toilets] | False | True | 2 | rejected (evidencia limitada (N=2 < 5): faltan datos) | En Baños el equipo tardó 5,0 min de media en dar con la persona (N=2): «Baños» es demasiado amplio; propongo que el ASK pida un punto concreto (torre, puesto o acceso numerado) mientras el equipo va de camino — EVIDENCIA LIMITADA, cambio conservador |
| C-08 | weather_standdown_min | None | 10 | 48 | approved (N=48 ≥ 5) | Meteorología: 55 de 247 alertas de viento no llegaron a más y se desactivaron a los 9,6 min de media (N=48); propongo cancelar los preparativos tras 10 min seguidos en calma, en vez de dejarlos abiertos. No cambia ningún criterio de seguridad: viento de parada 70 km/h, escalones 40/50/60, densidades de alerta y aprobación humana para parar, evacuar o pedir ayuda externa siguen igual. |
| C-09 | weather_followup_min | 5 | 3 | 159 | approved (N=159 ≥ 5) | Meteorología: en 159 alertas el viento pasó de preaviso a riesgo en menos de 5 min; propongo revisar cada 3 min mientras haya alerta. No cambia ningún criterio de seguridad: viento de parada 70 km/h, escalones 40/50/60, densidades de alerta y aprobación humana para parar, evacuar o pedir ayuda externa siguen igual. |

Mirado y NO cambiado: Contacto de tech: todos contestan parecido (84 % de media, N=641); se sigue llamando al más cercano · Contacto de volunteer: todos contestan parecido (91 % de media, N=144); se sigue llamando al más cercano · En Restauración se da con la persona en 2,9 min de media (N=89): no hace falta pedir más · En Frente de escenario se da con la persona en 2,9 min de media (N=68): no hace falta pedir más · En Puerta B (principal) se da con la persona en 2,0 min de media (N=2): no hace falta pedir más · Duplicados: 2497 avisos repetidos fundidos, el 95 % a ≤ 15 min del aviso anterior; 0 equipos movidos por un duplicado, ninguno fuera de la ventana de 15 min: no se toca (N=2497).

### day2_train (N=400 por brazo; errores {'initial': 0, 'revised': 0, 'legacy': 0}; acciones inseguras {'initial': 0, 'revised': 0, 'legacy': 0})

| Métrica (solo mundo) | N pares | Inicial | IC 95 % | Revisado | IC 95 % | Diferencia pareada | IC 99 % | ¿IC no pareados se solapan? | Veredicto |
|---|---|---|---|---|---|---|---|---|---|
| roturas de stock de agua que llegan a ocurrir (por caso) | 400 | 0.33 | [0.268, 0.398] | 0.175 | [0.128, 0.223] | -0.155 | [-0.212, -0.105] | no | **MEJORA** |
| minutos-punto con el depósito a cero (por caso) | 400 | 4.393 | [3.342, 5.52] | 2.485 | [1.685, 3.368] | -1.907 | [-2.79, -1.145] | sí | **MEJORA** |
| incidentes de calor espontáneos (por caso) | 400 | 0.427 | [0.318, 0.557] | 0.425 | [0.312, 0.557] | -0.003 | [-0.018, 0.018] | sí | **sin evidencia de mejora** |
| incidentes derivados que se evitan, `skipped_events` (por caso) | 400 | 0.117 | [0.077, 0.16] | 0.125 | [0.085, 0.168] | 0.007 | [0.0, 0.025] | sí | **sin evidencia de mejora** |
| minutos del aviso al despacho que acaba llegando | 389 | 0.902 | [0.796, 1.014] | 0.939 | [0.813, 1.07] | 0.038 | [-0.031, 0.139] | sí | **sin evidencia de mejora** |
| equipos movidos por un duplicado (por caso) | 400 | 0.158 | [0.095, 0.242] | 0.172 | [0.107, 0.268] | 0.015 | [-0.02, 0.05] | sí | **sin evidencia de mejora** |
| minutos buscando a la persona en zona amplia | 112 | 4.292 | [3.97, 4.644] | 2.854 | [2.574, 3.14] | -1.438 | [-2.006, -0.963] | no | **MEJORA** |
| minutos hasta la primera atención | 389 | 2.914 | [2.708, 3.127] | 2.805 | [2.599, 3.028] | -0.108 | [-0.234, 0.018] | sí | **sin evidencia de mejora** |
| críticos fallidos (por caso) | 400 | 0.258 | [0.207, 0.307] | 0.263 | [0.212, 0.312] | 0.005 | [-0.013, 0.022] | sí | **sin evidencia de mejora** |
| `world_score` (solo-mundo, 0–100) | 400 | 82.6 | [81.031, 84.216] | 82.716 | [81.076, 84.327] | 0.115 | [-0.478, 0.686] | sí | **sin evidencia de mejora** |

Veces que un parámetro aprendido cambió una decisión (brazo revisado): `{"contact_order[security]": 173, "require_precise_location[general]": 181, "resupply_lead_min[water_n]": 114, "resupply_lead_min[water_s]": 105, "weather_followup_min": 384, "weather_standdown_min": 10}`.

**day2_train (N=400 por brazo, mismos casos y semillas): con los parámetros revisados MEJORA: roturas de stock de agua que llegan a ocurrir (por caso): 0.33 → 0.175 (diferencia pareada -0.155, IC 99 % [-0.212, -0.105], N=400); minutos-punto con el depósito a cero (por caso): 4.393 → 2.485 (diferencia pareada -1.907, IC 99 % [-2.79, -1.145], N=400; ojo: los intervalos NO pareados de los dos brazos se solapan, solo vale como diferencia pareada); minutos buscando a la persona en zona amplia: 4.292 → 2.854 (diferencia pareada -1.438, IC 99 % [-2.006, -0.963], N=112). sin evidencia de mejora en: incidentes de calor espontáneos (por caso); incidentes derivados que se evitan, `skipped_events` (por caso); minutos del aviso al despacho que acaba llegando; equipos movidos por un duplicado (por caso); minutos hasta la primera atención; críticos fallidos (por caso); `world_score` (solo-mundo, 0–100).**

### heldout (N=400 por brazo; errores {'initial': 0, 'revised': 0, 'legacy': 0}; acciones inseguras {'initial': 0, 'revised': 0, 'legacy': 0})

| Métrica (solo mundo) | N pares | Inicial | IC 95 % | Revisado | IC 95 % | Diferencia pareada | IC 99 % | ¿IC no pareados se solapan? | Veredicto |
|---|---|---|---|---|---|---|---|---|---|
| roturas de stock de agua que llegan a ocurrir (por caso) | 400 | 0.383 | [0.32, 0.448] | 0.247 | [0.195, 0.3] | -0.135 | [-0.19, -0.083] | no | **MEJORA** |
| minutos-punto con el depósito a cero (por caso) | 400 | 5.338 | [4.197, 6.588] | 3.522 | [2.567, 4.647] | -1.815 | [-2.665, -1.04] | sí | **MEJORA** |
| incidentes de calor espontáneos (por caso) | 400 | 0.398 | [0.302, 0.505] | 0.4 | [0.305, 0.507] | 0.003 | [-0.03, 0.043] | sí | **sin evidencia de mejora** |
| incidentes derivados que se evitan, `skipped_events` (por caso) | 400 | 0.028 | [0.013, 0.045] | 0.028 | [0.013, 0.045] | 0.0 | [0.0, 0.0] | sí | **sin evidencia de mejora** |
| minutos del aviso al despacho que acaba llegando | 394 | 1.001 | [0.886, 1.117] | 0.97 | [0.861, 1.085] | -0.031 | [-0.088, 0.033] | sí | **sin evidencia de mejora** |
| equipos movidos por un duplicado (por caso) | 400 | 0.212 | [0.158, 0.278] | 0.215 | [0.152, 0.287] | 0.003 | [-0.028, 0.033] | sí | **sin evidencia de mejora** |
| minutos buscando a la persona en zona amplia | 121 | 4.648 | [4.311, 5.02] | 2.846 | [2.563, 3.16] | -1.802 | [-2.409, -1.221] | no | **MEJORA** |
| minutos hasta la primera atención | 394 | 3.073 | [2.867, 3.302] | 2.837 | [2.661, 3.033] | -0.236 | [-0.373, -0.121] | sí | **MEJORA** |
| críticos fallidos (por caso) | 400 | 0.398 | [0.328, 0.47] | 0.383 | [0.312, 0.455] | -0.015 | [-0.045, 0.013] | sí | **sin evidencia de mejora** |
| `world_score` (solo-mundo, 0–100) | 400 | 78.824 | [76.553, 81.002] | 79.377 | [77.073, 81.561] | 0.553 | [-0.189, 1.344] | sí | **sin evidencia de mejora** |

Veces que un parámetro aprendido cambió una decisión (brazo revisado): `{"contact_order[security]": 221, "require_precise_location[general]": 197, "resupply_lead_min[water_n]": 129, "resupply_lead_min[water_s]": 97, "weather_followup_min": 395, "weather_standdown_min": 13}`.

**heldout (N=400 por brazo, mismos casos y semillas): con los parámetros revisados MEJORA: roturas de stock de agua que llegan a ocurrir (por caso): 0.383 → 0.247 (diferencia pareada -0.135, IC 99 % [-0.19, -0.083], N=400); minutos-punto con el depósito a cero (por caso): 5.338 → 3.522 (diferencia pareada -1.815, IC 99 % [-2.665, -1.04], N=400; ojo: los intervalos NO pareados de los dos brazos se solapan, solo vale como diferencia pareada); minutos buscando a la persona en zona amplia: 4.648 → 2.846 (diferencia pareada -1.802, IC 99 % [-2.409, -1.221], N=121); minutos hasta la primera atención: 3.073 → 2.837 (diferencia pareada -0.236, IC 99 % [-0.373, -0.121], N=394; ojo: los intervalos NO pareados de los dos brazos se solapan, solo vale como diferencia pareada). sin evidencia de mejora en: incidentes de calor espontáneos (por caso); incidentes derivados que se evitan, `skipped_events` (por caso); minutos del aviso al despacho que acaba llegando; equipos movidos por un duplicado (por caso); críticos fallidos (por caso); `world_score` (solo-mundo, 0–100).**

## Fallos encontrados en otros módulos

Ver `motor/harness/out/BUGS.md`.
