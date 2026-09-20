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
  const TAB_IDS = ["ahora", "equipo", "enjambre", "recursos", "comunicaciones", "aprendizaje", "historial"];
  const AGENT_ROLES = [
    { id: "triaje", label: "Triaje" }, { id: "prioridad", label: "Prioridad" },
    { id: "recursos", label: "Recursos" }, { id: "avisos", label: "Avisos" },
    { id: "vigia", label: "Vigía" }, { id: "critico", label: "Crítico" },
  ];
  const AGENT_EXTRA = { coordinador: "Coordinador", aprende: "Aprende" };

  // ---------------------------------------------------------------- estado local
  let S = null, F = null, plano = null, connected = false, firstPaint = true;
  let sel = { incident: null, zone: null, resource: null };
  let filter = "todos", query = "", showOldPlan = false;
  let chats = [], chatAt = 0, webcalls = [], webcallAt = 0;
  let whatif = null, toastTimer = 0;
  let currentTab = "ahora", adaptacion = null, adaptAt = 0, lecciones = null, leccAt = 0;
  let historial = null, histAt = 0, agentCache = {}, agentFetch = {};
  let historyDetail = null, historyError = "", historyRequest = 0, sessionEpoch = 0;
  let workflowBusy = false, workflowRequest = null;
  const beacons = new Map();
  const notes = new Map();   // nota escrita por el operador, por acción: sobrevive a cada repintado
  const armed = new Set();   // acciones graves esperando el segundo clic de confirmación
  const signatures = new Map(), deciding = new Set();
  const graveAction = (a) => ["evacuate", "stop_show", "request_external", "set_zone"].includes(a.kind);

  function resetSession() {
    sessionEpoch += 1;
    sel = { incident: null, zone: null, resource: null };
    filter = "todos"; query = ""; showOldPlan = false;
    $("search").value = "";
    chats = []; chatAt = 0; webcalls = []; webcallAt = 0; whatif = null;
    adaptacion = null; adaptAt = 0; lecciones = null; leccAt = 0;
    historial = null; histAt = 0; historyDetail = null; historyError = ""; historyRequest += 1;
    agentCache = {}; agentFetch = {}; workflowBusy = false; workflowRequest = null;
    $("workflow-form").reset();
    $("workflow-text").disabled = false; $("workflow-zone").disabled = false;
    $("workflow-result").textContent = "";
    $("workflow-zone").querySelectorAll("option:not(:first-child)").forEach((o) => o.remove());
    delete $("workflow-zone").dataset.loaded;
    notes.clear(); armed.clear(); signatures.clear(); deciding.clear(); tgSince.clear();
    beacons.forEach((b) => b.remove());
    beacons.clear();
    closeAll();
  }

  function scoped(promise, callback) {
    const epoch = sessionEpoch;
    return promise.then((value) => { if (epoch === sessionEpoch) callback(value); });
  }

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
    if (!s.agentes || typeof s.agentes !== "object" || Array.isArray(s.agentes)) s.agentes = {};
    if (s.enjambre != null && (typeof s.enjambre !== "object" || Array.isArray(s.enjambre))) s.enjambre = null;
    return s;
  }

  function cerebroMode() { return (S && S.session && S.session.cerebro) || "reglas"; }
  function cerebroSimLabel() {
    const mode = S.calls && S.calls.mode === "happyrobot";
    const label = (S.presentation && S.presentation.happyrobot) || (mode ? "conectado" : "simulado");
    const sim = !mode || /simulad/i.test(label);
    const session = S.session || {};
    return { mode: session.cerebro_cadena || cerebroMode(), configured: cerebroMode(),
      degraded: session.modo_degradado || "", sim, label };
  }
  function switchTab(id) {
    if (!TAB_IDS.includes(id)) return;
    currentTab = id;
    TAB_IDS.forEach((t) => {
      const panel = $("tab-" + t), btn = $("tab-btn-" + (t === "comunicaciones" ? "comms" : t));
      if (panel) { panel.classList.toggle("on", t === id); panel.hidden = t !== id; }
      if (btn) btn.setAttribute("aria-selected", String(t === id));
    });
    try { sessionStorage.setItem("mando-sala-tab", id); } catch (e) { /* sin almacenamiento */ }
    render();
  }
  try {
    const saved = sessionStorage.getItem("mando-sala-tab");
    if (saved && TAB_IDS.includes(saved)) currentTab = saved;
  } catch (e) { /* idem */ }
  $("tabs").addEventListener("click", (ev) => {
    const b = ev.target.closest("button[data-tab]");
    if (b) switchTab(b.dataset.tab);
  });

  const ROL_TG = { medico: "médico", enfermero: "enfermero", sanitario: "sanitario", ambulancia: "ambulancia",
    seguridad: "seguridad", tecnico: "técnico", logistica: "logística", voluntario: "voluntario",
    jefe_zona: "jefe de zona", organizador: "organizador",
    staff_entradas: "staff entradas", bomberos: "bomberos", policia: "policía" };
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
    const gate = window.SALA_SYNC.snapshotGate({
      revision: "version", session: (s) => s.session && s.session.id, onReset: resetSession,
    });
    window.SALA_SYNC.connect({
      stateURL: "/api/state", streamURL: "/api/stream",
      accept(s) {
        if (!gate.accept(s)) return false;
        S = normalize(s);
        for (const id of armed) if (!S.approvals.some((a) => a.id === id)) armed.delete(id);
        schedule();
        return true;
      },
      onStatus(status) {
        online(status === "live" || status === "poll");
        if (status === "auth") toast("Sesión de operador caducada. Entra en /acceso y recarga.", true);
      },
    });
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
    if (currentTab !== "ahora") switchTab(currentTab);
    setInterval(() => {
      const tg = telegramState();
      if (tg && (tg.asignaciones || []).some((a) => a.estado === "pending")) schedule();
    }, 1000);
  }).catch(() => { online(false); setTimeout(() => location.reload(), 4000); });

  // ---------------------------------------------------------------- pintado
  function render() {
    if (!S || !plano) return;
    head(); sidebar(); renderModo(); renderEquipoStrip(); renderTabBadges();
    if (currentTab === "ahora") { band(); map(); queue(); renderAhoraExtras(); }
    else if (currentTab === "equipo") { renderWorkflow(); panelEquipo(); }
    else if (currentTab === "enjambre") panelEnjambre();
    else if (currentTab === "recursos") { aside(); panelCalls(); }
    else if (currentTab === "comunicaciones") { chatPanel(); panelCommsCalls(); }
    else if (currentTab === "aprendizaje") panelAprendizaje();
    else if (currentTab === "historial") panelHistorial();
    ficha();
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
      ? "posición simulada por zona"
      : "en pausa · posición simulada";

    // Enlace con HappyRobot: rótulo real / simulado según el propio estado.
    const mode = S.calls.mode === "happyrobot";
    const label = S.presentation.happyrobot || (mode ? "conectado" : "simulado");
    const wired = Object.values(S.happyrobot).filter((w) => w && w.configured).length;
    const link = $("hr-link");
    link.className = "hr-link " + (mode && !/simulad/.test(label) ? "on" : mode ? "sim" : "off");
    $("hr-link-text").textContent = `Enlace directo · ${label} · ${wired} workflows configurados`;
    link.title = `Modo de comunicaciones: ${S.calls.mode} · llamadas reales enviadas: ${S.calls.real_sent || 0}`
      + ` · caídas a simulación: ${S.calls.fallbacks || 0} · voz: ${S.presentation.voice || "—"}`;

    const cb = cerebroSimLabel();
    const chip = $("cerebro-chip"), lbl = $("cerebro-label");
    chip.className = "cerebro-chip" + (cb.degraded ? " degradado" : "");
    lbl.textContent = `Cerebro: ${cb.mode === "llm_local" ? "LLM local" : cb.mode}${cb.degraded ? " · DEGRADADO" : ""}`;
    chip.title = `Configurado: ${cb.configured} · razonamiento: ${cb.mode}${cb.degraded ? " · " + cb.degraded : ""} · voz: ${cb.label}`;
  }

  function renderModo() {
    const now = Date.now();
    if (now - adaptAt > 5000) {
      adaptAt = now;
      scoped(fetch("/api/adaptacion").then((r) => (r.ok ? r.json() : null)), (d) => { adaptacion = d; schedule(); }).catch(() => {});
    }
    const ej = S.enjambre && S.enjambre.modo;
    const m = (adaptacion && adaptacion.modo) || (ej && ej.nombre) || (ej && ej.id) || null;
    const why = (adaptacion && adaptacion.porque) || (ej && ej.porque) || (ej && ej.texto) || "";
    const chip = $("modo-chip");
    if (!m) { chip.hidden = true; return; }
    chip.hidden = false;
    const cls = String(m).toLowerCase();
    chip.className = "modo-chip" + (cls.includes("crisis") ? " m-crisis" : cls.includes("carga") ? " m-carga" : " m-calma");
    $("modo-label").textContent = String(m).toUpperCase();
    $("modo-why").textContent = why;
    chip.title = why || "Modo adaptativo del sistema";
  }

  function agentStatusText(role) {
    const cards = S.agentes || {};
    let bestS = null, latest = null, latestH = "";
    Object.keys(cards).forEach((iid) => {
      const card = cards[iid] || {};
      const hit = ((card.abanico || {}).llegados || []).find((x) => x && x.papel === role);
      const ag = (card.agentes || {})[role];
      const s = (hit && hit.s != null) ? hit.s : (ag && ag.s);
      if (s != null && (bestS == null || s < bestS)) bestS = s;
      if (ag && ag.hora && (!latest || ag.hora > latestH)) { latest = ag; latestH = ag.hora; }
    });
    const lat = fmtLatency(bestS);
    if (lat) return lat;
    const ej = S.enjambre;
    if (ej && ej.equipo_vivo && ej.equipo_vivo[role]) return ej.equipo_vivo[role];
    if (latest) return `decidió · ${latest.hora}`;
    if (cerebroMode() === "reglas") return "plan B de reglas activo";
    return "en espera";
  }

  function renderEquipoStrip() {
    const strip = $("equipo-strip");
    const cb = cerebroSimLabel();
    const pills = AGENT_ROLES.map((r) => {
      const st = agentStatusText(r.id);
      const cls = /pensando/i.test(st) ? "think" : /espera|pendiente/i.test(st) ? "wait"
        : /plan B|reglas/i.test(st) ? "rules" : "";
      return `<div class="equipo-pill ${cls}"><b>${E(r.label)}</b><span>${E(st)}</span></div>`;
    }).join("");
    setHTML(strip, `<div class="equipo-pill ${cb.degraded ? "rules" : ""}"><b>Razonamiento</b><span>${E(cb.mode === "llm_local" ? "LLM local" : cb.mode)}${cb.degraded ? " · DEGRADADO" : ""}</span></div>${pills}`);
    strip.hidden = false;
  }

  function renderTabBadges() {
    const pend = (S.approvals || []).length;
    const badgeA = $("badge-ahora");
    if (badgeA) { badgeA.hidden = !pend; badgeA.textContent = pend ? `${pend} decisión${pend > 1 ? "es" : ""}` : ""; }
    const agentInc = Object.keys(S.agentes || {}).length;
    const badgeE = $("badge-equipo");
    if (badgeE) { badgeE.hidden = !agentInc; badgeE.textContent = agentInc ? `${agentInc} inc.` : ""; }
    if (Date.now() - leccAt > 8000) {
      leccAt = Date.now();
      scoped(U.api("/api/memoria"), (d) => { lecciones = d.cerebro_lecciones || []; schedule(); }).catch(() => {});
    }
    const nuevas = (lecciones || []).filter((l) => l.estado === "propuesta").length;
    const badgeL = $("badge-aprendizaje");
    if (badgeL) { badgeL.hidden = !nuevas; badgeL.textContent = nuevas ? `${nuevas} nueva${nuevas > 1 ? "s" : ""}` : ""; }
  }

  function buildRecomendacion() {
    const cards = S.agentes || {};
    const open = openIncidents().sort((a, b) => (b.priority || 0) - (a.priority || 0));
    for (const i of open) {
      const c = cards[i.id];
      if (!c) continue;
      const rec = (c.agentes || {}).recursos, pri = (c.agentes || {}).prioridad;
      const parts = [];
      if (rec && rec.razonamiento) parts.push(rec.razonamiento);
      else if (pri && pri.razonamiento) parts.push(pri.razonamiento);
      const res = (c.ejecutado || []).filter((x) => x.recurso || x.resource).map((x) => x.recurso || x.resource);
      const eta = (S.resources || []).filter((r) => res.includes(r.id) && r.eta != null).map((r) => `${shortName(r)} ${r.eta} min`);
      if (parts.length || res.length) {
        return `Recomendado: ${parts[0] || i.label || i.id}${res.length ? "; " + res.map((r) => {
          const rr = (S.resources || []).find((x) => x.id === r);
          return rr ? shortName(rr) + (rr.eta != null ? " en camino, " + rr.eta + " min" : "") : r;
        }).join(", ") : ""}`;
      }
    }
    const top = open[0];
    if (!top) return "";
    const f = (S.fronts || []).find((x) => x.id === top.id);
    if (f && f.resources && f.resources.length) {
      return `Recomendado: ${f.resources.join(", ")}${f.eta != null ? "; ETA " + f.eta + " min" : ""}`;
    }
    return "";
  }

  function renderAhoraExtras() {
    const rec = buildRecomendacion();
    const el = $("recom-main");
    if (rec) { el.hidden = false; setHTML(el, `<b>Equipo de agentes:</b> ${E(rec)}`); }
    else el.hidden = true;
    const pend = (S.approvals || []);
    const box = $("ahora-pend");
    if (!pend.length) { box.hidden = true; return; }
    box.hidden = false;
    setHTML(box, pend.map((a) => {
      const i = (S.incidents || []).find((x) => x.id === a.incident) || {};
      return `<div class="ahora-card" data-incident="${E(a.incident)}"><b>${E(i.label || a.incident)}</b> · ${E(KIND_ES[a.kind] || a.kind)}
        <p class="tiny">${E((a.card && a.card.question) || a.why || "")}</p>
        <div class="row" style="margin-top:6px">
          <button class="btn-ok" data-decide="1" data-id="${E(a.id)}" data-grave="0">APROBAR</button>
          <button class="btn-no" data-decide="0" data-id="${E(a.id)}" data-grave="0">VETAR</button></div></div>`;
    }).join(""));
    box.onclick = (ev) => {
      const d = ev.target.closest("[data-decide]");
      if (d) decide(d.dataset.id, d.dataset.decide === "1", d.dataset.grave === "1");
      const row = ev.target.closest("[data-incident]");
      if (row) pick({ incident: row.dataset.incident });
    };
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

  function fmtLatency(s) {
    if (s == null || !Number.isFinite(Number(s))) return null;
    const n = Math.max(0, Math.round(Number(s)));
    if (n < 60) return n + " s";
    const m = Math.floor(n / 60), r = n % 60;
    return r ? m + " min " + r + " s" : m + " min";
  }

  function velocidadLine(card) {
    const parts = [];
    const v = (card && card.velocidad) || {};
    const rap = fmtLatency(v.rapida_s);
    if (rap != null || v.revision || (card && card.fases && (card.fases.rapida || card.fases.revision))) {
      const ver = String(v.revision || "pendiente");
      const verShow = ver.toUpperCase() === "PENDIENTE" ? "pendiente" : ver.toUpperCase();
      const line = "Decisión rápida en " + (rap || "—") + " · enjambre: " + verShow;
      let cls = "";
      if (ver.toUpperCase() === "CORRIGE") cls = " corrige";
      else if (ver.toUpperCase() === "CONFIRMA") cls = " confirma";
      let extra = "";
      if (ver.toUpperCase() === "CORRIGE") {
        const fase = (card.fases || {}).revision || {};
        const cambio = card.plan_cambio || {};
        const why = fase.porque || cambio.porque || "";
        const plan = cambio.nuevo || cambio.objetivo || "";
        extra = `<p class="tiny">${E(why)}${plan ? " · plan nuevo: " + E(plan) : ""}</p>`;
      }
      parts.push(`<p class="velocidad-line${cls}">${E(line)}</p>${extra}`);
    }
    const ab = card && card.abanico;
    if (ab && (ab.lanzados || ab.llegados || ab.primera_decision_s != null || ab.fuente)) {
      const first = fmtLatency(ab.primera_decision_s);
      const fin = fmtLatency(ab.final_s);
      let line = first ? ("Primera decisión en " + first) : "Enjambre en curso";
      line += " · enjambre completo " + (fin ? ("en " + fin) : "pendiente");
      let cls = "";
      if (ab.fuente === "reglas") cls = " corrige";
      else if (ab.fuente === "local") cls = " confirma";
      const to = (ab.timeouts || []).length ? `<p class="tiny">Sin respuesta a tiempo: ${E(ab.timeouts.join(", "))}</p>` : "";
      parts.push(`<p class="velocidad-line${cls}">${E(line)}</p>${to}`);
    }
    return parts.join("");
  }

  function agentCardHtml(name, ag, extra) {
    const label = (AGENT_ROLES.find((r) => r.id === name) || {}).label || AGENT_EXTRA[name] || name;
    const row = ag || {};
    const lat = fmtLatency(row.s);
    const title = lat ? (label + " · " + lat) : label;
    const conf = row.confianza != null ? ` · confianza ${num(row.confianza, 2)}` : "";
    const sup = (row.supuestos || []).length
      ? `<ul>${row.supuestos.map((s) => `<li>${E(s)}</li>`).join("")}</ul>` : "";
    return `<article class="agent-card"><h4>${E(title)}${E(conf)}</h4>
      <p>${E(row.razonamiento || "—")}</p>
      ${row.hora ? `<p class="tiny">Hora ${E(row.hora)}</p>` : ""}${sup}${extra || ""}</article>`;
  }

  function agentDetailBox(iid, card) {
    const bloq = (card.bloqueado || []).map((b) =>
      `<p class="blocked">Bloqueado: ${E(b.motivo || b.kind || JSON.stringify(b))}</p>`).join("");
    const ejec = (card.ejecutado || []).length
      ? `<p class="tiny"><b>Ejecutado:</b> ${E(card.ejecutado.map((x) => x.kind || x.recurso || x.id).join(", "))}</p>` : "";
    const espera = (card.espera_persona || []).length
      ? `<p class="tiny"><b>Espera a una persona:</b> ${E(card.espera_persona.map((x) => x.kind || x.motivo).join(", "))}</p>` : "";
    const latBy = {};
    ((card.abanico || {}).llegados || []).forEach((x) => { if (x && x.papel != null) latBy[x.papel] = x.s; });
    const agents = AGENT_ROLES.map((r) => {
      const ag = Object.assign({}, (card.agentes || {})[r.id] || {});
      if (ag.s == null && latBy[r.id] != null) ag.s = latBy[r.id];
      if (!ag.razonamiento) ag.razonamiento = "—";
      return agentCardHtml(r.id, ag, "");
    }).join("");
    const vel = velocidadLine(card);
    const planB = cerebroMode() === "reglas" ? '<p class="tiny">Plan B de reglas activo (modo degradado).</p>' : "";
    return `<div class="box"><h3>CÓMO LO HA DECIDIDO EL EQUIPO</h3>${vel}${planB}
      <div class="agent-grid">${agents}</div>
      ${ejec}${bloq}${espera}</div>`;
  }

  function ensureAgentDetail(iid, cb) {
    if (agentCache[iid]) { cb(agentCache[iid]); return; }
    if (agentFetch[iid]) return;
    const local = (S.agentes || {})[iid];
    if (local && Object.keys(local.agentes || {}).length) {
      agentCache[iid] = local;
      cb(local);
      return;
    }
    agentFetch[iid] = true;
    const epoch = sessionEpoch;
    scoped(U.api("/api/agentes/" + encodeURIComponent(iid)), (d) => {
      agentCache[iid] = d;
      delete agentFetch[iid];
      schedule();
    }).catch(() => { if (epoch === sessionEpoch) delete agentFetch[iid]; });
  }

  function renderWorkflow() {
    const cfg = S.workflow_rapido || { ready: false, missing: ["Backend sin integración del workflow rápido"] };
    $("workflow-config").textContent = cfg.ready
      ? `Configurado para ${cfg.environment} · espera máxima ${cfg.timeout_s} s. La publicación y conectividad se verifican al ejecutar.`
      : "Pendiente: " + (cfg.missing || []).join(", ");
    $("workflow-launch").disabled = workflowBusy || !cfg.ready;
    $("workflow-launch").textContent = workflowBusy ? "Registrando aviso…" : `Lanzar en HappyRobot (${cfg.environment || "—"})`;
    const zone = $("workflow-zone");
    if (!zone.dataset.loaded && S.zones) {
      S.zones.forEach((z) => {
        const option = document.createElement("option");
        option.value = z.id; option.textContent = z.name || z.id; zone.appendChild(option);
      });
      zone.dataset.loaded = "true";
    }
    const labels = { pendiente: "Pendiente", en_curso: "En curso", esperando_callback: "Run terminado; esperando decisión",
      decision_recibida: "Decisión rápida recibida", decision_bloqueada: "Decisión bloqueada por MANDO",
      fallido: "Error de HappyRobot", timeout: "Sin decisión dentro del plazo" };
    setHTML($("workflow-runs"), (cfg.runs || []).slice().reverse().map((r) => `
      <div class="workflow-run">
        <button data-workflow-incident="${E(r.incident_id)}">${E(r.incident_id)} · ${E(labels[r.status] || r.status)}</button>
        <p class="tiny">Run: ${E(r.run_id || "sin confirmar")} · Aviso: ${E(r.report_id)}</p>
        <p class="tiny">Revisión del equipo: ${E(r.revision ? "recibida" : "pendiente")}</p>
        ${r.error ? `<p>${E(r.error)}</p>` : ""}
      </div>`).join(""));
  }
  $("workflow-form").addEventListener("input", () => { workflowRequest = null; });
  $("workflow-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    if (workflowBusy) return;
    const text = $("workflow-text").value.trim();
    if (!text) { $("workflow-result").textContent = "Escribe un aviso."; return; }
    if (!workflowRequest) workflowRequest = `sala-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    const epoch = sessionEpoch;
    workflowBusy = true;
    $("workflow-text").disabled = true; $("workflow-zone").disabled = true;
    renderWorkflow();
    const result = await post("/api/workflows/rapido", {
      text, zone: $("workflow-zone").value || null, request_id: workflowRequest,
    });
    if (epoch !== sessionEpoch) return;
    workflowBusy = false;
    $("workflow-text").disabled = false; $("workflow-zone").disabled = false;
    if (result.ok) {
      $("workflow-result").textContent = result.workflow_status === "sin_ejecucion"
        ? `Aviso ${result.report_id} registrado sin nuevo run: no abrió un incidente pendiente de decisión.`
        : `Aviso ${result.report_id} registrado. El estado del run se actualiza abajo.`;
      $("workflow-text").value = ""; workflowRequest = null;
    } else {
      $("workflow-result").textContent = result.error || "No se pudo registrar el aviso.";
    }
    renderWorkflow();
  });
  $("workflow-runs").addEventListener("click", (ev) => {
    const button = ev.target.closest("[data-workflow-incident]");
    if (button) pick({ incident: button.dataset.workflowIncident });
  });

  function panelEquipo() {
    const cards = S.agentes || {};
    const ids = Object.keys(cards);
    const el = $("panel-equipo");
    if (!ids.length) {
      setHTML(el, '<p class="tiny empty-tab">Sin votos del equipo de agentes todavía.</p>');
      return;
    }
    const open = openIncidents().map((i) => i.id);
    const sorted = ids.sort((a, b) => {
      const ao = open.includes(a) ? 1 : 0, bo = open.includes(b) ? 1 : 0;
      if (ao !== bo) return bo - ao;
      const ia = (S.incidents || []).find((x) => x.id === a);
      const ib = (S.incidents || []).find((x) => x.id === b);
      return (ib && ib.priority || 0) - (ia && ia.priority || 0);
    });
    setHTML(el, sorted.map((iid) => {
      const card = cards[iid];
      const inc = (S.incidents || []).find((x) => x.id === iid) || {};
      return `<section class="box"><h3>${E(inc.label || iid)} <span class="tiny">${E(iid)}</span></h3>
        ${agentDetailBox(iid, card)}</section>`;
    }).join(""));
  }

  function panelEnjambre() {
    const ej = S.enjambre;
    const el = $("panel-enjambre");
    if (!ej || typeof ej !== "object") {
      setHTML(el, '<p class="tiny empty-tab">Sin datos de enjambre todavía.</p>');
      return;
    }
    const nodes = ["triaje", "prioridad", "recursos", "avisos", "vigia", "critico", "coordinador", "aprende"];
    const msgs = (ej.mensajes || ej.pizarra || []).slice(-40);
    const revs = (ej.revisiones || []).slice(-12);
    const conf = ej.confianza || {};
    const autonomia = ej.autonomia || {};
    const ritmo = ej.ritmo_vigia || ej.vigia_ritmo;
    const edges = {};
    msgs.forEach((m) => {
      const f = m.de || m.from, t = m.a || m.to;
      if (!f || !t) return;
      const k = f + "→" + t;
      edges[k] = (edges[k] || 0) + 1;
    });
    const cx = 400, cy = 180, R = 130;
    const pos = {};
    nodes.forEach((n, i) => {
      const a = (i / nodes.length) * Math.PI * 2 - Math.PI / 2;
      pos[n] = { x: cx + R * Math.cos(a), y: cy + R * Math.sin(a) };
    });
    let svg = `<svg id="enjambre-svg" viewBox="0 0 800 360" role="img" aria-label="Red de agentes">`;
    Object.keys(edges).forEach((k) => {
      const parts = k.split("→"), f = parts[0], t = parts[1];
      const p1 = pos[f], p2 = pos[t];
      if (!p1 || !p2) return;
      const w = Math.min(8, 1 + edges[k]), x1 = p1.x, y1 = p1.y, x2 = p2.x, y2 = p2.y;
      svg += `<line class="enj-edge" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke-width="${w}"/>`;
    });
    nodes.forEach((n) => {
      const p = pos[n], px = p.x, py = p.y;
      const lbl = AGENT_EXTRA[n] || (AGENT_ROLES.find((r) => r.id === n) || {}).label || n;
      svg += `<g class="enj-node"><circle cx="${px}" cy="${py}" r="22" fill="var(--paper)" stroke="var(--brand)"/>`;
      svg += `<text x="${px}" y="${py + 4}" text-anchor="middle" font-size="9" font-weight="700">${E(lbl.slice(0, 8))}</text></g>`;
    });
    svg += "</svg>";
    const msgList = msgs.length
      ? msgs.slice(-10).reverse().map((m) =>
        `<div class="enj-msg"><b>${E(m.de || m.from)} → ${E(m.a || m.to)}:</b> ${E(m.texto || m.text || "")}</div>`).join("")
      : '<p class="tiny">Sin mensajes recientes en la pizarra.</p>';
    const revList = revs.length
      ? revs.map((r) => `<div class="enj-msg"><b>${E(r.de || r.from)} → ${E(r.a || r.to)}:</b> ${E(r.tipo || r.kind || "revisión")}: ${E(r.texto || r.text || "")}</div>`).join("")
      : "";
    const confList = Object.keys(conf).length
      ? Object.entries(conf).map(([k, v]) => {
        const n = (v && v.n) != null ? v.n : (typeof v === "object" ? v.N : "");
        const score = (v && v.score) != null ? v.score : (typeof v === "number" ? v : "");
        const trend = (v && v.tendencia) ? ` · ${v.tendencia}` : "";
        return `<p class="tiny"><b>${E(k)}</b>: ${E(num(score, 2))}${n ? ` (N=${E(n)})` : ""}${E(trend)}</p>`;
      }).join("")
      : '<p class="tiny">Sin confianza aprendida publicada.</p>';
    const autoList = Object.keys(autonomia).length
      ? Object.entries(autonomia).map(([k, v]) => `<p class="tiny"><b>${E(k)}</b>: ${E(String(v))}</p>`).join("")
      : '<p class="tiny">Sin autonomía adaptativa publicada.</p>';
    const lecAct = (ej.lecciones_activas || {});
    const lecHtml = Object.keys(lecAct).length
      ? Object.entries(lecAct).map(([ag, ls]) =>
        `<p class="tiny"><b>${E(ag)}</b>: ${E((ls || []).map((l) => l.texto || l).join(" · "))}</p>`).join("")
      : "";
    setHTML(el, `<div class="enjambre-grid"><div>${svg}<h3 class="tiny" style="margin-top:8px">MENSAJES RECIENTES</h3>${msgList}
      ${revList ? `<h3 class="tiny" style="margin-top:8px">REVISIONES</h3>${revList}` : ""}</div>
      <div><h3 class="tiny">CONFIANZA</h3>${confList}
      <h3 class="tiny" style="margin-top:10px">AUTONOMÍA</h3>${autoList}
      ${ritmo ? `<p class="tiny"><b>Ritmo del vigía:</b> ${E(String(ritmo))}</p>` : ""}
      ${lecHtml ? `<h3 class="tiny" style="margin-top:10px">LECCIONES ACTIVAS</h3>${lecHtml}` : ""}</div></div>`);
  }

  function panelCalls() {
    const calls = (S.calls.calls || []).slice(-12).reverse();
    const el = $("calls-block");
    if (!calls.length) { setHTML(el, ""); return; }
    setHTML(el, `<h3>LLAMADAS RECIENTES</h3>${calls.map((c) => {
      const res = c.result === "accept" ? "ACEPTA" : c.result === "reject" ? "RECHAZA" : c.result === "no_answer" ? "SIN RESPUESTA" : (c.stage || "—");
      return `<div class="call-line"><b>${E(c.incident || "—")}</b> · ${E(c.title || c.to || "")}: <b>${E(res)}</b>
        ${c.real ? " · real" : " · simulada"}${c.eta_min != null ? " · ETA " + E(c.eta_min) + " min" : ""}</div>`;
    }).join("")}`);
  }

  function panelCommsCalls() {
    panelCalls();
    const el = $("comms-calls");
    const calls = (S.calls.calls || []).slice(-20).reverse();
    const byCh = {};
    calls.forEach((c) => { const ch = c.channel || "voz"; (byCh[ch] = byCh[ch] || []).push(c); });
    const chs = Object.keys(byCh);
    if (!chs.length && !chats.length) {
      setHTML(el, '<p class="tiny">Sin llamadas ni mensajes todavía.</p>');
      return;
    }
    setHTML(el, chs.map((ch) => `<section class="box"><h3>${E(ch.toUpperCase())}</h3>
      ${byCh[ch].map((c) => `<p class="tiny">${E(c.title || c.to || "")}: ${E(c.result || c.stage || "—")}</p>`).join("")}</section>`).join(""));
  }

  function renderPromptDiff(ev) {
    if (!ev) return "";
    if (ev.diff) return String(ev.diff).split("\n").map((ln) => {
      if (ln.startsWith("+")) return `<span class="add">${E(ln)}</span>`;
      if (ln.startsWith("-")) return `<span class="del">${E(ln)}</span>`;
      return E(ln);
    }).join("\n");
    if (ev.anterior && ev.nuevo) {
      return `<span class="del">${E(ev.anterior)}</span>\n<span class="add">${E(ev.nuevo)}</span>`;
    }
    return "";
  }

  function panelAprendizaje() {
    const el = $("panel-aprendizaje");
    const rows = lecciones || [];
    const prompts = rows.filter((l) => (l.evidencia && l.evidencia.tipo === "prompt") || /^prompt/i.test(l.id || ""));
    const normales = rows.filter((l) => !prompts.includes(l));
    if (!rows.length) {
      setHTML(el, '<p class="tiny empty-tab">Sin lecciones todavía.</p>');
      return;
    }
    const card = (l, extra) => {
      const n = l.n || (l.evidencia && l.evidencia.n) || "";
      const diff = renderPromptDiff(l.evidencia);
      return `<article class="lesson-card ${E(l.estado || "")}"><p><b>${E(l.id)}</b> · ${E(l.estado || "")}${n ? ` · N=${E(n)}` : ""}</p>
        <p>${E(l.texto || "")}</p>${diff ? `<pre class="prompt-diff">${diff}</pre>` : ""}${extra || ""}</article>`;
    };
    const prop = normales.filter((l) => l.estado === "propuesta");
    const ok = normales.filter((l) => l.estado === "aprobada");
    const no = normales.filter((l) => l.estado === "rechazada");
    const btns = (l) => l.estado === "propuesta" ? `<div class="row" style="margin-top:8px">
      <button class="btn-ok" data-leccion="aprobar" data-id="${E(l.id)}">APROBAR</button>
      <button class="btn-no" data-leccion="rechazar" data-id="${E(l.id)}">RECHAZAR</button></div>` : "";
    const revert = (l) => l.estado === "aprobada" ? `<button data-leccion="rechazar" data-id="${E(l.id)}">VOLVER ATRÁS</button>` : "";
    setHTML(el, `${prop.length ? `<h3 class="tiny">PROPUESTAS</h3>${prop.map((l) => card(l, btns(l))).join("")}` : ""}
      ${prompts.length ? `<h3 class="tiny">VERSIONES DE PROMPT</h3>${prompts.map((l) => card(l, btns(l) + revert(l))).join("")}` : ""}
      ${ok.length ? `<h3 class="tiny">ACTIVAS</h3>${ok.map((l) => card(l, `<p class="tiny">Aplica desde aprobación${l.by ? " · " + E(l.by) : ""}</p>` + revert(l))).join("")}` : ""}
      ${no.length ? `<h3 class="tiny">RECHAZADAS</h3>${no.map((l) => card(l, "")).join("")}` : ""}`);
    el.onclick = async (ev) => {
      const b = ev.target.closest("[data-leccion]");
      if (!b) return;
      const epoch = sessionEpoch;
      const r = await post("/api/memoria/lecciones", { id: b.dataset.id, accion: b.dataset.leccion, by: "operador-sala" });
      if (epoch !== sessionEpoch) return;
      if (r.ok !== false) { leccAt = 0; lecciones = null; toast("Lección actualizada."); schedule(); }
    };
  }

  function panelHistorial() {
    const el = $("panel-historial");
    if (Date.now() - histAt > 12000) {
      histAt = Date.now();
      scoped(U.api("/api/historial/incidentes?tamano=20").then((data) => ({ data }), (error) => ({ error })), (result) => {
        historyError = result.error ? "Historial no disponible: " + result.error.message : "";
        historial = result.data ? result.data.items || [] : null;
        schedule();
      });
    }
    const items = historial || [];
    setHTML(el, `${historyError ? `<p role="alert">${E(historyError)}</p>` : ""}
      ${items.length ? items.map((h) =>
      `<button class="hist-row" data-hist="${E(h.id)}" data-scene="${E(h.escena_id)}"><b>${E(h.id)}</b> · ${E(h.etiqueta || h.tipo || "")}
      · ${E(h.zona || "")} · ${E(h.estado || "")} · escena ${E(h.escena_id)}</button>`).join("")
      : `<p class="tiny empty-tab">${historial ? "Sin incidentes guardados." : historyError ? "No se puede consultar la memoria persistente." : "Cargando historial…"}</p>`}
      ${historyDetailHTML()}`);
    el.onclick = (ev) => {
      const row = ev.target.closest("[data-hist]");
      if (!row) return;
      const request = ++historyRequest;
      historyDetail = null;
      scoped(U.api("/api/historial/incidente/" + encodeURIComponent(row.dataset.hist)
        + "?escena=" + encodeURIComponent(row.dataset.scene)).then((data) => ({ data }), (error) => ({ error })), (result) => {
        if (request !== historyRequest) return;
        historyDetail = result.data || null;
        historyError = result.error ? result.error.message : "";
        schedule();
      });
    };
  }

  function historyDetailHTML() {
    if (!historyDetail) return "";
    const d = historyDetail, i = d.incident || {};
    const linked = [["reports", "Avisos"], ["plans", "Planes"], ["calls", "Llamadas"], ["decisions", "Decisiones"]];
    return `<section class="box"><h3>${E(i.id)} · escena ${E(i.escena_id)}</h3>
      <p>${E(i.etiqueta || i.tipo || "")}</p><h4>Cronología</h4>
      <ul class="timeline">${(d.timeline || []).map((e) => `<li><time>min ${E(e.minuto)} · ${E(e.tipo)}</time>${E(e.texto)}</li>`).join("")}</ul>
      ${!(d.timeline || []).length ? '<p class="tiny">Sin eventos guardados para este incidente.</p>' : ""}
      ${linked.map(([key, title]) => `<details><summary>${E(title)} (${E((d[key] || []).length)})</summary>
        ${(d[key] || []).map((item) => `<pre class="parte">${E(JSON.stringify(item, null, 2))}</pre>`).join("")}</details>`).join("")}</section>`;
  }

  // ---------------------------------------------------------------- recursos (pestaña)
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
          <b>${E(shortName(r))}</b><span class="res-name">${E(r.name.split(" (")[0])}</span><span>${E(detail)}</span></button>`;
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

    if (currentTab === "comunicaciones") chatPanel();
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
    if (Date.now() - chatAt > 3500) { chatAt = Date.now(); scoped(U.api("/api/chats"), (d) => { chats = d.chats || []; paintChats(); }).catch(() => {}); }
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
    if (i) {
      parts.push(quePasa(i), fuentes(i), planBox(i));
      const agCard = (S.agentes || {})[i.id];
      if (agCard) parts.push(agentDetailBox(i.id, agCard));
      else ensureAgentDetail(i.id, () => schedule());
      parts.push(decisionBox(i), tgBox(i), hrBox(i), cronologia(i));
    }
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
      const grave = graveAction(a), signature = signatures.get(a.id);
      const votes = signature ? signature.votes : a.votes || 0;
      const required = signature ? signature.required : a.required || 1;
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
        <p class="tiny">${E(votes)} de ${E(required)} firmas registradas.</p>
        <p class="status" role="status" id="st-${E(a.id)}">${signature ? E(signature.text) : ""}</p></div>`;
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
      scoped(fetch("/api/webcalls").then((r) => (r.ok ? r.json() : [])), (w) => { webcalls = w; schedule(); }).catch(() => {});
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
    if (d) return decide(d.dataset.id, d.dataset.decide === "1");
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
      const epoch = sessionEpoch;
      const r = await post("/api/whatif/order", { action: whatif.action, note: "Alternativa ensayada en la Sala de control" });
      if (epoch !== sessionEpoch) return;
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
  async function decide(id, ok) {
    const action = S && S.approvals.find((a) => a.id === id);
    if (!action || deciding.has(id)) return;
    const epoch = sessionEpoch;
    // Lo grave (evacuar, parar el concierto, cerrar zona, pedir ayuda externa) exige un segundo clic.
    if (ok && graveAction(action) && !armed.has(id)) {
      armed.add(id);
      setTimeout(() => { if (epoch === sessionEpoch) { armed.delete(id); render(); } }, 8000);
      render();
      return;
    }
    armed.delete(id);
    const note = notes.get(id) || "";
    const st = $("st-" + id);
    if (st) st.textContent = "Enviando la decisión…";
    deciding.add(id);
    const r = await post("/api/approve", { action_id: id, session_id: S.session.id, ok, note });
    if (epoch !== sessionEpoch) return;
    deciding.delete(id);
    const text = r.ok === false ? r.error : r.pending
      ? `Firma registrada; esperando segunda persona (${r.votes} de ${r.required}).`
      : "Decisión registrada; esperando confirmación del estado.";
    if (r.ok !== false) {
      signatures.set(id, { votes: r.votes || 0, required: r.required || action.required || 1, text });
      if (!r.pending) notes.delete(id);
    }
    render();
    const status = $("st-" + id);
    if (status) { status.textContent = text; status.className = "status" + (r.ok === false ? " err" : ""); }
  }
  async function runWhatif(zone) {
    const epoch = sessionEpoch;
    const kind = ($("wi-kind") || {}).value || "reroute";
    const to = ($("wi-to") || {}).value;
    const body = { kind, zone, to, fraction: 0.5, state: "restricted", minutes: 15 };
    $("wi-status").textContent = "Ensayando los próximos 15 minutos en el gemelo…";
    try {
      const r = await U.api("/api/whatif", body);
      if (epoch !== sessionEpoch) return;
      whatif = Object.assign({}, r, { action: body });
      render();
    } catch (e) { if (epoch === sessionEpoch && $("wi-status")) { $("wi-status").textContent = e.message; $("wi-status").className = "status err"; } }
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
          <p class="status" role="status" id="st-${E(a.id)}">${E((signatures.get(a.id) || {}).text || `${a.votes || 0} de ${a.required || 1} firmas registradas.`)}</p></div>`).join("")
        : `<div class="box"><h3>NO HAY NINGUNA PETICIÓN PENDIENTE</h3>
          <p class="tiny">Mando propone «pedir ayuda externa» cuando el caso lo necesita (por ejemplo, una parada cardiaca
            que corresponde a una ambulancia del 112). Cuando lo haga, aparecerá aquí para que una persona lo autorice.
            Sin esa autorización registrada, el servidor no deja salir la acción (segundo cerrojo en el bucle).</p></div>`}`);
  }
  $("ext-body").addEventListener("click", (ev) => {
    const d = ev.target.closest("[data-decide]");
    if (d) decide(d.dataset.id, d.dataset.decide === "1");
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
    $("theme").textContent = dark ? "Oscuro" : "Claro";
    $("theme").title = dark ? "Cambiar a modo oscuro" : "Cambiar a modo claro";
    try { localStorage.setItem("mando-sala-tema", dark ? "light" : "dark"); } catch (e) { /* sin almacenamiento: da igual */ }
  };
  try {
    if (localStorage.getItem("mando-sala-tema") === "dark") {
      document.documentElement.dataset.theme = "dark";
      $("theme").setAttribute("aria-pressed", "true");
      $("theme").textContent = "Claro";
      $("theme").title = "Cambiar a modo claro";
    }
  } catch (e) { /* idem */ }

  document.addEventListener("keydown", (ev) => {
    if (ev.metaKey || ev.ctrlKey || ev.altKey || ev.repeat) return;
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
      decide(a.id, k === "a");
    }     else if (k === "e") document.body.classList.toggle("escena");
    else if (/^[1-7]$/.test(k)) switchTab(TAB_IDS[Number(k) - 1]);
  });
})();
