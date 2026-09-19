# MANDO dentro de HappyRobot — arquitectura del «cerebro» (rama `ana`)

**Idea:** todo entra y sale por HappyRobot, y quien razona es un agente de la plataforma (LLM con herramientas), no un árbol
de reglas. El backend de MANDO deja de decidir: pasa a ser las HERRAMIENTAS del agente, las barandillas y la memoria.

```
 Telegram · teléfono · Web call · email · SMS · web · sensores
        │  (cada canal, su workflow de entrada; todos acaban igual)
        ▼
 ┌──────────────────────── HappyRobot ─────────────────────────┐
 │ 1. ENTENDER   AI Extract → aviso estructurado (qué, dónde, gravedad percibida, quién, idioma)       │
 │ 2. CONTEXTO   herramienta `contexto` → incidentes abiertos, recursos libres, estado del recinto,     │
 │               previsiones del gemelo, LECCIONES aprobadas y casos parecidos del pasado               │
 │ 3. RAZONAR    agente «mando-cerebro»: ¿es nuevo o se fusiona? ¿qué va primero y por qué? ¿a quién se │
 │               avisa, por qué canal y qué se le dice? ¿qué recurso va y a quién se deja esperando?    │
 │               ¿hay que tirar el plan? Puede llamar a `ensayar` (gemelo) antes de decidir.            │
 │               Devuelve JSON: decisión + razonamiento + confianza + supuestos + qué vigilar.          │
 │ 4. BARANDILLAS (deterministas, fuera del LLM): evacuar / parar / ayuda externa → SIEMPRE persona;    │
 │               riesgo vital → despacho inmediato, nunca espera; lista blanca de destinos.             │
 │ 5. ACTUAR     Telegram con botones al staff · llamada de voz por oficio · SMS/email · difusión       │
 │ 6. GUARDAR    herramienta `memoria.guardar`: entrada, contexto visto, razonamiento, decisión,        │
 │               acciones, respuestas (acepta / rechaza / silencio), resultado y tiempos.               │
 │ 7. APRENDER   «mando-aprende» (al cerrar un incidente y al final del día): compara decisión y        │
 │               resultado, propone LECCIONES en lenguaje natural con su evidencia (N casos); una        │
 │               persona las aprueba; las aprobadas entran en el paso 2 la próxima vez.                 │
 └───────────────────────────────────────────────────────────────┘
        ▲ herramientas (webhooks con token)                         │ espejo de todo
        │                                                           ▼
 Backend MANDO: /hr/tools/contexto · /hr/tools/ensayar · /hr/tools/recursos · /hr/tools/memoria/*        Sala de control
 (simulador del recinto, gemelo, previsiones, ledger SQLite, barandillas)                                (ver, aprobar, vetar)
```

**Qué se conserva:** simulador y gemelo, previsiones, Sala, ledger, espejo de Telegram, evals. Si la plataforma no contesta decide el MISMO equipo de agentes con un LLM local; el planificador con reglas
queda como **plan B** (si la plataforma cae) y como **vara de medir**: mismo banco de casos, tres brazos — lista fija, reglas,
agente LLM — con su N.

**Qué cambia de discurso:** ya no «cero LLM en el núcleo». Ahora: «razona un agente; las barandillas no las decide el
agente; cada decisión queda escrita con su porqué; y lo que aprende lo aprueba una persona».

**Riesgos:** latencia (un LLM tarda segundos: lo vital se despacha por barandilla ANTES de razonar), coste y límites de la
plataforma, no determinismo (por eso evals con N y plan B), y tiempo: es sábado por la tarde.
