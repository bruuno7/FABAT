/* App del asistente del festival. Sin dependencias: HTML + CSS + este fichero, y el plano compartido (plano.js).
   Todo texto que viene del servidor o de la persona se pinta escapado. */
(function () {
  "use strict";

  /* ------------------------------------------------------------------ utilidades */
  const $ = (id) => document.getElementById(id);
  const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ESC[c]);
  const icon = (id, cls) => `<svg class="ic${cls ? " " + cls : ""}" aria-hidden="true"><use href="#${id}"/></svg>`;
  const buzz = (p) => { try { if (navigator.vibrate) navigator.vibrate(p); } catch (e) { /* sin vibración */ } };
  const reduced = () => window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const qs = new URLSearchParams(location.search);
  const cache = new WeakMap();
  function setHTML(el, html) { if (cache.get(el) !== html) { cache.set(el, html); el.innerHTML = html; return true; } return false; }
  async function api(method, url, body) {
    const r = await fetch(url, { method, headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined });
    let j = null;
    try { j = await r.json(); } catch (e) { /* sin cuerpo */ }
    return { ok: r.ok, status: r.status, j: j || {} };
  }

  /* ------------------------------------------------------------------ lo que se recuerda en este móvil */
  const KEY = "asistente.v2";
  const store = Object.assign({ lang: null, name: "", zone: null, entered: false, toured: false, num: 0, session: null, convs: [], cur: null, strikes: [] }, (() => {
    try { return JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) { return {}; }
  })());
  if (!store.num) store.num = 1 + Math.floor(Math.random() * 40000);
  if (!store.lang) store.lang = (qs.get("lang") || navigator.language || "es").toLowerCase().startsWith("en") ? "en" : "es";
  let saveTimer = 0;
  function save() { clearTimeout(saveTimer); saveTimer = setTimeout(() => { try { localStorage.setItem(KEY, JSON.stringify(store)); } catch (e) { /* modo privado */ } }, 150); }

  /* ------------------------------------------------------------------ textos ES / EN */
  const TX = {
    es: {
      "brand": "Festival Abierto", "band.you": "Tu pulsera", "band.of": "nº {n} de 40.000",
      "w.title": "Estás dentro del Festival Abierto. Eres una de 40.000 personas.",
      "w.lead": "Mando es el sistema que coordina la seguridad esta noche. Si ves algo, cuéntaselo aquí a su agente y mira en directo qué hace con tu aviso.",
      "w.where": "¿Dónde estás? Toca el plano.", "w.unknown": "No sé dónde estoy", "w.name": "Tu nombre (opcional, sale en el marcador)", "w.enter": "Entrar al festival",
      "w.picked": "Estás en: {z}", "w.nozone": "Sin zona: el agente te preguntará dónde estás.",
      "hdr.anon": "Asistente nº {n}", "hdr.nozone": "No sé dónde estoy", "day": "Día {d}",
      "tab.chat": "Avisar", "tab.live": "El festival ahora", "tab.test": "Poner a prueba",
      "sim.done": "El simulacro ha terminado. Pide al equipo que lo reinicie para seguir.", "sim.paused": "El simulacro está en pausa: Mando no avanza hasta que el equipo lo reanude.",
      "sim.reset": "El simulacro ha empezado de nuevo: tus avisos anteriores ya no cuentan.",
      "net.down": "Sin conexión, reintentando…", "net.back": "Conectado de nuevo",
      "c.voice": "Prefiero hablar", "c.voice.on": "Se abre una llamada con el agente de voz", "c.voice.off": "La voz no está configurada en esta demo",
      "c.voice.explain": "La llamada de voz no está configurada en esta demo. Escribe aquí: llega a Mando igual.",
      "c.telegram": "Escribir por Telegram", "c.telegram.on": "Mismo agente, en tu Telegram", "c.telegram.off": "El bot no está configurado en esta demo",
      "c.telegram.explain": "El bot de Telegram no está configurado en esta demo.",
      "c.placeholder": "Escribe qué pasa…", "c.placeholder.answer": "Tu respuesta…", "c.send": "Enviar", "c.mic": "Dictar", "c.mic.off": "El dictado no funciona en este navegador.",
      "c.new": "Otro aviso", "c.conv": "Aviso {n}", "c.greet": "Hola. Soy el agente de avisos del festival. ¿Qué está pasando?",
      "c.greet.why": "Lo que me cuentes llega al momento a Mando, que decide a quién mandar.",
      "c.whyq": "Por qué te pregunto esto", "c.typing": "Escribiendo",
      "c.direct": "El agente no está disponible ahora: tu mensaje ha entrado directo al centro de control.",
      "c.degraded": "Hoy cada mensaje tuyo entra como aviso directo al centro de control.",
      "c.fail": "No se ha podido enviar. Comprueba la conexión y vuelve a tocar Enviar.",
      "c.added": "Añadido a tu aviso.", "c.ack": "Recibido. Lo paso al centro de control.",
      "chip.collapse": "Persona que no responde", "chip.surge": "Mucha gente empujando", "chip.water": "No hay agua", "chip.fight": "Una pelea",
      "chip.smoke": "Humo o fuego", "chip.child": "Un niño perdido", "chip.power": "Se ha ido la luz", "chip.other": "Otra cosa",
      "say.collapse": "Hay una persona en el suelo que no responde.", "say.surge": "Hay mucha gente empujando, nos estamos aplastando.", "say.water": "No hay agua en el punto de agua.",
      "say.fight": "Hay una pelea.", "say.smoke": "Sale humo y huele a quemado.", "say.child": "He encontrado a un niño perdido, está solo.", "say.power": "Se ha ido la luz en esta zona.",
      "q.yes": "Sí", "q.no": "No", "q.dk": "No lo sé", "q.map": "Marcar en el plano", "q.here": "Estoy en {z}", "q.3": "3 o más",
      "slot.where": "Dónde", "slot.what": "Qué pasa", "slot.people": "Cuántas personas", "slot.responds": "Responde", "slot.breathes": "Respira", "slot.known": "Lo que ya sé",
      "instr.title": "Mientras llega ayuda", "instr.hide": "ocultar", "instr.show": "ver pasos", "metro.b": "Sigue este ritmo", "metro.s": "110 por minuto. No pares hasta que llegue el equipo.",
      "who.agent": "Agente", "who.mando": "Mando", "who.me": "Tú",
      "rail.0": "Recibido", "rail.1": "Entendido", "rail.2": "En camino", "rail.3": "En el sitio", "rail.4": "Resuelto",
      "h.received": "Recibido. Mando lo está leyendo.", "h.understood": "Entendido: {label}", "h.merged": "Es el mismo incidente que otros {n} avisos",
      "h.ask": "Mando te pregunta: {q}", "h.hold": "Mando lo confirma antes de mover un equipo", "h.wait": "En cola: falta {need}",
      "h.calling": "Llamando a {who}…", "h.accept": "{who} ACEPTA. Llega en {eta} min", "h.accept0": "{who} ACEPTA. Ya está al lado", "h.reject": "{who} RECHAZA. Busco otro equipo", "h.noanswer": "{who} no contesta. Busco otro equipo",
      "h.onscene": "Ya hay un equipo contigo", "h.resolved": "Resuelto", "h.failed": "No se llegó a tiempo", "h.false": "Cerrado: allí no ven nada",
      "h.reserved": "Tu aviso se está atendiendo", "h.prio": "Prioridad {v} de 10", "h.why": "por qué", "h.yourreport": "Tu aviso",
      "m.understood": "Lo he entendido como <strong>{label}</strong>{where}.", "m.where": ", en {z}", "m.nowhere": ", todavía sin zona",
      "m.reserved": "Tu aviso está en el centro de control y se está atendiendo. Por discreción, aquí no damos detalles.",
      "m.merged": "Es el mismo incidente que otros <strong>{n}</strong> avisos. No mando dos equipos a lo mismo: sumo el tuyo a los demás.",
      "m.prio": "Le doy prioridad <strong>{v} de 10</strong>.", "m.ask": "Necesito saber una cosa: <span class=\"q\">{q}</span>",
      "m.hold": "Solo tengo un aviso y no está claro. Antes de mover un equipo, lo confirmo con quien esté cerca.",
      "m.wait": "Ahora mismo no queda libre: <strong>{need}</strong>. Están en algo más urgente. Tu aviso está en cola y lo reviso cada minuto.",
      "m.calling": "<span class=\"stamp call\">LLAMANDO</span>{who}", "m.accept": "<span class=\"stamp ok\">ACEPTA</span>{who} va hacia ti. Llega en <strong>{eta} min</strong>.", "m.accept0": "<span class=\"stamp ok\">ACEPTA</span>{who} está al lado y va ya.",
      "m.reject": "<span class=\"stamp bad\">RECHAZA</span>{who} no puede ir. Busco otro equipo.", "m.noanswer": "<span class=\"stamp bad\">NO CONTESTA</span>{who} no coge el teléfono. Busco otro equipo.",
      "m.onscene": "{who} ya está en el sitio.", "m.ext_wait": "He pedido ayuda de fuera del recinto. Eso no lo decido yo: lo aprueba una persona del centro de control. Espero su respuesta.",
      "m.ext_ok": "Una persona lo ha aprobado: la ayuda de fuera está pedida.", "m.ext_no": "La persona responsable ha dicho que no: se resuelve con los equipos del recinto.",
      "m.replan": "He cambiado el plan. {why}", "m.in_progress": "Ya os están atendiendo.", "m.resolved": "Resuelto. Gracias por avisar.",
      "m.failed": "No se llegó a tiempo. Queda registrado como fallo para que no se repita.", "m.false": "Quien está en el sitio dice que no ve nada. Lo cierro. Si sigue pasando, avisa otra vez.",
      "m.r_onway": "Hay personal de camino.", "m.r_there": "Ya hay personal en el sitio.",
      "need.medical": "equipo médico", "need.ambulance": "ambulancia", "need.security": "seguridad", "need.tech": "técnicos", "need.logistics": "logística", "need.volunteer": "voluntarios",
      "mini.you": "Tú", "mini.dens": "Tu zona, {z}: <b>{d} personas por m²</b>. {word}", "mini.nozone": "Todavía no sabemos dónde estás: márcalo en el plano.",
      "dens.ok": "Se anda bien.", "dens.mid": "Está llena.", "dens.bad": "Demasiada gente: si puedes, sal hacia los lados.",
      "l.n1": "cosa está atendiendo Mando ahora mismo", "l.n": "cosas a la vez está atendiendo Mando ahora mismo", "l.n0": "Todo tranquilo: Mando no tiene nada abierto",
      "l.sub": "{hh} · {temp} °C · viento {wind} km/h", "l.map": "Dónde hay mucha gente", "l.lg.ok": "se anda bien", "l.lg.mid": "lleno", "l.lg.bad": "evítala",
      "l.avoid.none": "Ahora mismo se anda bien por todo el recinto.", "l.avoid": "Evítala: {d} personas por m²", "l.closed": "Cerrada", "l.restricted": "Entrada restringida",
      "l.pa": "Avisos por megafonía", "l.pa.none": "Todavía no se ha dicho nada por megafonía.", "l.pa.at": "{hh} · en {z}",
      "l.fronts": "Qué está atendiendo Mando", "l.fronts.none": "Nada abierto ahora mismo.", "l.reserved": "Incidente reservado", "l.prio": "prioridad",
      "x.title": "Pon a prueba a Mando",
      "x.lead": "Mando está coordinando el festival ahora mismo. Provoca un imprevisto y mira en directo cómo cambia su plan. Tienes 3.",
      "x.left": "Te quedan {n} de 3", "x.left0": "Ya has gastado tus 3 imprevistos", "x.left.room": "El jurado ya ha gastado los 3 imprevistos de esta partida",
      "x.jury": "Jurado", "x.score.how": "Punto para Mando si aguanta un imprevisto sin que falle nada grave. Punto para el jurado si algo grave se queda sin atender a tiempo.",
      "x.go": "Provocar este imprevisto", "x.cancel": "Ahora no", "x.which": "¿Qué puerta?", "x.sent": "Imprevisto lanzado. Mira qué hace Mando.",
      "x.block_ambulance": "La ambulancia se queda atrapada", "x.block_ambulance.d": "La gente la rodea y no puede moverse durante 15 minutos.",
      "x.close_gate": "Se cierra una puerta", "x.close_gate.d": "Tú eliges cuál. Quien iba a pasar por ahí tiene que buscar otra.",
      "x.no_answer": "Un equipo no coge el teléfono", "x.no_answer.d": "El equipo que va de camino a un incidente deja de contestar 8 minutos.",
      "x.food_blackout": "Se va la luz en la zona de comida", "x.food_blackout.d": "Los puestos se apagan y la gente se va hacia la pista.",
      "x.storm": "Se levanta una tormenta", "x.storm.d": "Viento de 72 km/h y lluvia sobre todo el recinto.",
      "x.voice_down": "Se cae la red de llamadas", "x.voice_down.d": "Durante 10 minutos Mando no puede llamar a nadie: solo mensajes.",
      "x.r.at": "Lo provocaste a las {hh}", "x.r.counted": "Mando contaba con esto: <s>{a}</s>. Ya no vale.", "x.r.plan": "Plan nuevo: <strong>{o}</strong>", "x.r.nocall": "Llamó a {who} y {res}. Buscó otro equipo.",
      "x.r.rejects": "dijo que no", "x.r.silent": "no contestó", "x.r.waiting": "Mando sigue trabajando. Aquí verás si tiene que cambiar algo.",
      "x.r.nochange": "No ha tenido que cambiar ningún plan.",
      "x.v.pending": "Todavía en juego: si en {m} min no falla nada grave, punto para Mando.", "x.v.mando": "Mando lo ha aguantado.", "x.v.mando.s": "Nada grave se quedó sin atender. Punto para Mando.",
      "x.v.jury": "Algo grave se quedó sin atender a tiempo.", "x.v.jury.s": "Punto para el jurado.",
      "x.v.locked": "Tu fallo queda bloqueado como prueba nº {n}: a partir de ahora Mando tiene que superarla siempre.",
      "x.v.canlock": "El equipo puede guardarlo ahora como prueba nº {n}: Mando tendrá que superarla siempre.",
      "tour.skip": "Saltar", "tour.next": "Siguiente", "tour.done": "Empezar", "tour.of": "{i} de 3",
      "tour.1.t": "Cuéntale al agente lo que ves", "tour.1.b": "Escríbelo, díctalo o toca una respuesta rápida. El agente te pregunta solo lo que le falta y te dice qué hacer mientras llega ayuda.",
      "tour.2.t": "Mira qué hace Mando con tu aviso", "tour.2.b": "En la misma conversación ves, en directo, a quién llama, si acepta, cuánto tarda y cuándo queda resuelto.",
      "tour.3.t": "Ponlo a prueba", "tour.3.b": "En «Poner a prueba» puedes provocar 3 imprevistos (una tormenta, una puerta cerrada…) y ver cómo Mando cambia su plan.",
      "zone.title": "¿Dónde estás?", "zone.body": "Toca tu zona en el plano.", "zone.ok": "Estoy aquí", "server.es": "",
    },
    en: {
      "brand": "Festival Abierto", "band.you": "Your wristband", "band.of": "no. {n} of 40,000",
      "w.title": "You are inside Festival Abierto. You are one of 40,000 people.",
      "w.lead": "Mando is the system coordinating safety tonight. If you see something, tell its agent here and watch live what it does with your report.",
      "w.where": "Where are you? Tap the map.", "w.unknown": "I don't know where I am", "w.name": "Your name (optional, shown on the scoreboard)", "w.enter": "Enter the festival",
      "w.picked": "You are at: {z}", "w.nozone": "No zone: the agent will ask where you are.",
      "hdr.anon": "Attendee no. {n}", "hdr.nozone": "I don't know where I am", "day": "Day {d}",
      "tab.chat": "Report", "tab.live": "Festival now", "tab.test": "Test Mando",
      "sim.done": "The drill has ended. Ask the team to restart it.", "sim.paused": "The drill is paused: Mando will not move until the team resumes it.",
      "sim.reset": "The drill has restarted: your earlier reports no longer count.",
      "net.down": "No connection, retrying…", "net.back": "Connected again",
      "c.voice": "I'd rather talk", "c.voice.on": "Opens a call with the voice agent", "c.voice.off": "Voice is not set up in this demo",
      "c.voice.explain": "The voice call is not set up in this demo. Type here: it reaches Mando just the same.",
      "c.telegram": "Write on Telegram", "c.telegram.on": "Same agent, in your Telegram", "c.telegram.off": "The bot is not set up in this demo",
      "c.telegram.explain": "The Telegram bot is not set up in this demo.",
      "c.placeholder": "Type what is happening…", "c.placeholder.answer": "Your answer…", "c.send": "Send", "c.mic": "Dictate", "c.mic.off": "Dictation does not work in this browser.",
      "c.new": "New report", "c.conv": "Report {n}", "c.greet": "Hi. I'm the festival's reporting agent. What is happening?",
      "c.greet.why": "What you tell me reaches Mando at once, and Mando decides who to send.",
      "c.whyq": "Why I'm asking this", "c.typing": "Typing",
      "c.direct": "The agent is unavailable right now: your message went straight to the control room.",
      "c.degraded": "Today each message you send goes straight to the control room as a report.",
      "c.fail": "Could not send. Check your connection and tap Send again.",
      "c.added": "Added to your report.", "c.ack": "Received. Passing it to the control room.",
      "chip.collapse": "Someone not responding", "chip.surge": "Crowd pushing", "chip.water": "No water", "chip.fight": "A fight",
      "chip.smoke": "Smoke or fire", "chip.child": "A lost child", "chip.power": "Power is out", "chip.other": "Something else",
      "say.collapse": "Someone has collapsed and is not responding.", "say.surge": "People are pushing, there is a crush.", "say.water": "There is no water at the water point.",
      "say.fight": "There is a fight.", "say.smoke": "There is smoke, something is on fire.", "say.child": "I found a lost child, alone.", "say.power": "The power is out in this area.",
      "q.yes": "Yes", "q.no": "No", "q.dk": "I don't know", "q.map": "Mark on the map", "q.here": "I'm at {z}", "q.3": "3 or more",
      "slot.where": "Where", "slot.what": "What", "slot.people": "How many people", "slot.responds": "Responding", "slot.breathes": "Breathing", "slot.known": "What I know so far",
      "instr.title": "While help arrives", "instr.hide": "hide", "instr.show": "show steps", "metro.b": "Follow this rhythm", "metro.s": "110 per minute. Do not stop until the team arrives.",
      "who.agent": "Agent", "who.mando": "Mando", "who.me": "You",
      "rail.0": "Received", "rail.1": "Understood", "rail.2": "On the way", "rail.3": "On site", "rail.4": "Resolved",
      "h.received": "Received. Mando is reading it.", "h.understood": "Understood: {label}", "h.merged": "Same incident as {n} other reports",
      "h.ask": "Mando asks you: {q}", "h.hold": "Mando is confirming before moving a team", "h.wait": "Queued: no {need} free",
      "h.calling": "Calling {who}…", "h.accept": "{who} ACCEPTS. Arriving in {eta} min", "h.accept0": "{who} ACCEPTS. Right next to you", "h.reject": "{who} DECLINES. Finding another team", "h.noanswer": "{who} is not answering. Finding another team",
      "h.onscene": "A team is with you now", "h.resolved": "Resolved", "h.failed": "Help did not arrive in time", "h.false": "Closed: nothing found there",
      "h.reserved": "Your report is being handled", "h.prio": "Priority {v} of 10", "h.why": "why", "h.yourreport": "Your report",
      "m.understood": "I understood it as <strong>{label}</strong>{where}.", "m.where": ", at {z}", "m.nowhere": ", no zone yet",
      "m.reserved": "Your report is with the control room and is being handled. For discretion, no details are shown here.",
      "m.merged": "This is the same incident as <strong>{n}</strong> other reports. I won't send two teams to the same thing: yours is added to the rest.",
      "m.prio": "I'm giving it priority <strong>{v} of 10</strong>.", "m.ask": "I need to know one thing: <span class=\"q\">{q}</span>",
      "m.hold": "I only have one report and it is unclear. Before moving a team, I'm confirming with someone nearby.",
      "m.wait": "Right now none free: <strong>{need}</strong>. They are on something more urgent. Your report is queued and I check every minute.",
      "m.calling": "<span class=\"stamp call\">CALLING</span>{who}", "m.accept": "<span class=\"stamp ok\">ACCEPTS</span>{who} is heading to you. Arriving in <strong>{eta} min</strong>.", "m.accept0": "<span class=\"stamp ok\">ACCEPTS</span>{who} is right there and going now.",
      "m.reject": "<span class=\"stamp bad\">DECLINES</span>{who} cannot go. Finding another team.", "m.noanswer": "<span class=\"stamp bad\">NO ANSWER</span>{who} is not picking up. Finding another team.",
      "m.onscene": "{who} is on site.", "m.ext_wait": "I have asked for outside help. That is not my call: a person in the control room approves it. Waiting for their answer.",
      "m.ext_ok": "A person approved it: outside help has been requested.", "m.ext_no": "The person in charge said no: on-site teams will handle it.",
      "m.replan": "I changed the plan. {why}", "m.in_progress": "You are being attended now.", "m.resolved": "Resolved. Thank you for reporting.",
      "m.failed": "Help did not arrive in time. It is logged as a failure so it does not happen again.", "m.false": "The person on site sees nothing. Closing it. If it is still happening, report again.",
      "m.r_onway": "Staff are on their way.", "m.r_there": "Staff are on site.",
      "need.medical": "medical team", "need.ambulance": "ambulance", "need.security": "security", "need.tech": "technicians", "need.logistics": "logistics", "need.volunteer": "volunteers",
      "mini.you": "You", "mini.dens": "Your zone, {z}: <b>{d} people per m²</b>. {word}", "mini.nozone": "We don't know where you are yet: mark it on the map.",
      "dens.ok": "Easy to move.", "dens.mid": "It is full.", "dens.bad": "Too crowded: if you can, move out to the sides.",
      "l.n1": "thing Mando is handling right now", "l.n": "things Mando is handling at once right now", "l.n0": "All quiet: Mando has nothing open",
      "l.sub": "{hh} · {temp} °C · wind {wind} km/h", "l.map": "Where it is crowded", "l.lg.ok": "easy to move", "l.lg.mid": "full", "l.lg.bad": "avoid",
      "l.avoid.none": "Right now it is easy to move everywhere.", "l.avoid": "Avoid: {d} people per m²", "l.closed": "Closed", "l.restricted": "Restricted entry",
      "l.pa": "PA announcements", "l.pa.none": "Nothing has been announced yet.", "l.pa.at": "{hh} · at {z}",
      "l.fronts": "What Mando is handling", "l.fronts.none": "Nothing open right now.", "l.reserved": "Reserved incident", "l.prio": "priority",
      "x.title": "Put Mando to the test",
      "x.lead": "Mando is coordinating the festival right now. Cause something unexpected and watch live how its plan changes. You have 3.",
      "x.left": "{n} of 3 left", "x.left0": "You have used your 3", "x.left.room": "The jury has already used the 3 for this round",
      "x.jury": "Jury", "x.score.how": "Point for Mando if it absorbs the surprise with nothing serious failing. Point for the jury if something serious is not attended in time.",
      "x.go": "Make this happen", "x.cancel": "Not now", "x.which": "Which gate?", "x.sent": "Done. Watch what Mando does.",
      "x.block_ambulance": "The ambulance gets stuck", "x.block_ambulance.d": "The crowd surrounds it and it cannot move for 15 minutes.",
      "x.close_gate": "A gate closes", "x.close_gate.d": "You choose which. Anyone heading there has to find another.",
      "x.no_answer": "A team stops picking up", "x.no_answer.d": "The team on its way to an incident stops answering for 8 minutes.",
      "x.food_blackout": "Power goes out at the food area", "x.food_blackout.d": "Stalls go dark and people drift to the main floor.",
      "x.storm": "A storm hits", "x.storm.d": "72 km/h wind and rain over the whole site.",
      "x.voice_down": "The call network drops", "x.voice_down.d": "For 10 minutes Mando cannot call anyone: messages only.",
      "x.r.at": "You caused it at {hh}", "x.r.counted": "Mando was counting on this: <s>{a}</s>. No longer true.", "x.r.plan": "New plan: <strong>{o}</strong>", "x.r.nocall": "It called {who}, who {res}. It found another team.",
      "x.r.rejects": "said no", "x.r.silent": "did not answer", "x.r.waiting": "Mando keeps working. You will see here if it has to change anything.",
      "x.r.nochange": "It did not need to change any plan.",
      "x.v.pending": "Still in play: if nothing serious fails in {m} min, point for Mando.", "x.v.mando": "Mando absorbed it.", "x.v.mando.s": "Nothing serious went unattended. Point for Mando.",
      "x.v.jury": "Something serious was not attended in time.", "x.v.jury.s": "Point for the jury.",
      "x.v.locked": "Your failure is locked as test no. {n}: from now on Mando must always pass it.",
      "x.v.canlock": "The team can now save it as test no. {n}: Mando will always have to pass it.",
      "tour.skip": "Skip", "tour.next": "Next", "tour.done": "Start", "tour.of": "{i} of 3",
      "tour.1.t": "Tell the agent what you see", "tour.1.b": "Type it, dictate it or tap a quick reply. The agent only asks what it is missing and tells you what to do while help arrives.",
      "tour.2.t": "Watch what Mando does with your report", "tour.2.b": "In the same conversation you see, live, who it calls, whether they accept, how long it takes and when it is resolved.",
      "tour.3.t": "Put it to the test", "tour.3.b": "Under \"Test Mando\" you can cause 3 surprises (a storm, a closed gate…) and watch Mando change its plan.",
      "zone.title": "Where are you?", "zone.body": "Tap your zone on the map.", "zone.ok": "I'm here", "server.es": " (control-room text, in Spanish)",
    },
  };
  function t(key, vars) {
    let s = (TX[store.lang] && TX[store.lang][key]); if (s == null) s = TX.es[key]; if (s == null) return key;
    return s.replace(/\{(\w+)\}/g, (m, k) => (vars && vars[k] != null ? vars[k] : ""));
  }
  const num = (v, d) => (v == null || isNaN(v) ? "–" : Number(v).toFixed(d == null ? 1 : d).replace(".", store.lang === "es" ? "," : "."));
  const thousands = (n) => String(n).replace(/\B(?=(\d{3})+(?!\d))/g, store.lang === "es" ? "." : ",");

  const SHORT = {
    es: { gate_a: "Puerta A", gate_b: "Puerta B", gate_c: "Puerta C", food: "Comida", toilets: "Baños", water_n: "Agua", medical_2: "Médico", vip: "VIP", corridor_n: "Pasillo norte", general: "Pista",
      front_pit: "Foso", backstage: "Backstage", corridor_s: "Pasillo sur", exit_transport: "Metro", water_s: "Agua", medical_1: "Médico", pmr: "PMR" },
    en: { gate_a: "Gate A", gate_b: "Gate B", gate_c: "Gate C", food: "Food", toilets: "Toilets", water_n: "Water", medical_2: "Medical", vip: "VIP", corridor_n: "North corridor", general: "Floor",
      front_pit: "Front", backstage: "Backstage", corridor_s: "South corridor", exit_transport: "Metro", water_s: "Water", medical_1: "Medical", pmr: "Access" },
  };
  const CHIPS = [["collapse", "i-collapse"], ["surge", "i-surge"], ["water", "i-water"], ["fight", "i-fight"], ["smoke", "i-smoke"], ["child", "i-child"], ["power", "i-power"], ["other", "i-other"]];
  const STRIKE_ICON = { block_ambulance: "i-amb", close_gate: "i-gate", no_answer: "i-noanswer", food_blackout: "i-power", storm: "i-storm", voice_down: "i-voice" };

  /* ------------------------------------------------------------------ estado vivo */
  let F = null, S = null, names = {}, sseLive = false, view = "chat";
  const zoneName = (id) => (id && names[id]) || "";
  const curConv = () => store.convs.find((c) => c.cid === store.cur) || null;

  /* ------------------------------------------------------------------ plano (reutiliza PLANO.build) */
  let planSeq = 0;
  function makePlan(svg, opts) {
    opts = opts || {};
    const ref = window.PLANO.build(svg, F, { selectable: !!opts.pick });
    const n = ++planSeq;
    const hatch = svg.querySelector("#hatch"); if (hatch) { hatch.id = "hatch-" + n; svg.querySelectorAll(".zone-hatch").forEach((r) => r.setAttribute("fill", `url(#hatch-${n})`)); }
    const arr = svg.querySelector("#arr"); if (arr) arr.id = "arr-" + n;
    const P = { ref, svg, sel: null };
    P.labels = function () {
      Object.entries(ref.zones).forEach(([id, z]) => {
        const L = z.L, label = (SHORT[store.lang] || SHORT.es)[id] || id, thin = L.h < 100;
        const fs = Math.max(17, Math.min(27, (L.w - 18) / (label.length * 0.58)));
        z.name.textContent = label; z.name.style.fontSize = fs + "px";
        if (thin) { z.name.setAttribute("x", L.x + 14); z.name.setAttribute("y", L.y + L.h / 2); z.name.setAttribute("text-anchor", "start"); }
        else { z.name.setAttribute("x", L.x + L.w / 2); z.name.setAttribute("y", L.y + L.h / 2 - (opts.dens ? 16 : 0)); z.name.setAttribute("text-anchor", "middle"); }
        z.name.setAttribute("dominant-baseline", "central");
        if (opts.dens) {
          z.dens.setAttribute("dominant-baseline", "central");
          if (thin) { z.dens.setAttribute("x", L.x + L.w - 14); z.dens.setAttribute("y", L.y + L.h / 2); z.dens.setAttribute("text-anchor", "end"); }
          else { z.dens.setAttribute("x", L.x + L.w / 2); z.dens.setAttribute("y", L.y + L.h / 2 + 20); z.dens.setAttribute("text-anchor", "middle"); }
        }
        if (opts.pick) z.g.setAttribute("aria-label", names[id] || label), z.g.setAttribute("role", "button");
      });
    };
    P.select = function (id) { P.sel = id; Object.entries(ref.zones).forEach(([k, z]) => z.g.classList.toggle("sel", k === id)); };
    P.density = function (zones) {
      (zones || []).forEach((z) => {
        const p = ref.zones[z.id]; if (!p) return;
        const keep = ["sel", "me"].filter((c) => p.g.classList.contains(c)).join(" ");
        p.g.setAttribute("class", `zone ${window.PLANO.densityClass(z.density)} st-${z.state || "open"} ${keep}`);
        if (opts.dens) p.dens.textContent = num(z.density, 1);
      });
    };
    P.labels();
    if (opts.pick) {
      const pick = (g) => { if (!g) return; const id = g.dataset.zone; P.select(id); buzz(12); if (opts.onPick) opts.onPick(id); };
      svg.addEventListener("click", (ev) => pick(ev.target.closest("[data-zone]")));
      svg.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); pick(ev.target.closest("[data-zone]")); } });
    }
    return P;
  }

  /* ------------------------------------------------------------------ hoja inferior */
  let sheetClose = null, sheetFocus = null;
  function openSheet(title, html, onClose) {
    sheetFocus = document.activeElement;
    $("sheet-title").textContent = title; $("sheet-body").innerHTML = html;
    $("scrim").hidden = false; $("sheet").hidden = false; sheetClose = onClose || null;
    const f = $("sheet").querySelector("button.primary, button.danger, [data-zone]"); if (f && f.focus) f.focus({ preventScroll: true });
  }
  function closeSheet() { $("scrim").hidden = true; $("sheet").hidden = true; $("sheet-body").innerHTML = ""; const f = sheetClose; sheetClose = null; if (sheetFocus?.isConnected) sheetFocus.focus({preventScroll:true}); if (f) f(); }
  $("sheet").addEventListener("keydown", e => {
    if(e.key !== "Tab") return;
    const nodes = Array.from($("sheet").querySelectorAll('button:not(:disabled),a[href],input,select,textarea,[tabindex="0"]')).filter(el => !el.hidden && el.getClientRects().length);
    const first=nodes[0], last=nodes[nodes.length-1];
    if(!nodes.length) { e.preventDefault(); return; }
    if(e.shiftKey && document.activeElement===first) { e.preventDefault(); last.focus(); }
    else if(!e.shiftKey && document.activeElement===last) { e.preventDefault(); first.focus(); }
  });
  $("sheet-x").onclick = closeSheet; $("scrim").onclick = closeSheet;
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("sheet").hidden) closeSheet(); });

  function zoneSheet(done) {
    openSheet(t("zone.title"), `<p>${esc(t("zone.body"))}</p><div class="plan-wrap"><svg id="plan-sheet" class="plano pick"></svg></div><p id="zs-picked" class="picked"></p>
      <button type="button" class="btn primary wide" id="zs-ok" disabled>${esc(t("zone.ok"))}</button><button type="button" class="btn quiet wide" id="zs-dk">${esc(t("w.unknown"))}</button>`);
    let chosen = null;
    const P = makePlan($("plan-sheet"), { pick: true, onPick: (id) => { chosen = id; $("zs-picked").textContent = t("w.picked", { z: zoneName(id) }); $("zs-ok").disabled = false; } });
    if (S) P.density(S.zones);
    if (store.zone) { P.select(store.zone); chosen = store.zone; $("zs-ok").disabled = false; $("zs-picked").textContent = t("w.picked", { z: zoneName(chosen) }); }
    $("zs-ok").onclick = () => { closeSheet(); done(chosen); };
    $("zs-dk").onclick = () => { closeSheet(); done(null); };
  }
  function setZone(id) { store.zone = id || null; save(); header(); if (miniPlan) miniDraw(); }

  let toastTimer = 0;
  function toast(text) { const el = $("toast"); el.textContent = text; el.hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => (el.hidden = true), 3200); }

  /* ------------------------------------------------------------------ idioma, tema, cabecera */
  function applyLang() {
    document.documentElement.lang = store.lang;
    document.querySelectorAll("[data-i18n]").forEach((el) => (el.textContent = t(el.dataset.i18n)));
    document.querySelectorAll('[data-act="lang"]').forEach((b) => { b.querySelector(".lang-code").textContent = store.lang === "es" ? "EN" : "ES"; b.setAttribute("aria-label", store.lang === "es" ? "Switch to English" : "Cambiar a español"); });
    $("band-num").textContent = t("band.of", { n: thousands(store.num) });
    $("c-text").placeholder = t("c.placeholder"); $("btn-mic").setAttribute("aria-label", t("c.mic")); $("c-send").setAttribute("aria-label", t("c.send"));
    [planWelcome, planLive, miniPlan].forEach((p) => p && p.labels());
    header(); links(); renderAll(true);
    if (!$("welcome").hidden) $("w-picked").textContent = store.zone ? t("w.picked", { z: zoneName(store.zone) }) : "";
  }
  function effectiveTheme() { return document.documentElement.getAttribute("data-theme") || (window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark"); }
  function applyThemeChrome() {
    const th = effectiveTheme();
    document.querySelectorAll('[data-act="theme"] use').forEach((u) => u.setAttribute("href", th === "dark" ? "#i-sun" : "#i-moon"));
    const m = document.querySelector('meta[name="theme-color"]'); if (m) m.content = th === "dark" ? "#06090d" : "#edf1f4";
  }
  document.addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-act]"); if (!b) return;
    if (b.dataset.act === "lang") { store.lang = store.lang === "es" ? "en" : "es"; save(); applyLang(); }
    if (b.dataset.act === "theme") {
      const next = effectiveTheme() === "dark" ? "light" : "dark"; document.documentElement.setAttribute("data-theme", next);
      try { localStorage.setItem("asistente.theme", next); } catch (e) { /* modo privado */ }
      applyThemeChrome();
    }
  });
  function header() {
    $("hdr-name").textContent = store.name || t("hdr.anon", { n: thousands(store.num) });
    $("hdr-zone").textContent = store.zone ? zoneName(store.zone) : t("hdr.nozone");
    if (S) { $("hdr-time").textContent = S.clock.hhmm; $("hdr-day").textContent = t("day", { d: S.clock.day }); }
    const note = $("sim-note");
    if (S && S.session.done) { note.hidden = false; note.textContent = t("sim.done"); }
    else if (S && !S.session.running) { note.hidden = false; note.textContent = t("sim.paused"); }
    else note.hidden = true;
  }
  $("hdr-where").onclick = () => zoneSheet(setZone);

  /* ------------------------------------------------------------------ enlaces de voz y Telegram */
  function safeUrl(u) { if (!u || !String(u).trim()) return null; try { const x = new URL(u, location.href); return ["https:", "http:", "tg:"].includes(x.protocol) ? x.href : null; } catch (e) { return null; } }
  function linkFor(kind) {
    const fromQs = qs.get(kind === "voice" ? "webcall" : kind);
    const L = (S && S.links) || {};
    const value = (kind === "voice" ? L.webcall_public : L[kind]) || fromQs || "";
    if (kind === "email") { const email = String(value).replace(/^mailto:/i, ""); return /^[^\s@?&]+@[^\s@?&]+\.[^\s@?&]+$/.test(email) ? "mailto:" + email : null; }
    if (kind === "sms") { if (value === '/canal/sms') return value; const phone = String(value).replace(/^sms:/i, "").replace(/[ ()-]/g, ""); return /^\+?[0-9]{5,16}$/.test(phone) ? "sms:" + phone : null; }
    return safeUrl(value);
  }
  function links() {
    ["email", "sms"].forEach(kind => { const a = $("btn-" + kind), u = linkFor(kind); a.hidden = !u; if(u) a.href = u; else a.removeAttribute("href"); });
    ["voice", "telegram"].forEach(kind => $("btn-" + kind).setAttribute("aria-disabled", String(!linkFor(kind))));
    $("voice-sub").textContent = t(linkFor("voice") ? "c.voice.on" : "c.voice.off");
    $("telegram-sub").textContent = t(linkFor("telegram") ? "c.telegram.on" : "c.telegram.off");
    $("btn-voice").classList.toggle("call", !!linkFor("voice")); $("btn-voice").classList.toggle("quiet", !linkFor("voice"));
  }
  $("btn-voice").onclick = () => { const u = linkFor("voice"); if (u) window.open(u, "_blank", "noopener"); else toast(t("c.voice.explain")); };
  $("btn-telegram").onclick = () => { const u = linkFor("telegram"); if (u) window.open(u, "_blank", "noopener"); else toast(t("c.telegram.explain")); };

  /* ------------------------------------------------------------------ pestañas */
  function go(tab) {
    view = tab;
    ["chat", "live", "test"].forEach((k) => { $("view-" + k).hidden = k !== tab; });
    document.querySelectorAll(".tabs button").forEach((b) => (b.dataset.tab === tab ? b.setAttribute("aria-current", "page") : b.removeAttribute("aria-current")));
    if (tab === "chat") { const c = curConv(); if (c) c.unread = 0; badge(); scrollEnd(true); }
    window.scrollTo(0, tab === "chat" ? document.body.scrollHeight : 0);
    renderAll(true);
  }
  document.querySelector(".tabs").addEventListener("click", (ev) => { const b = ev.target.closest("[data-tab]"); if (b) go(b.dataset.tab); });
  function badge() { const n = store.convs.reduce((a, c) => a + (c.unread || 0), 0); $("badge").hidden = !n; $("badge").textContent = n > 9 ? "9+" : String(n); }

  /* ------------------------------------------------------------------ conversaciones */
  function newConv() {
    const c = { cid: "c" + Date.now().toString(36), sid: null, reports: [], msgs: [], slots: null, instr: null, instrOpen: true, unread: 0, live: null, evSeq: 0, direct: false, first: "", ask: null, n: store.convs.length + 1 };
    store.convs.push(c); store.cur = c.cid;
    c.msgs.push({ id: "greet", who: "agent", kind: "greet", hh: S ? S.clock.hhmm : "", at: Date.now() });
    save(); return c;
  }
  function addMsg(conv, m) {
    m.at = Date.now(); m.hh = S ? S.clock.hhmm : ""; m.id = m.id || "m" + m.at.toString(36) + conv.msgs.length;
    conv.msgs.push(m);
    if (m.who !== "me" && (view !== "chat" || store.cur !== conv.cid)) { conv.unread = (conv.unread || 0) + 1; badge(); }
    if (m.who === "mando" && m.buzz !== false) buzz([18, 50, 18]);
    save();
    if (store.cur === conv.cid) { renderChat(); scrollEnd(m.who === "me"); }
    return m;
  }
  function upsert(conv, id, kind, p, tone) {
    const old = conv.msgs.find((m) => m.id === id);
    if (!old) return addMsg(conv, { id, who: "mando", kind, p, tone });
    const a = JSON.stringify([old.kind, old.p]), b = JSON.stringify([kind, p]);
    if (a !== b) { old.kind = kind; old.p = p; old.tone = tone; save(); }
    return old;
  }
  function scrollEnd(force) {
    const near = window.innerHeight + window.scrollY > document.body.scrollHeight - 260;
    if (view === "chat" && (force || near)) requestAnimationFrame(() => window.scrollTo({ top: document.body.scrollHeight, behavior: reduced() ? "auto" : "smooth" }));
  }

  function normInstr(x) {
    if (!x) return null;
    let o = x;
    if (typeof x === "string") o = { title: "", steps: x.split(/(?<=[.!?])\s+/).map((s) => s.trim()).filter(Boolean) };
    const steps = (o.steps || []).map((s) => (typeof s === "string" ? s : s.text || s.say || "")).filter(Boolean);
    if (!steps.length) return null;
    const all = (o.title || "") + " " + steps.join(" ") + " " + (o.id || o.key || "");
    return { title: o.title || "", steps, cpr: typeof o.metronome === "boolean" ? o.metronome : /\bRCP\b|\bCPR\b|pecho|compresi|chest|not_responding/i.test(all) };
  }
  function slotValue(value) {
    if(!value || typeof value!=="object") return value;
    if(Array.isArray(value)) return value.map(slotValue).join(", ");
    if("zone" in value || "point" in value) return [value.zone ? zoneName(value.zone) : "",value.point || ""].filter(Boolean).join(" · ") || null;
    return Object.values(value).map(slotValue).filter(v=>v!=null).join(" · ");
  }
  function normSlots(state) {
    if (!state) return null;
    if (Array.isArray(state.slots)) return state.slots.map((s) => ({ id: s.id, label: s.label || s.id, value: slotValue(s.value), confidence: s.confidence }));
    const src = state.slots && typeof state.slots === "object" ? state.slots : null;
    if (!src) return null;
    return Object.keys(src).map((k) => { const v = src[k]; return v && typeof v === "object" ? { id: k, label: v.label || k, value: slotValue(v.value), confidence: v.confidence } : { id: k, label: k, value: slotValue(v) }; });
  }

  let sending = false;
  async function sayToAgent(text, opts) {
    text = (text || "").trim(); if (!text || sending) return;
    const conv = curConv() || newConv();
    opts = opts || {};
    if (!conv.first) conv.first = text;
    conv.quickReplies = null;
    addMsg(conv, { who: "me", text: opts.display || text });
    sending = true; renderChat(); scrollEnd(true);
    try {
      let r = null;
      if (!conv.direct) {
        r = await api("POST", "/api/chat", { session_id: conv.sid || undefined, text, channel: "web", lang: store.lang, zone_hint: opts.zone || store.zone || undefined, source: store.name || undefined });
        if (r.status === 404 || r.status === 405 || r.status >= 500) { conv.direct = true; r = null; }
        else if (!r.ok) throw new Error(r.j.error || r.j.detail || "chat");
      }
      if (r) applyTurn(conv, r.j); else await directReport(conv, text, opts);
    } catch (e) {
      addMsg(conv, { who: "note", text: t("c.fail"), err: true });
    } finally { sending = false; renderChat(); scrollEnd(true); }
  }
  function applyTurn(conv, j) {
    const fresh = !conv.sid; conv.sid = j.session_id || conv.sid;
    (j.reports || []).concat(j.report_id ? [j.report_id] : []).forEach((id) => { if (id && !conv.reports.includes(id)) conv.reports.push(id); });
    const ins = normInstr(j.instruction); if (ins) { conv.instr = ins; conv.instrOpen = true; }
    const sl = normSlots(j.state); if (sl) { const before = JSON.stringify(conv.slots || []); conv.slots = sl; if (before !== JSON.stringify(sl)) conv.slotsAt = Date.now(); }
    if (j.answered_mando) conv.ask = null;
    const opt = j.quick_replies || j.options || (j.state && j.state.options) || null;
    const options = Array.isArray(opt) ? opt.map(o => typeof o === "string" ? {label:o,value:o} : {label:String(o.label ?? o.value ?? ""),value:String(o.value ?? o.label ?? "")}).filter(o => o.label) : null;
    conv.quickReplies = options;
    if (j.say) addMsg(conv, { who: "agent", text: j.say, why: j.why_next || "", options });
    if (j.degraded && !conv.toldDegraded) { conv.toldDegraded = true; addMsg(conv, { who: "note", text: t("c.degraded") }); }
    if (fresh || !chatES) chatEvents();
    save(); if (S) derive(conv, S);
  }
  async function directReport(conv, text, opts) {
    let r = null;
    if (conv.ask && conv.reports.length) { r = await api("POST", `/api/report/${encodeURIComponent(conv.ask.report || conv.reports[0])}/answer`, { text }); if (r.ok) { conv.ask = null; addMsg(conv, { who: "agent", text: t("c.added") }); return; } }
    r = await api("POST", "/api/report", { channel: "whatsapp", text, zone: opts.zone || store.zone || null, preset: opts.preset || null, source: store.name || "asistente", lang: store.lang, reply_to: conv.reports[0] || undefined });
    if (!r.ok) throw new Error("report");
    const firstOne = !conv.reports.length;
    if (r.j.report_id) conv.reports.push(r.j.report_id);
    const ins = normInstr(r.j.safety); if (ins && firstOne) { conv.instr = ins; conv.instrOpen = true; }
    addMsg(conv, { who: "agent", text: t(firstOne ? "c.ack" : "c.added") });
    if (!conv.toldDirect) { conv.toldDirect = true; addMsg(conv, { who: "note", text: t("c.direct") }); }
    save(); if (S) derive(conv, S);
  }

  /* Novedades que el servidor empuja a ESTA conversación: preguntas de Mando y, si el estado general no llega, cambios de estado. */
  let chatES = null, chatESsid = null, chatFails = 0;
  function chatEvents() {
    const conv = curConv();
    if (chatES && (!conv || chatESsid !== conv.sid)) { chatES.close(); chatES = null; }
    if (!conv || !conv.sid || chatES || !window.EventSource) return;
    chatESsid = conv.sid;
    const es = (chatES = new EventSource(`/api/chat/${encodeURIComponent(conv.sid)}/events?after=${conv.evSeq || 0}`));
    const on = (ev) => {
      let e; try { e = JSON.parse(ev.data); } catch (x) { return; }
      chatFails = 0; if (e.seq) conv.evSeq = Math.max(conv.evSeq || 0, e.seq);
      if (e.type === "ask") {
        conv.quickReplies=null;
        conv.ask = { action: e.action_id, q: e.text }; upsert(conv, "ask:" + (e.action_id || e.seq), "ask", { q: e.text, open: true }, "ask"); renderChat(); scrollEnd(); }
      else if (!sseLive && e.text) addMsg(conv, { id: "ev" + e.seq, who: "mando", text: e.text });
      save();
    };
    es.addEventListener("ask", on); es.addEventListener("status", on); es.onmessage = on;
    es.onerror = () => { es.close(); if (chatES === es) chatES = null; if (++chatFails < 6) setTimeout(chatEvents, 1500 * chatFails); };
  }

  /* ------------------------------------------------------------------ de lo que dice /api/state a TU hilo */
  const CLOSED = ["resolved", "false_alarm", "failed"];
  function roleOf(action, res, call) {
    if (call && call.title) return call.title;
    const why = action.why || "", name = (res && res.name) || "";
    if (name && why.startsWith(name + " (")) { const rest = why.slice(name.length + 2), end = rest.indexOf("): "); if (end > 0) return rest.slice(0, end); }
    return "";
  }
  function derive(conv, s) {
    const ids = conv.reports; if (!ids.length) return;
    const L = (conv.live = conv.live || {});
    const incs = (s.incidents || []).filter((i) => (i.reports || []).some((r) => ids.includes(r)));
    const inc = incs.sort((a, b) => (CLOSED.includes(a.status) - CLOSED.includes(b.status)) || ((b.priority || 0) - (a.priority || 0)))[0];
    if (!inc) { if (!L.inc) Object.assign(L, { stage: 0, tone: "", now: ["h.received"] }); return; }
    const reserved = !!(inc.reserved || inc.zone_masked);
    const resById = {}; (s.resources || []).forEach((r) => (resById[r.id] = r));
    Object.assign(L, { inc: inc.id, status: inc.status, reserved, label: reserved ? "" : inc.label || "", zone: reserved ? null : inc.zone, zoneName: reserved ? "" : inc.zone_name || "",
      prio: reserved ? null : inc.priority, explain: reserved ? "" : inc.explain || "", team: [] });
    upsert(conv, "understood", reserved ? "reserved" : "understood", reserved ? {} : { label: inc.label, z: inc.zone_name || "" });
    let now = reserved ? ["h.reserved"] : ["h.understood", { label: inc.label }], tone = "", stage = 1;
    if (!reserved) {
      const others = (inc.reports || []).filter((r) => !ids.includes(r)).length;
      if (others > 0) { upsert(conv, "merged", "merged", { n: others }); now = ["h.merged", { n: others }]; }
      if (inc.priority != null && !conv.msgs.some((m) => m.id === "prio")) upsert(conv, "prio", "prio", { v: inc.priority, explain: inc.explain || "" });
      if (inc.hold) { upsert(conv, "hold", "hold", {}); now = ["h.hold"]; tone = "warn"; }
      if ((inc.waiting || []).length) { const need = inc.waiting.map((n) => t("need." + n)).join(", "); upsert(conv, "wait:" + inc.waiting.join("+"), "wait", { needs: inc.waiting }, "warn"); now = ["h.wait", { need }]; tone = "warn"; }
    }
    const acts = (s.actions || []).filter((a) => a.incident === inc.id || ((a.params || {}).reports || []).some((r) => ids.includes(r)));
    const calls = ((s.calls || {}).calls || []);
    acts.forEach((a) => {
      const p = a.params || {};
      if (a.kind === "dispatch") {
        const res = resById[a.resource], call = calls.find((c) => c.action_id === a.id), name = (res && res.name) || (call && call.to) || "", role = roleOf(a, res, call);
        const who = reserved ? "" : role ? `${role}` : name;
        if (res) L.team.push({ id: res.id, kind: res.kind, zone: res.zone, status: res.status, eta: res.eta, name: res.name });
        if (reserved) { upsert(conv, "r_onway", "r_onway", {}); stage = Math.max(stage, 2); if (p.outcome === "on_scene") { upsert(conv, "r_there", "r_there", {}); stage = 3; } return; }
        upsert(conv, `d:${a.id}:call`, "calling", { who, name });
        const result = (call && call.result) || (a.status === "rejected" ? "reject" : a.status === "failed" ? "no_answer" : a.status === "done" ? "accept" : null);
        if (a.status === "executing" && !result) { now = ["h.calling", { who }]; tone = "warn"; stage = Math.max(stage, 1); }
        if (result === "accept") { const eta = call && call.eta_min != null ? call.eta_min : p.eta; upsert(conv, `d:${a.id}:res`, "accept", { who: name, eta }, "ok"); stage = Math.max(stage, 2);
          if (p.outcome !== "on_scene") { now = [eta ? "h.accept" : "h.accept0", { who: name, eta: (res && res.status === "en_route" && res.eta) || eta }]; tone = "ok"; } }
        if (result === "reject" || result === "no_answer") { upsert(conv, `d:${a.id}:res`, result === "reject" ? "reject" : "noanswer", { who: name }, "bad"); now = [result === "reject" ? "h.reject" : "h.noanswer", { who: name }]; tone = "bad"; }
        if (p.outcome === "on_scene") { upsert(conv, `d:${a.id}:scene`, "onscene", { who: name }, "ok"); stage = Math.max(stage, 3); now = ["h.onscene"]; tone = "ok"; }
      } else if (a.kind === "ask" && !a.resource && !resById[p.to] && (p.reports || []).some((r) => ids.includes(r)) && !reserved) {
        const open = a.status === "executing" || a.status === "proposed";
        upsert(conv, "ask:" + a.id, "ask", { q: p.message || "", purpose: p.purpose || "", open }, "ask");
        if (open) { conv.ask = conv.ask || { action: a.id, q: p.message, report: (p.reports || []).find((r) => ids.includes(r)) }; conv.ask.purpose = p.purpose; }
        else if (conv.ask && conv.ask.action === a.id) conv.ask = null;
      } else if (a.kind === "request_external" && !reserved) {
        const k = a.status === "awaiting_approval" || a.status === "proposed" ? "ext_wait" : a.status === "rejected" || a.status === "cancelled" ? "ext_no" : "ext_ok";
        upsert(conv, "ext:" + a.id, k, {}, k === "ext_wait" ? "warn" : "");
      }
    });
    if (!reserved && inc.plan) { const plan = (s.plans || []).find((p) => p.id === inc.plan); if (plan && plan.supersedes && plan.why) upsert(conv, "plan:" + plan.id, "replan", { why: plan.why }); }
    if (conv.ask && conv.ask.q && !CLOSED.includes(inc.status)) { now = ["h.ask", { q: conv.ask.q }]; tone = "ask"; }
    if (inc.status === "in_progress") { if (!reserved) upsert(conv, "st:in", "in_progress", {}, "ok"); stage = Math.max(stage, 3); if (!conv.ask) { now = ["h.onscene"]; tone = "ok"; } }
    if (inc.status === "resolved") { upsert(conv, "st:res", "resolved", {}, "ok"); stage = 4; now = ["h.resolved"]; tone = "ok"; conv.ask = null; }
    if (inc.status === "failed") { upsert(conv, "st:fail", "failed", {}, "bad"); now = ["h.failed"]; tone = "bad"; conv.ask = null; }
    if (inc.status === "false_alarm") { upsert(conv, "st:false", "false", {}); stage = 4; now = ["h.false"]; tone = ""; conv.ask = null; }
    const key = JSON.stringify(now); if (L.nowKey !== key) { L.nowKey = key; L.changed = Date.now(); }
    Object.assign(L, { now, tone, stage });
  }

  /* Si el estado general no llega (SSE caído), se sondea SOLO tu aviso: es poco, pero no te quedas a ciegas. */
  async function pollReports() {
    const conv = curConv(); if (!conv || !conv.reports.length) return;
    if (sseLive && conv.sid) return;   // con todo en marcha no hace falta; sin conversación en el servidor, el sondeo es lo que dice «sigo aquí»
    try {
      const { ok, j } = await api("GET", "/api/report/" + encodeURIComponent(conv.reports[0])); if (!ok) return;
      if (j.ask && j.ask.question) { conv.ask = { action: j.ask.action_id, q: j.ask.question, report: conv.reports[0] }; upsert(conv, "ask:" + j.ask.action_id, "ask", { q: j.ask.question, open: true }, "ask"); }
      if (!sseLive && j.found) {
        const L = (conv.live = conv.live || {});
        Object.assign(L, { inc: j.incident, status: j.status, reserved: !!j.reserved, label: j.label, zoneName: j.zone_name || "", prio: j.priority, explain: j.explain || "" });
        upsert(conv, "understood", j.reserved ? "reserved" : "understood", j.reserved ? {} : { label: j.label, z: j.zone_name || "" });
        if (j.merged_with > 0) upsert(conv, "merged", "merged", { n: j.merged_with });
        const c = j.call || {}, who = (j.resource && (j.resource.role || j.resource.name)) || "";
        L.stage = j.status === "resolved" ? 4 : j.status === "in_progress" ? 3 : c.state === "acepta" ? 2 : 1;
        L.now = j.status === "resolved" ? ["h.resolved"] : j.status === "in_progress" ? ["h.onscene"] : c.state === "acepta" ? ["h.accept", { who, eta: c.eta_min }] : c.state === "llamando" ? ["h.calling", { who }] : ["h.understood", { label: j.label }];
      }
      renderChat();
    } catch (e) { /* se reintenta solo */ }
  }
  setInterval(pollReports, 2500);

  /* ------------------------------------------------------------------ pintar la conversación */
  function msgHTML(m, conv) {
    const fresh = Date.now() - m.at < 1200 ? " new" : "";
    const hh = m.hh ? `<i>${esc(m.hh)}</i>` : "";
    if (m.who === "me") return `<div class="msg me${fresh}"><span class="who">${esc(t("who.me"))}${hh}</span>${esc(m.text)}</div>`;
    if (m.who === "note") return `<div class="msg note${m.err ? " err" : ""}">${esc(m.text)}</div>`;
    if (m.who === "agent") {
      const body = m.kind === "greet" ? esc(t("c.greet")) : esc(m.text);
      const why = m.kind === "greet" ? t("c.greet.why") : m.why;
      return `<div class="msg agent${fresh}"><span class="who">${esc(t("who.agent"))}${hh}</span>${body}${why ? `<details class="whyq"><summary>${esc(t("c.whyq"))}</summary>${esc(why)}</details>` : ""}</div>`;
    }
    const p = m.p || {}; let body;
    if (!m.kind) body = esc(m.text);
    else if (m.kind === "understood") body = t("m.understood", { label: esc(p.label), where: p.z ? t("m.where", { z: esc(p.z) }) : t("m.nowhere") });
    else if (m.kind === "wait") body = t("m.wait", { need: esc((p.needs || []).map((n) => t("need." + n)).join(", ")) });
    else if (m.kind === "prio") body = t("m.prio", { v: num(p.v) }) + (p.explain ? `<span class="why">${esc(p.explain)}${esc(t("server.es"))}</span>` : "");
    else if (m.kind === "replan") body = t("m.replan", { why: esc(capital(p.why)) + "." });
    else if (m.kind === "reserved") body = t("m.reserved");
    else { const v = {}; Object.keys(p).forEach((k) => (v[k] = k === "eta" ? num(p[k], 0) : esc(p[k]))); body = t("m." + m.kind + (m.kind === "accept" && !p.eta ? "0" : ""), v); }
    if (m.kind === "calling" && conv.msgs.every((x) => x.id !== m.id.replace(":call", ":res"))) body += `<span class="dots3" aria-label="${esc(t("c.typing"))}"><i></i><i></i><i></i></span>`;
    return `<div class="msg mando${m.tone ? " t-" + m.tone : ""}${fresh}"><span class="who">${esc(t("who.mando"))}${hh}</span>${body}</div>`;
  }
  const capital = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : "");

  function inferReplies(conv) {
    if (sending) return [];
    // La pregunta del agente sigue vigente aunque llegue una actualización del equipo al hilo.
    if (Array.isArray(conv.quickReplies)) return conv.quickReplies.map(o => typeof o === "string" ? {label:o,value:o} : o);
    const last = conv.msgs[conv.msgs.length - 1]; if (!last || last.who === "me" || last.who === "note" || sending) return [];
    if (last.kind === "greet") return [];
    const pin = { label: t("q.map"), act: "map", ic: "i-pin" }, dk = { label: t("q.dk") };
    if (last.who === "mando") { if (last.kind !== "ask" || !(last.p || {}).open) return []; }
    if (Array.isArray(last.options)) return last.options.map(o => typeof o === "string" ? {label:o,value:o} : o);
    const q = last.who === "mando" ? (last.p || {}).q || "" : last.text || "";
    if (!/\?/.test(q)) return [];
    if ((last.p || {}).purpose === "zone" || /d[oó]nde|qu[eé] (puerta|zona)|where|which (gate|zone|area)/i.test(q)) return [pin].concat(store.zone ? [{ label: t("q.here", { z: zoneName(store.zone) }) }] : [], [dk]);
    if (/cu[aá]nt[oa]s|how many/i.test(q)) return [{ label: "1" }, { label: "2" }, { label: t("q.3") }, dk];
    if (/^[\s¿]*(respira|responde|est[aá]s?|hay|puedes?|sigue|tiene|has|ves|se |es |son |hace|necesit|is |are |can |do |does |did |has |have |was )/i.test(q.split(/[.!]\s+/).pop() || q)) return [{ label: t("q.yes") }, { label: t("q.no") }, dk];
    return [];
  }

  function localSlots(conv) {
    const L = conv.live || {};
    return [{ id: "where", label: t("slot.where"), value: L.zoneName || zoneName(store.zone) || null }, { id: "what", label: t("slot.what"), value: L.label || (conv.first ? conv.first.slice(0, 40) : null) }];
  }
  let metroTimer = 0;
  function renderChat() {
    const conv = curConv(); if (!conv || view !== "chat") return;
    // varias conversaciones en paralelo
    const tabs = store.convs.length > 1 || conv.reports.length;
    $("th-tabs").hidden = !tabs;
    if (tabs) setHTML($("th-tabs"), store.convs.map((c) => {
      const L = c.live || {}, st = L.now ? plain(t(L.now[0], L.now[1])) : c.reports.length ? t("h.received") : "…";
      return `<button type="button" role="tab" class="th-tab${c.unread ? " unread" : ""}" aria-selected="${c.cid === conv.cid}" data-cid="${esc(c.cid)}"><b>${esc(L.label ? capital(L.label) : c.first ? c.first.slice(0, 28) : t("c.conv", { n: c.n }))}</b><small>${esc(st)}</small></button>`;
    }).join("") + `<button type="button" class="th-tab add" data-cid="new">${icon("i-plus")}${esc(t("c.new"))}</button>`);

    // línea de estado viva
    const L = conv.live, hero = $("th-hero");
    hero.hidden = !conv.reports.length;
    if (conv.reports.length) {
      const now = (L && L.now) || ["h.received"], stage = (L && L.stage) || 0, swap = L && L.changed && Date.now() - L.changed < 900;
      hero.className = "hero" + (L && L.tone ? " tone-" + L.tone : "");
      const sub = L && L.inc && !L.reserved ? `${esc(capital(L.label))}${L.zoneName ? " · " + esc(L.zoneName) : ""}` : esc(t("h.yourreport"));
      const prio = L && L.prio != null ? `<details><summary>${esc(t("h.prio", { v: num(L.prio) }))} · ${esc(t("h.why"))}</summary>${esc(L.explain)}${esc(t("server.es"))}</details>` : "";
      const failed = L && L.status === "failed";
      setHTML(hero, `<div class="what"><span>${sub}</span></div><p class="now${swap ? " swap" : ""}">${esc(plain(t(now[0], now[1])))}</p>
        <div class="rail">${[0, 1, 2, 3, 4].map((i) => `<i class="${i <= stage ? "on" : ""}${i === stage && stage < 4 && !failed ? " cur" : ""}"></i>`).join("")}</div>
        <div class="rail-labels">${[0, 1, 2, 3, 4].map((i) => `<span class="${i === stage ? "on" : ""}">${esc(t("rail." + i))}</span>`).join("")}</div>${prio}`);
    }
    // instrucción de seguridad, fija arriba
    const box = $("th-instr"); box.hidden = !conv.instr;
    clearInterval(metroTimer);
    if (conv.instr) {
      const I = conv.instr, open = conv.instrOpen !== false;
      box.className = "instr" + (open ? "" : " closed");
      setHTML(box, `<button type="button" class="instr-head" aria-expanded="${open}">${icon("i-shield")}<span>${esc(I.title || t("instr.title"))}</span><i>${esc(t(open ? "instr.hide" : "instr.show"))}</i></button>
        <ol>${I.steps.map((s) => `<li>${esc(s)}</li>`).join("")}</ol>${I.cpr ? `<div class="metro"><div class="metro-dot" id="metro-dot">${icon("i-heart")}</div><p><b>${esc(t("metro.b"))}</b><small>${esc(t("metro.s"))}</small></p></div>` : ""}`);
      if (I.cpr && open && !reduced()) metroTimer = setInterval(() => { const d = $("metro-dot"); if (!d) return; d.classList.add("beat"); setTimeout(() => d.classList.remove("beat"), 160); }, 60000 / 110);
    }
    // burbujas
    const started = conv.msgs.some((m) => m.who === "me");
    let html = conv.msgs.map((m) => msgHTML(m, conv)).join("");
    if (!started) html += `<div class="starters">${CHIPS.map(([k, ic]) => `<button type="button" class="chip" data-chip="${k}">${icon(ic)}<span>${esc(t("chip." + k))}</span></button>`).join("")}</div>`;
    if (sending) html += `<div class="msg agent typing"><span class="dots3" aria-label="${esc(t("c.typing"))}"><i></i><i></i><i></i></span></div>`;
    setHTML($("th-chat"), html);
    $("talk").className = "talk" + (started ? " small" : "");
    // respuestas rápidas y «lo que ya sé»
    setHTML($("quick"), inferReplies(conv).map((o) => `<button type="button" class="qr" data-say="${esc(o.value ?? o.label)}"${o.act ? ` data-qact="${o.act}"` : ""}>${o.ic ? icon(o.ic) : ""}${esc(o.label)}</button>`).join(""));
    const slots = started ? (Array.isArray(conv.slots) ? conv.slots : localSlots(conv)) : [];
    const freshSlots = conv.slotsAt && Date.now() - conv.slotsAt < 1500;
    setHTML($("slots"), slots.map((s) => { const full = s.value != null && s.value !== "" && s.value !== false || s.value === false; const v = s.value === true ? t("q.yes") : s.value === false ? t("q.no") : s.value;
      return `<span class="slot${full ? " full" + (freshSlots ? " fresh" : "") : ""}">${full ? icon("i-check") : ""}${esc(s.label)}${full ? `: <b>${esc(v)}</b>` : ""}</span>`; }).join(""));
    $("slots").setAttribute("aria-label", t("slot.known"));
    $("c-text").placeholder = t(conv.ask ? "c.placeholder.answer" : "c.placeholder");
    // mini-plano
    const showMini = !!(L && L.inc && !L.reserved);
    $("mini-fig").hidden = !showMini;
    if (showMini) miniDraw();
  }
  const plain = (s) => String(s).replace(/<[^>]+>/g, "");

  $("th-chat").addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-chip]"); if (!b) return;
    buzz(10);
    if (b.dataset.chip === "other") { $("c-text").focus(); return; }
    const preset = { collapse: "collapse", surge: "surge", fight: "fight", smoke: "smoke", child: "child" }[b.dataset.chip] || null;
    sayToAgent(t("say." + b.dataset.chip), { preset });
  });
  $("quick").addEventListener("click", (ev) => {
    const b = ev.target.closest(".qr"); if (!b) return; buzz(10);
    if (b.dataset.qact === "map") return zoneSheet((z) => { if (z) { setZone(z); sayToAgent(t("q.here", { z: zoneName(z) }), { zone: z }); } else sayToAgent(t("q.dk")); });
    sayToAgent(b.dataset.say, {display:b.textContent.trim()});
  });
  $("th-instr").addEventListener("click", (ev) => { if (!ev.target.closest(".instr-head")) return; const c = curConv(); c.instrOpen = c.instrOpen === false; save(); renderChat(); });
  $("th-tabs").addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-cid]"); if (!b) return;
    if (b.dataset.cid === "new") newConv(); else { store.cur = b.dataset.cid; const c = curConv(); if (c) c.unread = 0; }
    badge(); save(); chatEvents(); renderChat(); scrollEnd(true);
  });
  $("composer").addEventListener("submit", (ev) => { ev.preventDefault(); const v = $("c-text").value; if (!v.trim()) return; $("c-text").value = ""; sayToAgent(v); });

  /* dictado: solo si el navegador lo trae */
  (function mic() {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition, b = $("btn-mic");
    if (!SR) { b.closest(".reply-row").classList.add("nomic"); return; }
    b.hidden = false; let rec = null;
    b.onclick = () => {
      if (rec) { rec.stop(); return; }
      try {
        rec = new SR(); rec.lang = store.lang === "es" ? "es-ES" : "en-US"; rec.interimResults = true;
        rec.onresult = (e) => { $("c-text").value = Array.from(e.results).map((r) => r[0].transcript).join(" "); };
        rec.onerror = (e) => { if (e.error !== "aborted" && e.error !== "no-speech") toast(t("c.mic.off")); };
        rec.onend = () => { rec = null; b.classList.remove("rec"); $("c-text").focus(); };
        rec.start(); b.classList.add("rec"); buzz(15);
      } catch (e) { rec = null; toast(t("c.mic.off")); }
    };
  })();

  /* ------------------------------------------------------------------ mini-plano: tu zona, quién va hacia ti, cuánta gente hay */
  let miniPlan = null, miniVB = null, miniAnim = 0;
  function miniDraw() {
    const conv = curConv(), L = conv && conv.live; if (!F || !L || !S) return;
    if (!miniPlan) { miniPlan = makePlan($("plan-mini"), {}); miniPlan.gYou = window.PLANO.el("g", { class: "you" }, miniPlan.ref.gPins); miniPlan.toks = {}; }
    const P = miniPlan, PL = window.PLANO, my = L.zone || store.zone;
    P.density(S.zones);
    Object.entries(P.ref.zones).forEach(([k, z]) => z.g.classList.toggle("me", k === my));
    P.gYou.innerHTML = "";
    if (my && PL.ZONES[my]) { const c = PL.center(my); PL.el("circle", { class: "halo", cx: c.x, cy: c.y + 26, r: 16 }, P.gYou); PL.el("circle", { cx: c.x, cy: c.y + 26, r: 13 }, P.gYou); }
    const seen = {}; P.ref.gReroutes.innerHTML = "";
    (L.team || []).forEach((r, i) => {
      if (!PL.ZONES[r.zone] || seen[r.id]) return; seen[r.id] = 1;
      let g = P.toks[r.id];
      if (!g) { g = P.toks[r.id] = PL.el("g", { class: "tok k-" + r.kind }, P.ref.gTokens); PL.el("circle", { r: 19 }, g);
        if (r.kind === "medical" || r.kind === "ambulance") PL.el("path", { d: "M-9 0H9M0-9V9" }, g); else PL.el("text", {}, g).textContent = (r.kind || "?").charAt(0).toUpperCase(); }
      const c = PL.center(r.zone), x = c.x + (i % 3 - 1) * 46 * (r.zone === my ? 1 : 0.4), y = c.y - 24;
      g.style.transform = `translate(${x}px, ${y}px)`; g.classList.toggle("off", r.status === "offline");
      if (my && r.zone !== my && r.status === "en_route") { const m = PL.center(my); PL.el("path", { class: "trail", d: `M${x} ${y} L${m.x} ${m.y + 26}` }, P.ref.gReroutes); }
    });
    Object.keys(P.toks).forEach((id) => { if (!seen[id]) { P.toks[id].remove(); delete P.toks[id]; } });
    // encuadre: tu zona y quien viene, no el recinto entero
    const zs = [my].concat((L.team || []).map((r) => r.zone)).filter((z) => PL.ZONES[z]);
    let vb = [0, 0, PL.W, PL.H];
    if (zs.length) {
      let x1 = 1e9, y1 = 1e9, x2 = -1e9, y2 = -1e9;
      zs.forEach((z) => { const Z = PL.ZONES[z]; x1 = Math.min(x1, Z.x); y1 = Math.min(y1, Z.y); x2 = Math.max(x2, Z.x + Z.w); y2 = Math.max(y2, Z.y + Z.h); });
      const pad = 90, ar = 1.75; let w = Math.max(640, x2 - x1 + pad * 2), h = Math.max(w / ar, y2 - y1 + pad * 2); w = Math.max(w, h * ar);
      const cx = (x1 + x2) / 2, cy = (y1 + y2) / 2;
      vb = [Math.max(0, Math.min(PL.W - w, cx - w / 2)), Math.max(0, Math.min(PL.H - h, cy - h / 2)), Math.min(w, PL.W), Math.min(h, PL.H)];
    }
    zoomTo(vb);
    const zd = (S.zones || []).find((z) => z.id === my);
    $("mini-cap").innerHTML = zd ? t("mini.dens", { z: esc(zd.name), d: num(zd.density), word: esc(t(zd.density > 5 ? "dens.bad" : zd.density >= 2 ? "dens.mid" : "dens.ok")) }) : esc(t("mini.nozone"));
  }
  function zoomTo(vb) {
    const svg = $("plan-mini");
    if (!miniVB || reduced()) { miniVB = vb; svg.setAttribute("viewBox", vb.join(" ")); return; }
    if (vb.every((v, i) => Math.abs(v - miniVB[i]) < 2)) return;
    cancelAnimationFrame(miniAnim);
    const from = miniVB.slice(), t0 = performance.now();
    const step = (now) => { const k = Math.min(1, (now - t0) / 700), e = 1 - Math.pow(1 - k, 3); miniVB = from.map((v, i) => v + (vb[i] - v) * e); svg.setAttribute("viewBox", miniVB.map((v) => v.toFixed(1)).join(" ")); if (k < 1) miniAnim = requestAnimationFrame(step); };
    miniAnim = requestAnimationFrame(step);
  }

  /* ------------------------------------------------------------------ el festival ahora */
  let planLive = null, lastCount = null;
  function renderLive() {
    if (view !== "live" || !S || !F) return;
    if (!planLive) planLive = makePlan($("plan-live"), { dens: true });
    planLive.density(S.zones);
    const open = (S.fronts || []).length, el = $("lv-n");
    el.textContent = String(open); if (lastCount !== null && lastCount !== open) { el.classList.remove("bump"); void el.offsetWidth; el.classList.add("bump"); } lastCount = open;
    $("lv-n-text").textContent = open === 0 ? t("l.n0") : open === 1 ? t("l.n1") : t("l.n");
    $("lv-n-sub").textContent = t("l.sub", { hh: S.clock.hhmm, temp: S.weather.temp_c, wind: S.weather.wind_kmh });
    const avoid = (S.zones || []).filter((z) => z.density > 4 || z.state !== "open").sort((a, b) => b.density - a.density);
    setHTML($("lv-avoid"), avoid.length ? `<div class="rows">${avoid.map((z) => `<div class="row ${z.density > 5 || z.state === "closed" ? "bad" : "mid"}">${icon("i-people")}<div>${esc(z.name)}<small>${esc(z.state === "closed" ? t("l.closed") : z.state !== "open" ? t("l.restricted") : t("l.avoid", { d: num(z.density) }))}</small></div><span class="val">${num(z.density)}</span></div>`).join("")}</div>`
      : `<p class="empty small">${esc(t("l.avoid.none"))}</p>`);
    const pa = (S.actions || []).filter((a) => a.kind === "broadcast" && ["done", "executing"].includes(a.status) && (a.params || {}).message).slice(-5).reverse();
    setHTML($("lv-pa"), pa.length ? `<div class="rows">${pa.map((a) => `<div class="row">${icon("i-mega")}<div>${esc(a.params.message)}<small>${esc(t("l.pa.at", { hh: hhmmAt(a.t), z: zoneName(a.zone) || "—" }))}</small></div></div>`).join("")}</div>`
      : `<p class="empty small">${esc(t("l.pa.none"))}</p>`);
    const fr = (S.fronts || []).slice(0, 6);
    setHTML($("lv-fronts"), fr.length ? `<div class="rows">${fr.map((f) => `<div class="row${f.new ? " new" : ""}">${icon(f.reserved ? "i-shield" : "i-bell")}<div>${esc(f.reserved ? t("l.reserved") : capital(f.label))}<small>${esc(f.reserved ? "" : f.zone_name + " · ")}${esc(f.state)}${f.resources && f.resources.length && !f.reserved ? " · " + esc(f.resources.join(", ")) : ""}</small></div><span class="val" title="${esc(t("l.prio"))}">${f.reserved ? "" : num(f.priority)}</span></div>`).join("")}</div>`
      : `<p class="empty small">${esc(t("l.fronts.none"))}</p>`);
  }
  function hhmmAt(tmin) {
    if (!S) return ""; const [h, m] = S.clock.hhmm.split(":").map(Number); let x = h * 60 + m - (S.t - tmin); x = ((x % 1440) + 1440) % 1440;
    return String(Math.floor(x / 60)).padStart(2, "0") + ":" + String(x % 60).padStart(2, "0");
  }

  /* ------------------------------------------------------------------ pon a prueba a Mando */
  const GRACE = 12;
  function strikesLeft() { const mine = 3 - store.strikes.length, room = S && S.scoreboard ? S.scoreboard.left : 3; return { mine: Math.max(0, mine), room, n: Math.max(0, Math.min(mine, room == null ? 3 : room)) }; }
  function renderTest() {
    if (view !== "test" || !F) return;
    const left = strikesLeft();
    setHTML($("x-dots"), [0, 1, 2].map((i) => `<i class="${i < left.n ? "on" : ""}"></i>`).join(""));
    $("x-left").textContent = left.n ? t("x.left", { n: left.n }) : left.mine ? t("x.left.room") : t("x.left0");
    setHTML($("x-cards"), Object.keys(F.strike_presets || {}).map((k) => `<button type="button" class="card" data-k="${esc(k)}" ${left.n ? "" : "disabled"}>${icon(STRIKE_ICON[k] || "i-bolt")}<span><b>${esc(TX.es["x." + k] ? t("x." + k) : F.strike_presets[k])}</b><small>${esc(TX.es["x." + k + ".d"] ? t("x." + k + ".d") : "")}</small></span></button>`).join(""));
    if (S && S.scoreboard) { $("sc-j").textContent = S.scoreboard.jury || 0; $("sc-m").textContent = S.scoreboard.mando || 0; }
    setHTML($("x-results"), store.strikes.slice().reverse().map(resultHTML).join(""));
  }
  function trackStrikes() {
    if (!S) return;
    store.strikes.forEach((k) => {
      const all = S.strikes || [], me = all.find((x) => x.t === k.t && x.label === k.label && (x.author || "") === (k.author || ""));
      if (me) k.outcome = me.outcome;
      const next = all.filter((x) => x.t > k.t).map((x) => x.t).sort((a, b) => a - b)[0], end = Math.min(k.t + GRACE, next == null ? 1e9 : next);
      k.broken = k.broken || []; k.plans = k.plans || []; k.calls = k.calls || [];
      (S.plans || []).forEach((p) => {
        (p.assumptions || []).forEach((a) => { if (a.broken_at != null && a.broken_at >= k.t && a.broken_at <= end && !k.broken.some((b) => b.id === a.id)) { k.broken.push({ id: a.id, text: a.text }); buzz([20, 60, 20]); } });
        if (p.t >= k.t && p.t <= end && p.supersedes && !k.plans.some((x) => x.id === p.id)) k.plans.push({ id: p.id, o: p.objective, why: p.why });
      });
      ((S.calls || {}).calls || []).forEach((c) => { if (c.t >= k.t && c.t <= end && (c.result === "reject" || c.result === "no_answer") && c.kind === "dispatch" && !k.calls.some((x) => x.id === c.action_id)) k.calls.push({ id: c.action_id, who: c.to, res: c.result }); });
      k.leftMin = Math.max(0, k.t + GRACE - S.t);
      if (S.scoreboard && k.outcome === "failed") { k.locked = (S.scoreboard.locked || {}).n || k.locked || null; k.nextN = S.scoreboard.can_lock ? S.scoreboard.next_n : null; }
    });
    save();
  }
  function resultHTML(k) {
    const items = [];
    (k.broken || []).forEach((b) => items.push(`<li class="broke">${t("x.r.counted", { a: esc(b.text) })}</li>`));
    (k.calls || []).forEach((c) => items.push(`<li>${t("x.r.nocall", { who: esc(c.who), res: esc(t(c.res === "reject" ? "x.r.rejects" : "x.r.silent")) })}</li>`));
    (k.plans || []).slice(-3).forEach((p) => items.push(`<li class="plan">${t("x.r.plan", { o: esc(p.o) })}<small>${esc(capital(p.why))}${esc(t("server.es"))}</small></li>`));
    if (!items.length) items.push(`<li class="wait">${esc(t(k.outcome === "absorbed" ? "x.r.nochange" : "x.r.waiting"))}</li>`);
    let verdict;
    if (k.outcome === "failed") verdict = `<div class="verdict jury">${esc(t("x.v.jury"))}<small>${esc(t("x.v.jury.s"))} ${esc(k.locked ? t("x.v.locked", { n: k.locked }) : k.nextN ? t("x.v.canlock", { n: k.nextN }) : "")}</small></div>`;
    else if (k.outcome === "absorbed") verdict = `<div class="verdict mando">${esc(t("x.v.mando"))}<small>${esc(t("x.v.mando.s"))}</small></div>`;
    else verdict = `<div class="verdict">${esc(t("x.v.pending", { m: k.leftMin == null ? GRACE : k.leftMin }))}</div>`;
    return `<article class="result"><h3>${esc(TX.es["x." + k.key] ? t("x." + k.key) : k.label)}${k.zone ? " · " + esc(zoneName(k.zone)) : ""}</h3><p class="when">${esc(t("x.r.at", { hh: k.hh || "" }))}</p><ol>${items.join("")}</ol>${verdict}</article>`;
  }
  $("x-cards").addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-k]"); if (!b || b.disabled) return;
    const k = b.dataset.k, gate = k === "close_gate";
    openSheet(TX.es["x." + k] ? t("x." + k) : F.strike_presets[k], `<p>${esc(TX.es["x." + k + ".d"] ? t("x." + k + ".d") : "")}</p>
      ${gate ? `<p><b>${esc(t("x.which"))}</b></p><div class="gates">${["gate_a", "gate_b", "gate_c"].map((g, i) => `<button type="button" class="btn" data-gate="${g}" aria-pressed="${i === 0}">${esc((SHORT[store.lang] || SHORT.es)[g])}</button>`).join("")}</div>` : ""}
      <button type="button" class="btn danger wide" id="x-go">${icon("i-bolt")}<span>${esc(t("x.go"))}</span></button><button type="button" class="btn quiet wide" id="x-no">${esc(t("x.cancel"))}</button><p id="x-err" class="err" role="alert" hidden></p>`);
    let zone = gate ? "gate_a" : null;
    $("sheet-body").querySelectorAll("[data-gate]").forEach((g) => (g.onclick = () => { zone = g.dataset.gate; buzz(10); $("sheet-body").querySelectorAll("[data-gate]").forEach((x) => x.setAttribute("aria-pressed", String(x === g))); }));
    $("x-no").onclick = closeSheet;
    $("x-go").onclick = async () => {
      $("x-go").disabled = true;
      try {
        const r = await api("POST", "/api/strike", Object.assign({ preset: k, origin: "jury", author: store.name || t("hdr.anon", { n: thousands(store.num) }) }, zone ? { zone } : {}));
        if (!r.ok) { $("x-err").hidden = false; $("x-err").textContent = r.j.error || r.j.detail || t("c.fail"); $("x-go").disabled = false; return; }
        const it = r.j.strike || {};
        store.strikes.push({ key: k, t: it.t, label: it.label, author: it.author || "", zone, hh: S ? S.clock.hhmm : "", outcome: "pending", broken: [], plans: [], calls: [] });
        save(); buzz([30, 40, 60]); closeSheet(); toast(t("x.sent")); trackStrikes(); renderTest(); window.scrollTo({ top: 0, behavior: reduced() ? "auto" : "smooth" });
      } catch (e) { $("x-err").hidden = false; $("x-err").textContent = t("c.fail"); $("x-go").disabled = false; }
    };
  });

  /* ------------------------------------------------------------------ recorrido de la primera vez (3 pasos, saltable) */
  function tour(i) {
    i = i || 1;
    const pics = { 1: "i-thread", 2: "i-live", 3: "i-bolt" }, tabOf = { 1: "chat", 2: "chat", 3: "test" };
    document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("coach", b.dataset.tab === tabOf[i]));
    const end = () => { store.toured = true; save(); document.querySelectorAll(".tabs button").forEach((b) => b.classList.remove("coach")); };
    openSheet(t("tour." + i + ".t"), `<div class="tour-pic${i === 3 ? " v" : ""}">${icon(pics[i])}</div><p>${esc(t("tour." + i + ".b"))}</p>
      <button type="button" class="btn primary wide" id="tour-next">${esc(t(i < 3 ? "tour.next" : "tour.done"))}</button>${i < 3 ? `<button type="button" class="btn quiet wide" id="tour-skip">${esc(t("tour.skip"))}</button>` : ""}
      <div class="tour-dots" aria-label="${esc(t("tour.of", { i }))}">${[1, 2, 3].map((n) => `<i class="${n === i ? "on" : ""}"></i>`).join("")}</div>`, end);
    $("tour-next").onclick = () => { sheetClose = null; closeSheet(); if (i < 3) tour(i + 1); else end(); };
    if ($("tour-skip")) $("tour-skip").onclick = closeSheet;
  }

  /* ------------------------------------------------------------------ entrada */
  let planWelcome = null;
  function welcome() {
    $("welcome").hidden = false; $("app").hidden = true;
    planWelcome = makePlan($("plan-welcome"), { pick: true, onPick: (id) => { store.zone = id; save(); $("w-picked").textContent = t("w.picked", { z: zoneName(id) }); } });
    if (store.zone) { planWelcome.select(store.zone); $("w-picked").textContent = t("w.picked", { z: zoneName(store.zone) }); }
    $("w-name").value = store.name || "";
    $("w-unknown").onclick = () => { store.zone = null; planWelcome.select(null); $("w-picked").textContent = t("w.nozone"); buzz(10); };
    $("w-enter").onclick = enter; $("w-name").addEventListener("keydown", (e) => { if (e.key === "Enter") enter(); });
  }
  function enter() {
    store.name = $("w-name").value.trim().slice(0, 24); store.entered = true; save();
    $("welcome").hidden = true; startApp(); window.scrollTo(0, 0);
    if (!store.toured) tour(1);
  }
  function startApp() {
    $("app").hidden = false;
    if (!curConv()) newConv();
    header(); links(); badge(); go("chat"); chatEvents();
  }

  /* ------------------------------------------------------------------ estado en directo: SSE con reconexión */
  let es = null, retry = 0, wasDown = false, netTimer = 0;
  function net(down) {
    const el = $("net");
    if (down) { wasDown = true; el.className = "net"; el.textContent = t("net.down"); el.hidden = false; clearTimeout(netTimer); }
    else if (wasDown) { wasDown = false; el.className = "net back"; el.textContent = t("net.back"); el.hidden = false; clearTimeout(netTimer); netTimer = setTimeout(() => (el.hidden = true), 1800); }
  }
  function connect() {
    if (es) es.close();
    if (!window.EventSource) return setInterval(() => api("GET", "/api/state").then((r) => r.ok && onState(r.j)).catch(() => net(true)), 2000);
    es = new EventSource("/api/stream");
    es.addEventListener("state", (ev) => { let s; try { s = JSON.parse(ev.data); } catch (e) { return; } sseLive = true; retry = 0; net(false); onState(s); });
    es.onopen = () => { sseLive = true; retry = 0; net(false); };
    es.onerror = () => { es.close(); sseLive = false; net(true); retry = Math.min(retry + 1, 5); setTimeout(connect, 600 * Math.pow(1.7, retry)); };
  }
  window.addEventListener("online", () => { if (!sseLive) connect(); });
  window.addEventListener("offline", () => { sseLive = false; net(true); });
  document.addEventListener("visibilitychange", () => { if (!document.hidden && !sseLive) connect(); });

  let lastRender = 0, pending = 0;
  function onState(s) {
    S = s;
    if (store.session && s.session && store.session !== s.session.id && (store.convs.some((c) => c.reports.length) || store.strikes.length)) {
      store.convs = []; store.strikes = []; store.cur = null; if (store.entered) { newConv(); toast(t("sim.reset")); }
    }
    if (s.session) store.session = s.session.id;
    store.convs.forEach((c) => derive(c, s)); trackStrikes();
    const wait = 250 - (Date.now() - lastRender);   // el servidor emite hasta 10 veces por segundo: se pinta como mucho 4
    clearTimeout(pending); if (wait <= 0) renderAll(); else pending = setTimeout(renderAll, wait);
  }
  function renderAll(force) {
    lastRender = Date.now();
    if (!store.entered || !F) return;
    if (force) [$("th-chat"), $("th-hero"), $("th-instr"), $("quick"), $("slots"), $("th-tabs"), $("x-cards"), $("x-results"), $("lv-avoid"), $("lv-pa"), $("lv-fronts")].forEach((el) => cache.delete(el));
    header(); links();
    if (view === "chat") renderChat(); else if (view === "live") renderLive(); else renderTest();
  }

  /* ------------------------------------------------------------------ instalable: manifiesto generado aquí mismo */
  (function manifest() {
    try {
      const ic = "data:image/svg+xml," + encodeURIComponent("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 512 512'><rect width='512' height='512' fill='#06090d'/><path d='M196 116l120 36v208l-120 36z' fill='#ffb02e'/></svg>");
      const m = { name: "Festival Abierto", short_name: "Festival", start_url: location.origin + location.pathname + location.search, scope: location.origin + "/", display: "standalone",
        background_color: "#06090d", theme_color: "#06090d", icons: [{ src: ic, sizes: "512x512", type: "image/svg+xml", purpose: "any maskable" }] };
      const link = document.createElement("link"); link.rel = "manifest"; link.href = URL.createObjectURL(new Blob([JSON.stringify(m)], { type: "application/manifest+json" })); document.head.appendChild(link);
      const at = document.createElement("link"); at.rel = "apple-touch-icon"; at.href = ic; document.head.appendChild(at);
    } catch (e) { /* no es imprescindible */ }
  })();

  /* ------------------------------------------------------------------ arranque */
  applyThemeChrome();
  if (window.matchMedia) window.matchMedia("(prefers-color-scheme: light)").addEventListener("change", applyThemeChrome);
  (async function boot() {
    for (let i = 0; !F; i++) {
      try { const r = await api("GET", "/api/festival"); if (r.ok) { F = r.j; break; } } catch (e) { /* reintento */ }
      net(true); await new Promise((ok) => setTimeout(ok, Math.min(4000, 600 * (i + 1))));
    }
    net(false);
    (F.zones || []).forEach((z) => (names[z.id] = z.name));
    if (store.zone && !names[store.zone]) store.zone = null;
    if (store.entered) { $("welcome").hidden = true; startApp(); } else welcome();
    applyLang(); connect();
  })();
})();
