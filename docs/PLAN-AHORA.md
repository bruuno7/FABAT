# Plan de ahora mismo — qué estamos haciendo y qué falta (sáb 19-sep, 19:10)

Entrega del Gran Premio: **domingo 11:00**, jueces de San Francisco (en inglés): **vídeo de 3 min**, **demo que puedan probar**
y **repo**. Criterios: creatividad, problem solving, craftsmanship. Finalistas: pitch de 5 min a VCs. Track: ~10 min ante sus jueces.

## La idea en una frase
Un **equipo de agentes de HappyRobot** recibe los avisos (Telegram, teléfono, web), **decide la prioridad y reparte el trabajo**,
avisa a la gente de verdad, **vigila su plan y lo rehace** cuando algo cambia, y **aprende** de lo que pasó; una persona ve su
razonamiento y manda en lo grave. Nuestro backend es el mundo, las herramientas y las barandillas del equipo.

## Cómo encaja todo
```
Telegram ─► puente Vercel (Bruno) ─► fa-entrada-tg ──Call Workflow──► prueba-ana-rapido (decide en ~40 s)
                                                                       │            └─► enjambre de 6 especialistas revisa detrás
                                                                       ▼                (confirma o corrige)
                                                        backend MANDO /hr/tools/decidir (barandillas)
                                                          │                           │
                                staff por Telegram ◄──────┘ (espejo, botones)          └─► llamada de voz (mando-despacho-telefono)
                                                                       ▼
                                                        Sala de control: ver · aprobar · vetar · lecciones
```

## Hecho y comprobado
- Equipo de agentes **publicado en HappyRobot** (development): `prueba-ana-rapido`, `prueba-ana-equipo` y seis especialistas
  (triaje, prioridad, recursos, avisos, vigía, crítico). **Ciclo real completo comprobado**: el aviso entra, los agentes razonan en
  la plataforma, la decisión llega a nuestro backend y aparece en la Sala (incidentes M-001 y M-002).
- **Agente rápido: 39 s** medido (la cadena de seis tardaba 3–6 min).
- Barandillas funcionando en real: lo vital se despachó al instante; lo marcado «para una persona» no se ejecutó solo.
- Backend: **561 tests en verde**, prueba de humo de 293 peticiones sin ningún error 500 (`docs/BACKEND-VERIFICADO.md`).
- **Aprendizaje medido** con un LLM real (N = 40 escenarios): barandillas 39/40, recurso 32/40 frente a 21/40 de la lista fija;
  lecciones aprobadas cambian decisiones el día 2 con 0 regresiones (`python3 -m motor.evals aprende --demo`).
- **Una sola base de datos**, Sala en pestañas, repo limpio (lo movido está en `archivo/`, ver `docs/LIMPIEZA.md`).
- **Demo pública** en https://mando-fabat.onrender.com (modo simulado hasta que se pongan los secretos).
- Túnel fijo con ngrok para el portátil: `https://skintight-oxidizing-prognosis.ngrok-free.dev`.

## En marcha (agentes, ~19:30)
- Dos velocidades en el backend y la Sala: seis tarjetas por papel y «decisión rápida en N s · enjambre: CONFIRMA/CORRIGE».
- Enjambre en abanico: el backend lanza a los seis especialistas en paralelo por la API y compone la decisión a medida que llegan.
- Ronda final: encajar todo, dejar las pruebas en verde dos veces, corregir el bloqueo de recurso duplicado.
- Documentación en inglés: README, `docs/TRY-IT.md`, `docs/VIDEO-3MIN.md`, `docs/PITCH-5MIN.md`.

## Lo que falta y de quién es
| # | Qué | Quién | Cuándo |
|---|---|---|---|
| 1 | Verificar la ronda final, fusionar `ana` en `main` (PR #17) y redesplegar Render | Ana (agente) + aprobación del equipo | ~19:35 |
| 2 | En `fa-entrada-tg`: nodo **Call Workflow → `prueba-ana-rapido`** con `texto`, `canal`, `zona_sugerida`, `correlation_id`, `callback_url`, `callback_token` | **Bruno** | ya |
| 3 | En Vercel: `MANDO_BACKEND_URL` = URL del backend (ngrok para la demo en directo) | **Bruno** | ya |
| 4 | Un móvil de alguien que acepte la llamada de prueba, para `MANDO_ALLOWED_NUMBERS` (si da «SIP 403», Web call) | **Equipo** | ya |
| 5 | Secretos en Render (Environment) si la demo pública debe usar HappyRobot: `HR_API_KEY`, `HR_SECRET`, `MANDO_OPERATOR_TOKEN`, `MANDO_CEREBRO=agente` | **Ana** (a mano) | tras 1 |
| 6 | Prueba de punta a punta real y grabarla: Telegram → agente rápido → despacho → «Acudo» → llamada → Sala → veto | Todos | ~20:00 |
| 7 | Vídeo de 3 min en inglés con `docs/VIDEO-3MIN.md` (se puede empezar ya grabando la Sala) | **Talía y Firdaous** | ya |
| 8 | Entrega (vídeo + demo + repo) | Todos | antes de las 11:00 |

## Reglas que no cambian
Lo grave (evacuar, parar, ayuda externa) **siempre** lo decide una persona · lo vital no espera · nunca se llama a un número fuera
de la lista blanca · toda cifra va con su N · lo simulado se dice simulado · workflows de prueba con prefijo `prueba-ana-`.
