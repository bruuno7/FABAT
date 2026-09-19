
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const es = (x, nd) => (x == null || isNaN(x) ? "–" : Number(x).toFixed(nd == null ? 1 : nd).replace(".", ","));
  const post = (url, body) => MANDO_UI.api(url, body).catch(e=>{ $("duel-error").textContent=e.message;return {ok:false}; });
  const planos = {}, tokens = { left: {}, right: {} };
  let S = null, strikeKey = null, hideStrike = 0;
  MANDO_UI.api("/api/festival").then((f) => {
    ["left", "right"].forEach((k) => (planos[k] = PLANO.build($("plano-" + k), f)));
    const src = new EventSource("/api/duel/stream");
    src.addEventListener("state", (ev) => { $("duel-error").textContent=""; S = JSON.parse(ev.data); requestAnimationFrame(render); });
    src.onerror = () => { $("duel-error").textContent="Sin conexión. Reintentando…"; };
  }).catch(e=>$("duel-error").textContent="No se pudo cargar el plano: "+e.message);
  fetch("/api/cases").then((r) => r.json()).then((cs) => cs.forEach((c) => { const o = document.createElement("option"); o.value = c.alias; o.textContent = c.alias + " · " + c.title; $("case-select").append(o); })).catch(()=>$("duel-error").textContent="No se pudo cargar la lista de casos.");

  function audience(text) { return String(text || '').replace(/supuestos?/gi,'datos de los que dependía el plan').replace(/frentes/gi,'incidentes').replace(/golpes?/gi,'imprevisto').replace(/replanifica(?:ndo|ción|ciones|r)?/gi,'cambia el plan'); }
  function side(k) {
    const d = S[k], p = planos[k], zs = {};
    d.zones.forEach((z) => {
      zs[z.id] = z; const e = p.zones[z.id]; if (!e) return;
      e.g.setAttribute("class", `zone ${PLANO.densityClass(z.density)} st-${z.state}`);
      e.dens.textContent = es(z.density); e.pct.textContent = Math.round(z.ratio * 100) + " %";
      e.state.textContent = z.state === "closed" ? "CERRADA" : z.state === "restricted" ? "RESTRINGIDA" : "";
    });
    Object.values(p.edges).forEach((e) => { if (!e.flow) return; const sc = (zs[e.b].delta || 0) - (zs[e.a].delta || 0), m = Math.abs(sc);
      e.flow.setAttribute("class", "flow" + (m < 12 ? "" : (sc > 0 ? " fwd" : " rev") + (m > 120 ? " strong" : ""))); });
    Object.entries(p.outside).forEach(([g, l]) => l.setAttribute("class", "flow outside" + (zs[g].state === "closed" ? "" : " fwd")));
    p.gReroutes.textContent = "";
    d.zones.forEach((z) => { const to = z.flags && z.flags.reroute_to; if (!to) return;
      const a = PLANO.center(z.id), b = PLANO.center(to), bend = a.x === b.x ? 95 : 0, g = PLANO.el("g", { class: "reroute" }, p.gReroutes);
      PLANO.el("path", { d: `M${a.x} ${a.y} Q ${(a.x + b.x) / 2 + bend} ${(a.y + b.y) / 2} ${b.x} ${b.y}`, "marker-end": "url(#arr)" }, g);
      PLANO.el("text", { x: (a.x + b.x) / 2 + bend / 2, y: (a.y + b.y) / 2 - 12 }, g).textContent = "DESVÍO"; });
    p.gPins.textContent = "";
    const per = {};
    d.incidents.filter((i) => !/resolved|false_alarm|failed/.test(i.status) && i.zone && PLANO.ZONES[i.zone]).slice(0, 10).forEach((i) => {
      const L = PLANO.ZONES[i.zone], n = (per[i.zone] = (per[i.zone] || 0) + 1) - 1;
      if (n >= 2) return;  // la lista fija abre un ticket por aviso: con dos marcadores ya se entiende
      const g = PLANO.el("g", { class: "pin " + (i.severity >= 8 ? "sev-hi" : i.severity >= 5 ? "sev-mid" : "sev-lo"), transform: `translate(${L.x + L.w - 26 - n * 46}, ${L.y + 26})` }, p.gPins);
      PLANO.el("circle", { r: 20 }, g); PLANO.el("text", {}, g).textContent = i.priority ? es(i.priority) : "!"; });
    const sc = d.score || {}, tile = (v, l, cls) => `<div class="tile ${cls}"><div class="v">${v}</div><div class="l">${l}</div></div>`;
    $("nums-" + k).innerHTML = tile(`${sc.critical_failed}<small>/${sc.critical_total}</small>`, "críticos fallidos", sc.critical_failed ? "bad" : "good") +
      tile(es(sc.peak_density) + "<small>/m²</small>", "pico de densidad", sc.peak_density > 6.5 ? "bad" : sc.peak_density > 5 ? "" : "good") +
      tile(sc.minutes_over_5, "minutos por encima de 5/m²", sc.minutes_over_5 ? "bad" : "good");
    const peakNow = (d.zones || []).reduce((best,z)=>!best || z.density > best.density ? z : best,null);
    const routes=(d.zones || []).filter(z=>z.flags?.reroute_to).map(z=>`${z.name || z.id} → ${zs[z.flags.reroute_to]?.name || z.flags.reroute_to}`);
    $("label-"+k).textContent = `${peakNow ? "Ahora: " + (peakNow.name || peakNow.id) + " · " + es(peakNow.density) + "/m². " : ""}Pico ${es(sc.peak_density)}/m² · ${sc.minutes_over_5 ?? "—"} min > 5/m². ${routes.length ? "Desvío: " + routes.join("; ") : "Sin desvíos activos."}`;
    const last = d.log.slice(-1)[0], el = $("last-" + k); el.textContent = "";
    if (last) { if (last.kind === "assumption_broken") { const b = document.createElement("b"); b.textContent = "EL PLAN YA NO SIRVE · "; el.append(b); } el.append(String(last.t).padStart(3, "0") + "′ " + audience(last.text)); }
  }
  function render() {
    if (!S) return;
    $("clock-day").textContent = "DÍA " + (S.clock.day || "–"); $("clock-hhmm").textContent = S.clock.hhmm || "--:--";
    $("clock-t").textContent = `min ${S.t} / ${S.session.duration_min || "–"}`;
    $("same").textContent = `MISMO CASO (${S.session.case}) · MISMA SEMILLA (${S.session.seed}) · MISMOS IMPREVISTOS` + (S.session.done ? " · FIN" : "");
    const bp = $("btn-play"); bp.textContent = S.session.done ? "FIN" : S.session.running ? "PAUSA" : "REANUDAR"; bp.className = "btn" + (S.session.running ? "" : " paused");
    document.querySelectorAll("#speed button").forEach((b) => b.classList.toggle("on", Number(b.dataset.speed) === Number(S.session.speed)));
    side("left"); side("right");
    $("duel-note").textContent = `Simulación · N = 1 caso por lado · decisiones graves: operador simulado a los ${S.session.auto_approve_min ?? "—"} min`;
    const choices=S.session.baselines || S.baselines;
    const select=$("baseline-select"), current=S.session.baseline || S.left.kind || "baseline";
    if(Array.isArray(choices) && document.activeElement!==select) {
      const html=choices.map(o=>`<option value="${MANDO_UI.esc(typeof o==='string'?o:o.id)}">${MANDO_UI.esc(typeof o==='string'?o:o.label)}</option>`).join('');
      if(select.innerHTML!==html) select.innerHTML=html;
      select.value=current; $("baseline-note").textContent="Cambiar de lista reinicia la comparación con el mismo caso y semilla.";
    } else if(!choices) {$("baseline-note").textContent="Lista fija original: única opción disponible en el servidor.";}
    $("baseline-title").textContent=S.left.agent || "Lista fija";
    const all=[...(S.left.strikes || []),...(S.right.strikes || [])];
    const strike=all[all.length-1];
    const key=strike?`${S.session.case}:${strike.n ?? ''}:${strike.t}:${strike.label}`:'';
    if(key && key!==strikeKey) {
      clearTimeout(hideStrike);
      ["left","right"].forEach(k=>{const el=$("strike-"+k);el.textContent=`Imprevisto en ambos lados · min ${strike.t}: ${strike.label || "cambio en el recinto"}`;el.hidden=false;el.style.animation='none';void el.offsetWidth;el.style.animation='';});
      hideStrike=setTimeout(()=>["left","right"].forEach(k=>$("strike-"+k).hidden=true),6000);
    }
    strikeKey=key;
  }
  $("btn-play").onclick = () => post("/api/duel/control", { cmd: "toggle" });
  $("btn-reset").onclick = () => restart();
  $("speed").onclick = (ev) => ev.target.dataset.speed && post("/api/duel/control", { cmd: "speed", value: Number(ev.target.dataset.speed) });
  function restart(caseId) { strikeKey=null; return post("/api/duel/session", {case_id:caseId || S?.session.case || "demo-gates",seed:S?.session.seed,speed:S?.session.speed || 4,baseline:$("baseline-select").value}); }
  $("case-select").onchange = ev => restart(ev.target.value);
  $("baseline-select").onchange = () => restart();
  document.addEventListener("keydown", (ev) => { if (/SELECT|INPUT|BUTTON|A/.test(ev.target.tagName) || ev.ctrlKey || ev.metaKey || ev.altKey) return;
    if (ev.key === " ") { ev.preventDefault(); post("/api/duel/control", { cmd: "toggle" }); }
    if (ev.key.toLowerCase() === "r") restart(); });
})();
