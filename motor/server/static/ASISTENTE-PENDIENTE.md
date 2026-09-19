# App del asistente — estado y traspaso (sáb 19-sep, mañana)

Ficheros: `asistente.html`, `asistente.js`, `asistente.css` (nada más; no dependen de `style.css` ni de `jurado.*`).
Reutiliza `plano.js` importándolo (`PLANO.build`), sin copiarlo. Sin frameworks, sin build, sin CDN, sin fuentes externas.
Se abre en `/asistente` (la ruta ya existe en `app.py`) o en `/static/asistente.html`.

## 1. Qué está hecho, a medias y sin empezar

| Pieza | Estado | Notas |
|---|---|---|
| Entrada en 5 s (pulsera «nº X de 40.000», plano tocable con vibración, «No sé dónde estoy», nombre opcional) | HECHO, probado | La zona y el nombre se guardan en `localStorage` (`asistente.v2`) |
| Conversación con el agente como pantalla principal (`POST /api/chat`), chips típicos como respuestas rápidas dentro del chat | HECHO, probado contra el servidor actual (que responde `degraded: true`) | Con `motor.intake` real NO se ha podido probar: no existe todavía |
| Respuestas rápidas Sí / No / No lo sé, «Marcar en el plano», 1 / 2 / 3 o más | A MEDIAS | Se INFIEREN del texto de la pregunta (`inferReplies`). Si el servidor manda `quick_replies` u `options`, se usan esas. Sin probar con preguntas reales del agente |
| Tarjeta de instrucción fija arriba, pasos numerados grandes, plegable | HECHO, probado | Acepta `instruction` como cadena (se parte en frases) o `{title, steps[]}` |
| Metrónomo de RCP a 110/min | HECHO, probado | Se activa si `instruction.metronome === true` o si el texto habla de RCP/pecho/compresiones. Es visual; no vibra |
| Tira «lo que ya sé» | A MEDIAS | Con `state.slots` del servidor pinta esas fichas. Hoy (modo degradado) solo rellena en local «Dónde» y «Qué pasa» |
| «Por qué te pregunto esto» bajo cada pregunta | HECHO (pinta `why_next`) | Sin probar con datos reales: hoy `why_next` llega `null` |
| Dictado (Web Speech API) | HECHO, sin probar con voz | El botón se oculta si el navegador no la trae. En `http://<ip>` de un móvil Chrome la rechaza (exige contexto seguro): sale un aviso |
| Botón «Prefiero hablar» (Web call) y «Escribir por Telegram» | HECHO | Lee `state.links.webcall_public` / `state.links.telegram` o `?webcall=` / `?telegram=`. Sin enlace, el botón explica que no está configurado. Solo abre `http(s):` y `tg:` |
| Hilo vivo del aviso: línea de estado, carril de 5 pasos, burbujas de Mando (entendido, fusionado, prioridad con su cuenta, en cola, LLAMANDO, ACEPTA/RECHAZA/NO CONTESTA, en el sitio, ayuda externa pendiente de una persona, cambio de plan, resuelto/fallido/falsa alarma) | HECHO, probado | Se deriva de `/api/stream`. Incidentes reservados: solo mensajes neutros |
| Mini-plano (tu zona, equipo moviéndose, densidad de tu zona, encuadre que se acerca) | HECHO, probado | |
| Preguntas de Mando a quien avisó (ASK) con respuesta en el mismo hilo | A MEDIAS | Llegan por `GET /api/chat/{sid}/events` (evento `ask`) y por `/api/state`; la respuesta va por `/api/chat`. No se ha visto un ASK real a un asistente en las pruebas (ver §3, fallo del enrutado) |
| Varios avisos en paralelo, cada uno con su hilo | HECHO, probado | Pestañas arriba + «Otro aviso». Solo la conversación ABIERTA mantiene su SSE de eventos (límite de 6 conexiones por host) |
| «Pon a prueba a Mando» (antes «Rompe el plan»): frase de entrada, 6 cartas en lenguaje llano, confirmación, resultado en vivo, marcador explicado | HECHO, probado (lanzado «ambulancia atrapada») | No se ha visto en pruebas un golpe que rompa un supuesto ni uno que falle: esas ramas (`x.r.counted`, `x.v.jury`, test nº N) están escritas y sin ver |
| «El festival ahora»: contador de cosas abiertas, plano con densidad, zonas a evitar, megafonía, qué atiende Mando | HECHO, probado | |
| Recorrido guiado de 3 pasos, saltable, solo la primera vez | HECHO, probado | |
| ES / EN | HECHO | Los textos que vienen del servidor siguen en español; en inglés se rotulan «(control-room text, in Spanish)» |
| Accesibilidad | HECHO en lo básico | Objetivos ≥ 44 px, foco visible, `aria-live`, `prefers-reduced-motion`, claro/oscuro con conmutador. SIN HACER: medir contraste AA con herramienta, probar con lector de pantalla, atrapar el foco dentro de la hoja inferior |
| Reconexión del SSE con aviso «Sin conexión, reintentando…» | HECHO, sin probar cortando la red | Si cae el SSE, sondea `GET /api/report/{id}` |
| Instalable | A MEDIAS | Metaetiquetas y manifiesto generado en el cliente (blob). Sin service worker: Chrome no ofrecerá instalar por `http` de red local; en iOS «Añadir a inicio» sí |
| Probar en un móvil de verdad | SIN EMPEZAR | Todo se probó en Chrome de escritorio con ventana estrecha |

## 2. Decisiones de diseño (no romper)

- **Un solo producto con la pantalla de mando**: mismos tokens que `style.css` en oscuro (`--bg #06090d`, `--panel #0c1218`,
  `--panel-2 #111a22`, `--line #1e2b37`, `--line-2 #2c3e4e`, `--text #e8eef3`, ámbar `#ffb02e`, cian `#4cc9f0`, verde `#2fd17a`,
  violeta `#b595ff`). Cambios a propósito: `--dim` sube a `#9aabb9` y `--red` a `#ff6b6b` para contraste en texto pequeño.
  El tema claro redefine los mismos nombres (fondo `#edf1f4`, NO crema) y añade `--amber-text` (`#8a5600`): el ámbar solo se usa
  como relleno con tinta oscura, nunca como texto sobre blanco.
- **Significado de los colores**: ámbar = acción principal y seguridad; cian = tú (tu zona, tu burbuja, foco); verde = acepta /
  resuelto / voz; rojo = rechaza / fallo / evítala; **violeta = solo «poner a prueba»**, igual que el golpe del jurado en mando.
- **Tipografía**: la de mando. `--sans` (Helvetica Neue / sistema) para todo; `--mono` SOLO para cifras (hora, prioridad,
  densidad, marcador, nº de pulsera). Titulares en 800, sin mayúsculas sostenidas ni etiquetas encima de los títulos.
- **El elemento con carácter es la pulsera** (`.band`): identidad del asistente en la entrada y, en pequeño, cabecera de la app.
  La marca es el trapecio ámbar de mando (`.band-mark`). Todo lo demás es sobrio: no añadir degradados, sombras de tarjeta ni confeti.
- **Componentes**: `.btn` (+ `.primary` ámbar, `.quiet`, `.call` verde, `.danger` violeta), `.tool` (botón redondo de 44 px),
  `.chip` (incidente típico con icono), `.qr` (respuesta rápida), `.slot` (ficha de «lo que ya sé»), `.msg.me|agent|mando|note`,
  `.stamp` (ACEPTA / RECHAZA / LLAMANDO), `.hero` + `.rail` (línea de estado y carril), `.instr` + `.metro`, `.mini` (figura con
  plano), `.row` (filas de «El festival ahora»), `.card` y `.result` (imprevistos), `.sheet` (hoja inferior), `.net`, `.toast`.
- **Iconos**: SVG propios en un `<svg><defs>` al principio del HTML, trazo 2, `currentColor`. Ningún emoji.
- **Lenguaje**: ningún término interno en pantalla. supuesto → «Mando contaba con esto»; frente → «cosas que Mando atiende»;
  golpe → «imprevisto»; replanificar → «he cambiado el plan». Una acción principal por pantalla. Textos en `TX.es` / `TX.en`.
- **Movimiento**: solo como respuesta (burbuja nueva, cambio de estado, ficha que se rellena, zona elegida) y una animación de
  entrada (la pulsera). El metrónomo va por JS para que funcione también con `prefers-reduced-motion`.
- **Seguridad**: todo texto del servidor o de la persona pasa por `esc()` antes de `innerHTML`. `setHTML()` solo repinta si cambia.
- El plano se rotula con nombres cortos propios (`SHORT`) porque los de `plano.js` no se leen a 360 px; se renombra el `id` del
  patrón `#hatch` por instancia porque hay varios planos en la misma página.

## 3. Lo que hace falta del servidor y todavía no existe (o falla)

1. **`motor.intake.IntakeSession`**: hoy `/api/chat` responde siempre `degraded: true` (un mensaje = un aviso, `why_next: null`,
   `state: {}`). La app ya está preparada para `say`, `instruction`, `state.slots`, `why_next`, `reports`, `done`.
2. **`POST /api/chat` → `quick_replies`**: `["Sí", "No", "No lo sé"]` o `[{label, value}]`. Sin él, la app adivina las opciones por el texto.
3. **`POST /api/chat` → `state.slots`**: lista `[{id, label, value, confidence}]` con `label` ya en el idioma de la persona;
   `value: null` = ficha vacía; `true/false` se pintan «Sí/No».
4. **`POST /api/chat` → `instruction`**: `{id, title, steps: [str], metronome: bool}`. Hoy llega una cadena y el metrónomo se decide por palabras.
5. **`POST /api/chat` acepta `source`/nombre** (la app ya lo envía como `source`): hoy el aviso entra como `chat:N` y el nombre del
   jurado no sale en mando. También `preset` (los chips hoy dependen de que el texto contenga las palabras clave de `JURY_INCIDENTS`).
6. **Fallo de enrutado**: `ChatHub.route_ask` manda a la conversación web preguntas que Mando hace AL EQUIPO (`purpose: "sitrep"`,
   «¿Qué os encontráis?») porque comparten `params.reports`. Debe ignorar las acciones con `resource` o cuyo `params.to` sea un recurso.
   La app lo retira en cuanto lo ve en `/api/state`, pero la burbuja parpadea.
7. **Simulación que contesta por la persona**: un ASK a quien avisó lo contesta SimComms a los ~2 min simulados («aquí no pasa
   nada») y el incidente se cierra como falsa alarma antes de que una persona pueda responder a ×4. Hace falta que, si la
   conversación está viva, el ASK espere a la persona (o un plazo en segundos reales).
8. **Golpes por persona**: el presupuesto es global (3 por partida, `scoreboard.left`). Para «3 por persona»:
   `POST /api/strike {client_id}` y `GET /api/jury?client_id=` → `{left, budget}`. La app cuenta 3 en local y respeta además `left`.
9. **Identificador del golpe**: `POST /api/strike` → `strike.id`, y en `state.strikes[]` `{id, outcome, broken: [{assumption_id, text,
   plan}], new_plans: [{id, objective, why}], locked_test: n|null}`. Hoy la app casa su golpe por `t + label + author` y atribuye
   a ese golpe todo supuesto roto en los 12 min siguientes: es una heurística.
10. **Textos en inglés**: `label`, `explain`, `plan.why`, mensajes de megafonía y `say` llegan solo en español aunque se mande `lang: "en"`.
11. **`/asistente` y el QR** ya apuntan aquí. Falta que README liste la página y los endpoints `/api/chat*`.

## 4. Cómo probarla

```sh
uv run --project motor/server python -m motor.server --case demo-gates --speed 1 --play --port 8770
# http://127.0.0.1:8770/asistente   (o /static/asistente.html)
```

- A `--speed 4` el caso (90 min) dura 22 s: para ver un hilo entero usar `--speed 1` o menos. Reiniciar desde esta máquina:
  `curl -XPOST :8770/api/control -H 'Content-Type: application/json' -d '{"cmd":"reset"}'`, luego `{"cmd":"speed","value":0.5}` y `{"cmd":"play"}`.
- Empezar de cero en el navegador: borrar `localStorage` (`asistente.v2`, `asistente.theme`). Al cambiar de partida la app se limpia sola.
- Recorrido mínimo: tocar «Pista», Entrar → saltar el recorrido → chip «Persona que no responde» → en ~5 s: «Entendido», prioridad,
  LLAMANDO, ACEPTA, «En el sitio», mini-plano con el equipo; tarjeta de instrucción con metrónomo. «Otro aviso» → «No hay agua»
  (segundo hilo en paralelo). Pestaña «Poner a prueba» → «La ambulancia se queda atrapada» → resultado y marcador.
  Pestaña «El festival ahora». Conmutadores EN y claro/oscuro arriba a la derecha.
- Enlaces: `?webcall=https://…&telegram=https://t.me/…&lang=en`.
- NO usar Chrome headless contra esta página (SSE abierto: se cuelga). Consola sin errores en todas las pruebas hechas.
