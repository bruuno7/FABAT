(function (root) {
  "use strict";

  const roles = ["medico", "bomberos", "policia", "staff_entradas", "organizador"];
  const closed = new Set(["closed", "resolved", "merged", "cancelled"]);
  const grave = (actions) => actions.some((a) => ["evacuate", "stop_show", "request_external", "set_zone"].includes(a.kind));
  const label = (value) => ({
    offered: "Oferta pendiente", pending: "Pendiente", accepted: "Aceptada explícitamente",
    en_route: "En camino", arrived: "En destino", located: "Localizado", completed: "Completada",
    declined: "Rechazada", expired: "Caducada", cancelled: "Cancelada", available: "Disponible",
    unavailable: "No disponible", unknown: "Sin confirmar", ready: "Preparado", missing: "Falta configuración",
    degraded: "Degradado", retry: "Pendiente de reintento", failed: "Fallida", uncertain: "Entrega incierta",
    delivered: "Entregada", sending: "Enviando", approved: "Aprobada", rejected: "Vetada",
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
            onMessage("Conflicto de versión: el estado cambió. Se ha solicitado una actualización; revisa los datos y abre de nuevo la acción. No se reenvió el comando.", true);
            return { ok: false, error: "conflict" };
          }
          if (!response.ok || result.ok !== true) {
            const message = response.status === 401 || response.status === 403
              ? "Sesión de operador o permiso insuficiente. Vuelve a identificarte y recarga."
              : result.message || result.error || `No se pudo registrar (HTTP ${response.status}).`;
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
    const date = (value) => value ? new Date(Number(value) * 1000).toLocaleString("es-ES") : "Sin fecha";
    const empty = (message) => node("p", message, "muted");
    let state = null, sync, modal = null, lastZones = "";
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
      else input.type = options.checkbox ? "checkbox" : options.number ? "number" : "text";
      if (options.number) { input.min = "0"; input.max = "240"; input.step = "1"; }
      if (options.multiline) input.rows = 3;
      input.required = options.required !== false;
      if (options.value !== undefined) input.value = options.value;
      wrap.append(input); $("command-fields").append(wrap);
      return input;
    }
    const zones = () => state.zones.map((z) => [z.id, z.name || z.id]);
    function open(title, entity, build, payload) {
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
        } else if (kind === "offer") {
          field("actor_id", "Personal", { choices: state.actors.filter((a) => a.availability === "available").map((a) => [a.id, `${a.name} · ${(a.roles || []).join(", ")}`]) });
          field("role", "Rol necesario", { choices: Object.keys(i.needs || {}).filter((r) => roles.includes(r)).map((r) => [r, r]) });
          $("command-fields").append(empty("El servidor valida rol, disponibilidad y capacidad antes de reservar."));
        } else {
          field("action", "Acción propuesta", { choices: [["evacuate", "Evacuar"], ["stop_show", "Parar espectáculo"], ["request_external", "Solicitar ayuda externa"]] });
          field("zone", "Zona", { choices: zones(), value: i.zone || "" });
          field("reason", "Motivo", { multiline: true });
          $("command-fields").append(empty("Esta propuesta requiere aprobación humana independiente sobre su hash y versión."));
        }
      }, (data) => {
        const common = { incident_id: i.id };
        if (kind === "update") return { kind, fields: { ...common, text: data.get("text"), zone: data.get("zone") || null } };
        if (kind === "offer") return { kind, fields: { ...common, actor_id: data.get("actor_id"), role: data.get("role") } };
        return { kind, fields: { ...common, requiere_persona: true, reason: data.get("reason"), actions: [{ kind: data.get("action"), zone: data.get("zone") }] } };
      });
    }
    function approvalDialog(a, approved) {
      open(approved ? "Aprobar propuesta vigente" : "Vetar propuesta", a, () => {
        $("command-fields").append(facts([["Hash de contenido", a.content_hash], ["Caduca", date(a.expires_at)], ["Acciones exactas", a.actions], ["Motivo", a.reason]]));
        field("note", "Nota del operador", { multiline: true, required: false });
        if (approved && grave(a.actions || [])) field("confirmed", "He revisado las acciones graves y autorizo expresamente esta propuesta.", { checkbox: true });
      }, (data) => ({ kind: "decide", fields: decisionFields(a, approved, data.has("confirmed"), data.get("note")) }));
    }
    function showList(id, items, render, fallback) {
      const container = $(id);
      const key = JSON.stringify(items);
      if (container.dataset.snapshot === key) return;
      container.dataset.snapshot = key;
      const active = document.activeElement;
      const focusKey = active && active.dataset.focus;
      container.replaceChildren(...(items.length ? items.map(render) : [empty(fallback)]));
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
      const sim = [...modes].some((m) => ["sim", "simulation", "simulated", "demo"].includes(m));
      const real = modes.has("real");
      $("mode").textContent = sim && real ? "Canales mixtos: consulta el modo de cada canal."
        : real ? "Canales en modo real según el servidor. La configuración no acredita entrega."
        : sim ? "SIMULACIÓN · las acciones de demo no acreditan entrega a proveedores reales."
        : "Modo de transporte no confirmado por el servidor. No se presupone entrega real.";
      $("channels").replaceChildren(...(entries.length ? entries.map(([name, c]) => {
        const status = channelStatus(c);
        const item = card(name, status);
        item.append(facts([["Modo", c.mode || channels.mode || "No confirmado"], ["Falta", c.missing || []], ["Detalle", c.message || c.reason || c.degraded || "—"]]));
        if (c.workflows) item.append(facts([["Workflows", c.workflows]]));
        return item;
      }) : [empty("Sin diagnóstico de canales. Configuración pendiente de confirmar.")]));
    }
    function render() {
      $("revision").textContent = `Revisión ${state.revision} · ${date(state.server_time)}`;
      renderChannels();
      const zoneKey = JSON.stringify(state.zones);
      if (zoneKey !== lastZones) {
        lastZones = zoneKey;
        for (const id of ["report-zone", "staff-zone"]) {
          const select = $(id), selected = select.value;
          select.replaceChildren(...[["", "Sin confirmar"], ...zones()].map(([value, name]) => {
            const option = node("option", name); option.value = value; return option;
          }));
          select.value = selected;
        }
      }
      for (const id of ["report-form", "staff-form"]) $(id).querySelector("fieldset").disabled = false;
      const incidents = state.incidents.filter((i) => $("incident-filter").value === "all" || !closed.has(i.status))
        .sort((a, b) => b.priority - a.priority || a.created_at - b.created_at);
      $("incident-count").textContent = `(${incidents.length})`;
      showList("incidents", incidents, (i) => {
        const item = card(`${i.id} · prioridad ${i.priority}/10`, i.status, i.priority >= 8 ? "urgent" : "");
        item.append(node("p", i.text, "detail"), facts([["Ubicación", zoneName(i.zone)], ["Necesidades", i.needs], ["Por qué espera", i.why_waiting || "Sin espera comunicada"], ["Versión", i.version]]));
        if (!closed.has(i.status)) item.append(actionGroup(i.id, [["Actualizar", () => incidentDialog(i, "update")], ["Ofrecer tarea", () => incidentDialog(i, "offer")], ["Proponer acción", () => incidentDialog(i, "propose")]]));
        return item;
      }, "Sin incidentes en esta vista. Registra un aviso o espera uno desde los canales.");
      showList("actors", state.actors, (a) => {
        const item = card(`${a.name} · ${a.id}`, a.availability);
        item.append(facts([["Roles", (a.roles || []).join(", ") || "Sin roles"], ["Canal", a.channel], ["Ubicación", zoneName(a.zone)]]));
        item.append(actionGroup(a.id, [["Disponibilidad", () => open("Cambiar disponibilidad", a, () => {
          field("availability", "Disponibilidad", { choices: ["available", "unavailable", "unknown"].map((v) => [v, label(v)]), value: a.availability });
        }, (data) => ({ kind: "availability", fields: { actor_id: a.id, availability: data.get("availability") } }))]]));
        return item;
      }, "Sin personal registrado. Da de alta los equipos y concede sus roles para recibir ofertas.");
      showList("assignments", state.assignments, (a) => {
        const item = card(`${a.incident_id} · ${actorName(a.actor_id)}`, a.status, ["offered", "pending"].includes(a.status) ? "pending" : ["accepted", "en_route"].includes(a.status) ? "accepted" : "");
        item.append(facts([["Asignación / tarea", `${a.id} / ${a.task_id || "—"}`], ["Rol", a.role], ["Destino", zoneName(a.zone)], ["ETA", a.eta_min == null ? "Sin confirmar" : `${a.eta_min} min`], ["Caduca", date(a.expires_at)], ["Versión", a.version]]));
        if (a.communication?.result) item.append(facts([["Resultado de comunicación", a.communication.result]]));
        const names = { accept: "Aceptar", decline: "Rechazar", eta: "ETA", arrive: "Llegada", locate: "Localizar", complete: "Completar" };
        item.append(actionGroup(a.id, assignmentActions(a.status).map((kind) => [names[kind], () => assignmentDialog(a, kind)])));
        return item;
      }, "Sin asignaciones. Las necesidades y la disponibilidad determinan las ofertas.");
      showList("approvals", state.approvals, (a) => {
        const item = card(`${a.id} · incidente ${a.incident_id}`, a.status, grave(a.actions || []) ? "urgent" : "");
        item.append(facts([["Acciones", a.actions], ["Motivo", a.reason], ["Versión", a.version], ["Hash", a.content_hash], ["Caduca", date(a.expires_at)]]));
        if (a.status === "pending") item.append(actionGroup(a.id, [["Revisar y aprobar", () => approvalDialog(a, true)], ["Vetar", () => approvalDialog(a, false)]]));
        return item;
      }, "No hay propuestas que revisar. Las acciones graves siempre requieren aprobación.");
      showList("deliveries", state.deliveries, (d) => {
        const item = card(`${d.channel} · ${d.purpose}`, d.status);
        item.append(facts([["Entrega", d.id], ["Incidente / asignación", `${d.incident_id || "—"} / ${d.assignment_id || "—"}`], ["Intentos", d.attempts], ["Último error", d.last_error || "Sin error comunicado"]]));
        return item;
      }, "Sin entregas registradas.");
      showList("workflows", state.workflows || [], (w) => {
        const item = card(`${w.channel} · ${w.incident_id}`, w.status);
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
    $("refresh").onclick = () => sync.refresh(true);
    const gate = root.SALA_SYNC.snapshotGate();
    sync = root.SALA_SYNC.connect({
      stateURL: "/api/operations/state", streamURL: "/api/operations/stream",
      accept(next) {
        if (!next || !["zones", "incidents", "actors", "assignments", "approvals", "deliveries", "events"].every((key) => Array.isArray(next[key]))) return false;
        if (!gate.accept(next)) return false;
        state = next; render(); return true;
      },
      onStatus(status) {
        $("connection").textContent = { connecting: "Conectando…", live: "En directo · SSE", poll: "Estado por consulta periódica", reconnecting: "Reconectando · consulta periódica activa", offline: "Sin conexión · mostrando último estado", auth: "Acceso de operador caducado" }[status];
        if (status === "auth") {
          message("Identifícate de nuevo como operador y recarga esta página.", true);
          for (const id of ["report-form", "staff-form"]) $(id).querySelector("fieldset").disabled = true;
        }
      },
    });
    root.addEventListener("pagehide", () => { $("staff-address").value = ""; sync.stop(); });
    return { client, render, state: () => state };
  }

  root.MANDO_OPERATIONS = { createClient, decisionFields, assignmentActions, channelEntries, channelStatus, grave, label, mount };
  if (root.document) mount(root.document);
})(typeof window === "undefined" ? globalThis : window);
