(() => {
  "use strict";

  const byId = id => document.getElementById(id);
  const ui = {
    scene: byId("scene"), query: byId("query"), status: byId("status"),
    family: byId("family"), zone: byId("zone"), since: byId("since"), until: byId("until"),
    apply: byId("apply"), list: byId("history-list"), detail: byId("history-detail"),
    count: byId("result-count"), statusLine: byId("history-status"), pageLabel: byId("page"),
    previous: byId("previous"), next: byId("next"), json: byId("export-json"), csv: byId("export-csv")
  };
  const view = {tab: "incidents", page: 1, pages: 1, selected: null, request: 0, detailRequest: 0};

  function node(tag, options = {}, children = []) {
    const element = document.createElement(tag);
    if (options.className) element.className = options.className;
    if (options.text !== undefined) element.textContent = String(options.text);
    if (options.scope) element.scope = options.scope;
    if (options.tabIndex !== undefined) element.tabIndex = options.tabIndex;
    for (const child of children) {
      element.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return element;
  }

  function safe(value, fallback = "—") {
    return value === null || value === undefined || value === "" ? fallback : String(value);
  }

  function scene() {
    return ui.scene.value;
  }

  async function api(path, params = {}) {
    const url = new URL(path, location.origin);
    for (const [key, value] of Object.entries(params)) {
      if (value !== null && value !== undefined && value !== "") url.searchParams.set(key, value);
    }
    const response = await fetch(url, {credentials: "same-origin", headers: {"Accept": "application/json"}});
    if (!response.ok) {
      let message = `Error ${response.status}`;
      try {
        const body = await response.json();
        message = body.error || body.detail || message;
      } catch (_) {
        // La respuesta puede no ser JSON.
      }
      throw new Error(message);
    }
    return response.json();
  }

  function setStatus(message, ok = false) {
    ui.statusLine.textContent = message;
    ui.statusLine.classList.toggle("ready", ok);
  }

  function updateExports() {
    const selected = encodeURIComponent(scene());
    ui.json.href = `/api/historial/export.json?escena=${selected}`;
    ui.csv.href = `/api/historial/export.csv?escena=${selected}`;
    ui.json.setAttribute("download", "");
    ui.csv.setAttribute("download", "");
  }

  function cell(text, className = "") {
    return node("td", {text: safe(text), className});
  }

  function headingRow(columns) {
    const row = node("tr");
    for (const label of columns) row.append(node("th", {text: label, scope: "col"}));
    return row;
  }

  function table(columns) {
    const result = node("table", {className: "history-table"});
    result.append(node("thead", {}, [headingRow(columns)]), node("tbody"));
    return result;
  }

  function stateBadge(value) {
    return node("span", {text: safe(value), className: `state ${String(value || "").toLowerCase()}`});
  }

  function incidentRow(item) {
    const row = node("tr", {tabIndex: 0});
    row.dataset.id = item.id;
    if (item.id === view.selected) row.classList.add("selected");
    const name = node("td");
    name.append(node("span", {text: safe(item.etiqueta, "Incidente sin etiqueta"), className: "incident-name"}),
                node("span", {text: `${safe(item.id)} · min ${safe(item.apertura_min)}`, className: "incident-ref"}));
    const severity = cell(item.gravedad, `severity ${Number(item.gravedad) >= 8 ? "high" : ""}`);
    const status = node("td");
    status.append(stateBadge(item.estado));
    row.append(name, cell(item.familia), cell(item.zona), severity, status);
    const open = () => openIncident(item.id, row);
    row.addEventListener("click", open);
    row.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        open();
      }
    });
    return row;
  }

  function genericRow(values) {
    const row = node("tr");
    for (const value of values) row.append(cell(value));
    return row;
  }

  function renderIncidents(payload) {
    const result = table(["Incidente", "Familia", "Zona", "Gravedad", "Estado"]);
    const body = result.tBodies[0];
    for (const item of payload.items) body.append(incidentRow(item));
    if (!payload.items.length) {
      const empty = node("td", {text: "No hay incidentes que coincidan con estos filtros.", className: "empty"});
      empty.colSpan = 5;
      body.append(node("tr", {}, [empty]));
    }
    ui.list.replaceChildren(result);
    ui.count.textContent = `${payload.total} incidentes`;
    view.pages = Math.max(1, payload.pages);
    ui.pageLabel.textContent = `Página ${payload.page} de ${view.pages}`;
    ui.previous.disabled = payload.page <= 1;
    ui.next.disabled = payload.page >= view.pages;
  }

  function renderDecisions(items) {
    const result = table(["Minuto", "Decisión", "Acción", "Operador", "Latencia"]);
    for (const item of items) {
      result.tBodies[0].append(genericRow([
        item.minuto, item.resultado, item.accion_id,
        [item.operador, item.papel].filter(Boolean).join(" · "), item.latencia_s == null ? "—" : `${item.latencia_s} s`
      ]));
    }
    ui.list.replaceChildren(result);
    ui.count.textContent = `N = ${items.length}`;
    renderNote("Decisiones humanas", "Aprobaciones, vetos y correcciones conservados con identidad, nota y latencia.");
  }

  function renderResources(items) {
    const result = table(["Equipo o recurso", "Acciones", "Desde", "Hasta", "Ocupado"]);
    for (const item of items) {
      result.tBodies[0].append(genericRow([
        item.recurso, item.acciones, item.desde_min, item.hasta_min,
        item.ocupado_min == null ? "—" : `${item.ocupado_min} min`
      ]));
    }
    ui.list.replaceChildren(result);
    ui.count.textContent = `N = ${items.length} recursos`;
    renderNote("Actividad de equipos", "Los tiempos proceden del primer y último estado observado de cada acción.");
  }

  function renderServices(items) {
    const result = table(["Minuto", "Servicio", "Estado", "Latencia"]);
    for (const item of items) {
      result.tBodies[0].append(genericRow([
        item.minuto, item.servicio, item.estado, item.latencia_ms == null ? "—" : `${item.latencia_ms} ms`
      ]));
    }
    ui.list.replaceChildren(result);
    ui.count.textContent = `N = ${items.length} muestras`;
    renderNote("Servicios y canales", "Cada fila es una muestra persistida; no presupone que el servicio siga en ese estado.");
  }

  function figure(label, metric, suffix = "") {
    const value = metric && metric.value !== null ? `${metric.value}${suffix}` : "Sin dato";
    return node("div", {className: "summary-figure"}, [
      node("strong", {text: value}), node("span", {text: `${label} · N = ${metric ? metric.n : 0}`})
    ]);
  }

  function renderSummary(data) {
    const families = Object.entries(data.incidentes.por_familia || {})
      .map(([key, value]) => `${key}: ${value}`).join(" · ") || "Sin incidentes";
    const calls = data.llamadas || {};
    const main = node("section", {className: "summary-grid"}, [
      figure("Incidentes registrados", {value: data.incidentes.n, n: data.incidentes.n}),
      figure("Mediana hasta primera acción", data.primera_accion_mediana_min, " min"),
      figure("Mediana de decisión humana", data.decision_humana_mediana_s, " s"),
      figure("Previsiones cumplidas", {
        value: data.previsiones_acertadas.value === null ? null : `${Math.round(data.previsiones_acertadas.value * 100)} %`,
        n: data.previsiones_acertadas.n
      })
    ]);
    ui.list.replaceChildren(main);
    ui.count.textContent = `N = ${data.incidentes.n} incidentes`;
    ui.detail.replaceChildren(
      node("h3", {text: "Resumen de la escena"}),
      node("h4", {text: "Incidentes por familia"}),
      node("p", {text: families}),
      node("h4", {text: "Llamadas"}),
      node("p", {text: `Aceptadas ${calls.aceptadas || 0} · Rechazadas ${calls.rechazadas || 0} · Sin respuesta ${calls.sin_respuesta || 0} · N = ${calls.n || 0}`})
    );
  }

  function renderNote(title, text) {
    ui.detail.replaceChildren(node("h3", {text: title}), node("p", {text}));
  }

  function meta(label, value) {
    return node("div", {}, [node("small", {text: label}), node("strong", {text: safe(value)})]);
  }

  function renderDetail(data) {
    const incident = data.incident;
    const fragment = document.createDocumentFragment();
    fragment.append(
      node("h3", {text: safe(incident.etiqueta, "Incidente")}),
      node("p", {text: `Referencia ${safe(incident.id)} · escena ${safe(incident.escena_id)}`, className: "muted"}),
      node("div", {className: "record-meta"}, [
        meta("Estado", incident.estado), meta("Familia", incident.familia),
        meta("Zona", incident.zona), meta("Prioridad", incident.prioridad),
        meta("Gravedad", incident.gravedad), meta("Primera acción", incident.primera_accion_min == null ? null : `min ${incident.primera_accion_min}`)
      ])
    );
    fragment.append(node("h4", {text: `Avisos fusionados · N = ${data.reports.length}`}));
    const sources = node("ul", {className: "source-list"});
    for (const report of data.reports) {
      sources.append(node("li", {}, [
        node("time", {text: `min ${safe(report.minuto)} · ${safe(report.canal)}`}),
        node("span", {text: safe(report.texto)})
      ]));
    }
    fragment.append(sources);

    fragment.append(node("h4", {text: `Planes y supuestos · N = ${data.plans.length}`}));
    const plans = node("ul", {className: "plan-list"});
    for (const plan of data.plans) {
      const assumptions = node("ul", {className: "assumptions"});
      for (const assumption of plan.assumptions || []) {
        assumptions.append(node("li", {
          text: `${assumption.estado === "roto" ? "✕" : "✓"} ${safe(assumption.texto)}`,
          className: assumption.estado === "roto" ? "broken" : ""
        }));
      }
      plans.append(node("li", {}, [
        node("strong", {text: `Plan ${safe(plan.version, safe(plan.id))}: ${safe(plan.objetivo)}`}),
        node("small", {text: safe(plan.porque)}), assumptions
      ]));
    }
    fragment.append(plans);

    fragment.append(node("h4", {text: `Cronología · N = ${data.timeline.length}`}));
    const timeline = node("ol", {className: "audit-line"});
    for (const event of data.timeline) {
      timeline.append(node("li", {}, [
        node("time", {text: `min ${safe(event.minuto)}`}),
        node("strong", {text: safe(event.tipo)}),
        node("span", {text: safe(event.texto)})
      ]));
    }
    fragment.append(timeline);

    fragment.append(node("h4", {text: `Llamadas · N = ${data.calls.length}`}));
    const calls = node("ul", {className: "source-list"});
    for (const call of data.calls) {
      calls.append(node("li", {}, [
        node("strong", {text: `${safe(call.resultado, "EN CURSO")} · ${safe(call.destinatario)}`}),
        node("span", {text: `${safe(call.workflow)} · ${call.latencia_ms == null ? "latencia sin dato" : `${call.latencia_ms} ms`}`})
      ]));
    }
    fragment.append(calls);
    ui.detail.replaceChildren(fragment);
  }

  async function openIncident(id, row) {
    const request = ++view.detailRequest;
    view.selected = id;
    for (const item of ui.list.querySelectorAll("tr")) item.classList.toggle("selected", item === row);
    setStatus("Abriendo ficha…");
    try {
      const data = await api(`/api/historial/incidente/${encodeURIComponent(id)}`, {escena: scene()});
      if (request !== view.detailRequest) return;
      renderDetail(data);
      setStatus(`Ficha ${id} cargada.`, true);
    } catch (error) {
      if (request !== view.detailRequest) return;
      setStatus(error.message);
    }
  }

  function filters() {
    return {
      escena: scene(), estado: ui.status.value, familia: ui.family.value.trim(),
      zona: ui.zone.value.trim(), desde: ui.since.value, hasta: ui.until.value,
      q: ui.query.value.trim(), pagina: view.page, tamano: 50
    };
  }

  async function loadCurrent() {
    const request = ++view.request;
    view.detailRequest += 1;
    view.selected = null;
    ui.detail.replaceChildren(node("p", {
      text: "Selecciona una fila para abrir su ficha completa.",
      className: "empty"
    }));
    setStatus("Consultando la base de datos…");
    try {
      if (view.tab === "incidents") {
        const data = await api("/api/historial/incidentes", filters());
        if (request !== view.request) return;
        renderIncidents(data);
      } else if (view.tab === "decisions") {
        const data = await api("/api/historial/decisiones", {escena: scene()});
        if (request !== view.request) return;
        renderDecisions(data.items);
      } else if (view.tab === "resources") {
        const data = await api("/api/historial/recursos", {escena: scene()});
        if (request !== view.request) return;
        renderResources(data.items);
      } else if (view.tab === "services") {
        const data = await api("/api/historial/servicios", {escena: scene()});
        if (request !== view.request) return;
        renderServices(data.items);
      } else {
        const data = await api("/api/historial/resumen", {escena: scene()});
        if (request !== view.request) return;
        renderSummary(data);
      }
      setStatus("Historial actualizado.", true);
    } catch (error) {
      if (request !== view.request) return;
      ui.list.replaceChildren(node("p", {text: error.message, className: "empty"}));
      setStatus(error.message);
    }
  }

  async function loadScenes() {
    try {
      const payload = await api("/api/historial/escenas");
      ui.scene.replaceChildren();
      for (const item of payload.items) {
        const option = node("option", {text: `${safe(item.caso, "Caso")} · ${safe(item.id)} · min ${safe(item.fin_min, 0)}`});
        option.value = item.id;
        ui.scene.append(option);
      }
      if (!payload.items.length) {
        ui.scene.append(node("option", {text: "Todavía no hay escenas"}));
        ui.apply.disabled = true;
        setStatus("Todavía no hay estados grabados.");
        return;
      }
      updateExports();
      await loadCurrent();
    } catch (error) {
      setStatus(error.message);
    }
  }

  document.querySelectorAll("[data-tab]").forEach(button => {
    button.addEventListener("click", () => {
      view.tab = button.dataset.tab;
      view.page = 1;
      document.querySelectorAll("[data-tab]").forEach(item => item.setAttribute("aria-pressed", String(item === button)));
      loadCurrent();
    });
  });
  ui.apply.addEventListener("click", () => { view.page = 1; loadCurrent(); });
  ui.query.addEventListener("keydown", event => {
    if (event.key === "Enter") {
      view.page = 1;
      loadCurrent();
    }
  });
  ui.scene.addEventListener("change", () => { view.page = 1; view.selected = null; updateExports(); loadCurrent(); });
  ui.previous.addEventListener("click", () => { if (view.page > 1) { view.page -= 1; loadCurrent(); } });
  ui.next.addEventListener("click", () => { if (view.page < view.pages) { view.page += 1; loadCurrent(); } });

  loadScenes();
})();
