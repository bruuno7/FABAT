/* SALA DE CONTROL · MANDO
   Todo lo que se pinta sale de /api/state (SSE /api/stream) y de endpoints que ya existían.
   Si un dato no está en el estado, no se pinta o se deriva con la regla escrita y visible.
   Ningún texto del público se inserta como HTML: siempre por textContent o por E() (escape). */
(function () {
  "use strict";
  const U = window.MANDO_UI, P = window.SALA_PLANO;
  const $ = (id) => document.getElementById(id);
  const E = U.esc;
  const num = (v, d) => (v == null || !Number.isFinite(Number(v)) ? "—" : Number(v).toFixed(d == null ? 1 : d).replace(".", ","));

  // ---------------------------------------------------------------- vocabulario
  const GRAV = {
    vital: "VITAL", emergencia: "EMERGENCIA", urgente: "URGENTE", leve: "LEVE", sin: "SIN CLASIFICAR",
  };
  const KIND_ES = { dispatch: "ENVIAR", recall: "RETIRAR", notify: "AVISAR", ask: "PREGUNTAR", set_zone: "ZONA",
    reroute: "DESVIAR", broadcast: "MEGAFONÍA", request_external: "AYUDA EXTERNA", evacuate: "EVACUAR",
    stop_show: "PARAR CONCIERTO", resupply: "REABASTECER", merge: "FUSIONAR", dismiss: "DESCARTAR" };
  const RES_KIND_ES = { medical: "equipos médicos", ambulance: "ambulancias", security: "equipos de seguridad",
    tech: "equipos técnicos", logistics: "equipos de logística", volunteer: "voluntarios" };
  const GROUPS = [
    { title: "EQUIPOS MÉDICOS SVA", kinds: ["medical", "ambulance"] },
    { title: "SEGURIDAD Y CONTROL", kinds: ["security"] },
    { title: "APOYO E INFRAESTRUCTURA", kinds: ["tech", "logistics"] },
    { title: "VOLUNTARIADO Y RELEVO", kinds: ["volunteer"] },
  ];
  const TYPE_GLYPH = { medical: "✚", crowd: "▦", security: "⚠", violence: "⚠", infra: "⚙", weather: "☂", fire: "▲" };
  // Mismos nombres que motor/happyrobot/MAPA-WORKFLOWS.md. La ranura se deriva igual que hr_routing.workflow_slot.
  const WF_NAME = { sanitario: "mando-despacho-sanitario", seguridad: "mando-despacho-seguridad",
    tecnico: "mando-despacho-tecnico", logistica: "mando-despacho-logistica", director: "mando-escalada-director",
    externos: "mando-aviso-servicios-externos", difusion: "mando-difusion-publico", relevo: "mando-relevo-y-refuerzo",
    dispatch: "mando-despacho-telefono", webcall: "mando-despacho-webcall", notify: "despacho genérico (aviso)",
    ask: "despacho genérico (aclaración)", followup: "despacho genérico (seguimiento)", intake: "mando-ingesta-texto",
    voice: "mando-ingesta-voz", chat: "mando-asistente-chat" };
  const WF_ES = { sanitario: "sanitario", seguridad: "seguridad", tecnico: "técnico", logistica: "logística",
    director: "director", externos: "externos", difusion: "difusión", relevo: "relevo",
    dispatch: "genérico", webcall: "llamada web", notify: "genérico", ask: "genérico", followup: "genérico" };
  const SPEEDS = [1, 4, 16];

  // ---------------------------------------------------------------- estado local
  let S = null, F = null, plano = null, connected = false, firstPaint = true;
  let sel = { incident: null, zone: null, resource: null };
  let filter = "todos", query = "", showOldPlan = false;
  let chats = [], chatAt = 0, webcalls = [], webcallAt = 0;
  let whatif = null, toastTimer = 0;
  const beacons = new Map();
  const notes = new Map();   // nota escrita por el operador, por acción: sobrevive a cada repintado
  const armed = new Set();   // acciones graves esperando el segundo clic de confirmación

  // ---------------------------------------------------------------- utilidades
  function toast(text, bad) {
    const t = $("toast");
    t.textContent = text; t.hidden = false; t.style.background = bad ? "var(--bad)" : "var(--vital)";
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.hidden = true; }, 6000);
  }
  async function post(url, body) {
    try { return await U.api(url, body || {}); }
    catch (e) {
      const m = /operador/i.test(e.message) ? e.message + " Entra en /acceso o usa el puesto de control." : e.message;
      toast(m, true); return { ok: false, error: e.message };
    }
  }
  // Se construye a partir de plantillas cuyos valores dinámicos pasan SIEMPRE por E(): nada del público llega crudo.
  const painted = new WeakMap();
  function setHTML(el, html) {
    if (painted.get(el) === html) return;
    painted.set(el, html);
    const focus = document.activeElement, id = focus && focus.id, at = focus && focus.selectionStart;
    const t = document.createElement("template");
    t.innerHTML = html;
    el.textContent = "";
    el.appendChild(t.content);
    if (id && el.contains(focus) === false && $(id) && el.querySelector("#" + CSS.escape(id))) {
      const again = $(id);
      again.focus({ preventScroll: true });
      if (at != null && again.setSelectionRange) { try { again.setSelectionRange(at, at); } catch (e) { /* no es de texto */ } }
    }
  }

  // ---------------------------------------------------------------- reglas derivadas
  /* GRAVEDAD, cinco tramos. Regla única, la misma que explica el botón «?» de la leyenda. */
  function gravity(i) {
    const p = Number(i && i.priority);
    if (i && i.priority == null) return "sin";
    if (!Number.isFinite(p)) return "sin";
    if (p >= 9 || i.life_threat) return "vital";
    if (p >= 7) return "emergencia";
    if (p >= 5) return "urgente";
    return "leve";
  }
  const CLOSED = { resolved: 1, false_alarm: 1, failed: 1 };
  const openIncidents = () => (S.incidents || []).filter((i) => !CLOSED[i.status]);

  /* Ranura de workflow de HappyRobot para una comunicación: misma regla que hr_routing.workflow_slot. */
  function workflowSlot(call) {
    if (call.workflow) return call.workflow;
    const r = (S.resources || []).find((x) => x.id === call.resource);
    if (call.kind === "request_external") return "externos";
    if (call.kind === "broadcast") return "difusion";
    if (r) return { medical: "sanitario", ambulance: "sanitario", security: "seguridad", tech: "tecnico",
      logistics: "logistica", volunteer: "relevo" }[r.kind] || "dispatch";
    const to = String(call.to || "").toLowerCase();
    if (/director|plan de actuación|suplente/.test(to)) return "director";
    if (/sanitar|médic|medical|ambulan/.test(to)) return "sanitario";
    if (/segurid|security|sector/.test(to)) return "seguridad";
    if (/técnic|tecnic|tech/.test(to)) return "tecnico";
    if (/logíst|logist|proveedor/.test(to)) return "logistica";
    if (call.kind === "ask") return "ask";
    if (call.kind === "notify") return "notify";
    return "dispatch";
  }
  /* Qué está haciendo HappyRobot con ese incidente, según la última comunicación suya. */
  function hrFor(incidentId) {
    const list = (S.calls && S.calls.calls || []).filter((c) => c.incident === incidentId);
    if (!list.length) return null;
    const c = list[list.length - 1];
    const slot = workflowSlot(c);
    const status = (S.happyrobot || {})[slot] || {};
    const out = { call: c, slot, wf: WF_NAME[slot] || slot, configured: !!status.configured,
      run_url: c.hr_run_url || status.run_url || null, real: !!c.real, cls: "idle", text: "" };
    const eta = c.eta_min != null ? ` · ETA ${c.eta_min} min` : "";
    if (c.taken_over) { out.cls = "human"; out.text = "Requiere humano: la lleva una persona"; }
    else if (c.waiting_pickup) { out.cls = "call"; out.text = "Llamada web esperando a que descuelguen"; }
    else if (c.result === "accept") { out.cls = "accept"; out.text = "ACEPTA" + eta; }
    else if (c.result === "reject") { out.cls = "reject"; out.text = "RECHAZA: " + (c.reason || c.detail || c.reason_code || c.text || "sin motivo"); }
    else if (c.result === "no_answer") { out.cls = "reject"; out.text = "Sin respuesta"; }
    else if (c.result === "answer") { out.cls = "accept"; out.text = "Respuesta recibida"; }
    else { out.cls = "call"; out.text = "Llamando a " + (c.title || c.to || "—"); }
    if (c.fell_back) { out.text += " · plan B en uso (cayó a simulación)"; out.cls = "reject"; }
    const ms = c.turn_latency_ms || c.first_word_ms || c.answer_ms;
    if (ms) out.text += " · " + ms + " ms";
    return out;
  }

  /* ESTADO de la fila: los seis rótulos del diseño, derivados del estado real. */
  function rowState(i) {
    const pend = (S.approvals || []).some((a) => a.incident === i.id);
    if (pend) return { cls: "espera", text: "ESPERA DECISIÓN" };
    if (i.status === "resolved") return { cls: "resuelto", text: "RESUELTO" };
    if (i.status === "false_alarm") return { cls: "resuelto", text: "FALSA ALARMA" };
    if (i.status === "failed") return { cls: "espera", text: "FALLIDO" };
    if (i.status === "in_progress") return { cls: "sitio", text: "EN EL SITIO" };
    const mine = (i.assigned || []).map((r) => (S.resources || []).find((x) => x.id === r)).filter(Boolean);
    if (mine.some((r) => r.status === "en_route")) return { cls: "ruta", text: "EN RUTA" };
    if (mine.length) return { cls: "asignado", text: "ASIGNADO" };
    const ext = (S.actions || []).some((a) => a.incident === i.id && a.kind === "request_external");
    return { cls: "nuevo", text: ext ? "NUEVO (112)" : "NUEVO" };
  }

  /* Hora del recinto en la que nació el incidente: el reloj actual menos los minutos transcurridos.
     El simulador va a 1 tick = 1 minuto, así que es exacta al minuto (no hay segundos que enseñar). */
  function hhmmAt(t) {
    const now = (S.clock || {}).hhmm;
    if (!now || !/^\d{1,2}:\d{2}$/.test(now) || t == null) return "—";
    const [h, m] = now.split(":").map(Number);
    const total = ((h * 60 + m - (S.t - t)) % 1440 + 1440) % 1440;
    return String(Math.floor(total / 60)).padStart(2, "0") + ":" + String(total % 60).padStart(2, "0");
  }

  /* Déficit REAL: incidentes graves abiertos que esperan un tipo de recurso del que no queda ninguno libre. */
  function deficit() {
    const free = {};
    (S.resources || []).forEach((r) => { if (r.status === "available") free[r.kind] = (free[r.kind] || 0) + 1; });
    const need = {};
    openIncidents().forEach((i) => {
      const g = gravity(i);
      if (g !== "vital" && g !== "emergencia") return;
      const kinds = (i.waiting && i.waiting.length) ? i.waiting : (i.assigned || []).length ? [] : Object.keys(i.needs || {});
      kinds.forEach((k) => { if (!free[k]) (need[k] = need[k] || []).push(i); });
    });
    const worst = Object.keys(need).sort((a, b) => need[b].length - need[a].length)[0];
    if (!worst) return null;
    const n = need[worst].length;
    return { kind: worst, incidents: need[worst],
      text: `Déficit: 0 ${RES_KIND_ES[worst] || worst} libres para ${n} incidente${n > 1 ? "s" : ""} grave${n > 1 ? "s" : ""}` };
  }
  /* Supuesto roto vivo: plan invalidado en los últimos 8 minutos simulados. */
  function brokenPlan() {
    return (S.plans || []).filter((p) => p.invalidated_by &&
      (p.assumptions || []).some((a) => a.id === p.invalidated_by && a.broken_at != null && S.t - a.broken_at <= 8))
      .sort((a, b) => b.t - a.t)[0] || null;
  }
  const successor = (p) => (S.plans || []).filter((x) => x.supersedes === p.id).slice(-1)[0] || null;

  // ---------------------------------------------------------------- conexión
  function normalize(s) {
    ["resources", "zones", "incidents", "fronts", "reports", "plans", "approvals", "actions", "log", "strikes", "forecasts"]
      .forEach((k) => { if (!Array.isArray(s[k])) s[k] = []; });
    s.session = s.session || {}; s.metrics = s.metrics || {}; s.clock = s.clock || {};
    s.calls = s.calls || {}; s.calls.calls = s.calls.calls || [];
    s.happyrobot = s.happyrobot || {}; s.presentation = s.presentation || {};
    return s;
  }

  const ROL_TG = { medico: "médico", enfermero: "enfermero", sanitario: "sanitario", ambulancia: "ambulancia",
    seguridad: "seguridad", tecnico: "técnico", logistica: "logística", voluntario: "voluntario",
    jefe_zona: "jefe de zona", organizador: "organizador" };
  const tgSince = new Map();
  function telegramState() {
    const t = S && S.telegram;
    if (!t || typeof t !== "object" || Array.isArray(t)) return null;
    if (!t.staff || !Array.isArray(t.asignaciones)) return null;
    return t;
  }
  function tgRol(r) { return ROL_TG[r] || r || "staff"; }
  function tgAlias(a) {
    const s = String((a && a.alias) || "");
    if (!s || /\+?\d[\d\s().-]{8,}/.test(s)) return "staff";
    return s;
  }
  function tgZoneLabel(id) {
    if (!id) return "";
    const n = zoneName(id);
    return n.replace(/\s*\([^)]*\)\s*/g, "").trim() || n;
  }
  function tgPhrase(a) {
    const rol = tgRol(a.rol), alias = tgAlias(a);
    if (a.estado === "pending") {
      const key = [a.incident_id, a.rol, a.intento, a.alias].join("|");
      if (!tgSince.has(key)) tgSince.set(key, Date.now());
      const s = Math.max(0, Math.round((Date.now() - tgSince.get(key)) / 1000));
      return "Telegram → " + rol + ": pendiente " + s + " s";
    }
    if (a.estado === "accepted") {
      const eta = a.eta_min != null ? " · " + a.eta_min + " min" : "";
      const desde = a.desde_zona ? " · desde " + tgZoneLabel(a.desde_zona) : "";
      return "ACUDE " + alias + eta + desde;
    }
    if (a.estado === "declined" || a.estado === "timeout") {
      return "No puede → reasignando (intento " + (Number(a.intento || 1) + (a.estado === "declined" ? 1 : 0)) + ")";
    }
    if (a.estado === "covered") return "Cubierto";
    return "";
  }
  function tgIdsFor(i) {
    const ids = new Set([i.id]);
    (i.reports || []).forEach((r) => ids.add(r));
    (S.log || []).forEach((e) => {
      const iid = e.data && e.data.incident;
      if (iid && (e.ref === i.id || (i.reports || []).includes(e.ref))) ids.add(iid);
    });
    return ids;
  }
  function tgAsignaciones(i) {
    const tg = telegramState();
    if (!tg) return [];
    const ids = tgIdsFor(i);
    return tg.asignaciones.filter((a) => ids.has(a.incident_id));
  }
  function tgEscaladas(i) {
    const tg = telegramState();
    if (!tg) return [];
    const ids = tgIdsFor(i);
    return (tg.escaladas || []).filter((e) => ids.has(e.incident_id));
  }
  function tgCls(estado) {
    return estado === "accepted" || estado === "covered" ? "accept" : estado === "pending" ? "call"
      : estado === "escalada" ? "escalada" : "reject";
  }

  function connect() {
    const poll = () => U.api("/api/state").then((s) => { online(true); S = normalize(s); schedule(); }).catch(() => online(false));
    poll();
    if (!window.EventSource) { setInterval(poll, 2000); return; }
    const src = new EventSource("/api/stream");
    src.addEventListener("state", (ev) => { online(true); S = normalize(JSON.parse(ev.data)); schedule(); });
    src.onerror = () => online(false);
  }
  function online(ok) { connected = ok; $("reconnect").hidden = ok; $("sync-dot").style.background = ok ? "var(--ok)" : "var(--bad)"; }
  let queued = false;
  function schedule() { if (!queued) { queued = true; requestAnimationFrame(() => { queued = false; render(); }); } }

  U.api("/api/version").then((v) => { $("version").textContent = "v" + (v.version || "—"); })
    .catch(() => { $("version").textContent = "v—"; });
  U.api("/api/festival").then((f) => {
    F = f;
    plano = P.build($("plano"), f);
    Object.entries(plano.zones).forEach(([id, z]) => {
      z.g.addEventListener("click", () => pick({ zone: id }));
      z.g.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); pick({ zone: id }); } });
    });
    connect();
    setInterval(() => {
      const tg = telegramState();
      if (tg && (tg.asignaciones || []).some((a) => a.estado === "pending")) schedule();
    }, 1000);
  }).catch(() => { online(false); setTimeout(() => location.reload(), 4000); });

  // ---------------------------------------------------------------- pintado
  function render() {
    if (!S || !plano) return;
    head(); sidebar(); band(); map(); queue(); aside(); ficha();
    if ($("inyeccion").hidden === false) injection();
    if ($("externa").hidden === false) external();
    firstPaint = false;
  }

  function head() {
    const total = (S.zones || []).reduce((a, z) => a + (z.capacity || 0), 0);
    $("pax").textContent = total >= 1000 ? Math.round(total / 1000) + "K PAX" : total + " PAX";
    $("pax").title = `Suma de los aforos de las 17 zonas de motor/world/festival.json: ${total.toLocaleString("es-ES")} personas`;
    const run = S.session.running, done = S.session.done;
    const st = $("event-state");
    st.textContent = done ? "CASO TERMINADO" : run ? "FESTIVAL ABIERTO" : "FESTIVAL EN PAUSA";
    st.className = "nav-state" + (run && !done ? "" : " paused");
    st.title = `Caso ${S.session.case} · semilla ${S.session.seed} · minuto ${S.t} de ${S.session.duration_min || "—"} · simulación`;

    $("clock").textContent = (S.clock && S.clock.hhmm) || "—:—";
    $("clock").title = `Reloj del recinto simulado · minuto ${S.t}`
      + (S.clock && S.clock.show_phase ? ` · ${S.clock.show_phase}` : "");

    const open = openIncidents();
    const crit = open.filter((i) => ["vital", "emergencia"].includes(gravity(i))).length;
    const free = (S.resources || []).filter((r) => r.status === "available").length;
    $("c-activos").textContent = open.length;
    $("c-criticos").textContent = crit;
    $("c-libres").textContent = free + "/" + (S.resources || []).length;

    // Carga médica: ocupación real de los equipos sanitarios (médicos + ambulancia).
    const med = (S.resources || []).filter((r) => r.kind === "medical" || r.kind === "ambulance");
    const busy = med.filter((r) => r.status !== "available" && r.status !== "offline").length;
    const pct = med.length ? Math.round(busy * 100 / med.length) : 0;
    $("alarm").hidden = pct < 80;
    $("alarm-text").textContent = `Carga médica al ${pct} %`;
    $("alarm").title = `${busy} de ${med.length} equipos sanitarios ocupados en este minuto simulado`;

    $("speed-label").textContent = (S.session.speed || 1) + "x";
    $("live-chip").className = "live-chip" + (S.session.running ? "" : " paused");
    $("live-sub").textContent = S.session.running
      ? "posición por zona · sin GPS"
      : "en pausa · posición por zona";

    // Enlace con HappyRobot: rótulo real / simulado según el propio estado.
    const mode = S.calls.mode === "happyrobot";
    const label = S.presentation.happyrobot || (mode ? "conectado" : "simulado");
    const wired = Object.values(S.happyrobot).filter((w) => w && w.configured).length;
    const link = $("hr-link");
    link.className = "hr-link " + (mode && !/simulad/.test(label) ? "on" : mode ? "sim" : "off");
    $("hr-link-text").textContent = `Enlace directo · ${label} · ${wired} workflows configurados`;
    link.title = `Modo de comunicaciones: ${S.calls.mode} · llamadas reales enviadas: ${S.calls.real_sent || 0}`
      + ` · caídas a simulación: ${S.calls.fallbacks || 0} · voz: ${S.presentation.voice || "—"}`;
  }

  function sidebar() {
    const open = openIncidents();
    $("n-todos").textContent = open.length;
    $("n-grave").textContent = open.filter((i) => ["vital", "emergencia"].includes(gravity(i))).length;
    $("n-sin-recurso").textContent = open.filter((i) => !(i.assigned || []).length).length;
    $("n-sector").textContent = sel.zone ? open.filter((i) => i.zone === sel.zone).length : 0;
    const note = $("sector-note");
    note.hidden = !sel.zone;
    if (sel.zone) note.textContent = "Sector activo: " + zoneName(sel.zone);
    document.querySelectorAll(".filters button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.filter === filter)));
  }
  const zoneName = (id) => ((S.zones || []).find((z) => z.id === id) || {}).name || id || "zona sin confirmar";

  function band() {
    const b = $("plan-band"), broken = brokenPlan(), def = deficit();
    const trouble = broken || def;
    b.className = "plan-band" + (trouble ? " broken" : "");
    $("plan-title").textContent = trouble ? "EL PLAN HA DEJADO DE VALER" : "El plan sigue en pie";
    $("plan-toggle").hidden = !broken;
    let cause;
    if (broken) {
      const a = (broken.assumptions || []).find((x) => x.id === broken.invalidated_by) || {};
      const next = successor(broken);
      cause = showOldPlan
        ? `Plan viejo: ${broken.objective} · ya no vale (minuto ${a.broken_at})`
        : `Supuesto roto: «${a.text || "un supuesto del plan"}»` + (next ? ` → plan nuevo: ${next.objective}` : " → replanificando…");
      if (def) cause += " · " + def.text;
    } else if (def) {
      cause = def.text;
    } else {
      const live = (S.plans || []).filter((p) => !p.invalidated_by).slice(-1)[0];
      cause = live ? `${live.objective} · ${(live.assumptions || []).length} supuestos vigilados` : "Mando todavía no ha necesitado un plan.";
    }
    const el = $("plan-cause");
    el.textContent = cause;
    el.className = showOldPlan && broken ? "old-plan" : "";
    $("legend-note").textContent = noRouteNote();
  }
  /* La nota de trayectos del diseño, calculada: incidentes graves sin baliza asignada. */
  function noRouteNote() {
    const bad = openIncidents().filter((i) => ["vital", "emergencia"].includes(gravity(i)) && !(i.assigned || []).length);
    if (!bad.length) return "";
    const i = bad[0];
    const kinds = Object.keys(i.needs || {}).map((k) => RES_KIND_ES[k] || k).join(" / ") || "recurso";
    return `${i.id} en ${zoneName(i.zone)}: SIN baliza · sin ${kinds} asignada`;
  }

  // ---------------------------------------------------------------- plano
  function map() {
    const byId = {}; (S.zones || []).forEach((z) => (byId[z.id] = z));
    Object.entries(plano.zones).forEach(([id, p]) => {
      const z = byId[id]; if (!z) return;
      const L = p.L;
      const cls = ["sala-zone", P.densityClass(z.density), z.state === "closed" ? "closed" : "",
        L.out ? "out" : "", L.gate ? "gate" : "", L.pma ? "pma" : "",
        sel.zone === id ? "sel" : "", linkedZone(id) ? "linked" : ""].filter(Boolean).join(" ");
      p.g.setAttribute("class", cls);
      if (p.sub) p.sub.textContent = z.name;   // en las cajas bajas no cabe: el nombre real va en el título
      p.figure.textContent = `${num(z.density, 2)} p/m² · ${Math.round((z.ratio || 0) * 100)} %`;
      let flag = z.state === "closed" ? "CERRADA" : z.state === "restricted" ? "RESTRINGIDA" : "";
      if (z.flags && z.flags.evacuating) flag = "EVACUANDO";
      if (z.flags && z.flags.power === false) flag = (flag ? flag + " · " : "") + "SIN LUZ";
      p.flag.textContent = flag;
      p.heat.classList.toggle("on", (z.density || 0) >= 2);
      p.heat.setAttribute("rx", L.w * (0.4 + Math.min(0.2, (z.density || 0) / 30)));
      p.title.textContent = `${L.label} · ${z.name} · ${num(z.density, 2)} personas/m² · ${z.occupancy} personas`
        + ` (estimación del simulador, no hay sensores reales)`;
    });

    // Marcadores de incidente, por gravedad y con el icono del tipo.
    plano.gPins.textContent = "";
    const perZone = {};
    openIncidents().slice(0, 18).forEach((i) => {
      if (!i.zone || !P.ZONES[i.zone]) return;
      const L = P.ZONES[i.zone], n = (perZone[i.zone] = (perZone[i.zone] || 0) + 1) - 1;
      const g = P.el("g", { class: `pin g-${gravity(i)}` + (sel.incident === i.id ? " sel" : linkedIncident(i.id) ? " linked" : ""),
        transform: `translate(${L.x + L.w - 20 - n * 32}, ${L.y + 20})`, tabindex: 0, role: "button" }, plano.gPins);
      P.el("title", {}, g).textContent = `${i.id} · ${i.label} · ${GRAV[gravity(i)]} · ${i.explain || "sin explicación de prioridad"}`;
      P.el("circle", { r: 13 }, g);
      P.el("text", { y: 4 }, g).textContent = TYPE_GLYPH[i.family] || TYPE_GLYPH[i.type] || "•";
      g.addEventListener("click", () => pick({ incident: i.id, zone: i.zone }));
      g.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); pick({ incident: i.id, zone: i.zone }); } });
    });

    // Balizas: una por recurso, en la zona que publica el simulador. No hay GPS.
    const slots = {};
    (S.resources || []).forEach((r) => {
      if (!P.ZONES[r.zone]) return;
      const n = (slots[r.zone] = (slots[r.zone] || 0) + 1) - 1;
      const at = P.slot(r.zone, n);
      let b = beacons.get(r.id);
      if (!b) {
        b = P.el("g", { class: "beacon", tabindex: 0, role: "button" }, plano.gBeacons);
        P.el("title", {}, b);
        P.el("circle", { r: 11, class: "body" }, b);
        P.el("text", { y: 3.5, class: "mark" }, b);
        b.addEventListener("click", () => pick({ resource: r.id, incident: r.task || null, zone: r.zone }));
        b.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); pick({ resource: r.id, incident: r.task || null }); } });
        beacons.set(r.id, b);
      }
      b.setAttribute("class", `beacon k-${r.kind} s-${r.status}` + (r.status === "en_route" ? " en_route" : "")
        + (sel.resource === r.id ? " sel" : linkedResource(r.id) ? " linked" : ""));
      b.setAttribute("transform", `translate(${at.x}, ${at.y})`);
      b.querySelector(".mark").textContent = shortName(r);
      b.querySelector("title").textContent = `${r.name} · ${statusES(r)}`
        + (r.task ? ` · ${r.task}` : "") + " · posición simulada por zona (no hay GPS)";
    });
    beacons.forEach((b, id) => { if (!(S.resources || []).some((r) => r.id === id)) { b.remove(); beacons.delete(id); } });

    // Trayectos: del recurso en ruta a la zona de su incidente, en línea discontinua y con su ETA.
    plano.gRoutes.textContent = "";
    (S.resources || []).forEach((r) => {
      if (r.status !== "en_route" || !r.task) return;
      const inc = (S.incidents || []).find((i) => i.id === r.task);
      const from = P.center(r.zone), to = inc && P.center(inc.zone);
      if (!from || !to) return;
      const g = P.el("g", {}, plano.gRoutes);
      P.el("path", { class: "route", "marker-end": "url(#sala-arrow)",
        d: `M${from.x} ${from.y} Q ${(from.x + to.x) / 2} ${(from.y + to.y) / 2 - 42} ${to.x} ${to.y}` }, g);
      const label = P.el("text", { class: "route-eta", x: (from.x + to.x) / 2, y: (from.y + to.y) / 2 - 30, "text-anchor": "middle" }, g);
      label.textContent = `${shortName(r)} · ETA ${r.eta != null ? r.eta + " min" : "—"}`;
    });

    // Desvíos decididos por Mando (flags.reroute_to del estado).
    (S.zones || []).forEach((z) => {
      const to = z.flags && z.flags.reroute_to;
      if (!to || !P.ZONES[to] || !P.ZONES[z.id]) return;
      const a = P.center(z.id), b = P.center(to);
      const g = P.el("g", {}, plano.gRoutes);
      P.el("path", { class: "route", "marker-end": "url(#sala-arrow)", d: `M${a.x} ${a.y} L ${b.x} ${b.y}` }, g);
      const t = P.el("text", { class: "route-eta", x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 - 8, "text-anchor": "middle" }, g);
      t.textContent = "DESVÍO DE MANDO";
    });
  }
  function shortName(r) {
    const n = Number(String(r.id).replace(/\D+/g, "")) || "";
    return ({ medical: "M", ambulance: "A", security: "S", tech: "T", logistics: "L", volunteer: "V" }[r.kind] || "?") + n;
  }
  function statusES(r) {
    return { available: "libre", en_route: "en ruta" + (r.eta != null ? ` · ETA ${r.eta} min` : ""), busy: "ocupado",
      on_scene: "en el sitio", offline: "fuera de servicio", resting: "en descanso" }[r.status] || r.status;
  }

  // ---------------------------------------------------------------- cola
  function visible() {
    let list = openIncidents();
    if (filter === "grave") list = list.filter((i) => ["vital", "emergencia"].includes(gravity(i)));
    if (filter === "sin-recurso") list = list.filter((i) => !(i.assigned || []).length);
    if (filter === "sector") list = sel.zone ? list.filter((i) => i.zone === sel.zone) : [];
    if (query) {
      const q = query.toLowerCase();
      list = list.filter((i) => [i.id, i.label, i.type, i.family, i.zone, i.zone_name || zoneName(i.zone)]
        .some((v) => String(v || "").toLowerCase().includes(q)));
    }
    return list.sort((a, b) => (b.priority || 0) - (a.priority || 0) || a.t_open - b.t_open);
  }
  function queue() {
    const list = visible(), all = openIncidents();
    $("q-total").textContent = `${all.length} TOTALES` + (list.length !== all.length ? ` · ${list.length} A LA VISTA` : "");
    const rows = list.map((i) => {
      const g = gravity(i), st = rowState(i), hr = hrFor(i.id);
      const front = (S.fronts || []).find((f) => f.id === i.id) || {};
      const team = (front.resources || []).join(", ");
      const eta = front.eta != null ? ` · ETA ${front.eta} min` : "";
      const res = team
        ? `<span>${E(team)}${E(eta)}</span>`
        : `<span class="deficit">${E(front.why_waiting || "Sin recurso asignado")}</span>`;
      const asg = tgAsignaciones(i), esc = tgEscaladas(i);
      let hrCell;
      if (esc.length) {
        const e = esc[esc.length - 1];
        hrCell = `<span class="hrcell tg escalada" title="${E(e.workflow_voz || "")}">${E("ESCALADA POR VOZ · " + tgRol(e.rol))}</span>`;
      } else if (asg.length) {
        const a = asg[asg.length - 1];
        hrCell = `<span class="hrcell tg ${tgCls(a.estado)}">${E(tgPhrase(a))}</span>`;
      } else if (hr) {
        hrCell = `<span class="hrcell ${hr.cls}" title="${E(hr.wf + (hr.configured ? " · configurado" : " · borrador, sale por el genérico") + (hr.real ? " · llamada real" : " · llamada simulada"))}">${E(hr.text)}</span>`;
      } else {
        hrCell = '<span class="hrcell idle">Sin comunicación todavía</span>';
      }
      return `<tr data-incident="${E(i.id)}" data-zone="${E(i.zone || "")}" tabindex="0"
          class="${sel.incident === i.id ? "sel" : linkedIncident(i.id) ? "linked" : ""}">
        <td><span class="g-pill g-${g}" title="${E(i.explain || "Sin explicación de prioridad")}">${E(GRAV[g])}</span></td>
        <td class="id"><span class="ref">${E(i.id)}</span><b>${E(i.label || i.type || "")}</b></td>
        <td>${E(i.zone_name || zoneName(i.zone))}</td>
        <td class="hora">${E(hhmmAt(i.t_open))}<br><span class="tiny">min ${E(i.t_open)}</span></td>
        <td><span class="st ${st.cls}">${E(st.text)}</span></td>
        <td>${res}</td>
        <td>${hrCell}</td></tr>`;
    }).join("");
    setHTML($("q-rows"), rows || `<tr><td colspan="7" class="empty">${list.length === all.length ? "Ningún incidente abierto." : "Ningún incidente con este filtro."}</td></tr>`);
  }
  $("q-rows").addEventListener("click", (ev) => {
    const tr = ev.target.closest("tr[data-incident]");
    if (tr) pick({ incident: tr.dataset.incident, zone: tr.dataset.zone || null });
  });
  $("q-rows").addEventListener("keydown", (ev) => {
    const tr = ev.target.closest("tr[data-incident]");
    if (tr && (ev.key === "Enter" || ev.key === " ")) { ev.preventDefault(); pick({ incident: tr.dataset.incident, zone: tr.dataset.zone || null }); }
  });

  // ---------------------------------------------------------------- panel derecho
  function aside() {
    const html = GROUPS.map((grp) => {
      const list = (S.resources || []).filter((r) => grp.kinds.includes(r.kind));
      if (!list.length) return "";
      const free = list.filter((r) => r.status === "available").length;
      const out = free === 0;
      const cards = list.map((r) => {
        const cls = r.status === "available" ? "free" : r.status === "offline" ? "offline" : "busy";
        const detail = r.status === "available" ? "Libre"
          : (r.task ? r.task + " · " : "") + statusES(r);
        return `<button class="res ${cls}${sel.resource === r.id ? " sel" : linkedResource(r.id) ? " linked" : ""}"
          data-resource="${E(r.id)}" data-incident="${E(r.task || "")}" title="${E(r.name + " · " + statusES(r))}">
          <b>${E(shortName(r))} · ${E(r.name.split(" (")[0])}</b><span>${E(detail)}</span></button>`;
      }).join("");
      return `<section class="res-group${out ? " out" : ""}"><h3>${E(grp.title)}
        <span>${free} / ${list.length} LIBRES${out ? " – AGOTADO" : ""}</span></h3>
        <div class="res-list">${cards}</div></section>`;
    }).join("") + staffTelegramCard() + coordCard();
    setHTML($("res-groups"), html);

    // Abiertos por gravedad.
    const open = openIncidents();
    const counts = ["vital", "emergencia", "urgente", "leve"].map((g) => ({ g, n: open.filter((i) => gravity(i) === g).length }));
    const max = Math.max(1, ...counts.map((c) => c.n));
    setHTML($("sev-bars"), counts.map((c) => `<div class="bar g-${c.g}"><span>${E(({ vital: "Vital", emergencia: "Emerg.", urgente: "Urg.", leve: "Leve" })[c.g])} (${c.n})</span>
      <i><b style="width:${Math.round(c.n / max * 100)}%"></b></i></div>`).join(""));

    chatPanel();
  }
  /* STAFF POR TELEGRAM: solo si el espejo ha publicado S.telegram. */
  function staffTelegramCard() {
    const tg = telegramState();
    if (!tg) return "";
    const s = tg.staff || {}, d = s.disponibles, n = s.total;
    const vivas = (tg.asignaciones || []).filter((a) => a.estado === "pending" || a.estado === "accepted");
    const cards = vivas.length
      ? vivas.slice(-8).map((a) => `<button class="res ${a.estado === "accepted" ? "free" : "busy"}" data-incident="${E(a.incident_id)}" title="${E(tgPhrase(a))}">
          <b>${E(tgAlias(a))} · ${E(tgRol(a.rol))}</b><span>${E(tgPhrase(a))}</span></button>`).join("")
      : '<p class="tiny">Nadie avisado por Telegram en este minuto.</p>';
    return `<section class="res-group"><h3>STAFF POR TELEGRAM
      <span>${E(d)}/${E(n)} DISPONIBLES</span></h3>
      <p class="tiny">Staff por Telegram · ${E(d)}/${E(n)} disponibles</p>
      <div class="res-list">${cards}</div></section>`;
  }
  /* MESA DE COORDINACIÓN: el enlace con HappyRobot, con su cifra real (llamadas vivas y configuración). */
  function coordCard() {
    const mode = S.calls.mode === "happyrobot";
    const live = S.calls.in_flight_real || 0;
    const wired = Object.entries(S.happyrobot).filter(([, w]) => w && w.configured).map(([k]) => WF_ES[k] || k);
    return `<section class="res-group"><h3>MESA DE COORDINACIÓN <span>${E(mode ? (live ? live + " EN CURSO" : "EN ESPERA") : "SIMULADA")}</span></h3>
      <div class="res-list"><button class="res ${live ? "busy" : mode ? "free" : ""}" data-drawer="inyeccion" title="Modo de comunicaciones de esta sesión">
        <b>COORD-MANDO</b><span>${E(mode ? "Agente HR · enlace " + (S.presentation.happyrobot || "") : "Llamadas simuladas (SimComms)")}</span></button></div>
      <p class="tiny">Workflows configurados: ${E(wired.length ? wired.join(", ") : "ninguno; todo sale por el camino genérico o simulado")}.</p></section>`;
  }
  $("res-groups").addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-resource]");
    if (b) { pick({ resource: b.dataset.resource, incident: b.dataset.incident || null }); return; }
    const t = ev.target.closest("[data-incident]");
    if (!t) return;
    const id = t.dataset.incident;
    const inc = (S.incidents || []).find((i) => i.id === id || tgIdsFor(i).has(id));
    if (inc) pick({ incident: inc.id, zone: inc.zone });
  });

  // ---------------------------------------------------------------- chat de los canales
  function chatPanel() {
    const chs = new Set((S.reports || []).map((r) => r.via || r.channel).filter(Boolean));
    $("chat-channels").textContent = chs.size ? Array.from(chs).join(" · ") : "sin canales";
    if (!$("chat-panel").open) return;
    if (Date.now() - chatAt > 3500) { chatAt = Date.now(); U.api("/api/chats").then((d) => { chats = d.chats || []; paintChats(); }).catch(() => {}); }
    paintChats();
  }
  function paintChats() {
    if (!chats.length) { setHTML($("chat-body"), '<p class="tiny">Sin conversaciones abiertas todavía. Aquí entran /asistente, Telegram y el widget de chat.</p>'); return; }
    setHTML($("chat-body"), chats.map((c) => `<article class="conv"><header>
        <b>Conversación ${E(c.n)}</b><span>${E(c.channel)}${c.lang && c.lang !== "es" ? " · " + E(c.lang) : ""}</span>
        ${c.reserved ? '<span class="demo-tag">RESERVADO</span>' : ""}
        <span style="margin-left:auto">${E(c.reports)} aviso(s)</span></header>
        ${(c.messages || []).slice(-6).map((m) => `<p class="msg ${m.who === "mando" ? "mando" : ""}"><em>${E(m.who === "mando" ? "Mando" : "Persona")}</em>${E(m.text)}</p>`).join("")}
        ${c.instruction ? `<p class="tiny">Instrucción enviada: ${E(c.instruction)}</p>` : ""}</article>`).join(""));
  }
  $("chat-panel").addEventListener("toggle", () => { chatAt = 0; chatPanel(); });

  // ---------------------------------------------------------------- selección cruzada
  function pick(what) {
    sel = { incident: what.incident || null, zone: what.zone || (what.incident ? incZone(what.incident) : null), resource: what.resource || null };
    if (sel.incident || sel.resource || sel.zone) openDrawer("ficha");
    whatif = null;
    render();
  }
  const incZone = (id) => ((S.incidents || []).find((i) => i.id === id) || {}).zone || null;
  function linkedIncident(id) {
    if (sel.incident) return sel.incident === id;
    if (sel.resource) { const r = (S.resources || []).find((x) => x.id === sel.resource); return !!r && r.task === id; }
    return !!sel.zone && incZone(id) === sel.zone;
  }
  function linkedResource(id) {
    if (sel.resource === id) return true;
    const r = (S.resources || []).find((x) => x.id === id);
    if (!r) return false;
    if (sel.incident) return r.task === sel.incident || ((S.incidents || []).find((i) => i.id === sel.incident) || {}).assigned?.includes(id);
    return !!sel.zone && r.zone === sel.zone;
  }
  function linkedZone(id) {
    if (sel.zone === id) return true;
    if (sel.incident) return incZone(sel.incident) === id;
    if (sel.resource) return ((S.resources || []).find((x) => x.id === sel.resource) || {}).zone === id;
    return false;
  }

  // ---------------------------------------------------------------- ficha del incidente
  function ficha() {
    if ($("ficha").hidden) return;
    const i = sel.incident ? (S.incidents || []).find((x) => x.id === sel.incident) : null;
    const zone = sel.zone;
    if (!i && !zone && !sel.resource) { closeDrawer("ficha"); return; }
    $("ficha-title").textContent = i ? (i.label || i.type || i.id) : sel.resource
      ? (((S.resources || []).find((r) => r.id === sel.resource) || {}).name || sel.resource) : zoneName(zone);
    $("ficha-sub").textContent = i
      ? `${i.id} · ${i.zone_name || zoneName(i.zone)} · abierto en el minuto ${i.t_open} (${hhmmAt(i.t_open)}) · ${GRAV[gravity(i)]}`
      : zone ? `Sector ${zoneName(zone)} · ${(S.zones.find((z) => z.id === zone) || {}).occupancy || 0} personas` : "";

    const parts = [];
    if (i) parts.push(quePasa(i), fuentes(i), planBox(i), decisionBox(i), tgBox(i), hrBox(i), cronologia(i));
    parts.push(previsiones(zone || (i && i.zone)), whatifBox(zone || (i && i.zone)));
    setHTML($("ficha-body"), parts.filter(Boolean).join(""));
  }

  function quePasa(i) {
    const g = gravity(i);
    return `<div class="box"><h3>QUÉ PASA</h3>
      <p><b>${E(i.label || i.type)}</b> · ${E(i.zone_name || zoneName(i.zone))}</p>
      <p class="tiny">Gravedad <b>${E(GRAV[g])}</b> · prioridad ${E(num(i.priority))} de 10 · severidad ${E(i.severity)}
        ${i.deadline != null ? " · plazo " + E(i.deadline) + " min" : ""}</p>
      <p class="tiny">${E(i.explain || "El motor todavía no ha publicado el porqué de esta prioridad.")}</p>
      ${i.life_threat ? '<p class="tiny"><b>Riesgo vital declarado por el triaje.</b></p>' : ""}
      ${i.reserved ? '<p class="tiny"><span class="demo-tag">RESERVADO</span> el detalle se enmascara en el servidor.</p>' : ""}</div>`;
  }
  function fuentes(i) {
    const reps = (S.reports || []).filter((r) => r.incident === i.id);
    return `<div class="box"><h3>FUENTES FUSIONADAS (${reps.length})</h3>
      ${i.sources_text ? `<p class="tiny">${E(i.sources_text)}</p>` : ""}
      ${reps.length ? reps.slice(-5).map((r) => `<p class="tiny" style="margin-top:6px"><b>${E((U.labels[r.via || r.channel] || r.channel || "canal"))}</b>
        · ${E(r.source || "sin firmar")}${r.understood ? " · entendido por " + E(r.understood) : ""}<br>${E(r.text)}</p>`).join("")
        : '<p class="tiny">Este incidente no viene de un aviso: lo ha generado el caso o un golpe.</p>'}</div>`;
  }
  function planBox(i) {
    const plans = (S.plans || []).filter((p) => p.incident === i.id);
    if (!plans.length) return '<div class="box"><h3>PLAN</h3><p class="tiny">Todavía no hay plan para este incidente.</p></div>';
    const live = plans.filter((p) => !p.invalidated_by).slice(-1)[0];
    const dead = plans.filter((p) => p.invalidated_by).slice(-1)[0];
    const one = (p, old) => {
      const brokenId = p.invalidated_by;
      return `<div class="${old ? "old-plan" : ""}"><p><b>${E(p.objective)}</b> <span class="tiny">${E(p.id)} · minuto ${E(p.t)}${p.versions_total > 1 ? ` · versión ${E(p.version)} de ${E(p.versions_total)}` : ""}</span></p>
        ${p.why ? `<p class="tiny">${E(p.why)}</p>` : ""}
        <ol>${(p.steps || []).slice(0, 6).map((s) => `<li class="tiny"><b>${E(KIND_ES[s.kind] || s.kind)}</b> ${E(s.why || s.reason || "")} <i>(${E(s.status)})</i></li>`).join("")}</ol>
        <p class="tiny" style="margin-top:6px"><b>SUPUESTOS</b></p>
        <ul>${(p.assumptions || []).map((a) => `<li class="tiny assume${a.holds === false ? " broken" : ""}">${a.holds === false ? "ROTO en el minuto " + E(a.broken_at) + ": " : ""}${E(a.text)}${a.id === brokenId ? " ← este tiró el plan" : ""}</li>`).join("")}</ul>
        ${(p.rehearsal || []).length ? `<p class="tiny" style="margin-top:6px"><b>ENSAYADO EN EL GEMELO:</b> ${E(p.rehearsal.map((o) => o.label + (o.value != null ? " → " + o.value : "") + (o.ok === false ? " ✗" : o.ok ? " ✓" : "")).join(" · "))}</p>` : ""}</div>`;
    };
    const next = dead ? successor(dead) : null;
    return `<div class="box${dead ? " bad" : ""}"><h3>PLAN${dead ? " · SUPUESTO ROTO" : ""}</h3>
      ${dead ? one(dead, true) + '<p class="tiny" style="margin:8px 0"><b>PLAN NUEVO</b></p>' + (next ? one(next, false) : (live ? one(live, false) : "<p class=\"tiny\">Replanificando…</p>")) : one(live, false)}</div>`;
  }
  function decisionBox(i) {
    const ap = (S.approvals || []).filter((a) => a.incident === i.id);
    if (!ap.length) return "";
    return ap.map((a) => {
      const c = a.card || {};
      const branch = (b, cls, title) => b ? `<div class="future ${cls}"><h4>${E(title)}</h4>${b.text ? `<p>${E(b.text)}</p>` : ""}
        ${(b.figures || []).map((f) => `<div class="fig"><b>${E(typeof f.v === "number" ? num(f.v, Number.isInteger(f.v) ? 0 : 2) : f.v)}</b><span>${E(f.k)}</span></div>`).join("")}</div>` : "";
      const grave = ["evacuate", "stop_show", "request_external", "set_zone"].includes(a.kind);
      return `<div class="box decision" data-card="${E(a.id)}"><h3>TARJETA DE DECISIÓN · ${E(KIND_ES[a.kind] || a.kind)}</h3>
        <p><b>${E(c.question || a.why || "")}</b></p>
        <p class="tiny">Decide: <b>${E(c.role || "Director del Plan de Actuación")}</b>${c.deputy ? " · suplente: " + E(c.deputy) : ""}
          ${c.remaining_min != null ? ` · quedan <b>${E(c.remaining_min)}</b> min de ventana` : ""}${c.escalated ? " · <b>ESCALADO AL SUPLENTE</b>" : ""}</p>
        ${(c.if_approved || c.if_vetoed) ? `<div class="futures">${branch(c.if_approved, "yes", "SI APRUEBAS" + (c.rehearsed ? " · ensayado" : ""))}${branch(c.if_vetoed, "no", "SI VETAS" + (c.rehearsed ? " · ensayado" : ""))}</div>`
          : '<p class="tiny">El motor no ha publicado los dos futuros ensayados de esta decisión: no se inventan.</p>'}
        <label class="tiny" for="nota-${E(a.id)}">Nota de la decisión</label>
        <input id="nota-${E(a.id)}" data-note="${E(a.id)}" maxlength="200" value="${E(notes.get(a.id) || "")}" placeholder="Por qué sí o por qué no (opcional)">
        <div class="row" style="margin-top:8px">
          <button class="btn-ok" data-decide="1" data-id="${E(a.id)}" data-grave="${grave ? 1 : 0}">${armed.has(a.id) ? "CONFIRMAR: ES UNA ACCIÓN GRAVE" : "APROBAR (A)"}</button>
          <button class="btn-no" data-decide="0" data-id="${E(a.id)}" data-grave="0">VETAR (V)</button></div>
        ${grave ? '<p class="tiny">Acción grave: se pedirá confirmación antes de ejecutarla.</p>' : ""}
        <p class="status" id="st-${E(a.id)}"></p></div>`;
    }).join("");
  }
  function tgBox(i) {
    const tg = telegramState();
    if (!tg) return "";
    const asg = tgAsignaciones(i).slice().sort((a, b) => (a.t || 0) - (b.t || 0));
    const esc = tgEscaladas(i);
    if (!asg.length && !esc.length) return "";
    const rows = asg.map((a) => `<li><time>min ${E(a.t)} · ${E(tgRol(a.rol))} · intento ${E(a.intento)}</time>${E(tgPhrase(a))}</li>`).join("");
    const voz = esc.map((e) => `<div class="box escalada"><h3>ESCALADA POR VOZ</h3>
      <p><b>${E(tgRol(e.rol))}</b> · workflow ${E(e.workflow_voz || "mando-despacho-telefono")}</p>
      <p class="tiny">${E(e.motivo || "Nadie ha contestado por Telegram; se propone llamar por voz.")}</p></div>`).join("");
    return `${voz}<div class="box"><h3>AGENTE HR · TELEGRAM</h3>
      <p class="tiny">Staff por Telegram · ${E(tg.staff.disponibles)}/${E(tg.staff.total)} disponibles. Alias, nunca un teléfono.</p>
      ${rows ? `<ul class="timeline">${rows}</ul>` : '<p class="tiny">Sin asignaciones todavía.</p>'}</div>`;
  }
  function hrBox(i) {
    const calls = (S.calls.calls || []).filter((c) => c.incident === i.id);
    const pend = (S.approvals || []).find((a) => a.incident === i.id && ["dispatch", "request_external", "notify", "broadcast"].includes(a.kind));
    const rows = calls.slice(-5).map((c) => {
      const slot = workflowSlot(c), st = (S.happyrobot || {})[slot] || {};
      const url = c.hr_run_url || st.run_url;
      return `<div style="border-top:1px solid var(--line);padding-top:6px;margin-top:6px">
        <p class="tiny"><b>${E(WF_NAME[slot] || slot)}</b> · ${E(c.real ? "llamada real" : "simulada")} · canal ${E(c.channel || "—")}
          ${st.configured ? "" : " · workflow sin configurar: sale por el camino genérico"}</p>
        <p class="tiny">${E(c.title || c.to || "")}: ${E(c.result === "accept" ? "ACEPTA" : c.result === "reject" ? "RECHAZA" : c.result === "no_answer" ? "SIN RESPUESTA" : (c.stage || "llamando").toUpperCase())}
          ${c.eta_min != null ? " · ETA " + E(c.eta_min) + " min" : ""}${c.fell_back ? " · plan B en uso" : ""}</p>
        ${c.text ? `<p class="tiny">«${E(c.text)}»</p>` : ""}
        ${c.signal ? `<p class="tiny"><b>Cambio de orden en la llamada:</b> ${E(c.signal.text)}</p>` : ""}
        ${url && /^https?:\/\//.test(url) ? `<p class="tiny"><a href="${E(url)}" target="_blank" rel="noopener">Ver el run en la plataforma</a></p>` : ""}
        ${c.can_take ? `<div class="row" style="margin-top:6px"><button data-listen="${E(c.action_id)}">ESCUCHAR</button>
          <button data-take="${E(c.action_id)}">TOMAR LA LLAMADA</button></div>
          <input data-signal-for="${E(c.action_id)}" maxlength="300" placeholder="Cambiar la orden dentro de la llamada y pulsar Intro">` : ""}
        ${c.waiting_pickup ? webcallLink(c) : ""}</div>`;
    }).join("");
    return `<div class="box"><h3>AGENTE HR · HAPPYROBOT</h3>
      <p class="tiny">Modo: <b>${E(S.calls.mode)}</b> · voz: ${E(S.presentation.voice || "—")} · ${E(S.presentation.banner || "sin avisos")}</p>
      ${rows || '<p class="tiny">Ninguna comunicación de HappyRobot para este incidente todavía.</p>'}
      ${pend ? `<div class="row" style="margin-top:8px"><button class="btn-ok" data-decide="1" data-id="${E(pend.id)}" data-grave="${pend.kind === "request_external" ? 1 : 0}">APROBAR Y LLAMAR POR HAPPYROBOT</button></div>` : ""}</div>`;
  }
  function webcallLink(c) {
    if (Date.now() - webcallAt > 3000) {
      webcallAt = Date.now();
      fetch("/api/webcalls").then((r) => (r.ok ? r.json() : [])).then((w) => { webcalls = w; schedule(); }).catch(() => {});
    }
    const w = webcalls[0];
    return w ? `<p class="tiny">Llamada web esperando: <a href="/llamada/${encodeURIComponent(w.call_id)}" target="_blank" rel="noopener">abrir en este equipo</a></p>` : '<p class="tiny">Llamada web esperando a que descuelguen.</p>';
  }
  function cronologia(i) {
    const log = (S.log || []).filter((e) => e.ref === i.id || (e.data && e.data.incident === i.id)).slice(-10);
    if (!log.length) return "";
    return `<div class="box"><h3>CRONOLOGÍA</h3><ul class="timeline">${log.map((e) =>
      `<li><time>min ${E(e.t)} · ${E(e.kind)}</time>${E(e.text)}</li>`).join("")}</ul></div>`;
  }
  function previsiones(zone) {
    const list = (S.forecasts || []).filter((f) => !zone || f.zone === zone || f.resource);
    if (!list.length) return '<div class="box"><h3>PREVISIONES DEL GEMELO</h3><p class="tiny">El gemelo no anticipa ningún cruce de umbral en los próximos 15 minutos.</p></div>';
    return `<div class="box"><h3>PREVISIONES DEL GEMELO (15 min)</h3>
      ${list.slice(0, 6).map((f) => `<p class="tiny"><span class="countdown">T−${E(f.eta_min)} min</span>
        · ${E(f.metric)} en ${E(f.zone ? zoneName(f.zone) : f.resource)}
        · ahora ${E(num(f.current, 2))} → previsto ${E(num(f.predicted, 2))} (umbral ${E(num(f.threshold, 1))})
        · <b>${E(f.status)}</b>${f.eta_min === 0 ? " · ahora" : " · cuenta atrás"}</p>`).join("")}
      <p class="tiny">Simulación, N = 1 ejecución. El gemelo no conoce los sucesos futuros del caso.</p></div>`;
  }
  function whatifBox(zone) {
    if (!zone) return "";
    const others = (S.zones || []).filter((z) => z.id !== zone);
    return `<div class="box"><h3>ENSAYAR UN «¿Y SI…?» EN EL GEMELO</h3>
      <p class="tiny">No toca el recinto: ensaya 15 minutos y compara. Exige operador.</p>
      <div class="row" style="margin-top:6px">
        <select id="wi-kind"><option value="reroute">Desviar público</option><option value="set_zone">Cambiar estado de zona</option></select>
        <select id="wi-to">${others.map((z) => `<option value="${E(z.id)}">${E(z.name)}</option>`).join("")}</select>
        <button id="wi-run" data-zone="${E(zone)}">ENSAYAR</button></div>
      <p class="status" id="wi-status">${E(whatif ? (whatif.verdict || "ensayo hecho") : "")}</p>
      ${whatif ? `<p class="tiny">${E(whatif.note || "")} Minuto del ensayo: ${E(whatif.t)}.</p>
        <div class="row"><button id="wi-order">ORDENAR ESTA ALTERNATIVA</button></div>` : ""}</div>`;
  }

  // ---------------------------------------------------------------- acciones de la ficha
  $("ficha-body").addEventListener("click", async (ev) => {
    const d = ev.target.closest("[data-decide]");
    if (d) return decide(d.dataset.id, d.dataset.decide === "1", d.dataset.grave === "1");
    const take = ev.target.closest("[data-take]"), listen = ev.target.closest("[data-listen]");
    if (take || listen) {
      const id = (take || listen).dataset.take || listen.dataset.listen;
      const r = await post(`/api/call/${encodeURIComponent(id)}/token`, { takeover: !!take });
      if (r.ok !== false) toast(take ? "Llamada tomada por el puesto de control." : "Escuchando la llamada.");
      return;
    }
    if (ev.target.id === "wi-run") return runWhatif(ev.target.dataset.zone);
    if (ev.target.id === "wi-order") {
      if (!whatif) return;
      const r = await post("/api/whatif/order", { action: whatif.action, note: "Alternativa ensayada en la Sala de control" });
      if (r.ok !== false) { toast("Orden enviada como corrección del operador."); whatif = null; render(); }
    }
  });
  $("ficha-body").addEventListener("keydown", async (ev) => {
    const inp = ev.target.closest("[data-signal-for]");
    if (inp && ev.key === "Enter") {
      ev.preventDefault();
      const r = await post(`/api/call/${encodeURIComponent(inp.dataset.signalFor)}/signal`, { text: inp.value });
      if (r.ok !== false) { inp.value = ""; toast("Orden cambiada dentro de la llamada (Signal)."); }
    }
  });
  document.addEventListener("input", (ev) => {
    const n = ev.target.closest("[data-note]");
    if (n) notes.set(n.dataset.note, n.value);
  });
  async function decide(id, ok, grave) {
    // Lo grave (evacuar, parar el concierto, cerrar zona, pedir ayuda externa) exige un segundo clic.
    if (grave && !armed.has(id)) {
      armed.add(id);
      setTimeout(() => { armed.delete(id); render(); }, 8000);
      render();
      return;
    }
    armed.delete(id);
    const note = notes.get(id) || "";
    const st = $("st-" + id);
    if (st) st.textContent = "Enviando la decisión…";
    const r = await post("/api/approve", { action_id: id, ok, note });
    if (r.ok !== false) notes.delete(id);
    if (st) { st.textContent = r.ok === false ? r.error : (ok ? "Aprobado" : "Vetado") + " y registrado con tu identidad de operador."; st.className = "status" + (r.ok === false ? " err" : ""); }
  }
  async function runWhatif(zone) {
    const kind = ($("wi-kind") || {}).value || "reroute";
    const to = ($("wi-to") || {}).value;
    const body = { kind, zone, to, fraction: 0.5, state: "restricted", minutes: 15 };
    $("wi-status").textContent = "Ensayando los próximos 15 minutos en el gemelo…";
    try {
      const r = await U.api("/api/whatif", body);
      whatif = Object.assign({}, r, { action: body });
      render();
    } catch (e) { $("wi-status").textContent = e.message; $("wi-status").className = "status err"; }
  }

  // ---------------------------------------------------------------- mesa de inyección
  function injection() {
    const b = S.scoreboard || {};
    const presets = (F && F.strike_presets) || {};
    const done = (S.strikes || []).slice().reverse().slice(0, 8);
    setHTML($("iny-body"), `<div class="box"><h3>PRESUPUESTO DE GOLPES</h3>
        <p class="budget">${Array.from({ length: b.budget || 3 }, (_, k) => `<i class="${k < (b.left || 0) ? "on" : ""}"></i>`).join("")}
          <span class="tiny" style="margin-left:8px">${E(b.left || 0)} de ${E(b.budget || 3)} disponibles · marcador jurado ${E(b.jury || 0)} — ${E(b.mando || 0)} Mando</span></p>
        <p class="tiny">Los golpes entran en el recinto SIMULADO. Nada sale a la calle.</p></div>
      <div class="box"><h3>GOLPES PREDEFINIDOS</h3>
        ${Object.entries(presets).map(([k, label]) => `<button class="strike" data-preset="${E(k)}" style="margin-bottom:6px">
          <b>${E(label)}</b><span class="tiny">preset ${E(k)}</span></button>`).join("")}
        <p class="tiny">«Cerrar una puerta» permite elegir puerta desde la consola de Caos (<a href="/caos">/caos</a>).</p></div>
      <div class="box"><h3>GOLPES YA DADOS (${E((S.strikes || []).length)})</h3>
        ${done.length ? done.map((k) => `<p class="tiny"><b>min ${E(k.t)}</b> · ${E(k.origin === "jury" ? "jurado" : k.origin)} · ${E(k.label)}
          ${(k.broken || []).length ? ` → rompió «${E(k.broken[0].text)}»` : ""}${(k.new_plans || []).length ? ` → plan nuevo ${E(k.new_plans[0].id)}` : ""}
          <br><span class="tiny">atribución ${E(k.attribution || "temporal")}: es cercanía en el tiempo, no una prueba causal.</span></p>`).join("")
          : '<p class="tiny">Ningún golpe todavía.</p>'}</div>
      <p class="status" id="iny-status"></p>`);
  }
  $("iny-body").addEventListener("click", async (ev) => {
    const b = ev.target.closest("[data-preset]");
    if (!b) return;
    b.disabled = true;
    const r = await post("/api/strike", { preset: b.dataset.preset, origin: "chaos" });
    b.disabled = false;
    const st = $("iny-status");
    if (st) { st.textContent = r.ok === false ? r.error : `Golpe lanzado: ${b.textContent.trim()}. Mira la banda del plan.`; st.className = "status" + (r.ok === false ? " err" : ""); }
  });

  // ---------------------------------------------------------------- 112 / ayuda externa
  function external() {
    const pend = (S.approvals || []).filter((a) => a.kind === "request_external");
    const wf = (S.happyrobot || {}).externos || {};
    const parte = (a) => {
      const i = (S.incidents || []).find((x) => x.id === a.incident) || {};
      return [`WORKFLOW: mando-aviso-servicios-externos (${wf.configured ? "configurado" : "borrador sin publicar"})`,
        "DESTINATARIO: contacto de PRUEBA de la lista blanca (su número no se enseña ni aquí ni en el estado)",
        `INCIDENTE: ${a.incident || "—"} · ${i.label || ""}`,
        `SECTOR: ${a.zone_name || zoneName(a.zone)}`,
        `GRAVEDAD: ${GRAV[gravity(i)] || "—"} · prioridad ${num(i.priority)} de 10`,
        `MOTIVO: ${a.why || ""}`,
        `HORA DEL RECINTO: ${(S.clock || {}).hhmm || "—"} (minuto ${S.t} del caso ${S.session.case})`].join("\n");
    };
    setHTML($("ext-body"), `<div class="box bad"><h3>ESTA PANTALLA NO MARCA NINGÚN NÚMERO</h3>
        <p class="tiny">El 112 real está en la lista <code>NEVER_DIAL</code> del servidor. Aquí solo se prepara el parte que
          saldría por el workflow <b>mando-aviso-servicios-externos</b> hacia un contacto de PRUEBA, y una persona lo autoriza.</p>
        <p><span class="demo-tag">ENTORNO DE DEMO · FICTICIO</span></p></div>
      ${pend.length ? pend.map((a) => `<div class="box"><h3>PETICIÓN PENDIENTE · ${E(a.id)}</h3>
          <pre class="parte">${E(parte(a))}</pre>
          <label class="tiny" for="nota-${E(a.id)}">Nota de la decisión</label>
          <input id="nota-${E(a.id)}" data-note="${E(a.id)}" maxlength="200" value="${E(notes.get(a.id) || "")}" placeholder="Por qué sí o por qué no (opcional)">
          <div class="row" style="margin-top:8px">
            <button class="btn-ok" data-decide="1" data-id="${E(a.id)}" data-grave="1">${armed.has(a.id) ? "CONFIRMAR: ES UNA ACCIÓN GRAVE" : "AUTORIZAR EL ENVÍO"}</button>
            <button class="btn-no" data-decide="0" data-id="${E(a.id)}" data-grave="0">VETAR</button></div>
          <p class="status" id="st-${E(a.id)}"></p></div>`).join("")
        : `<div class="box"><h3>NO HAY NINGUNA PETICIÓN PENDIENTE</h3>
          <p class="tiny">Mando propone «pedir ayuda externa» cuando el caso lo necesita (por ejemplo, una parada cardiaca
            que corresponde a una ambulancia del 112). Cuando lo haga, aparecerá aquí para que una persona lo autorice.
            Sin esa autorización registrada, el servidor no deja salir la acción (segundo cerrojo en el bucle).</p></div>`}`);
  }
  $("ext-body").addEventListener("click", (ev) => {
    const d = ev.target.closest("[data-decide]");
    if (d) decide(d.dataset.id, d.dataset.decide === "1", d.dataset.grave === "1");
  });

  // ---------------------------------------------------------------- cajones
  const DRAWERS = ["ficha", "inyeccion", "externa", "ayuda"];
  function openDrawer(id) {
    DRAWERS.forEach((x) => { if (x !== id) $(x).hidden = true; });
    $(id).hidden = false;
    $("scrim").hidden = id === "ficha";
    if (id === "inyeccion") injection();
    if (id === "externa") external();
  }
  function closeDrawer(id) { $(id).hidden = true; $("scrim").hidden = true; if (id === "ficha") { sel = { incident: null, zone: null, resource: null }; render(); } }
  function closeAll() { DRAWERS.forEach((x) => { $(x).hidden = true; }); $("scrim").hidden = true; }
  document.addEventListener("click", (ev) => {
    const c = ev.target.closest("[data-close]");
    if (c) closeDrawer(c.dataset.close);
    const d = ev.target.closest("[data-drawer]");
    if (d) openDrawer(d.dataset.drawer);
  });
  $("scrim").onclick = closeAll;
  $("btn-inject").onclick = () => openDrawer("inyeccion");
  $("btn-112").onclick = () => openDrawer("externa");
  $("help-gravedad").onclick = () => openDrawer("ayuda");
  $("btn-operator").onclick = () => U.api("/api/operators/me")
    .then((o) => toast(`Operador: ${o.operator.name} · ${o.operator.role}${o.local ? " · sesión local" : ""}`))
    .catch(() => toast("Sin identidad de operador: entra en /acceso.", true));

  // ---------------------------------------------------------------- controles
  document.querySelector(".filters").addEventListener("click", (ev) => {
    const b = ev.target.closest("button[data-filter]");
    if (!b) return;
    filter = b.dataset.filter;
    render();
  });
  $("search").addEventListener("input", (ev) => { query = ev.target.value.trim(); render(); });
  $("plan-toggle").onclick = () => { showOldPlan = !showOldPlan; render(); };
  $("t-routes").onclick = (ev) => { const on = ev.currentTarget.getAttribute("aria-pressed") !== "true"; ev.currentTarget.setAttribute("aria-pressed", String(on)); document.querySelector(".map").classList.toggle("routes-off", !on); };
  $("t-heat").onclick = (ev) => { const on = ev.currentTarget.getAttribute("aria-pressed") !== "true"; ev.currentTarget.setAttribute("aria-pressed", String(on)); document.querySelector(".map").classList.toggle("heat-on", on); };
  document.querySelector(".map").classList.add("heat-on");
  $("t-speed").onclick = () => speedStep(1);
  function speedStep(d) {
    const i = Math.max(0, SPEEDS.indexOf(Number(S.session.speed)));
    post("/api/control", { cmd: "speed", value: SPEEDS[Math.max(0, Math.min(SPEEDS.length - 1, i + d))] });
  }
  $("theme").onclick = () => {
    const dark = document.documentElement.dataset.theme === "dark";
    document.documentElement.dataset.theme = dark ? "light" : "dark";
    $("theme").setAttribute("aria-pressed", String(!dark));
    try { localStorage.setItem("mando-sala-tema", dark ? "light" : "dark"); } catch (e) { /* sin almacenamiento: da igual */ }
  };
  try { if (localStorage.getItem("mando-sala-tema") === "dark") { document.documentElement.dataset.theme = "dark"; $("theme").setAttribute("aria-pressed", "true"); } } catch (e) { /* idem */ }

  document.addEventListener("keydown", (ev) => {
    if (ev.metaKey || ev.ctrlKey || ev.altKey) return;
    if (ev.key === "Escape") { closeAll(); return; }
    if (/INPUT|TEXTAREA|SELECT/.test(ev.target.tagName)) return;
    if ((ev.key === " " || ev.key === "Enter") && /BUTTON|A|SUMMARY/.test(ev.target.tagName)) return;
    if (!S) return;
    const k = ev.key.toLowerCase();
    if (k === " ") { ev.preventDefault(); post("/api/control", { cmd: "toggle" }); }
    else if (k === "enter") {
      const a = (S.approvals || [])[0];
      if (a) pick({ incident: a.incident, zone: a.zone });
    }
    else if (k === "s") post("/api/control", { cmd: "step" });
    else if (k === "r") post("/api/control", { cmd: "reset" });
    else if (k === "k") post("/api/control", { cmd: "key_moment" });
    else if (k === "arrowright" || k === "arrowup") { ev.preventDefault(); speedStep(1); }
    else if (k === "arrowleft" || k === "arrowdown") { ev.preventDefault(); speedStep(-1); }
    else if (k === "a" || k === "v") {
      const a = (S.approvals || [])[0];
      if (!a) return toast("No hay ninguna decisión pendiente.");
      pick({ incident: a.incident, zone: a.zone });
      decide(a.id, k === "a", false);
    } else if (k === "e") document.body.classList.toggle("escena");
  });
})();
