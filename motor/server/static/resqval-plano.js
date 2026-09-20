/* Proyección de solo lectura: geometría de SALA_PLANO.ZONES, identidades del snapshot.
   No se usa el renderizador del simulador ni se infieren rutas, aforo o GPS. */
(function (root) {
  "use strict";
  const closed = new Set(["closed", "resolved", "merged", "cancelled"]);
  function project(state, geometry) {
    const incidents = state.incidents.filter((i) => !closed.has(i.status));
    const zones = state.zones.filter((z) => Object.hasOwn(geometry, z.id)).map((zone) => ({
      id: zone.id, name: zone.name || zone.id, layout: geometry[zone.id],
      incidents: incidents.filter((i) => i.zone === zone.id).length,
      actors: state.actors.filter((a) => a.zone === zone.id).length,
    }));
    const mapped = new Set(zones.map((z) => z.id));
    return { zones, unknownIncidents: incidents.filter((i) => !mapped.has(i.zone)).length,
      unknownActors: state.actors.filter((a) => !mapped.has(a.zone)).length };
  }
  function render(document, svg, state, selected = "") {
    const model = project(state, root.SALA_PLANO.ZONES);
    const node = (tag, attributes = {}, text) => {
      const element = document.createElementNS("http://www.w3.org/2000/svg", tag);
      for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, String(value));
      if (text !== undefined) element.textContent = text;
      return element;
    };
    svg.setAttribute("viewBox", "0 0 1060 612");
    svg.setAttribute("aria-label", `Mapa esquemático: ${model.zones.length} zonas con geometría; sin sensores ni GPS. Consulta el filtro y la tabla para el detalle.`);
    const children = [node("title", {}, "Recinto de MANDO · ubicaciones declaradas por zona"),
      node("rect", { x: 190, y: 30, width: 852, height: 560, rx: 14, class: "map-enclosure" })];
    for (const zone of model.zones) {
      const { x, y, w, h, vertical } = zone.layout;
      const group = node("g", { class: `map-zone${zone.incidents ? " active" : ""}${zone.id === selected ? " selected" : ""}` });
      group.append(node("title", {}, `${zone.name}: ${zone.incidents} avisos activos, ${zone.actors} recursos con ubicación declarada aquí.`),
        node("rect", { x, y, width: w, height: h, rx: 8 }));
      const label = node("text", { x: x + w / 2, y: y + h / 2 - 5 }, zone.name);
      if (vertical) label.setAttribute("transform", `rotate(-90 ${x + w / 2} ${y + h / 2 - 5})`);
      else {
        // Divide etiquetas largas sin truncar su nombre accesible en el title.
        const max = Math.max(8, Math.floor(w / 7));
        if (zone.name.length > max) {
          const words = zone.name.split(" "), lines = [""];
          for (const word of words) {
            const index = lines.length - 1;
            if (lines[index] && (lines[index] + " " + word).length > max) lines.push(word);
            else lines[index] += (lines[index] ? " " : "") + word;
          }
          label.textContent = "";
          lines.forEach((line, index) => label.append(node("tspan", { x: x + w / 2, dy: index ? 14 : -(lines.length - 1) * 7 }, line)));
        }
      }
      group.append(label);
      if (zone.incidents) group.append(node("text", { x: x + w / 2, y: y + h - 7, class: "zone-count" }, `${zone.incidents} avisos`));
      children.push(group);
    }
    svg.replaceChildren(...children);
    return model;
  }
  root.RESQVAL_PLANO = { project, render };
})(typeof window === "undefined" ? globalThis : window);
