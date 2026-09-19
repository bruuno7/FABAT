/* Plano ESQUEMÁTICO del recinto (no es un mapa): lo comparten la pantalla de mando y la página del jurado. */
(function () {
  "use strict";
  const NS = "http://www.w3.org/2000/svg";
  const W = 1200, SY = 1.3, H = Math.round(700 * SY);  // el panel central es casi cuadrado: se estira en vertical

  // Posición de cada zona en el plano. Ids fijos de festival.json.
  const ZONES = {
    gate_a:         { x: 24,   y: 60,  w: 150, h: 130, label: "PUERTA A" },
    gate_b:         { x: 24,   y: 285, w: 150, h: 130, label: "PUERTA B" },
    gate_c:         { x: 24,   y: 510, w: 150, h: 130, label: "PUERTA C" },
    food:           { x: 215,  y: 24,  w: 175, h: 112, label: "RESTAURACIÓN" },
    toilets:        { x: 402,  y: 24,  w: 130, h: 112, label: "BAÑOS" },
    water_n:        { x: 544,  y: 24,  w: 120, h: 112, label: "AGUA N" },
    medical_2:      { x: 676,  y: 24,  w: 120, h: 112, label: "MÉDICO 2" },
    vip:            { x: 808,  y: 24,  w: 152, h: 112, label: "VIP" },
    corridor_n:     { x: 215,  y: 166, w: 745, h: 64,  label: "PASILLO NORTE" },
    general:        { x: 330,  y: 256, w: 390, h: 188, label: "PISTA GENERAL" },
    front_pit:      { x: 740,  y: 256, w: 220, h: 188, label: "FRENTE ESCENARIO" },
    backstage:      { x: 1024, y: 256, w: 152, h: 188, label: "BACKSTAGE" },
    corridor_s:     { x: 215,  y: 470, w: 745, h: 64,  label: "PASILLO SUR · AMBULANCIA" },
    exit_transport: { x: 215,  y: 564, w: 200, h: 112, label: "SALIDA · METRO" },
    water_s:        { x: 427,  y: 564, w: 120, h: 112, label: "AGUA S" },
    medical_1:      { x: 559,  y: 564, w: 130, h: 112, label: "MÉDICO 1" },
    pmr:            { x: 701,  y: 564, w: 120, h: 112, label: "PMR" },
  };

  Object.values(ZONES).forEach((z) => { z.y = Math.round(z.y * SY); z.h = Math.round(z.h * SY); });

  function el(name, attrs, parent) {
    const e = document.createElementNS(NS, name);
    for (const k in attrs || {}) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  function center(id) { const z = ZONES[id]; return { x: z.x + z.w / 2, y: z.y + z.h / 2 }; }
  // Punto del borde de `a` más cercano al centro de `b`: las aristas salen de los bordes, no de los centros.
  function anchor(a, b) {
    const za = ZONES[a], cb = center(b);
    return { x: Math.max(za.x, Math.min(za.x + za.w, cb.x)), y: Math.max(za.y, Math.min(za.y + za.h, cb.y)) };
  }
  function edgePoints(a, b) {
    const p = anchor(a, b), q = anchor(b, a);
    // segunda pasada: alinear cuando las cajas se solapan en un eje, para que la línea salga recta
    const za = ZONES[a], zb = ZONES[b];
    const ox = Math.max(za.x, zb.x), ox2 = Math.min(za.x + za.w, zb.x + zb.w);
    if (ox < ox2) { p.x = q.x = Math.max(ox, Math.min(ox2, (p.x + q.x) / 2)); }
    const oy = Math.max(za.y, zb.y), oy2 = Math.min(za.y + za.h, zb.y + zb.h);
    if (oy < oy2) { p.y = q.y = Math.max(oy, Math.min(oy2, (p.y + q.y) / 2)); }
    return [p, q];
  }

  /* Dibuja el plano base dentro de `svg`. Devuelve referencias para actualizarlo sin redibujar. */
  function build(svg, festival, opts) {
    opts = opts || {};
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.innerHTML = "";
    const defs = el("defs", {}, svg);
    defs.innerHTML =
      '<marker id="arr" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">' +
      '<path d="M0 0 L10 5 L0 10 z" fill="currentColor"/></marker>' +
      '<pattern id="hatch" width="10" height="10" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">' +
      '<rect width="4" height="10" fill="rgba(255,255,255,.16)"/></pattern>';
    const gEdges = el("g", { class: "edges" }, svg);
    const gDecor = el("g", { class: "decor" }, svg);
    const gZones = el("g", { class: "zones" }, svg);
    const gReroutes = el("g", { class: "reroutes" }, svg);
    const gTokens = el("g", { class: "tokens" }, svg);
    const gPins = el("g", { class: "pins" }, svg);

    // Escenario (decorado) y entrada desde la calle
    const fp = ZONES.front_pit, sy = fp.y + fp.h / 2;
    el("rect", { x: 972, y: fp.y, width: 38, height: fp.h, rx: 3, class: "stage" }, gDecor);
    const st = el("text", { x: 991, y: sy, class: "stage-label", transform: `rotate(-90 991 ${sy})` }, gDecor);
    st.textContent = "ESCENARIO";

    const edges = {};
    (festival.edges || []).forEach((e) => {
      if (!ZONES[e.a] || !ZONES[e.b]) return;
      const [p, q] = edgePoints(e.a, e.b);
      const base = el("line", { x1: p.x, y1: p.y, x2: q.x, y2: q.y, class: "edge" + (e.staff_only ? " staff" : "") }, gEdges);
      const flow = e.staff_only ? null : el("line", { x1: p.x, y1: p.y, x2: q.x, y2: q.y, class: "flow" }, gEdges);
      edges[e.a + ">" + e.b] = { a: e.a, b: e.b, base, flow };
    });
    // Llegada desde fuera a cada puerta
    const outside = {};
    ["gate_a", "gate_b", "gate_c"].forEach((g) => {
      const z = ZONES[g], y = z.y + z.h / 2;
      outside[g] = el("line", { x1: 0, y1: y, x2: z.x - 2, y2: y, class: "flow outside" }, gEdges);
    });

    const zones = {};
    (festival.zones || []).forEach((z) => {
      const L = ZONES[z.id];
      if (!L) return;
      const g = el("g", { class: "zone", "data-zone": z.id, tabindex: opts.selectable ? 0 : -1 }, gZones);
      const rect = el("rect", { x: L.x, y: L.y, width: L.w, height: L.h, rx: 6, class: "zone-box" }, g);
      const hatch = el("rect", { x: L.x, y: L.y, width: L.w, height: L.h, rx: 6, class: "zone-hatch", fill: "url(#hatch)" }, g);
      const thin = L.h < 100;  // pasillos: todo en una línea, a la izquierda; fichas y marcadores a la derecha
      const name = el("text", { x: L.x + 9, y: L.y + 22, class: "zone-name" }, g);
      name.textContent = L.label;
      const dens = el("text", { x: L.x + 9, y: thin ? L.y + L.h - 14 : L.y + 66, class: "zone-density" + (thin ? " thin" : "") }, g);
      const pct = el("text", { x: thin ? L.x + 150 : L.x + 9, y: thin ? L.y + L.h - 14 : L.y + 94, class: "zone-pct" }, g);
      const state = el("text", { x: thin ? L.x + 330 : L.x + 9, y: thin ? L.y + 22 : L.y + L.h - 12, class: "zone-state" }, g);
      zones[z.id] = { g, rect, hatch, name, dens, pct, state, L };
    });
    return { svg, edges, outside, zones, gReroutes, gTokens, gPins };
  }

  function densityClass(d) { return d > 6.5 ? "d-crit" : d > 5 ? "d-red" : d >= 2 ? "d-amber" : "d-green"; }

  window.PLANO = { W, H, ZONES, NS, el, center, anchor, edgePoints, build, densityClass };
})();
