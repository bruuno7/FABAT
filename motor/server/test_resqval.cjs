"use strict";

// Pruebas locales de proyección y controles. El DOM es un mock, no un navegador.
const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { spawnSync } = require("node:child_process");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const source = (file) => readFileSync(path.join(__dirname, "static", file), "utf8");
const html = source("sala-operativa.html");
const tick = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };
const response = (body, status = 200) => ({ status, ok: status >= 200 && status < 300, json: async () => body });
function clock() {
  let serial = 0;
  const jobs = new Map();
  return { jobs, later(fn, ms) { const id = ++serial; jobs.set(id, { fn, ms }); return id; },
    cancel(id) { jobs.delete(id); },
    async run(ms) { const job = [...jobs].find(([, job]) => job.ms === ms); assert.ok(job, `Timer ${ms}`); jobs.delete(job[0]); job[1].fn(); await tick(); } };
}
class Element {
  constructor(tag, document) { this.tagName = tag.toUpperCase(); this.document = document; this.children = []; this.attrs = {}; this.dataset = {}; this.listeners = {}; this.value = ""; this._text = ""; }
  set id(value) { this.attrs.id = value; this.document.ids.set(value, this); }
  get id() { return this.attrs.id; }
  setAttribute(key, value) { this.attrs[key] = String(value); }
  getAttribute(key) { return this.attrs[key] ?? null; }
  removeAttribute(key) { delete this.attrs[key]; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; this._text = ""; }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map((child) => child.textContent).join(""); }
  set innerHTML(_) { throw new Error("Unsafe HTML sink"); }
  querySelectorAll(selector) {
    const [tag, type] = selector.replace("]", "").split("[type=");
    return this.children.flatMap((child) => [...(child.tagName === tag.toUpperCase() && (!type || child.type === type) ? [child] : []), ...child.querySelectorAll(selector)]);
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  addEventListener(event, fn) { this.listeners[event] = fn; }
  focus() { this.document.activeElement = this; }
  showModal() { this.open = true; }
  close() { this.open = false; this.listeners.close?.(); }
  reset() { this.didReset = true; }
}
function documentMock() {
  const document = { ids: new Map(), activeElement: null,
    createElement(tag) { return new Element(tag, this); }, createElementNS(_, tag) { return this.createElement(tag); },
    getElementById(id) { return this.ids.get(id); } };
  for (const match of html.matchAll(/<([\w-]+)[^>]*\bid="([^"]+)"/g)) document.createElement(match[1]).id = match[2];
  for (const id of ["report-form", "staff-form"]) {
    const fieldset = document.createElement("fieldset"), button = document.createElement("button");
    button.type = "submit"; fieldset.append(button); document.getElementById(id).append(fieldset);
  }
  const nav = document.getElementById("navigation");
  for (const match of html.match(/<nav[\s\S]*?<\/nav>/)[0].matchAll(/href="(#.+?)"/g)) {
    const a = document.createElement("a"); a.setAttribute("href", match[1]); nav.append(a);
  }
  document.getElementById("incident-filter").value = "active";
  return document;
}
function context(extra = {}) {
  const timers = clock();
  const c = vm.createContext({ AbortController, console, setTimeout: timers.later, clearTimeout: timers.cancel, fetch: async () => { throw new Error("No external HTTP in UI tests"); }, ...extra });
  c.window = c;
  for (const file of ["sala-sync.js", "sala-plano.js", "resqval-plano.js", "sala-operativa.js"]) vm.runInContext(source(file), c);
  return { c, timers };
}
function mount() {
  const { c, timers } = context(), document = documentMock(), requests = [], listeners = {};
  let transport, result = response({ ok: true }), serial = 0, now = 2000000;
  class TestDate extends Date { static now() { return now; } }
  c.Date = TestDate;
  c.crypto = { randomUUID: () => `synthetic-command-${++serial}` };
  c.addEventListener = (event, fn) => { listeners[event] = fn; };
  c.fetch = async (url, options) => { requests.push({ url, options, body: JSON.parse(options.body) }); return result; };
  c.FormData = class {
    constructor(form) { this.values = form.values || {}; }
    get(name) { return this.values[name] ?? null; }
    getAll(name) { const value = this.values[name]; return Array.isArray(value) ? value : value ? [value] : []; }
    has(name) { return Object.hasOwn(this.values, name); }
  };
  c.SALA_SYNC.connect = (config) => { transport = config; config.onStatus("connecting"); return { refresh: async () => true, stop() {} }; };
  const app = c.MANDO_OPERATIONS.mount(document), $ = (id) => document.getElementById(id);
  return { c, app, $, document, timers, requests,
    state: (state) => transport.accept(state), status: (status) => transport.onStatus(status),
    advance(ms) { now += ms; }, result(value) { result = value; }, stop: () => listeners.pagehide(),
    click(id, title) { const button = $(id).querySelectorAll("button").find((b) => b.textContent === title); assert.ok(button, title); button.onclick(); },
    async submit(id, values = {}) { $(id).values = values; await $(id).onsubmit({ preventDefault() {}, currentTarget: $(id) }); },
  };
}
function snapshot(revision = 1) {
  return { revision, server_time: 2000, mode: "operational",
    zones: [{ id: "stage_2", name: "Escenario 2" }, { id: "gate_a", name: "Puerta A" }],
    incidents: [
      { id: "victim-a", version: 2, text: "Aviso sintético idéntico", zone: "stage_2", status: "waiting", priority: 9, needs: { medico: 1 }, why_waiting: "Falta personal", created_at: 1 },
      { id: "victim-b", version: 3, text: "Aviso sintético idéntico", zone: "stage_2", status: "open", priority: 7, needs: { medico: 1 }, created_at: 2 },
    ],
    actors: [{ id: "unit-a", version: 2, name: "Equipo sintético", availability: "available", roles: ["medico"], channel: "web", zone: "gate_a" }],
    assignments: [{ id: "task-a", version: 4, actor_id: "unit-a", incident_id: "victim-a", zone: "stage_2", role: "medico", status: "offered", expires_at: 2120 }],
    approvals: [{ id: "approval-a", version: 2, incident_id: "victim-b", status: "pending", content_hash: "synthetic-hash", actions: [{ kind: "stop_show", zone: "stage_2" }], reason: "Revisar riesgo", expires_at: 2060 }],
    deliveries: [{ id: "delivery-a", channel: "phone", status: "delivered", purpose: "offer", assignment_id: "task-a", attempts: 1 }],
    events: [{ id: "event-a", kind: "assignment.offered", principal: "system", summary: "Reserva registrada", incident_id: "victim-a", assignment_id: "task-a", occurred_at: 1990 }],
    workflows: [], channels: { mode: "simulation" } };
}

test("ResQval shell has local assets, semantic table, real anchor destinations and POST logout", () => {
  assert.match(html, /ResQval <b>Ops/);
  assert.match(html, /<form action="\/salir" method="post">/);
  assert.match(html, /<table>.*<caption[\s\S]*<tbody id="incidents">/);
  assert.doesNotMatch(html, /https?:\/\/|tailwind|onclick=|14 U|112|SLA|pausar/i);
  const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map((match) => match[1]);
  assert.equal(new Set(ids).size, ids.length, "unique IDs");
  for (const match of html.matchAll(/href="#([^"]+)"/g)) assert.ok(ids.includes(match[1]), match[1]);
  for (const match of html.matchAll(/(?:src|href)="\/static\/([^"]+)"/g)) assert.ok(source(match[1]).length);
  const css = source("sala-operativa.css");
  assert.match(css, /--nav: #0d192e/);
  assert.match(css, /@media \(max-width: 700px\)/);
  assert.match(css, /:focus-visible/);
  for (const file of ["sala-sync.js", "sala-operativa.js", "resqval-plano.js"]) {
    assert.equal(spawnSync(process.execPath, ["--check", path.join(__dirname, "static", file)]).status, 0);
    assert.doesNotMatch(source(file), /innerHTML|insertAdjacentHTML|localStorage|sessionStorage/);
  }
});

test("snapshot KPIs preserve distinct victims and count reserved resources despite available declaration", () => {
  const ui = mount();
  ui.state(snapshot());
  assert.equal(ui.$("kpi-active").textContent, "2");
  assert.equal(ui.$("incidents").children.length, 2);
  assert.equal(ui.$("kpi-free").textContent, "0");
  assert.equal(ui.$("kpi-busy").textContent, "1");
  assert.match(ui.$("actors").textContent, /Reservado.*Disponibilidad declaradaDisponible/);
  assert.match(ui.$("actors").textContent, /Ubicación declaradaPuerta A/);
  assert.match(ui.$("actors").textContent, /destino Escenario 2/);
  for (const status of ["accepted", "en_route", "arrived", "located"]) {
    const next = snapshot(2); next.assignments[0].status = status; ui.state(next);
    assert.equal(ui.$("kpi-free").textContent, "0", status);
    assert.equal(ui.$("kpi-busy").textContent, "1", status);
  }
  const completed = snapshot(3); completed.assignments[0].status = "completed"; ui.state(completed);
  assert.equal(ui.$("kpi-free").textContent, "1");
  assert.equal(ui.$("kpi-busy").textContent, "0");
  assert.match(ui.$("actors").textContent, /Libre/);
});

test("missing values stay unknown; empty snapshot reports zero rather than prototype metrics", () => {
  const ui = mount(), state = snapshot();
  state.incidents[0].priority = null;
  state.actors[0].availability = "unknown";
  state.channels = {};
  ui.state(state);
  assert.match(ui.$("incidents").textContent, /Desconocida/);
  assert.match(ui.$("kpi-critical").textContent, /1 sin prioridad/);
  assert.match(ui.$("mode").textContent, /no confirmado/);
  assert.match(ui.$("kpi-resources").textContent, /1 con disponibilidad sin confirmar/);
  for (const key of ["incidents", "actors", "assignments", "approvals", "deliveries", "events"]) state[key] = [];
  state.revision++; ui.state(state);
  for (const id of ["active", "free", "busy", "approvals"]) assert.equal(ui.$("kpi-" + id).textContent, "0");
  assert.equal(ui.$("incidents").children[0].tagName, "TR");
  assert.equal(ui.$("incidents").children[0].children[0].colSpan, 4);
});

test("map reuses existing geometry and never places unknown zones or duplicates actors at destinations", () => {
  const ui = mount(), state = snapshot();
  state.zones.push({ id: "custom", name: "Zona sin geometría" });
  state.incidents.push({ id: "unknown", zone: "custom", status: "open" });
  state.actors.push({ id: "unlocated", availability: "unknown" });
  ui.state(state);
  const model = ui.c.RESQVAL_PLANO.project(state, ui.c.SALA_PLANO.ZONES);
  assert.equal(model.zones.length, 2);
  assert.equal(model.zones.find((z) => z.id === "stage_2").incidents, 2);
  assert.equal(model.zones.find((z) => z.id === "stage_2").actors, 0);
  assert.equal(model.zones.find((z) => z.id === "gate_a").actors, 1);
  assert.equal(model.unknownIncidents, 1); assert.equal(model.unknownActors, 1);
  const rectangles = ui.$("venue-map").querySelectorAll("rect");
  const stage = ui.c.SALA_PLANO.ZONES.stage_2;
  assert.ok(rectangles.some((rect) => rect.getAttribute("x") === String(stage.x) && rect.getAttribute("width") === String(stage.w)));
  assert.doesNotMatch(ui.$("venue-map").textContent, /Zona sin geometría|CAMPAMENTO|GPS real/);
  state.zones[0].name = "<script>not executable</script>"; state.revision++; ui.state(state);
  assert.match(ui.$("venue-map").textContent, /<script>not executable<\/script>/);
  assert.equal(ui.$("venue-map").querySelectorAll("script").length, 0);
});

test("search and zone/status filters only project data; they do not change overall KPI or snapshot", () => {
  const ui = mount(), state = snapshot();
  state.incidents[1].zone = null; ui.state(state);
  const original = JSON.stringify(state);
  ui.$("incident-search").value = "sintetico"; ui.$("incident-search").oninput();
  assert.equal(ui.$("incidents").children.length, 2, "accent insensitive");
  assert.match(ui.$("actors").textContent, /Equipo sintético/);
  ui.$("zone-filter").value = "unknown"; ui.$("zone-filter").onchange();
  assert.match(ui.$("incidents").textContent, /victim-b/);
  assert.doesNotMatch(ui.$("incidents").textContent, /victim-a/);
  ui.$("incident-filter").value = "closed"; ui.$("incident-filter").onchange();
  assert.match(ui.$("incidents").textContent, /Sin incidentes/);
  assert.equal(ui.$("kpi-active").textContent, "2");
  assert.equal(JSON.stringify(state), original);
});

test("navigation moves focus to a real section; detail renders latest trace and literal hostile text", () => {
  const ui = mount(), state = snapshot();
  state.incidents[0].text = "<img src=x onerror=unsafe()>"; ui.state(state);
  const link = ui.$("navigation").children.find((a) => a.getAttribute("href") === "#personal");
  link.onclick(); assert.equal(ui.document.activeElement, ui.$("personal")); assert.equal(link.getAttribute("aria-current"), "location");
  ui.click("incidents", "Ver detalle");
  assert.equal(ui.$("incident-dialog").open, true);
  assert.match(ui.$("incident-detail").textContent, /<img src=x onerror=unsafe\(\)>/);
  assert.match(ui.$("incident-detail").textContent, /Reserva registrada/);
  assert.equal(ui.$("incident-detail").querySelectorAll("img").length, 0);
  state.revision++; state.events[0].summary = "Replanificación verificada"; ui.state(state);
  assert.match(ui.$("incident-detail").textContent, /Replanificación verificada/);
  ui.$("incident-close").onclick(); assert.equal(ui.$("incident-dialog").open, false);
});

test("SSE preserves form selection, draft, focus and reviewed version while refreshing resource occupation", async () => {
  const ui = mount(); ui.state(snapshot());
  ui.$("report-zone").value = "gate_a"; ui.$("report-text").value = "Borrador sintético";
  ui.click("incidents", "Actualizar");
  const input = ui.$("command-text"); input.value = "Rectificación en curso"; input.focus();
  const next = snapshot(2); next.incidents[0].version = 9; next.zones.push({ id: "general", name: "Pista" }); next.assignments[0].status = "arrived";
  ui.state(next);
  assert.equal(ui.$("command-text"), input);
  assert.equal(input.value, "Rectificación en curso");
  assert.equal(ui.document.activeElement, input);
  assert.equal(ui.$("report-zone").value, "gate_a");
  assert.equal(ui.$("report-text").value, "Borrador sintético");
  assert.match(ui.$("actors").textContent, /Ocupado \/ atendiendo/);
  ui.result(response({ ok: false }, 409));
  await ui.submit("command-form", { text: input.value, zone: "stage_2", confirmed: "on" });
  assert.equal(ui.requests[0].body.expected_version, 2);
  assert.equal(ui.requests[0].body.confirmed, true);
  assert.equal(ui.requests.length, 1);
  assert.equal(ui.$("command-submit").disabled, true);
  assert.match(ui.$("error").textContent, /^Conflicto de versión/);
  ui.result(response({ ok: false, error: "address_already_registered", message: "address_already_registered" }, 409));
  await ui.submit("staff-form", { actor_id: "medico-2", name: "M2", channel: "phone", address: "+34600000001", zone: "gate_a", availability: "available", roles: "medic" });
  assert.match(ui.$("error").textContent, /contacto ya está registrado.*No se reenvió/);
  assert.equal(ui.requests.length, 2);
});

test("command forms keep lifecycle transitions and same-origin credentials, never optimistic completion", async () => {
  const ui = mount();
  const cases = [
    ["offered", "Aceptar", "accept", {}], ["offered", "Rechazar", "decline", { reason: "No disponible" }],
    ["accepted", "ETA", "eta", { eta_min: "0", destination_confirmed: "on" }],
    ["en_route", "Llegada", "arrive", {}], ["arrived", "Localizar", "locate", {}], ["located", "Completar", "complete", {}],
  ];
  for (const [index, [status, title, kind, fields]] of cases.entries()) {
    const state = snapshot(index + 1); state.assignments[0].status = status; state.assignments[0].version = index + 10;
    ui.state(state); ui.click("assignments", title); await ui.submit("command-form", fields);
    const sent = ui.requests.at(-1);
    assert.equal(sent.body.kind, kind); assert.equal(sent.body.expected_version, index + 10);
    assert.equal(sent.options.credentials, "same-origin");
    assert.equal(ui.app.state().assignments[0].status, status, "await authoritative snapshot");
    if (kind === "eta") { assert.equal(sent.body.eta_min, 0); assert.equal(sent.body.destination_zone_id, "stage_2"); }
  }
  assert.equal(new Set(ui.requests.map((request) => request.body.command_id)).size, cases.length);
});

test("report, manual offer, availability and proposal controls retain the operational contract", async () => {
  const ui = mount(), state = snapshot();
  state.actors.push({ id: "free-unit", name: "Equipo libre", roles: ["medico"], availability: "available", version: 1 }); ui.state(state);
  await ui.submit("report-form", { text: "Aviso nuevo sintético", zone: "gate_a" });
  assert.equal(ui.requests.at(-1).body.kind, "report");
  ui.click("incidents", "Ofrecer tarea");
  assert.deepEqual(ui.$("command-actor_id").children.map((o) => o.value), ["free-unit"], "reserved actor is not offered again");
  await ui.submit("command-form", { actor_id: "free-unit", role: "medico" });
  assert.equal(ui.requests.at(-1).body.kind, "offer");
  ui.click("actors", "Disponibilidad"); await ui.submit("command-form", { availability: "unavailable" });
  assert.equal(ui.requests.at(-1).body.kind, "availability");
  assert.equal(ui.requests.at(-1).body.expected_version, 2);
  ui.click("incidents", "Proponer acción"); await ui.submit("command-form", { action: "stop_show", zone: "stage_2", reason: "Riesgo sintético" });
  assert.equal(ui.requests.at(-1).body.kind, "propose"); assert.equal(ui.requests.at(-1).body.requiere_persona, true);
  assert.equal(ui.requests.at(-1).body.actions[0].kind, "stop_show");
});

test("approval expiration is checked again at submit; veto keeps exact hash without grave confirmation", async () => {
  const ui = mount(); ui.state(snapshot());
  ui.click("approvals", "Revisar y aprobar"); ui.advance(61000);
  await ui.submit("command-form", { confirmed: "on" });
  assert.equal(ui.requests.length, 0); assert.match(ui.$("command-error").textContent, /caducado/);
  ui.$("command-cancel").onclick();
  const state = snapshot(2); state.server_time += 61; state.approvals[0].expires_at += 120; ui.state(state);
  ui.click("approvals", "Vetar"); await ui.submit("command-form", { note: "Revisión sintética" });
  assert.equal(ui.requests[0].body.approved, false); assert.equal(ui.requests[0].body.content_hash, "synthetic-hash");
  assert.equal(ui.requests[0].body.expected_version, 2);
});

test("terminal task followup requires human confirmation and uses the captured assignment version", async () => {
  const ui = mount(), state = snapshot(); state.assignments[0].status = "expired"; ui.state(state);
  ui.click("assignments", "Confirmar seguimiento");
  await ui.submit("command-form", { reason: "Personal localizado" }); assert.equal(ui.requests.length, 0);
  await ui.submit("command-form", { reason: "Personal localizado", confirmed: "on" });
  assert.equal(ui.requests[0].body.kind, "followup"); assert.equal(ui.requests[0].body.expected_version, 4);
  assert.equal(ui.app.state().assignments[0].status, "expired");
});

test("auth expiry blocks form mutations; freshness is visible and pagehide clears private contact and timers", async () => {
  const ui = mount(); ui.state(snapshot());
  ui.advance(8000); await ui.timers.run(1000);
  assert.match(ui.$("freshness").textContent, /8 s/);
  ui.status("auth");
  await ui.submit("report-form", { text: "No debe enviarse" }); assert.equal(ui.requests.length, 0);
  assert.equal(ui.$("report-form").querySelector("fieldset").disabled, true);
  ui.$("staff-address").value = "private-synthetic-contact"; ui.stop();
  assert.equal(ui.$("staff-address").value, ""); assert.equal(ui.timers.jobs.size, 0);
});

function connection(fetcher) {
  const { c, timers } = context(), sources = [], statuses = [], received = [];
  class Source {
    constructor() { sources.push(this); }
    addEventListener(_, listener) { this.receive = listener; }
    emit(revision) { this.receive({ data: JSON.stringify({ revision }) }); }
    close() { this.closed = true; }
  }
  const gate = c.SALA_SYNC.snapshotGate();
  const sync = c.SALA_SYNC.connect({ stateURL: "/api/operations/state", streamURL: "/api/operations/stream", Source, fetcher,
    later: timers.later, cancel: timers.cancel, staleAfter: 30000,
    accept(state) { if (!gate.accept(state)) return false; received.push(state.revision); return true; }, onStatus: (status) => statuses.push(status) });
  return { timers, sources, statuses, received, sync };
}

test("silent SSE gets bounded health verification, no continuous duplicate poll loop, and recovers without revision rollback", async () => {
  let requests = 0;
  const t = connection(async (_, options) => { requests++; assert.equal(options.credentials, "same-origin"); return response({ revision: 3 }); });
  await tick(); t.sources[0].emit(3);
  assert.equal(t.timers.jobs.size, 1);
  await t.timers.run(30000);
  assert.equal(requests, 2); assert.ok(t.statuses.includes("stale")); assert.equal(t.statuses.at(-1), "live");
  assert.equal(t.timers.jobs.size, 1);
  t.sources[0].emit(2); assert.equal(t.received.at(-1), 3);
  t.sync.stop(); assert.equal(t.timers.jobs.size, 0);
});

test("failed SSE health verification falls back to polling and recovers; auth failure stops all loops", async () => {
  let failed = false, auth = false;
  const t = connection(async () => { if (failed) throw new Error("offline"); return response({ revision: 4 }, auth ? 401 : 200); });
  await tick(); t.sources[0].emit(4); failed = true;
  await t.timers.run(30000); assert.equal(t.statuses.at(-1), "offline");
  failed = false; await t.timers.run(4000); assert.equal(t.statuses.at(-1), "poll");
  t.sources[0].emit(5); auth = true;
  await t.timers.run(30000); assert.equal(t.statuses.at(-1), "auth");
  assert.equal(t.timers.jobs.size, 0); assert.equal(t.sources[0].closed, true);
});

test("backend down: SSE reconnect errors keep the stable offline indicator until state is readable again", async () => {
  let down = false;
  const t = connection(async () => { if (down) throw new Error("offline"); return response({ revision: 6 }); });
  await tick(); t.sources[0].emit(6); down = true;
  await t.timers.run(30000); assert.equal(t.statuses.at(-1), "offline");
  const next = () => t.timers.run([...t.timers.jobs.values()][0].ms);
  for (let i = 0; i < 6; i++) { await next(); if (t.sources.at(-1).receive) t.sources.at(-1).onerror(); assert.equal(t.statuses.at(-1), "offline"); }
  assert.ok(!t.statuses.slice(t.statuses.indexOf("offline")).includes("reconnecting"));
  down = false; for (let i = 0; i < 3 && t.statuses.at(-1) !== "poll"; i++) await next();
  assert.equal(t.statuses.at(-1), "poll");
  t.sources.at(-1).onerror(); assert.equal(t.statuses.at(-1), "reconnecting");
  t.sync.stop();
});

test("a late failed bootstrap cannot downgrade a newer healthy SSE snapshot", async () => {
  let reject;
  const pending = new Promise((_, fail) => { reject = fail; });
  const t = connection(() => pending);
  t.sources[0].emit(8); reject(new Error("late bootstrap failure")); await tick();
  assert.equal(t.statuses.at(-1), "live"); assert.deepEqual(t.received, [8]);
  t.sync.stop();
});
