/* Pantalla de mando. Sin dependencias. Todo texto que viene del servidor pasa por esc(): el jurado escribe libre. */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const es = (x, nd) => (x == null || isNaN(x) ? "–" : Number(x).toFixed(nd == null ? 1 : nd).replace(".", ","));
  const icon = (name) => `<svg aria-hidden="true"><use href="#i-${name}"/></svg>`;
  const post = (url, body) => MANDO_UI.api(url, body || {}).catch((e) => {
    $("action-error").textContent = e.message; $("action-error").hidden = false;
    setTimeout(() => { $("action-error").hidden = true; }, 7000); return {ok:false};
  });
  const reduced = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  function normalize(s) {
    ["resources","zones","incidents","fronts","reports","plans","approvals","actions","log","strikes"].forEach(k => { if (!Array.isArray(s[k])) s[k] = []; });
    s.session = s.session || {}; s.metrics = s.metrics || {}; s.calls = s.calls || {}; s.calls.calls = s.calls.calls || []; return s;
  }
  const wristbands = list => (list || []).map(w => `<span class="chip info">Pulsera · ${esc(w.label || w.access || w.code || "perfil")}${(w.tags || []).length ? " · " + esc(w.tags.join(", ")) : ""}</span>`).join("");

  const KIND_ES = { dispatch: "ENVIAR", recall: "RETIRAR", notify: "AVISAR", ask: "PREGUNTAR", set_zone: "ZONA", reroute: "DESVIAR",
    broadcast: "MEGAFONÍA", request_external: "AYUDA EXTERNA", evacuate: "EVACUAR", stop_show: "PARAR CONCIERTO", resupply: "REABASTECER",
    merge: "FUSIONAR", dismiss: "DESCARTAR" };
  const STATUS_ES = { proposed: "propuesta", awaiting_approval: "espera persona", executing: "en curso", done: "hecha", rejected: "rechazada",
    failed: "falló", cancelled: "cancelada" };
  const INC_STATUS = { open: ["ABIERTO", "warn"], assigned: ["ASIGNADO", "info"], in_progress: ["ATENDIDO", "ok"], resolved: ["RESUELTO", "ok"],
    false_alarm: ["FALSA ALARMA", ""], failed: ["FALLIDO", "bad"] };
  const PHASE_ES = { closed: "cerrado", doors: "apertura de puertas", concerts: "conciertos", concerts_peak: "conciertos", headliner: "cabeza de cartel",
    egress: "salida", stopped: "CONCIERTO PARADO" };
  const CH_ES = { voice: "voz", sms: "SMS", whatsapp: "WhatsApp", sensor: "sensor", radio: "radio", operator: "operador" };
  const LETTER = { security: "S", medical: "", ambulance: "", tech: "T", logistics: "L", volunteer: "V" };
  const CLOSED = { resolved: 1, false_alarm: 1, failed: 1 };

  let selectedIncident = null;
  window.addEventListener("mando:selection", ev => {selectedIncident=ev.detail; schedule();});
  let S = null, plano = null, festival = null, zoneName = {}, resName = {};
  let seenReports = new Set(), seenStrikes = 0, seenBreaks = new Set(), firstState = true;
  let sticky = null;       // {oldId, until}: la rotura de un supuesto se queda a la vista unos segundos REALES
  let bannerTimer = null;
  const tokens = {};

  // ------------------------------------------------------------------ arranque
  function loadFestival() { MANDO_UI.api("/api/festival").then((f) => {
    festival = f;
    (f.zones || []).forEach((z) => (zoneName[z.id] = z.name));
    plano = PLANO.build($("plano"), f);
    Object.entries(plano.zones).forEach(([id, p]) => {
      p.g.dataset.zone = id; p.g.dataset.select = "zone"; p.g.setAttribute("tabindex", "0"); p.g.setAttribute("role", "button"); p.g.setAttribute("aria-label", (zoneName[id] || id) + ": detalle y ensayo");
    });
    connect();
  }).catch(() => { $("conn").hidden=false; setTimeout(loadFestival,3000); }); }
  loadFestival();
  const caseAlias = {};
  fetch("/api/cases").then((r) => r.json()).then((cases) => {
    cases.forEach((c) => (caseAlias[c.id] = c.alias));
    $("case-select").innerHTML = cases.map((c) => `<option value="${esc(c.alias)}">${esc(c.alias)} · ${esc(c.title)}</option>`).join("");
  }).catch(()=>{ $("case-select").innerHTML='<option>Casos no disponibles</option>'; });

  function connect() {
    const poll=()=>MANDO_UI.api("/api/state").then(s=>{S=normalize(s);$("conn").hidden=true;schedule();}).catch(()=>$("conn").hidden=false);
    poll();
    if(!window.EventSource){setInterval(poll,2000);return;}
    const src = new EventSource("/api/stream");
    src.addEventListener("state", (ev) => { $("conn").hidden = true; S = normalize(JSON.parse(ev.data)); schedule(); });
    src.onerror = () => { $("conn").hidden = false; };
  }
  let queued = false;
  function schedule() { if (!queued) { queued = true; requestAnimationFrame(() => { queued = false; render(); }); } }

  // ------------------------------------------------------------------ pintado
  function render() {
    const presentation = $('presentation-status');
    if (presentation && S) { presentation.textContent = S.presentation?.banner || ''; presentation.hidden = !presentation.textContent; }
    const hrPanel = $("happyrobot-status");
    if (hrPanel && S) hrPanel.innerHTML = Object.entries(S.happyrobot || {}).map(([name, w]) =>
      `<p><b>${esc(name)}</b> · ${w.configured ? "configurado" : "sin configurar"}<br><small>Envío: ${esc(w.last_request || "—")} · Evento: ${esc(w.last_event || "—")}${w.last_error ? " · " + esc(w.last_error) : ""}</small>${w.run_url && /^https?:\/\//.test(w.run_url) ? ` · <a href="${esc(w.run_url)}" target="_blank" rel="noopener">Ver run</a>` : ""}</p>`).join("");
    if (!S || !plano) return;
    resName = {}; S.resources.forEach((r) => (resName[r.id] = r.name));
    header(); map(); fronts(); reports(); plan(); approvals(); log(); calls(); score(); strip(); board(); events();
    window.dispatchEvent(new CustomEvent("mando:state", {detail:S}));
    firstState = false;
  }

  function header() {
    const se = S.session, c = S.clock || {}, w = S.weather || {};
    $("case-title").innerHTML = `<strong>${esc(se.title || se.case)}</strong> · ${esc(se.case)} · semilla ${esc(se.seed)} · agente: ${esc(se.agent)}`;
    $("clock-day").textContent = "DÍA " + (c.day || "–");
    $("clock-hhmm").textContent = c.hhmm || "--:--";
    $("clock-t").textContent = `min ${S.t} / ${se.duration_min || "–"}`;
    const ph = $("clock-phase"); ph.textContent = PHASE_ES[c.show_phase] || c.show_phase || ""; ph.className = "phase" + (c.show_phase === "stopped" ? " stopped" : "");
    $("weather").innerHTML =
      `<span class="${w.temp_c >= 35 ? "hot" : ""}">${icon("temp")}${es(w.temp_c, 0)} °C</span>` +
      `<span class="${w.wind_kmh >= 50 ? "alert" : ""}">${icon("wind")}${es(w.wind_kmh, 0)} km/h</span>` +
      (w.rain ? `<span class="alert">${icon("rain")}lluvia</span>` : "") + (w.alert ? `<span class="alert">${icon("bolt")}${esc(w.alert)}</span>` : "");
    const bp = $("btn-play");
    bp.textContent = se.done ? "FIN DEL CASO" : se.running ? "PAUSA" : "REANUDAR"; bp.className = "btn" + (se.running ? "" : " paused");
    document.querySelectorAll("#speed button").forEach((b) => b.classList.toggle("on", Number(b.dataset.speed) === Number(se.speed)));
    if (document.activeElement !== $("comms-select")) $("comms-select").value = se.comms_mode;
    const cs = $("case-select"), mine = caseAlias[se.case];
    if (mine && document.activeElement !== cs && cs.value !== mine) cs.value = mine;
  }

  function sevClass(i) { return i.severity >= 8 ? "sev-hi" : i.severity >= 5 ? "sev-mid" : "sev-lo"; }

  function map() {
    const zs = {}; S.zones.forEach((z) => (zs[z.id] = z));
    const egress = (S.clock || {}).show_phase === "egress";
    S.zones.forEach((z) => {
      const p = plano.zones[z.id]; if (!p) return;
      p.g.setAttribute("class", `zone ${PLANO.densityClass(z.density)} st-${z.state}` + (z.flags && z.flags.evacuating ? " evac" : ""));
      p.dens.innerHTML = `${es(z.density)}<tspan> /m²</tspan>`;
      p.pct.textContent = Math.round(z.ratio * 100) + " %";
      let st = z.state === "closed" ? "CERRADA" : z.state === "restricted" ? "RESTRINGIDA" : "";
      if (z.flags && z.flags.evacuating) st = "EVACUANDO";
      if (z.flags && z.flags.power === false) st = (st ? st + " · " : "") + "SIN LUZ";
      if (z.flags && z.flags.structure_ok === false) st = (st ? st + " · " : "") + "ESTRUCTURA";
      p.state.textContent = st;
    });
    // flujo: sentido estimado por cómo cambian las ocupaciones de los dos extremos en el último minuto
    Object.values(plano.edges).forEach((e) => {
      if (!e.flow) return;
      const a = zs[e.a], b = zs[e.b]; if (!a || !b) return;
      const score = (b.delta || 0) - (a.delta || 0), mag = Math.abs(score);
      e.flow.setAttribute("class", "flow" + (mag < 12 ? "" : (score > 0 ? " fwd" : " rev") + (mag > 120 ? " strong" : "")));
    });
    Object.entries(plano.outside).forEach(([g, line]) => {
      const z = zs[g]; const closed = z && z.state === "closed";
      line.setAttribute("class", "flow outside" + (closed ? "" : egress ? " rev" : " fwd"));
    });
    // desvíos decididos por Mando
    plano.gReroutes.innerHTML = "";
    S.zones.forEach((z) => {
      const to = z.flags && z.flags.reroute_to; if (!to || !PLANO.ZONES[to]) return;
      const a = PLANO.center(z.id), b = PLANO.center(to);
      const bend = a.x === b.x ? 95 : 0;
      const g = PLANO.el("g", { class: "reroute" }, plano.gReroutes);
      PLANO.el("path", { d: `M${a.x} ${a.y} Q ${(a.x + b.x) / 2 + bend} ${(a.y + b.y) / 2} ${b.x} ${b.y}`, "marker-end": "url(#arr)" }, g);
      const t = PLANO.el("text", { x: (a.x + b.x) / 2 + bend / 2, y: (a.y + b.y) / 2 - 12 }, g); t.textContent = "DESVÍO DE MANDO";
    });
    // recursos: fichas que se mueven de zona en zona
    const slot = {};
    S.resources.forEach((r) => {
      const L = PLANO.ZONES[r.zone]; if (!L) return;
      const n = (slot[r.zone] = (slot[r.zone] || 0) + 1) - 1;
      const perRow = Math.max(1, Math.floor((L.w - 16) / 30));
      const x = L.x + L.w - 20 - (n % perRow) * 30, y = L.y + L.h - 18 - Math.floor(n / perRow) * 30;
      let t = tokens[r.id];
      if (!t) { t = tokens[r.id] = makeToken(r); }
      t.setAttribute("class", `token k-${r.kind} s-${r.status}` + (r.real ? " real" : ""));
      t.dataset.select="zone"; t.dataset.zone=r.zone; t.setAttribute("tabindex","0"); t.setAttribute("role","button"); t.setAttribute("aria-label",`${r.name || r.id}: ver zona y plan`);
      t.style.transform = `translate(${x}px, ${y}px)`;
      t.querySelector("title").textContent = `${r.name} · ${r.status}` + (r.eta ? ` · llega en ${r.eta} min` : "");
    });
    Object.keys(tokens).forEach((id) => { if (!resName[id]) { tokens[id].remove(); delete tokens[id]; } });
    // incidentes: marcador con su prioridad
    plano.gPins.innerHTML = "";
    const perZone = {};
    S.incidents.filter((i) => !CLOSED[i.status] && i.zone && PLANO.ZONES[i.zone]).slice(0, 12).forEach((i) => {
      const L = PLANO.ZONES[i.zone], n = (perZone[i.zone] = (perZone[i.zone] || 0) + 1) - 1;
      const g = PLANO.el("g", { class: `pin ${sevClass(i)}` + (i.life_threat ? " life" : ""), transform: `translate(${L.x + L.w - 26 - n * 46}, ${L.y + 26})` }, plano.gPins);
      PLANO.el("circle", { r: 20 }, g);
      PLANO.el("text", {}, g).textContent = i.priority >= 9.95 ? "10" : es(i.priority);
    });
  }

  function makeToken(r) {
    const g = PLANO.el("g", { class: "token", "data-resource": r.id }, plano.gTokens);
    PLANO.el("title", {}, g);
    PLANO.el("circle", { r: 17, class: "halo" }, g);
    PLANO.el("circle", { r: 14, class: "ring" }, g);
    if (r.kind === "security") PLANO.el("path", { d: "M-9 -10 H9 V1 Q9 9 0 12 Q-9 9 -9 1 Z", class: "shape" }, g);
    else if (r.kind === "medical") PLANO.el("circle", { r: 10, class: "shape" }, g);
    else if (r.kind === "ambulance") PLANO.el("rect", { x: -12, y: -9, width: 24, height: 18, rx: 4, class: "shape" }, g);
    else PLANO.el("rect", { x: -8, y: -8, width: 16, height: 16, class: "shape", transform: "rotate(45)" }, g);
    if (r.kind === "medical" || r.kind === "ambulance") PLANO.el("path", { d: "M0 -6 V6 M-6 0 H6", class: "plus" }, g);
    else PLANO.el("text", {}, g).textContent = LETTER[r.kind] || "";
    return g;
  }

  // Tablero de frentes: una fila por incidente vivo. La reordenación se ANIMA (técnica FLIP) para que se vea que
  // entra un imprevisto y Mando recoloca los demás sin soltar ninguno.
  const frontEls = { fronts: new Map(), "fronts-mini": new Map() };
  function frontRow(f) {
    const who = (f.resources || []).join(", ");
    const sev = f.severity >= 8 ? "sev-hi" : f.severity >= 5 ? "sev-mid" : "sev-lo";
    const wait = f.why_waiting ? `<span class="wait">${esc(f.why_waiting)}</span>` : "";
    return { cls: `front ${sev}` + (f.life_threat ? " life" : "") + (f.unforeseen ? " unforeseen" : ""), html:
      `<div class="prio">${f.priority >= 9.95 ? "10" : es(f.priority)}</div>
       <div class="what"><b>${esc(cap(f.label))}</b>
         ${wristbands(f.wristbands)}${f.unforeseen ? '<span class="chip x">IMPREVISTO</span>' : ""}${f.reports > 1 ? `<span class="chip">×${f.reports} avisos</span>` : ""}${f.replans > 1 ? `<span class="chip warn">replanificado ×${f.replans}</span>` : ""}</div>
       <div class="state"><span class="chip ${/sitio/.test(f.state) ? "ok" : /camino/.test(f.state) ? "info" : "warn"}">${esc(f.state)}</span></div>
       <div class="who"><span class="where">${esc(f.zone_name || "")}</span> · ${who ? esc(who) + (f.eta ? ` · <b>llega en ${esc(f.eta)} min</b>` : "") : wait || "sin equipo todavía"}${who && wait ? " · " + wait : ""}</div>` };
  }
  function fronts() {
    const list = S.fronts || [];
    const closed = S.incidents.length - list.length;
    $("inc-count").textContent = `${list.length} a la vez · ${closed} cerrados · pico ${S.metrics.fronts_peak || list.length}`;
    $("fronts-mini-count").textContent = `${list.length} a la vez`;
    ["fronts", "fronts-mini"].forEach((boxId) => {
      const box = $(boxId), els = frontEls[boxId], max = boxId === "fronts" ? 8 : (S.approvals || []).length ? 4 : 6;
      const before = new Map(); els.forEach((el, id) => before.set(id, el.getBoundingClientRect().top));
      const keep = new Set();
      list.slice(0, max).forEach((f) => {
        let el = els.get(f.id); const r = frontRow(f), fresh = !el;
        if (fresh) { el = document.createElement("div"); els.set(f.id, el); }
        el.className = r.cls; el.dataset.select = "incident"; el.dataset.incident = f.id; el.setAttribute("role", "button"); el.tabIndex = 0; if(el.innerHTML !== r.html) el.innerHTML = r.html; box.appendChild(el); keep.add(f.id);
        if (fresh && !firstState && !reduced()) el.animate([{ opacity: 0, transform: "translateX(-24px)", background: "rgba(181,149,255,.55)" },
          { opacity: 1, transform: "none", background: "rgba(181,149,255,.12)" }, { background: "transparent" }], { duration: 2400, easing: "ease-out" });
      });
      els.forEach((el, id) => { if (!keep.has(id)) { el.remove(); els.delete(id); } });
      els.forEach((el, id) => {
        const was = before.get(id); if (was == null) return;
        const dy = was - el.getBoundingClientRect().top;
        if (Math.abs(dy) > 2 && !reduced()) el.animate([{ transform: `translateY(${dy}px)` }, { transform: "none" }], { duration: 650, easing: "cubic-bezier(.2,.8,.2,1)" });
      });
      let more = box.querySelector(".more");
      if (list.length > max) { if (!more) { more = document.createElement("div"); more.className = "more"; } more.textContent = `+ ${list.length - max} frentes más, de menor prioridad`; box.appendChild(more); }
      else if (more) more.remove();
      let empty = box.querySelector(".empty");
      if (!list.length) { if (!empty) { empty = document.createElement("div"); empty.className = "empty"; empty.textContent = "Ningún frente abierto."; box.appendChild(empty); } }
      else if (empty) empty.remove();
    });
  }
  const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : "");

  function reports() {
    // Un renglón por incidente (el último aviso, con ×N) y uno por aviso todavía sin clasificar.
    const groups = new Map();
    S.reports.forEach((r) => {
      const key = r.incident || "_" + r.id;
      const g = groups.get(key) || { n: 0 };
      g.n += 1; g.last = r; groups.delete(key); groups.set(key, g);
    });
    const rows = Array.from(groups.values()).reverse().slice(0, 8).map((g) => {
      const r = g.last, fresh = !firstState && !seenReports.has(r.id);
      const jury = /^j-/.test(r.id) || r.source === "jurado";
      const ch = r.via || r.channel || "web";
      return `<div role="button" tabindex="0" data-select="report" data-report="${esc(r.id)}" data-incident="${esc(r.incident || "")}" class="rep ch-${esc(ch)}${jury ? " jury" : ""}${fresh ? " fresh" : ""}">${MANDO_UI.channel(ch)}
        <div class="txt"><em>${esc(MANDO_UI.labels[ch] || ch)} · ${esc(r.source || "")}${r.lang && r.lang !== "es" ? " · " + esc(r.lang) : ""}</em>${esc(r.text)}</div>
        <div class="tags">${wristbands(r.wristband ? [r.wristband] : [])}${g.n > 1 ? `<span class="chip x">×${g.n}</span>` : ""}${r.incident ? `<span class="chip info">${esc(r.incident)}</span>` : '<span class="chip">nuevo</span>'}${jury ? '<span class="chip x">JURADO</span>' : ""}</div></div>`;
    });
    S.reports.forEach((r) => seenReports.add(r.id));
    $("rep-count").textContent = S.reports.length + " recibidos";
    const focusedReport = document.activeElement?.dataset.report;
    $("reports").innerHTML = rows.join("") || '<div class="empty">Sin avisos todavía.</div>';
    if(focusedReport) Array.from($("reports").children).find(e=>e.dataset.report===focusedReport)?.focus({preventScroll:true});
  }

  function stepHtml(s, n) {
    const who = s.resource ? resName[s.resource] || s.resource : s.zone ? zoneName[s.zone] || s.zone : "";
    const cls = s.status === "done" ? "ok" : s.status === "executing" ? "info" : s.status === "awaiting_approval" ? "warn" : /failed|rejected|cancelled/.test(s.status) ? "bad" : "";
    return `<li class="step"><span class="n">${n}</span><span class="what"><b>${esc(KIND_ES[s.kind] || s.kind)}</b> ${esc(who)} <span>${esc(humanZones(s.reason || s.why || ""))}</span></span><span class="chip ${cls}">${esc(STATUS_ES[s.status] || s.status)}</span></li>`;
  }
  function planHtml(p, old, brokenId) {
    const steps = (p.steps || []).slice(0, old ? 2 : 5).map((s, k) => stepHtml(s, k + 1)).join("");
    const ass = (p.assumptions || []).filter((a) => !old || a.id === brokenId).slice(0, 5).map((a) => a.holds
      ? `<li class="assume">${icon("check")}<span>${esc(a.text)}</span></li>`
      : `<li class="assume broken">${icon("cross")}<span>${esc(a.text)}<small>roto en el minuto ${esc(a.broken_at)}</small></span></li>`).join("");
    const reh = !old && p.rehearsal ? `<div class="rehearsal"><b>ENSAYADO EN EL GEMELO</b>${p.rehearsal.map((o) =>
      `<span class="opt ${o.ok === false ? "bad" : o.ok ? "ok" : ""}${o.chosen ? " chosen" : ""}">${esc(o.label)}${o.value != null ? ` → <i>${esc(typeof o.value === "number" ? es(o.value) : o.value)}${esc(o.unit || "")}</i>` : ""}${o.ok === false ? icon("cross") : o.ok ? icon("check") : ""}</span>`).join("")}</div>` : "";
    const ver = p.versions_total > 1 ? ` · versión ${p.version} de ${p.versions_total}` : "";
    return `<div class="body ${old ? "plan-old" : ""}" data-plan="${esc(p.id)}" data-incident="${esc(p.incident || "")}"><div class="for">${esc(p.id)} · ${esc(p.incident || "")} · minuto ${esc(p.t)}${ver}</div>
      <div class="objective">${esc(p.objective)}</div>${reh}
      ${!old && p.why && p.supersedes ? `<div class="because"><b>PORQUE</b>${esc(p.why)}</div>` : ""}
      ${steps ? `<h3>PASOS</h3><ol>${steps}</ol>` : ""}
      ${ass ? `<h3>${old ? "SUPUESTO QUE FALLÓ" : "SUPUESTOS · de qué depende este plan"}</h3><ul>${ass}</ul>` : ""}</div>`;
  }
  function plan() {
    const plans = S.plans || [], byId = {}; plans.forEach((p) => (byId[p.id] = p));
    if(selectedIncident) {
      const selected=plans.filter(p=>p.incident===selectedIncident).slice(-1)[0];
      $("plan").innerHTML=selected ? planHtml(selected,false) : '<div class="empty">Todavía no hay plan para este incidente.</div>';
      $("plan-ref").textContent=selected ? selected.id : selectedIncident; return;
    }
    const now = Date.now();
    // roturas recientes: plan invalidado por un supuesto en los últimos minutos simulados
    const broken = plans.filter((p) => p.invalidated_by && (p.assumptions || []).some((a) => a.id === p.invalidated_by && a.broken_at != null && S.t - a.broken_at <= 6))
      .sort((a, b) => b.t - a.t)[0];
    if (broken && !seenBreaks.has(broken.id)) {
      seenBreaks.add(broken.id);
      if (!firstState) { sticky = { oldId: broken.id, until: now + 14000 }; bigBreak(broken, plans.filter((p) => p.supersedes === broken.id).slice(-1)[0]); }
    }
    const showOld = sticky && now < sticky.until && byId[sticky.oldId] ? byId[sticky.oldId] : broken;
    let html = "";
    if (showOld) {
      const next = plans.filter((p) => p.supersedes === showOld.id).slice(-1)[0];
      html = `<div class="broken-band"><span>SUPUESTO ROTO</span><small>${esc(showOld.id)} ya no vale</small></div>` + planHtml(showOld, true, showOld.invalidated_by) +
        (next ? '<div class="plan-new-tag">PLAN NUEVO</div>' + planHtml(next, false) : '<div class="plan-new-tag">REPLANIFICANDO…</div>');
      $("plan-ref").textContent = next ? next.id : "";
    } else {
      const order = {}; S.incidents.forEach((i, k) => (order[i.id] = CLOSED[i.status] ? 1000 + k : k));
      const live = plans.filter((p) => p.live !== false && !p.invalidated_by).sort((a, b) => (order[a.incident] ?? 999) - (order[b.incident] ?? 999) || b.t - a.t)[0] || plans.slice(-1)[0];
      html = live ? planHtml(live, false) : '<div class="empty">Mando todavía no ha necesitado un plan.</div>';
      $("plan-ref").textContent = live ? `${live.id} · ${plans.length} planes` : "";
    }
    $("plan").innerHTML = html;
  }

  // La firma del producto, a pantalla casi completa durante 3 s: supuesto roto → plan tachado → plan nuevo.
  let breakTimer = null, lastBig = 0;
  function bigBreak(old, next) {
    if (Date.now() - lastBig < 5000) { banner("break", "OTRO SUPUESTO ROTO → MANDO REPLANIFICA", 3000); return; }  // roturas seguidas: no se apilan
    lastBig = Date.now();
    const a = (old.assumptions || []).find((x) => x.id === old.invalidated_by) || {};
    $("bo-what").textContent = "«" + (a.text || "un supuesto del plan") + "»";
    $("bo-old").textContent = old.objective;
    $("bo-new").textContent = next ? next.objective + (next.why ? " — porque " + next.why : "") : "replanificando…";
    const o = $("break-overlay"); o.hidden = false; o.classList.remove("go"); void o.offsetWidth; o.classList.add("go");
    clearTimeout(breakTimer); breakTimer = setTimeout(() => (o.hidden = true), 3000);
  }

  function approvals() {
    const ap = S.approvals || [];
    $("approvals-panel").classList.toggle("waiting", ap.length > 0);
    $("ap-count").textContent = ap.length ? ap.length + " pendientes" + (ap[0].required===2 ? ` · ${ap[0].votes||0} de 2 firmas` : "") : "";
    if (ap.length && $("ap-note")?.dataset.id === ap[0].id) {
      const c=ap[0].card || {}, w=$("approvals").querySelector(".window b"), clock=$("approvals").querySelector(".window");
      if(w && c.remaining_min != null) w.textContent=c.remaining_min;
      if(clock) clock.classList.toggle("late", c.remaining_min != null && c.remaining_min<=1);
      const escalation=$("approval-escalation"); if(escalation) {escalation.hidden=!c.escalated; escalation.textContent="Sin decisión a tiempo · escalado al suplente"+(c.deputy?": "+c.deputy:"");}
      const count=$("approvals").querySelector(".ap-more"); if(count) count.textContent=ap.length>1?`+ ${ap.length-1} más en cola`:"";
      return; // Mantener el foco, la nota y las tablas abiertas mientras cambia el reloj.
    }
    if (!ap.length) { $("approvals").innerHTML = '<div class="ap-none">Nada pendiente. Lo grave (evacuar, parar el concierto, cerrar una zona, llamar al 112) siempre espera aquí.</div>'; return; }
    const focus = document.activeElement?.closest("#approvals button[data-ok]")?.dataset.ok;
    const savedNote = $("ap-note")?.dataset.id === ap[0].id ? $("ap-note").value : "";
    const a = ap[0], c = a.card;
    const branch = (b, cls, title) => b ? `<div class="future fut-${cls}"><h4>${title}${b.horizon_min ? ` · a ${esc(b.horizon_min)} min` : ""}</h4>${b.text ? `<p>${esc(b.text)}</p>` : ""}${(b.figures || []).map((f) =>
      `<div class="fig"><b>${esc(typeof f.v === "number" ? es(f.v, Number.isInteger(f.v) ? 0 : 1) : f.v)}</b><span>${esc(f.k)}</span></div>`).join("")}</div>` : "";
    const head = c ? `<div class="to"><span>DECIDE</span><b>${esc(c.role)}${c.name ? " · " + esc(c.name) : ""}</b>${c.deputy ? `<small>suplente: ${esc(c.deputy)}</small>` : ""}
        ${c.remaining_min != null ? `<div class="window ${c.remaining_min <= 1 ? "late" : ""}"><b>${esc(c.remaining_min)}</b> min de ventana</div>` : ""}</div>
        <div id="approval-escalation" class="escalated" ${c.escalated ? "" : "hidden"}>SIN DECISIÓN A TIEMPO · ESCALADO AL SUPLENTE${c.deputy ? ": " + esc(c.deputy) : ""}</div>` : "";
    $("approvals").innerHTML = `<div class="ap${c ? " card" : ""}"><div class="meta">${esc(a.id)} · ${esc(KIND_ES[a.kind] || a.kind)}${a.zone_name ? " · " + esc(a.zone_name) : ""} · pedido en el minuto ${esc(a.t)}</div>
      ${head}<div class="q">${esc((c && c.question) || a.why)}</div>
      ${c && (c.if_approved || c.if_vetoed) ? `<div class="futures">${branch(c.if_approved, "yes", "SI APRUEBAS" + (c.rehearsed ? " · ensayado" : ""))}${branch(c.if_vetoed, "no", "SI VETAS" + (c.rehearsed ? " · ensayado" : ""))}</div>` : ""}
      <div id="decision-graph"></div><label class="data-note" for="ap-note">Nota para la decisión</label><input id="ap-note" value="${esc(savedNote)}" data-id="${esc(a.id)}" placeholder="Nota para Mando (opcional): por qué sí o por qué no" maxlength="200">
      <div class="row"><button class="yes" data-ok="1">APROBAR<kbd>A</kbd></button><button class="no" data-ok="0">VETAR<kbd>V</kbd></button></div></div>` +
      (ap.length > 1 ? `<div class="ap-more">+ ${ap.length - 1} más en cola</div>` : "");
    if(focus) $("approvals").querySelector(`[data-ok="${focus}"]`)?.focus({preventScroll:true});
  }
  // Mando escribe los ids de zona («front_pit»): en pantalla va el nombre que entiende una persona.
  function humanZones(text) { return String(text || ""); }  // los ids ya llegan traducidos del servidor
  function decide(ok) {
    const a = S && (S.approvals || [])[0]; if (!a) return;
    const note = $("ap-note") ? $("ap-note").value : "";
    post("/api/approve", { action_id: a.id, ok: !!ok, note });
    if ($("ap-note")) $("ap-note").blur();
  }
  $("approvals").addEventListener("click", (ev) => { const b = ev.target.closest("button[data-ok]"); if (b) decide(b.dataset.ok === "1"); });

  function log() {
    const rows = (S.log || []).filter((e) => e.kind !== "report").slice(-7).reverse().map((e) =>
      `<div class="logline k-${esc(e.kind)}"><span class="t">${String(e.t).padStart(3, "0")}′</span><span class="k">${esc(LOG_ES[e.kind] || e.kind)}</span><span class="m">${esc(e.text)}</span></div>`);
    $("log").innerHTML = rows.join("");
    // eje de tiempo: una marca por plan, rotura, aprobación y golpe
    const dur = S.session.duration_min || Math.max(60, S.t), ax = $("axis"); const W = 1000;
    ax.setAttribute("viewBox", `0 0 ${W} 16`);
    const color = { plan: "#2fd17a", assumption_broken: "#ff4d4d", approval: "#ffb02e", chaos: "#b595ff" };
    let h = `<rect x="0" y="7" width="${W}" height="2" fill="#1e2b37"/><rect x="0" y="6" width="${(S.t / dur) * W}" height="4" fill="#4cc9f0"/>`;
    (S.log || []).forEach((e) => { if (color[e.kind]) h += `<rect x="${(e.t / dur) * W - 2}" y="${e.kind === "assumption_broken" || e.kind === "chaos" ? 0 : 3}" width="4" height="${e.kind === "assumption_broken" || e.kind === "chaos" ? 16 : 10}" fill="${color[e.kind]}"/>`; });
    ax.innerHTML = h;
  }
  const LOG_ES = { incident: "incidente", plan: "plan", assumption_broken: "supuesto roto", action: "acción", outcome: "resultado", approval: "persona", lesson: "lección", chaos: "golpe" };

  const RES = { accept: "ACEPTA", reject: "RECHAZA", no_answer: "NO CONTESTA", answer: "RESPONDE" };
  let pendingWeb = [], webTimer = 0;
  function calls() {
    const v = S.calls || { calls: [] };
    $("calls-mode").innerHTML = v.mode === "happyrobot" ? `<span class="chip real">HAPPYROBOT · ${v.voice_mode === "web_call" ? "LLAMADA WEB" : "TELÉFONO"}</span> ${v.real_sent} reales` + (v.fallbacks ? ` · ${v.fallbacks} a simulación` : "") : "simuladas";
    // Llamadas web esperando a que alguien descuelgue: el enlace secreto solo lo ve el puesto de control.
    if (v.calls.some((c) => c.waiting_pickup) && Date.now() - webTimer > 1500) {
      webTimer = Date.now();
      fetch("/api/webcalls").then((r) => (r.ok ? r.json() : [])).then((w) => { pendingWeb = w; schedule(); }).catch(() => {});
    } else if (!v.calls.some((c) => c.waiting_pickup)) pendingWeb = [];
    const web = pendingWeb.slice(0, 1).map((w) => `<div class="webcall"><img src="/qr?path=/llamada/${encodeURIComponent(w.call_id)}" alt="QR de la llamada">
      <div><span class="chip real">LLAMADA WEB</span><b>Llamada para ${esc(w.title)}</b><p>${esc(w.order_text)}</p>
      <a href="/llamada/${encodeURIComponent(w.call_id)}" target="_blank" rel="noopener">abrir en este equipo</a>${pendingWeb.length > 1 ? ` · <span class="chip warn">+${pendingWeb.length - 1} llamadas esperando</span>` : ""}</div></div>`);
    const rows = v.calls.filter((c) => (c.kind !== "notify" || c.real) && !c.waiting_pickup).slice(web.length ? -1 : -3).reverse().map((c) => {
      const verb = c.kind === "ask" ? "Preguntando a" : c.kind === "recall" ? "Retirando a" : c.channel === "sms" ? "SMS a" : "Llamando a";
      const res = c.result ? RES[c.result] + (c.result === "accept" && c.eta_min != null ? ` · ${c.eta_min} min` : "") : (c.stage || "llamando").toUpperCase();
      const name = c.real && c.title ? c.title : c.to;
      return `<div class="call"><div class="who">${esc(c.result ? name : verb + " " + name)}<small>${esc(CH_ES[c.channel] || c.channel)} · ${esc(c.incident || "")}</small>
        ${c.real ? '<span class="chip real">REAL</span>' : c.fell_back ? '<span class="chip warn">CAE A SIM</span>' : ""}${c.taken_over ? '<span class="chip warn">LA LLEVA UNA PERSONA</span>' : ""}</div>
        <div class="res ${c.result || "ringing"}">${esc(res)}</div>${c.signal ? `<div class="said sig">CAMBIO DE ORDEN EN LA LLAMADA: «${esc(c.signal.text)}»</div>` : c.text ? `<div class="said">«${esc(c.text)}»</div>` : ""}
        ${c.can_take ? `<div class="take"><button data-listen="${esc(c.action_id)}">ESCUCHAR</button><button class="hot" data-take="${esc(c.action_id)}">TOMAR LA LLAMADA</button></div>` : ""}</div>`;
    });
    $("calls").innerHTML = web.join("") + rows.join("") || '<div class="empty">Ninguna llamada todavía.</div>';
  }
  $("calls").addEventListener("click", (ev) => {
    const b = ev.target.closest("button"); if (!b) return;
    const id = b.dataset.take || b.dataset.listen; if (!id) return;
    window.open(`/llamada/puesto?accion=${encodeURIComponent(id)}&modo=${b.dataset.take ? "toma" : "escucha"}`, "_blank", "noopener");
  });

  // Tira del modo escena: la llamada en grande (con su sello) y tres cifras.
  function strip() {
    const v = (S.calls || {}).calls || [];
    // la llamada que importa: la real que sigue viva; si no, la última que ya tiene respuesta; si no, la última
    const talk = v.filter((x) => x.kind !== "notify");
    const c = talk.filter((x) => x.real && !x.result && (x.transcript || []).length).slice(-1)[0] || talk.filter((x) => x.real && !x.result).slice(-1)[0] || talk.filter((x) => x.result).sort((a, b) => (a.t_end || 0) - (b.t_end || 0)).slice(-1)[0] || talk.slice(-1)[0];
    let html = '<div class="quiet">Sin llamadas en curso</div>';
    if (c) {
      const lines = (c.transcript || []).slice(-2).map((l) => `<p class="${l.who === "mando" ? "m" : "p"}"><em>${l.who === "mando" ? "Mando" : esc(c.title || c.to)}</em>${esc(l.text)}</p>`).join("")
        || (c.text ? `<p class="p"><em>${esc(c.title || c.to)}</em>${esc(c.text)}</p>` : `<p class="m"><em>Mando</em>${esc((c.stage || "llamando") + "…")}</p>`);
      html = `<div class="sc-who"><span class="chip ${c.real ? "real" : ""}">${c.real ? (S.calls.voice_mode === "web_call" ? "LLAMADA WEB · HappyRobot" : "LLAMADA REAL · HappyRobot") : "llamada simulada"}</span><b>${esc(c.title || c.to)}</b></div>
        <div class="sc-lines">${c.signal ? `<p class="m sig"><em>Mando · cambio de orden</em>${esc(c.signal.text)}</p>` : ""}${lines}</div>
        <div class="stamp ${c.result || "ringing"}">${esc(c.result ? RES[c.result] + (c.result === "accept" && c.eta_min != null ? ` · ${c.eta_min} min` : "") : "EN CURSO")}</div>`;
    }
    $("strip-call").innerHTML = html;
    const m = S.metrics || {};
    const fig = (val, l, cls) => `<div class="fig ${cls || ""}"><b>${val}</b><span>${l}</span></div>`;
    $("strip-figs").innerHTML = fig(es(m.time_to_first_action), `min a la 1.ª acción · N=${m.time_to_first_action_n || 0}`) +
      fig(`${m.fronts_now || 0}`, `frentes a la vez · pico ${m.fronts_peak || 0}`) +
      fig(m.unsafe_actions, "decisiones graves sin una persona", m.unsafe_actions ? "bad" : "good");
  }

  function score() {
    const m = S.metrics || {};
    const tile = (v, l, cls, small) => `<div class="tile ${cls || ""}"><div class="v">${v}${small ? `<small>${small}</small>` : ""}</div><div class="l">${l}</div></div>`;
    $("score-n").textContent = `esta ejecución · ${m.incidents_total || 0} incidentes · ${m.strikes || 0} golpes`;
    // La latencia de voz se enseña medida y sin listón; el aviso legal inicial no cuenta como latencia del agente.
    const voice = m.voice_turn_latency_ms != null ? tile(m.voice_turn_latency_ms, "ms por turno de voz, medido", "", "N=" + m.voice_turn_latency_n)
      : m.first_word_ms != null ? tile(m.first_word_ms, "ms a la 1.ª palabra, sin el aviso legal", "", "N=" + m.first_word_n)
      : tile("sin llamadas reales", "latencia de voz", "na");
    $("score").innerHTML =
      tile(m.critical_failed, `críticos fallidos de ${m.critical_total}`, m.critical_failed ? "bad" : "good") +
      tile(es(m.time_to_first_action), "min a la primera acción", "", m.time_to_first_action_n ? "N=" + m.time_to_first_action_n : "") +
      tile(m.replans, `replanificaciones · ${m.assumptions_broken || 0} supuestos rotos`) +
      tile(`${m.fronts_now || 0}`, "frentes a la vez", "", "pico " + (m.fronts_peak || 0)) +
      tile(`${m.calls_failed}<small>→</small>${m.calls_recovered}`, "llamadas fallidas → recuperadas", m.calls_failed > m.calls_recovered ? "" : "good", "de " + m.calls_total) +
      tile(m.unsafe_actions, "acciones graves sin aprobación" + (m.unsafe_blocked ? ` · ${m.unsafe_blocked} bloqueadas` : ""), m.unsafe_actions ? "bad" : "good") +
      (m.decision_latency_n ? tile(es(m.decision_latency_min), "min de decisión humana" + (m.decision_latency_s != null ? ` · ${es(m.decision_latency_s, 0)} s reales` : ""), "", "N=" + m.decision_latency_n)
        : tile("sin decisiones", "latencia de decisión humana", "na")) + voice;
  }

  // Marcador JURADO — MANDO, golpes que le quedan al jurado y «el test con tu nombre».
  function board() {
    const b = S.scoreboard || {};
    $("sb-jury").textContent = b.jury || 0; $("sb-mando").textContent = b.mando || 0;
    $("sb-dots").innerHTML = Array.from({ length: b.budget || 3 }, (_, i) => `<i class="${i < (b.left || 0) ? "on" : ""}"></i>`).join("");
    const bar = $("lock-bar"), rp = S.session.replay;
    if (document.activeElement && document.activeElement.id === "lock-author") return;
    if (rp) {
      bar.hidden = false;
      bar.className = "lock-bar " + (rp.result ? (rp.result.passed ? "pass" : "fail") : "run");
      bar.innerHTML = `<b>TEST Nº ${esc(rp.n)} · autor: ${esc(rp.author)}</b><span>${rp.result ? (rp.result.passed ? "PASA" : "NO PASA") +
        ` · críticos fallidos: antes ${esc((rp.before || {}).critical_failed)}, ahora ${esc(rp.result.critical_failed)}` : "re-ejecutando la misma partida, misma semilla, a ×" + esc(S.session.speed)}</span>`;
    } else if (b.locked) {
      bar.hidden = false; bar.className = "lock-bar locked";
      bar.innerHTML = `<b>FALLO BLOQUEADO COMO TEST DE REGRESIÓN Nº ${esc(b.locked.n)} · autor: ${esc(b.locked.author)}</b><button data-run="${esc(b.locked.n)}">RE-EJECUTAR A ×16</button>`;
    } else if (b.can_lock) {
      bar.hidden = false; bar.className = "lock-bar fail";
      bar.innerHTML = `<span>Un golpe ha provocado un fallo crítico: «${esc((b.culprit || {}).label || "")}»</span>
        <input id="lock-author" placeholder="nombre de quien lo rompió" maxlength="40" value="${esc((b.culprit || {}).author || "")}">
        <button data-lock="1">BLOQUEAR COMO TEST Nº ${esc(b.next_n)}</button>`;
    } else bar.hidden = true;
  }
  $("lock-bar").addEventListener("click", (ev) => {
    const b = ev.target.closest("button"); if (!b) return;
    if (b.dataset.lock) { const author = $("lock-author").value; $("lock-author").blur(); post("/api/regression/lock", { author }); }
    if (b.dataset.run) { forget(); post("/api/regression/run", { n: Number(b.dataset.run), speed: 16 }); }
  });

  function events() {
    const n = (S.strikes || []).length ? S.metrics.strikes : 0;
    if (!firstState && n > seenStrikes) { const s = S.strikes[S.strikes.length - 1]; banner("strike", `GOLPE ${s.origin === "jury" ? "DEL JURADO" : "DE CAOS"}: ${s.label}`, 4000); }
    seenStrikes = n;
    if (S.session.done && !firstState && !$("banner").dataset.done) { $("banner").dataset.done = "1"; banner("done", "FIN DEL CASO · informe en /informe", 8000); }
    if (!S.session.done) delete $("banner").dataset.done;
  }
  function banner(kind, text, ms) {
    const b = $("banner"); b.className = "banner " + kind; b.textContent = text; b.hidden = false;
    clearTimeout(bannerTimer); bannerTimer = setTimeout(() => (b.hidden = true), ms);
  }
  setInterval(() => { if (sticky && Date.now() > sticky.until) { sticky = null; schedule(); } }, 1000);

  // ------------------------------------------------------------------ mandos
  const SPEEDS = [1, 4, 16];
  function speedStep(d) { const i = Math.max(0, SPEEDS.indexOf(Number(S.session.speed))); post("/api/control", { cmd: "speed", value: SPEEDS[Math.max(0, Math.min(SPEEDS.length - 1, i + d))] }); }
  $("btn-play").onclick = () => post("/api/control", { cmd: "toggle" });
  $("btn-step").onclick = () => post("/api/control", { cmd: "step" });
  $("btn-reset").onclick = reset;
  $("btn-key-moment").onclick = keyMoment;
  $("speed").onclick = (ev) => { if (ev.target.dataset.speed) post("/api/control", { cmd: "speed", value: Number(ev.target.dataset.speed) }); };
  $("case-select").onchange = (ev) => { forget(); post("/api/session", { case_id: ev.target.value, comms: $("comms-select").value }); ev.target.blur(); };
  $("comms-select").onchange = (ev) => { forget(); post("/api/session", { case_id: $("case-select").value || S.session.case, comms: ev.target.value }); ev.target.blur(); };
  function forget() { seenReports = new Set(); seenBreaks = new Set(); seenStrikes = 0; sticky = null; firstState = true; }
  function reset() { forget(); post("/api/control", { cmd: "reset" }); }
  function keyMoment() { forget(); post('/api/control', {cmd: 'key_moment'}); }
  function qr(show) {
    const o = $("qr-overlay");
    if (show === undefined) show = o.hidden;
    if (show) fetch("/qr").then((r) => { $("qr-url").textContent = r.headers.get("X-Jurado-Url") || ""; return r.blob(); }).then((b) => ($("qr-img").src = URL.createObjectURL(b)));
    o.hidden = !show;
  }
  $("btn-qr").onclick = () => qr(); $("qr-overlay").onclick = () => qr(false);
  // MODO ESCENA: tres gestos legibles sin sonido a cinco metros (plano, plan con supuestos, llamada y tres cifras).
  function scene(on) { document.body.classList.toggle("escena", on === undefined ? !document.body.classList.contains("escena") : on); schedule(); }
  if (new URLSearchParams(location.search).get("escena") === "1") scene(true);
  $("btn-scene").onclick = () => scene();

  document.addEventListener("keydown", (ev) => {
    if (ev.defaultPrevented || (/BUTTON|A|SUMMARY/.test(ev.target.tagName) && (ev.key === " " || ev.key === "Enter"))) return;
    if (/INPUT|TEXTAREA|SELECT/.test(ev.target.tagName)) { if (ev.key === "Escape") ev.target.blur(); return; }
    if (ev.metaKey || ev.ctrlKey || ev.altKey || !S || !$("detail-panel").hidden) return;
    const k = ev.key.toLowerCase();
    if (k === " ") { ev.preventDefault(); post("/api/control", { cmd: "toggle" }); }
    else if (k === "arrowright" || k === "arrowup") { ev.preventDefault(); speedStep(1); }
    else if (k === "arrowleft" || k === "arrowdown") { ev.preventDefault(); speedStep(-1); }
    else if (k === "a") decide(true);
    else if (k === "v") decide(false);
    else if (k === "s") post("/api/control", { cmd: "step" });
    else if (k === "r") reset();
    else if (k === "k") keyMoment();
    else if (k === "q") qr();
    else if (k === "e") scene();
    else if (k === "escape") qr(false);
  });
})();
