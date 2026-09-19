/* Plano de la Sala de control: disposición del diseño de las compañeras sobre las 17 zonas REALES de
   motor/world/festival.json. No se inventa ninguna zona: cada caja es un id del motor y la etiqueta grande
   es el nombre del diseño; debajo va siempre el nombre real que da el servidor.
   No hay GPS: la posición de las balizas es la zona que publica el simulador. */
(function () {
  "use strict";
  const NS = "http://www.w3.org/2000/svg";
  const W = 1060, H = 612;

  // x, y, w, h en el lienzo; `label` es el rótulo del diseño; `id` es la zona real del motor.
  const ZONES = {
    toilets:        { x: 14,  y: 64,  w: 172, h: 150, label: "ZONA DE SERVICIOS · ASEOS", out: true },
    exit_transport: { x: 14,  y: 330, w: 172, h: 190, label: "SALIDA · LANZADERAS Y METRO", out: true },
    medical_2:      { x: 206, y: 52,  w: 104, h: 76,  label: "PMA-N · MÉDICO 2", pma: true },
    front_pit:      { x: 352, y: 116, w: 320, h: 48,  label: "FOSO · FRONT STAGE" },
    vip:            { x: 716, y: 48,  w: 212, h: 92,  label: "ZONA VIP & PRODUCCIÓN" },
    water_n:        { x: 946, y: 48,  w: 82,  h: 92,  label: "AGUA NORTE" },
    corridor_n:     { x: 206, y: 184, w: 76,  h: 184, label: "PASILLO NORTE", vertical: true },
    general:        { x: 318, y: 184, w: 352, h: 184, label: "ZONA NORTE · PISTA CENTRAL", big: true },
    food:           { x: 716, y: 184, w: 212, h: 184, label: "ZONA FOOD TRUCKS" },
    backstage:      { x: 946, y: 184, w: 82,  h: 184, label: "BACKSTAGE", vertical: true },
    pmr:            { x: 206, y: 396, w: 104, h: 74,  label: "PLATAFORMA PMR" },
    corridor_s:     { x: 318, y: 396, w: 352, h: 74,  label: "PLAZA CENTRAL & ZONA SUR" },
    water_s:        { x: 716, y: 396, w: 100, h: 74,  label: "AGUA SUR" },
    medical_1:      { x: 832, y: 396, w: 196, h: 74,  label: "PMA-S · MÉDICO 1", pma: true },
    gate_a:         { x: 206, y: 498, w: 150, h: 74,  label: "ACCESO A · NORTE", gate: true },
    gate_b:         { x: 380, y: 498, w: 290, h: 74,  label: "ENTRADA GENERAL · CONTROL TORNOS", gate: true },
    gate_c:         { x: 716, y: 498, w: 150, h: 74,  label: "ACCESO C · SUR", gate: true },
  };
  const ENCLOSURE = { x: 190, y: 30, w: 852, h: 560 };
  const STAGE = { x: 352, y: 48, w: 320, h: 62 };

  function el(name, attrs, parent) {
    const e = document.createElementNS(NS, name);
    for (const k in attrs || {}) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  function center(id) { const z = ZONES[id]; return z ? { x: z.x + z.w / 2, y: z.y + z.h / 2 } : null; }
  /* Cuerpo del rótulo de cada caja. Tiene que ir a la par de `.sala-zone-label` en sala.css: aquí solo se
     usa para calcular cuántas letras caben; el tamaño que se ve lo manda la hoja de estilo. */
  function labelSize(L) { return L.big ? 17 : L.w < 100 ? 9 : L.w < 150 ? 10 : L.out ? 10 : 12; }
  /* Parte el rótulo del diseño en dos líneas cuando no cabe de una, cortando por el «·» si lo hay.
     Así se conserva el texto del diseño en las cajas estrechas en vez de encogerlo hasta no leerse. */
  function wrapLabel(text, maxChars) {
    if (text.length <= maxChars) return [text];
    const sep = text.includes(" · ") ? " · " : " ";
    const lines = [];
    text.split(sep).forEach((p) => {
      const last = lines.length - 1;
      if (lines.length && (lines[last] + sep + p).length <= maxChars) lines[last] += sep + p;
      else if (lines.length >= 2) lines[1] += sep + p;
      else lines.push(p);
    });
    return lines;
  }
  /* Dónde va cada cosa dentro de una caja: el rótulo del diseño arriba, el nombre real del motor debajo si
     cabe, las balizas en la banda de abajo y la cifra de densidad donde no las pise (a su derecha si la caja
     es ancha, encima de ellas si es estrecha). Con esto ninguna caja se solapa consigo misma. */
  function layout(L) {
    const cx = L.x + L.w / 2;
    if (L.big) return { labelY: L.y + L.h / 2 - 6, subY: L.y + L.h / 2 + 13, figX: cx, figY: L.y + L.h / 2 + 36,
      figAnchor: "middle", beaconX: L.x + 18, beaconY: L.y + L.h - 16, perRow: 9,
      flagX: L.x + 10, flagY: L.y + 18, flagAnchor: "start" };
    // Caja ancha: la cifra cabe a la derecha de las balizas. Caja estrecha: va debajo, y el nombre real
    // del motor solo se pinta si sobra alto (si no, queda en el título emergente y en la ficha).
    const wide = L.w >= 150, sub = L.h >= (wide ? 60 : 90);
    return { labelY: L.y + 17, subY: sub ? L.y + 30 : null,
      figX: wide ? L.x + L.w - 9 : cx, figY: L.y + L.h - (wide ? 11 : 9), figAnchor: wide ? "end" : "middle",
      beaconX: L.x + 16, beaconY: L.y + L.h - (wide ? 14 : 34),
      perRow: Math.max(1, Math.floor((L.w - (wide ? 96 : 20)) / 30)),
      // El aviso de zona cerrada nunca comparte sitio con los marcadores de incidente (arriba a la derecha).
      flagX: wide ? L.x + 10 : cx, flagY: wide ? L.y + 17 : L.y + (sub ? 42 : 29),
      flagAnchor: wide ? "start" : "middle" };
  }
  function anchor(a, b) {
    const za = ZONES[a], cb = center(b);
    return { x: Math.max(za.x, Math.min(za.x + za.w, cb.x)), y: Math.max(za.y, Math.min(za.y + za.h, cb.y)) };
  }
  function edgePoints(a, b) {
    const p = anchor(a, b), q = anchor(b, a), za = ZONES[a], zb = ZONES[b];
    const ox = Math.max(za.x, zb.x), ox2 = Math.min(za.x + za.w, zb.x + zb.w);
    if (ox < ox2) p.x = q.x = Math.max(ox, Math.min(ox2, (p.x + q.x) / 2));
    const oy = Math.max(za.y, zb.y), oy2 = Math.min(za.y + za.h, zb.y + zb.h);
    if (oy < oy2) p.y = q.y = Math.max(oy, Math.min(oy2, (p.y + q.y) / 2));
    return [p, q];
  }

  /* Construye el plano dentro de `svg` y devuelve las referencias para actualizarlo sin volver a dibujarlo. */
  function build(svg, festival) {
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.textContent = "";
    const defs = el("defs", {}, svg);
    // Cuadrícula clara del fondo y mancha de densidad: dos recursos propios, sin imágenes ni CDN.
    const grid = el("pattern", { id: "sala-grid", width: 28, height: 28, patternUnits: "userSpaceOnUse" }, defs);
    el("path", { d: "M28 0 H0 V28", fill: "none", stroke: "currentColor", "stroke-width": 1 }, grid);
    const blob = el("radialGradient", { id: "sala-blob" }, defs);
    el("stop", { offset: "0%", "stop-color": "var(--sala-heat)", "stop-opacity": ".55" }, blob);
    el("stop", { offset: "70%", "stop-color": "var(--sala-heat)", "stop-opacity": ".16" }, blob);
    el("stop", { offset: "100%", "stop-color": "var(--sala-heat)", "stop-opacity": "0" }, blob);
    const arrow = el("marker", { id: "sala-arrow", viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 5,
      markerHeight: 5, orient: "auto-start-reverse" }, defs);
    el("path", { d: "M0 0 L10 5 L0 10 z", fill: "currentColor" }, arrow);

    el("rect", { class: "sala-grid", x: 0, y: 0, width: W, height: H, fill: "url(#sala-grid)" }, svg);
    el("rect", Object.assign({ class: "sala-enclosure", rx: 14 }, rect(ENCLOSURE)), svg);

    const gEdges = el("g", { class: "sala-edges" }, svg);
    const gHeat = el("g", { class: "sala-heatmap" }, svg);
    const gZones = el("g", { class: "sala-zones" }, svg);
    const gDecor = el("g", { class: "sala-decor" }, svg);
    const gRoutes = el("g", { class: "sala-routes" }, svg);
    const gBeacons = el("g", { class: "sala-beacons" }, svg);
    const gPins = el("g", { class: "sala-pins" }, svg);

    const edges = {};
    (festival.edges || []).forEach((e) => {
      if (!ZONES[e.a] || !ZONES[e.b]) return;
      const [p, q] = edgePoints(e.a, e.b);
      edges[e.a + ">" + e.b] = el("line", { x1: p.x, y1: p.y, x2: q.x, y2: q.y,
        class: "sala-edge" + (e.staff_only ? " staff" : "") }, gEdges);
    });

    const zones = {};
    (festival.zones || []).forEach((z) => {
      const L = ZONES[z.id];
      if (!L) return;
      const P = layout(L);
      const g = el("g", { class: "sala-zone" + (L.w < 100 ? " tiny" : L.w < 150 ? " narrow" : ""),
        "data-zone": z.id, "data-select": "zone", tabindex: 0, role: "button" }, gZones);
      el("title", {}, g);
      el("rect", Object.assign({ class: "sala-zone-box", rx: 10 }, rect(L)), g);
      const heat = el("ellipse", { class: "sala-heat", cx: L.x + L.w / 2, cy: L.y + L.h / 2,
        rx: L.w * 0.52, ry: L.h * 0.62, fill: "url(#sala-blob)" }, gHeat);
      const cx = L.x + L.w / 2;
      const fs = labelSize(L), lines = wrapLabel(L.label, Math.floor((L.w - 10) / (fs * 0.68)));
      const label = el("text", { class: "sala-zone-label" + (L.big ? " big" : ""), x: cx,
        y: P.labelY - (lines.length - 1) * 5, "text-anchor": "middle" }, g);
      lines.forEach((ln, k) => { el("tspan", { x: cx, dy: k ? 11 : 0 }, label).textContent = ln; });
      const sub = P.subY == null ? null
        : el("text", { class: "sala-zone-sub", x: cx, y: P.subY + (lines.length - 1) * 6, "text-anchor": "middle" }, g);
      const figure = el("text", { class: "sala-zone-figure", x: P.figX, y: P.figY, "text-anchor": P.figAnchor }, g);
      const flag = el("text", { class: "sala-zone-flag", x: P.flagX, y: P.flagY, "text-anchor": P.flagAnchor }, g);
      zones[z.id] = { g, heat, label, sub, figure, flag, L, title: g.firstChild };
    });

    // El escenario es decorado: no es una zona del motor y no lleva cifras.
    el("rect", Object.assign({ class: "sala-stage", rx: 8 }, rect(STAGE)), gDecor);
    const st = el("text", { class: "sala-stage-label", x: STAGE.x + STAGE.w / 2, y: STAGE.y + 28, "text-anchor": "middle" }, gDecor);
    st.textContent = "ESCENARIO PRINCIPAL";
    const st2 = el("text", { class: "sala-stage-sub", x: STAGE.x + STAGE.w / 2, y: STAGE.y + 46, "text-anchor": "middle" }, gDecor);
    st2.textContent = "DECORADO · EL MOTOR NO SIMULA EL ESCENARIO";

    return { svg, edges, zones, gRoutes, gBeacons, gPins };
  }

  function rect(o) { return { x: o.x, y: o.y, width: o.w, height: o.h }; }
  // Umbrales de referencia del proyecto (INTERFACES.md): 2 = planificación, 5 = límite de pie, 7 = aplastamiento.
  function densityClass(d) { return d > 6.5 ? "d-crit" : d > 5 ? "d-red" : d >= 2 ? "d-amber" : "d-green"; }
  // Reparte las fichas por la banda inferior de la caja, hacia arriba, sin salirse de ella.
  function slot(id, n) {
    const L = ZONES[id];
    if (!L) return null;
    const P = layout(L);
    return { x: P.beaconX + (n % P.perRow) * 30, y: P.beaconY - Math.floor(n / P.perRow) * 28 };
  }

  window.SALA_PLANO = { W, H, ZONES, el, center, densityClass, build, slot };
})();
