(function (root) {
  "use strict";

  const roles = ["medico", "bomberos", "policia", "staff_entradas", "organizador"];
  const closed = new Set(["closed", "resolved", "merged", "cancelled"]);
  // Mismo conjunto ACTIVE que la autoridad operativa; availability no libera una reserva.
  const activeAssignments = new Set(["offered", "accepted", "en_route", "arrived", "located"]);
  const roleName = (role) => ({ medico: "Médico", bomberos: "Bomberos", policia: "Policía", staff_entradas: "Entradas", organizador: "Organizador" }[role] || role);
  const normalize = (value) => String(value ?? "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase("es");
  function resourceState(actor, assignments) {
    const active = assignments.filter((a) => a.actor_id === actor.id && activeAssignments.has(a.status));
    const status = active.some((a) => ["arrived", "located"].includes(a.status)) ? "busy"
      : active.some((a) => a.status === "en_route") ? "en_route"
      : active.length ? "reserved" : actor.availability === "available" ? "free" : actor.availability || "unknown";
    return { status, active, free: status === "free" };
  }
  function indicators(state) {
    const active = state.incidents.filter((i) => !closed.has(i.status));
    const resources = state.actors.map((a) => resourceState(a, state.assignments));
    return { active: active.length, critical: active.filter((i) => Number.isFinite(i.priority) && i.priority >= 8).length,
      unknownPriority: active.filter((i) => !Number.isFinite(i.priority)).length,
      free: resources.filter((a) => a.free).length, busy: resources.filter((a) => a.active.length).length,
      total: resources.length, unknown: state.actors.filter((a) => !a.availability || a.availability === "unknown").length,
      approvals: state.approvals.filter((a) => a.status === "pending").length };
  }
  const grave = (actions) => actions.some((a) => ["evacuate", "stop_show", "request_external", "set_zone"].includes(a.kind));
  const label = (value) => ({
    offered: "Oferta pendiente", pending: "Pendiente", accepted: "Aceptada explícitamente",
    en_route: "En camino", arrived: "En destino", located: "Localizado", completed: "Completada",
    declined: "Rechazada", expired: "Caducada", cancelled: "Cancelada", available: "Disponible",
    unavailable: "No disponible", unknown: "Sin confirmar", ready: "Preparado", missing: "Falta configuración",
    degraded: "Degradado", retry: "Pendiente de reintento", failed: "Fallida", uncertain: "Entrega incierta",
    delivered: "Entregada", sending: "Enviando", approved: "Aprobada", rejected: "Vetada",
    open: "Abierto", waiting: "En espera", assigned: "Con asignación", in_progress: "En atención", closed: "Cerrado", resolved: "Resuelto", merged: "Unificado",
    free: "Libre", reserved: "Reservado", busy: "Ocupado / atendiendo", invalidated: "Invalidada",
    leased: "Envío reclamado", launched: "Ejecución lanzada", succeeded: "Ejecución finalizada", timeout: "Tiempo agotado", local_required: "Requiere comunicación manual",
    accept: "Aceptación explícita", reject: "Rechazo explícito", unclear: "Respuesta ambigua", no_answer: "Sin respuesta", provider_failed: "Fallo del proveedor",
    phone: "Voz · HappyRobot", web: "Sala web", telegram: "Telegram", simulation: "Simulación", real: "Real", mixed: "Mixto", unconfirmed: "No confirmado",
    offer: "Oferta de tarea", update: "Actualización", notify: "Notificación", approval: "Decisión humana", call_ended: "Llamada terminada",
    evacuate: "Evacuar", stop_show: "Parar espectáculo", request_external: "Solicitar ayuda externa", set_zone: "Cambiar estado de zona",
  }[value] || value || "Sin confirmar");
  const assignmentActions = (status) => ({
    offered: ["accept", "decline"], pending: ["accept", "decline"],
    accepted: ["eta", "arrive", "decline"], en_route: ["eta", "arrive", "decline"],
    arrived: ["locate"], located: ["complete"],
  }[status] || []);
  function channelEntries(channels) {
    const entries = [];
    for (const [name, value] of Object.entries(channels)) {
      if (!value || typeof value !== "object" || Array.isArray(value)) continue;
      if (name === "workflows") {
        for (const [slot, workflow] of Object.entries(value)) {
          if (workflow && typeof workflow === "object") entries.push([`Workflow · ${slot}`, workflow]);
        }
      } else entries.push([name, value]);
    }
    return entries;
  }
  function channelStatus(channel) {
    const has = (value) => Array.isArray(value) ? value.length > 0 : Boolean(value);
    if (has(channel.degraded)) return "degraded";
    if (has(channel.missing) || channel.ready === false || channel.configured === false) return "missing";
    return channel.status || (channel.ready === true ? "ready" : "unknown");
  }

  const EXPLAINED = {
    address_already_registered: "Ese contacto ya está registrado en otro miembro del personal. Usa el mismo identificador para actualizarlo o un contacto distinto.",
    actor_busy: "Ese miembro del personal tiene una asignación activa; libérala o espera a que termine antes de cambiar su ficha.",
    actor_unavailable: "Ese miembro del personal no está disponible ahora.",
    incident_closed: "El incidente ya está cerrado.",
    offer_expired: "La oferta ha caducado; revisa el estado actual.",
    task_covered: "Esa necesidad ya está cubierta por otra asignación.",
    coordinator_unavailable: "No hay ningún organizador disponible que reciba la acción. Registra en Personal a alguien con rol Organizador y disponibilidad Disponible.",
    coordinator_required: "La persona elegida no tiene rol Organizador.",
    recipient_required: "Elige un destinatario para el aviso.",
    location_required: "El incidente no tiene ubicación confirmada; confírmala antes.",
    approval_expired_or_decided: "La aprobación ya caducó o se decidió.",
    approval_content_changed: "La propuesta cambió desde que la abriste; revísala de nuevo.",
    operator_review_required: "Requiere revisión del operador antes de continuar.",
  };

  function createClient({ fetcher = root.fetch.bind(root), refresh, onMessage, uuid = () => root.crypto.randomUUID() }) {
    let pending = false;
    return {
      busy: () => pending,
      async send(kind, fields, entity = null) {
        if (pending) return { ok: false, error: "busy" };
        if (entity && (!Number.isSafeInteger(entity.version) || entity.version < 0)) {
          onMessage("Versión no disponible. Actualiza antes de enviar.", true);
          return { ok: false, error: "version" };
        }
        pending = true;
        const controller = new AbortController();
        const timeout = root.setTimeout(() => controller.abort(), 15000);
        try {
          const body = { ...fields, kind, command_id: uuid() };
          if (entity) body.expected_version = entity.version;
          const response = await fetcher("/api/operations/command", {
            method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body), signal: controller.signal,
          });
          const result = await response.json().catch(() => ({}));
          if (response.status === 409) {
            await refresh(true);
            const explained = EXPLAINED[result.error];
            onMessage(explained
              ? `${explained} No se reenvió el comando.`
              : "Conflicto de versión: el estado cambió. Se ha solicitado una actualización; revisa los datos y abre de nuevo la acción. No se reenvió el comando.", true);
            return { ok: false, error: result.error || "conflict" };
          }
          if (!response.ok || result.ok !== true) {
            const message = response.status === 401 || response.status === 403
              ? "Sesión de operador o permiso insuficiente. Vuelve a identificarte y recarga."
              : EXPLAINED[result.error] || result.message || result.error || `No se pudo registrar (HTTP ${response.status}).`;
            onMessage(message, true);
            return { ok: false, error: result.error || "request" };
          }
          onMessage("Comando registrado. El estado del servidor confirma sus efectos; el envío no confirma entrega al personal.", false);
          await refresh(true);
          return result;
        } catch {
          onMessage("No se pudo confirmar el resultado. Puede haberse registrado: actualiza y revisa la cronología antes de crear otra acción.", true);
          await refresh(true);
          return { ok: false, error: "uncertain" };
        } finally {
          root.clearTimeout(timeout);
          pending = false;
        }
      },
    };
  }

  function decisionFields(approval, approved, confirmed, note) {
    if (approved && grave(approval.actions || []) && !confirmed) throw new Error("Confirma expresamente la acción grave.");
    return { approval_id: approval.id, approved, content_hash: approval.content_hash, note };
  }

  function mount(document) {
    const $ = (id) => document.getElementById(id);
    const node = (tag, text, className) => {
      const e = document.createElement(tag);
      if (text !== undefined) e.textContent = String(text);
      if (className) e.className = className;
      return e;
    };
    const text = (value) => typeof value === "object" && value !== null ? JSON.stringify(value) : String(value ?? "—");
    const date = (value) => Number.isFinite(value) && value > 0 ? new Date(value * 1000).toLocaleString("es-ES") : "Sin fecha confirmada";
    const empty = (message) => node("p", message, "muted");
    let state = null, sync, modal = null, lastZones = "", selectedIncident = null, authExpired = false;
    let receivedAt = null, ageTimer = null, stopped = false;
    const listCache = new Map();
    const expired = (approval) => Number.isFinite(approval.expires_at) && Number.isFinite(state.server_time)
      && approval.expires_at <= state.server_time + (receivedAt === null ? 0 : Math.max(0, Date.now() - receivedAt) / 1000);
    function freshness() {
      if (stopped) return;
      if (receivedAt !== null) $("freshness").textContent = `Última verificación hace ${Math.max(0, Math.floor((Date.now() - receivedAt) / 1000))} s`;
      ageTimer = root.setTimeout(freshness, 1000);
    }
    function message(content, error) {
      $("error").hidden = !error;
      $("error").textContent = error ? content : "";
      $("feedback").textContent = error ? "" : content;
      if (error) $("error").focus();
    }
    const client = createClient({ refresh: (fresh) => sync.refresh(fresh), onMessage: message });
    const zoneName = (id) => (state.zones.find((z) => z.id === id) || {}).name || id || "Sin ubicación confirmada";
    const actorName = (id) => (state.actors.find((a) => a.id === id) || {}).name || id;
    function button(title, action, className = "secondary") {
      const b = node("button", title, className);
      b.type = "button";
      b.onclick = action;
      return b;
    }
    function facts(items) {
      const list = node("dl");
      for (const [key, value] of items) list.append(node("dt", key), node("dd", text(value)));
      return list;
    }
    function card(title, status, className = "") {
      const item = node("article", undefined, className);
      item.append(node("h3", title), node("span", label(status), "badge"));
      return item;
    }
    function field(name, title, options = {}) {
      const wrap = node("label", title);
      const input = node(options.choices ? "select" : options.multiline ? "textarea" : "input");
      input.name = name; input.id = "command-" + name;
      if (options.choices) for (const [value, caption] of options.choices) {
        const option = node("option", caption); option.value = value; input.append(option);
      }
      else if (!options.multiline) input.type = options.checkbox ? "checkbox" : options.number ? "number" : "text";
      if (options.number) { input.min = "0"; input.max = "240"; input.step = "1"; }
      if (options.multiline) input.rows = 3;
      input.required = options.required !== false;
      if (options.value !== undefined) input.value = options.value;
      wrap.append(input); $("command-fields").append(wrap);
      return input;
    }
    const zones = () => state.zones.map((z) => [z.id, z.name || z.id]);
    function open(title, entity, build, payload) {
      if (authExpired) return message("La sesión ha caducado. Inicia sesión de nuevo.", true);
      if (client.busy()) return message("Espera a que termine el comando anterior.", true);
      $("command-fields").replaceChildren();
      $("command-title").textContent = title;
      $("command-context").textContent = `${entity.id} · versión ${entity.version}. Se enviará esta versión, aunque el estado cambie mientras revisas.`;
      $("command-error").hidden = true;
      $("command-submit").disabled = false;
      build();
      modal = { entity: { ...entity }, payload };
      $("command-dialog").showModal();
    }
    function assignmentDialog(a, kind) {
      const titles = { accept: "Aceptar tarea", decline: "Rechazar tarea", eta: "Comunicar ETA", arrive: "Confirmar llegada", locate: "Confirmar localización", complete: "Completar tarea" };
      open(titles[kind], a, () => {
        $("command-fields").append(node("p", `${actorName(a.actor_id)} · incidente ${a.incident_id} · destino ${zoneName(a.zone)}`));
        if (kind === "decline") field("reason", "Motivo del rechazo", { multiline: true });
        if (kind === "eta") {
          field("eta_min", "Minutos hasta el destino", { number: true, value: a.eta_min ?? 0 });
          field("destination_confirmed", `Confirmo el destino: ${zoneName(a.zone)}`, { checkbox: true });
        }
      }, (data) => ({
        kind, fields: { assignment_id: a.id,
          ...(kind === "decline" ? { reason: data.get("reason") } : {}),
          ...(kind === "eta" ? { eta_min: Number(data.get("eta_min")), destination_confirmed: data.has("destination_confirmed"), destination_zone_id: a.zone } : {}),
        },
      }));
    }
    function incidentDialog(i, kind) {
      open({ update: "Actualizar aviso", offer: "Ofrecer tarea", propose: "Proponer acción para aprobación" }[kind], i, () => {
        if (kind === "update") {
          field("text", "Información actualizada", { multiline: true, value: i.text });
          field("zone", "Ubicación", { choices: [["", "Sin confirmar"], ...zones()], value: i.zone || "", required: false });
          field("confirmed", "He verificado esta rectificación: puede reducir prioridad y necesidades.", { checkbox: true, required: false });
        } else if (kind === "offer") {
          field("actor_id", "Personal libre", { choices: state.actors.filter((a) => resourceState(a, state.assignments).free).map((a) => [a.id, `${a.name} · ${(a.roles || []).map(roleName).join(", ")}`]) });
          field("role", "Rol necesario", { choices: Object.keys(i.needs || {}).filter((r) => roles.includes(r)).map((r) => [r, roleName(r)]) });
          $("command-fields").append(empty("El servidor valida rol, disponibilidad y capacidad antes de reservar."));
        } else {
          field("action", "Acción propuesta", { choices: [["evacuate", "Evacuar"], ["stop_show", "Parar espectáculo"], ["request_external", "Solicitar ayuda externa"]] });
          field("zone", "Zona", { choices: zones(), value: i.zone || "" });
          field("reason", "Motivo", { multiline: true });
          $("command-fields").append(empty("Esta propuesta requiere aprobación humana independiente sobre su hash y versión."));
        }
      }, (data) => {
        const common = { incident_id: i.id };
        if (kind === "update") return { kind, fields: { ...common, text: data.get("text"), zone: data.get("zone") || null, confirmed: data.has("confirmed") } };
        if (kind === "offer") return { kind, fields: { ...common, actor_id: data.get("actor_id"), role: data.get("role") } };
        return { kind, fields: { ...common, requiere_persona: true, reason: data.get("reason"), actions: [{ kind: data.get("action"), zone: data.get("zone") }] } };
      });
    }
    function approvalDialog(a, approved) {
      if (expired(a)) return message("La propuesta ha caducado. Actualiza y revisa una propuesta vigente.", true);
      open(approved ? "Aprobar propuesta vigente" : "Vetar propuesta", a, () => {
        $("command-fields").append(facts([["Hash de contenido", a.content_hash], ["Caduca", date(a.expires_at)], ["Acciones exactas", a.actions], ["Motivo", a.reason]]));
        field("note", "Nota del operador", { multiline: true, required: false });
        if (approved && grave(a.actions || [])) field("confirmed", "He revisado las acciones graves y autorizo expresamente esta propuesta.", { checkbox: true });
      }, (data) => ({ kind: "decide", fields: decisionFields(a, approved, data.has("confirmed"), data.get("note")) }));
    }
    function showList(id, items, render, fallback, context = "") {
      const container = $(id);
      const key = JSON.stringify([items, context]);
      if (listCache.get(id) === key) return;
      listCache.set(id, key);
      const active = document.activeElement;
      const focusKey = active && active.dataset.focus;
      let placeholder = empty(fallback);
      if (id === "incidents") { placeholder = node("tr"); const cell = node("td", fallback); cell.colSpan = 4; placeholder.append(cell); }
      container.replaceChildren(...(items.length ? items.map(render) : [placeholder]));
      if (focusKey) for (const b of container.querySelectorAll("button")) if (b.dataset.focus === focusKey) b.focus();
    }
    function actionGroup(id, actions) {
      const group = node("div", undefined, "actions");
      actions.forEach(([title, run], index) => {
        const b = button(title, run); b.dataset.focus = `${id}-${index}`; group.append(b);
      });
      return group;
    }
    function renderChannels() {
      const channels = state.channels || {};
      const entries = channelEntries(channels);
      const modes = new Set([channels.mode, ...entries.map(([, c]) => c.mode)].filter(Boolean));
      const sim = modes.has("mixed") || [...modes].some((m) => ["sim", "simulation", "simulated", "demo"].includes(m));
      const real = modes.has("real") || modes.has("mixed");
      $("mode").textContent = sim && real ? "Canales mixtos: consulta el modo de cada canal."
        : real ? "Canales en modo real según el servidor. La configuración no acredita entrega."
        : sim ? "SIMULACIÓN · las acciones de demo no acreditan entrega a proveedores reales."
        : "Modo de transporte no confirmado por el servidor. No se presupone entrega real.";
      $("channels").replaceChildren(...(entries.length ? entries.map(([name, c]) => {
        const status = channelStatus(c);
        const item = card(name, status);
        item.append(facts([["Modo", label(c.mode || channels.mode || "unconfirmed")], ["Falta", c.missing || []], ["Detalle", c.message || c.reason || c.degraded || "—"]]));
        if (c.workflows) item.append(facts([["Workflows", c.workflows]]));
        return item;
      }) : [empty("Sin diagnóstico de canales. Configuración pendiente de confirmar.")]));
    }
    const needsText = (needs) => needs && typeof needs === "object" ? Object.entries(needs).map(([role, count]) => `${roleName(role)}: ${count}`).join(" · ") || "Sin necesidades publicadas" : "Desconocidas";
    function renderIncidentDetail() {
      if (!selectedIncident) return;
      const i = state.incidents.find((item) => item.id === selectedIncident);
      if (!i) { $("incident-detail").replaceChildren(empty("El incidente ya no figura en este snapshot.")); return; }
      $("incident-detail-title").textContent = `Incidente ${i.id}`;
      const list = node("ol", undefined, "timeline");
      for (const e of state.events.filter((e) => e.incident_id === i.id).slice().reverse()) {
        const row = node("li"); row.append(node("time", date(e.occurred_at)), node("strong", label(e.kind)), node("p", e.summary)); list.append(row);
      }
      const assignments = state.assignments.filter((a) => a.incident_id === i.id);
      $("incident-detail").replaceChildren(node("p", i.text, "detail"), facts([
        ["Estado del incidente", label(i.status)], ["Zona", zoneName(i.zone)], ["Prioridad", Number.isFinite(i.priority) ? `${i.priority}/10` : "Desconocida"],
        ["Necesidades por rol", needsText(i.needs)], ["Por qué espera", i.why_waiting || "Sin espera comunicada"],
        ["Incertidumbre", i.uncertainties || i.missing || "No publicada"], ["Revisión humana de la información", i.review_required ? "Pendiente: verificar antes de rectificar" : "No solicitada por el servidor"], ["Versión", i.version],
      ]), node("h3", "Asignaciones · rol, destino y progreso independientes"),
      ...assignments.map((a) => node("p", `${actorName(a.actor_id)} · ${roleName(a.role)} · destino ${zoneName(a.zone)} · ${label(a.status)} · ETA ${a.eta_min == null ? "sin confirmar" : a.eta_min + " min"}`)),
      node("h3", "Cronología del incidente"), list.children.length ? list : empty("Sin eventos publicados para este incidente."));
    }
    function render() {
      const kpi = indicators(state);
      for (const [id, value] of [["active", kpi.active], ["free", kpi.free], ["busy", kpi.busy], ["approvals", kpi.approvals]]) $("kpi-" + id).textContent = value;
      $("kpi-critical").textContent = `${kpi.critical} con prioridad ≥ 8/10 · ${kpi.unknownPriority} sin prioridad`;
      $("kpi-resources").textContent = `De ${kpi.total} registrados · ${kpi.unknown} con disponibilidad sin confirmar`;
      if (root.RESQVAL_PLANO) {
        const map = root.RESQVAL_PLANO.render(document, $("venue-map"), state, $("zone-filter").value);
        $("map-unknown").textContent = `Fuera del plano (zona desconocida o sin geometría): ${map.unknownIncidents} incidentes activos · ${map.unknownActors} recursos. No se inventa su posición.`;
      }
      renderIncidentDetail();
      $("revision").textContent = `Revisión ${state.revision} · ${date(state.server_time)}`;
      renderChannels();
      const zoneKey = JSON.stringify(state.zones);
      if (zoneKey !== lastZones) {
        lastZones = zoneKey;
        for (const id of ["report-zone", "staff-zone", "zone-filter"]) {
          const select = $(id), selected = select.value;
          const base = id === "zone-filter" ? [["", "Todas las zonas"], ["unknown", "Ubicación sin confirmar"]] : [["", "Sin confirmar"]];
          select.replaceChildren(...[...base, ...zones()].map(([value, name]) => {
            const option = node("option", name); option.value = value; return option;
          }));
          select.value = selected;
        }
      }
      for (const id of ["report-form", "staff-form"]) $(id).querySelector("fieldset").disabled = authExpired;
      const query = normalize($("incident-search").value), filter = $("incident-filter").value, zone = $("zone-filter").value;
      const incidents = state.incidents.filter((i) => (filter === "all" || (filter === "closed" ? closed.has(i.status) : !closed.has(i.status)))
        && (!zone || (zone === "unknown" ? !state.zones.some((z) => z.id === i.zone) : i.zone === zone))
        && normalize([i.id, i.text, zoneName(i.zone), label(i.status)].join(" ")).includes(query))
        .sort((a, b) => (b.priority ?? -1) - (a.priority ?? -1) || a.created_at - b.created_at);
      $("incident-count").textContent = `(${incidents.length})`;
      showList("incidents", incidents, (i) => {
        const item = node("tr", undefined, i.priority >= 8 ? "urgent" : "");
        const description = node("td"); description.append(node("strong", i.id), node("p", i.text, "detail"), node("small", needsText(i.needs)));
        const priority = node("td", Number.isFinite(i.priority) ? `${i.priority}/10` : "Desconocida");
        const location = node("td"); location.append(node("p", zoneName(i.zone)), node("span", label(i.status), "badge"));
        const controls = node("td"); controls.append(node("small", i.why_waiting || "Sin espera comunicada"));
        const actions = [["Ver detalle", () => { selectedIncident = i.id; renderIncidentDetail(); $("incident-dialog").showModal(); }]];
        if (!closed.has(i.status)) actions.push(["Actualizar", () => incidentDialog(i, "update")], ["Ofrecer tarea", () => incidentDialog(i, "offer")], ["Proponer acción", () => incidentDialog(i, "propose")]);
        controls.append(actionGroup(i.id, actions)); item.append(description, priority, location, controls);
        return item;
      }, "Sin incidentes en esta vista. Revisa los filtros o registra un aviso.", state.zones);
      const actors = state.actors.filter((a) => normalize([a.id, a.name, ...(a.roles || []).map(roleName), zoneName(a.zone)].join(" ")).includes(query));
      showList("actors", actors, (a) => {
        const occupation = resourceState(a, state.assignments);
        const item = card(`${a.name} · ${a.id}`, occupation.status);
        item.append(facts([["Disponibilidad declarada", label(a.availability)], ["Roles autorizados", (a.roles || []).map(roleName).join(", ") || "Sin roles"], ["Canal", label(a.channel)], ["Ubicación declarada", zoneName(a.zone)]]));
        for (const task of occupation.active) item.append(node("p", `${task.incident_id} · ${roleName(task.role)} · destino ${zoneName(task.zone)} · ${label(task.status)}`, "detail"));
        item.append(actionGroup(a.id, [["Disponibilidad", () => open("Cambiar disponibilidad", a, () => {
          field("availability", "Disponibilidad", { choices: ["available", "unavailable", "unknown"].map((v) => [v, label(v)]), value: a.availability });
        }, (data) => ({ kind: "availability", fields: { actor_id: a.id, availability: data.get("availability") } }))]]));
        return item;
      }, "Sin personal en esta vista. Revisa la búsqueda o registra los equipos autorizados.", [state.assignments, state.zones]);
      showList("assignments", state.assignments, (a) => {
        const item = card(`${a.incident_id} · ${actorName(a.actor_id)}`, a.status, ["offered", "pending"].includes(a.status) ? "pending" : ["accepted", "en_route"].includes(a.status) ? "accepted" : "");
        item.append(facts([["Asignación / tarea", `${a.id} / ${a.task_id || "—"}`], ["Rol", roleName(a.role)], ["Destino", zoneName(a.zone)], ["ETA", a.eta_min == null ? "Sin confirmar" : `${a.eta_min} min`], ["Caduca", date(a.expires_at)], ["Versión", a.version]]));
        if (a.communication?.result) item.append(facts([["Resultado de comunicación", label(a.communication.result)]]));
        const names = { accept: "Aceptar", decline: "Rechazar", eta: "ETA", arrive: "Llegada", locate: "Localizar", complete: "Completar" };
        const controls = assignmentActions(a.status).map((kind) => [names[kind], () => assignmentDialog(a, kind)]);
        if (["declined", "expired", "cancelled"].includes(a.status) && !a.followup_confirmed) controls.push(["Confirmar seguimiento", () => open("Seguimiento humano antes de una nueva oferta", a, () => {
          $("command-fields").append(node("p", `${actorName(a.actor_id)} · tarea ${a.id}. Verifica con el personal que está disponible. Esto permite al planificador generar nuevas ofertas; no se repetirá la llamada anterior.`));
          field("reason", "Resultado de la verificación humana", { multiline: true });
          field("confirmed", "He contactado con el personal y confirmo su disponibilidad para una nueva oferta.", { checkbox: true });
        }, (data) => {
          if (!data.has("confirmed")) throw new Error("Confirma expresamente el seguimiento con el personal.");
          return { kind: "followup", fields: { assignment_id: a.id, reason: data.get("reason") } };
        })]);
        item.append(actionGroup(a.id, controls));
        return item;
      }, "Sin asignaciones. Las necesidades y la disponibilidad determinan las ofertas.", [state.actors.map((a) => [a.id, a.name]), state.zones]);
      showList("approvals", state.approvals, (a) => {
        const item = card(`${a.id} · incidente ${a.incident_id}`, a.status, grave(a.actions || []) ? "urgent" : "");
        item.append(facts([["Acciones", a.actions], ["Motivo", a.reason], ["Crítica", a.critica || a.critique || "No publicada en este snapshot"], ["Versión", a.version], ["Hash", a.content_hash], ["Caduca", date(a.expires_at)]]));
        if (a.status === "pending" && !expired(a)) item.append(actionGroup(a.id, [["Revisar y aprobar", () => approvalDialog(a, true)], ["Vetar", () => approvalDialog(a, false)]]));
        else if (a.status === "pending") item.append(empty("Vigencia agotada según la hora del servidor. Actualiza para confirmar su estado."));
        return item;
      }, "No hay propuestas que revisar. Las acciones graves siempre requieren aprobación.", state.approvals.map(expired));
      showList("deliveries", state.deliveries, (d) => {
        const item = card(`${label(d.channel)} · ${label(d.purpose)}`, d.status);
        item.append(facts([["Entrega", d.id], ["Destinatario", actorName(d.recipient_id)], ["Mensaje", d.text || "Sin texto publicado"], ["Incidente / asignación", `${d.incident_id || "—"} / ${d.assignment_id || "—"}`], ["Intentos", d.attempts], ["Último error", d.last_error || "Sin error comunicado"]]));
        return item;
      }, "Sin entregas registradas.", state.actors.map((a) => [a.id, a.name]));
      showList("workflows", state.workflows || [], (w) => {
        const item = card(`${label(w.channel)} · ${w.incident_id}`, w.status);
        item.append(facts([["Entrega", w.delivery_id], ["Resultado", w.last_result || "Pendiente"], ["Error", w.last_error || "—"], ["Límite", date(w.deadline)]]));
        return item;
      }, "Sin ejecuciones externas registradas.");
      showList("events", state.events.slice().reverse(), (e) => {
        const item = node("li");
        item.append(node("time", date(e.occurred_at)), node("strong", `${e.kind} · ${e.principal}`), node("p", e.summary, "detail"), node("small", `${e.incident_id || ""} ${e.assignment_id || ""}`));
        return item;
      }, "Sin eventos registrados.");
    }
    $("command-form").onsubmit = async (event) => {
      event.preventDefault();
      if (!modal || client.busy()) return;
      if (authExpired) return message("La sesión ha caducado. Inicia sesión de nuevo.", true);
      if (modal.entity.content_hash && expired(modal.entity)) {
        $("command-error").textContent = "La propuesta ha caducado. Cierra y revisa una propuesta vigente.";
        $("command-error").hidden = false; $("command-submit").disabled = true; return;
      }
      $("command-submit").disabled = true; $("command-cancel").disabled = true;
      try {
        const { kind, fields } = modal.payload(new FormData(event.currentTarget));
        const result = await client.send(kind, fields, modal.entity);
        if (result.ok) $("command-dialog").close();
        else {
          $("command-error").textContent = $("error").textContent;
          $("command-error").hidden = false; $("command-error").focus();
          if (!["conflict", "uncertain"].includes(result.error)) $("command-submit").disabled = false;
        }
      } catch (error) {
        $("command-error").textContent = error.message; $("command-error").hidden = false;
        $("command-submit").disabled = false;
      } finally { $("command-cancel").disabled = false; }
    };
    $("command-dialog").addEventListener("cancel", (event) => { if (client.busy()) event.preventDefault(); });
    $("command-cancel").onclick = () => $("command-dialog").close();
    $("command-dialog").addEventListener("close", () => { modal = null; $("command-fields").replaceChildren(); });
    function form(id, kind, fields) {
      $(id).onsubmit = async (event) => {
        event.preventDefault();
        if (authExpired) return message("La sesión ha caducado. Inicia sesión de nuevo.", true);
        if (client.busy()) return message("Espera a que termine el comando anterior.", true);
        const target = event.currentTarget, data = new FormData(target);
        const body = fields(data);
        if (kind === "register_actor") {
          $("staff-address").value = "";
          if (!body.roles.length) return message("Selecciona al menos un rol autorizado.", true);
          if (body.channel !== "web" && !body.address) return message("El canal seleccionado necesita un contacto privado.", true);
        }
        const submit = target.querySelector("button[type=submit]");
        submit.disabled = true;
        const result = await client.send(kind, body);
        submit.disabled = false;
        if (result.ok) target.reset();
      };
    }
    form("report-form", "report", (data) => ({ text: data.get("text"), zone: data.get("zone") || null }));
    form("staff-form", "register_actor", (data) => ({
      actor_id: data.get("actor_id"), name: data.get("name"), roles: data.getAll("roles"),
      channel: data.get("channel"), address: data.get("address"), zone: data.get("zone") || null, availability: data.get("availability"),
    }));
    $("incident-filter").onchange = () => { if (state) render(); };
    $("zone-filter").onchange = () => { if (state) render(); };
    $("incident-search").oninput = () => { if (state) render(); };
    $("incident-close").onclick = () => $("incident-dialog").close();
    $("incident-dialog").addEventListener("close", () => { selectedIncident = null; });
    const nav = $("navigation");
    for (const link of nav.querySelectorAll("a")) link.onclick = () => {
      for (const other of nav.querySelectorAll("a")) other.removeAttribute("aria-current");
      link.setAttribute("aria-current", "location");
      const target = $(link.getAttribute("href").slice(1));
      if (target) target.focus({ preventScroll: true });
    };
    $("refresh").onclick = () => sync.refresh(true);
    const gate = root.SALA_SYNC.snapshotGate();
    sync = root.SALA_SYNC.connect({
      stateURL: "/api/operations/state", streamURL: "/api/operations/stream", staleAfter: 30000,
      accept(next) {
        if (!next || !["zones", "incidents", "actors", "assignments", "approvals", "deliveries", "events"].every((key) => Array.isArray(next[key]))) return false;
        if (!gate.accept(next)) return false;
        state = next; receivedAt = Date.now();
        $("freshness").textContent = "Última verificación hace 0 s";
        if (ageTimer === null) freshness();
        render(); return true;
      },
      onStatus(status) {
        $("connection").textContent = { connecting: "Conectando…", live: "En directo · SSE", poll: "Estado por consulta periódica", reconnecting: "Reconectando · consulta periódica activa", offline: "Sin conexión · mostrando último estado", stale: "Datos antiguos · verificando conexión", auth: "Acceso de operador caducado" }[status];
        $("connection").dataset.status = status;
        if (status === "auth") {
          authExpired = true;
          $("command-submit").disabled = true;
          message("Identifícate de nuevo como operador y recarga esta página.", true);
          for (const id of ["report-form", "staff-form"]) $(id).querySelector("fieldset").disabled = true;
        }
      },
    });
    root.addEventListener("pagehide", () => { $("staff-address").value = ""; stopped = true; root.clearTimeout(ageTimer); sync.stop(); });
    return { client, render, state: () => state };
  }

  root.MANDO_OPERATIONS = { createClient, decisionFields, assignmentActions, channelEntries, channelStatus, grave, label, resourceState, indicators, mount };
  if (root.document) mount(root.document);
})(typeof window === "undefined" ? globalThis : window);
