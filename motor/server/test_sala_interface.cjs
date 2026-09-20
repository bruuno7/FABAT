"use strict";

const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const test = require("node:test");
const vm = require("node:vm");

const staticDir = path.join(__dirname, "static");
const source = (name) => readFileSync(path.join(staticDir, name), "utf8");
const tick = async () => { for (let i = 0; i < 15; i += 1) await Promise.resolve(); };
const deferred = () => {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
};
const response = (body, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => body });
function context(extra = {}) {
  const scope = vm.createContext({ AbortController, console, setTimeout, clearTimeout, fetch: async () => response({}), ...extra });
  vm.runInContext(source("sala-sync.js"), scope);
  vm.runInContext(source("sala-operativa.js"), scope);
  return scope;
}
function timers() {
  let next = 0;
  const jobs = new Map();
  return {
    later(fn, ms) { const id = ++next; jobs.set(id, { fn, ms }); return id; },
    cancel(id) { jobs.delete(id); },
    async run(ms) {
      const found = [...jobs].find(([, job]) => job.ms === ms);
      assert.ok(found, `Timer ${ms} exists`);
      jobs.delete(found[0]); found[1].fn(); await tick();
    },
    jobs,
  };
}
function transport(accept, fetcher, SourceOverride) {
  const clock = timers(), statuses = [], sources = [];
  class Source {
    constructor(url) { this.url = url; this.listeners = {}; sources.push(this); }
    addEventListener(name, fn) { this.listeners[name] = fn; }
    emit(state) { this.listeners.state({ data: JSON.stringify(state) }); }
    close() { this.closed = true; }
  }
  const c = context();
  const connection = c.SALA_SYNC.connect({
    stateURL: "/api/operations/state", streamURL: "/api/operations/stream",
    accept, fetcher, Source: SourceOverride === undefined ? Source : SourceOverride,
    onStatus: (status) => statuses.push(status), later: clock.later, cancel: clock.cancel,
  });
  return { ...clock, connection, sources, statuses };
}

test("syntax checks cover all changed/new JavaScript", () => {
  for (const file of ["sala-sync.js", "sala.js", "sala-plano.js", "sala-operativa.js"]) {
    const checked = spawnSync(process.execPath, ["--check", path.join(staticDir, file)], { encoding: "utf8" });
    assert.equal(checked.status, 0, checked.stderr);
  }
});

test("snapshot gate prevents revision rollback and retired-session resurrection", () => {
  let resets = 0;
  const gate = context().SALA_SYNC.snapshotGate({ revision: "version", session: (s) => s.session.id, onReset: () => { resets += 1; } });
  const state = (id, version) => ({ session: { id }, version });
  assert.equal(gate.accept(state("one", 9)), true);
  assert.equal(gate.accept(state("one", 8)), false);
  assert.equal(gate.accept(state("one", 9)), true);
  assert.equal(gate.accept(state("two", 0)), true);
  assert.equal(resets, 1);
  assert.equal(gate.accept(state("one", 100)), false);
  assert.equal(gate.accept(state("two", -1)), false);
  assert.equal(gate.accept(state("two", "10")), false);
  assert.equal(gate.current().session.id, "two");
});

test("SSE wins over a delayed bootstrap even across a session reset", async () => {
  const first = deferred(), seen = [];
  const gate = context().SALA_SYNC.snapshotGate({ revision: "version", session: (s) => s.session.id });
  const t = transport((state) => { if (!gate.accept(state)) return false; seen.push(state); return true; }, () => first.promise);
  t.sources[0].emit({ session: { id: "new" }, version: 1 });
  first.resolve(response({ session: { id: "old" }, version: 99 }));
  await tick();
  assert.equal(seen.length, 1);
  assert.equal(seen[0].session.id, "new");
  t.connection.stop();
  assert.equal(t.jobs.size, 0);
});

test("terminal SSE error polls latest state and reconnects within a bounded interval", async () => {
  let revision = 2;
  const gate = context().SALA_SYNC.snapshotGate();
  const t = transport((state) => gate.accept(state), async () => response({ revision: revision++ }));
  await tick();
  t.sources[0].emit({ revision: 10 });
  t.sources[0].readyState = 2;
  t.sources[0].onerror();
  await t.run(2000);
  assert.equal(gate.current().revision, 10);
  await t.run(15000);
  assert.equal(t.sources.length, 2);
  assert.equal(t.sources[0].closed, true);
  t.sources[1].emit({ revision: 11 });
  assert.equal(t.statuses.at(-1), "live");
  assert.equal(t.jobs.size, 0);
  t.connection.stop();
});

test("missing EventSource continues polling; failures back off to at most 15 seconds", async () => {
  let attempts = 0;
  const t = transport(() => true, async () => { attempts += 1; throw new Error("offline"); }, null);
  await tick();
  await t.run(4000);
  await t.run(8000);
  await t.run(15000);
  assert.equal(attempts, 4);
  assert.equal([...t.jobs.values()][0].ms, 15000);
  t.connection.stop();
});

test("operator auth failure closes stream and stops retry loops", async () => {
  const t = transport(() => true, async () => response({}, 403));
  await tick();
  assert.equal(t.statuses.at(-1), "auth");
  assert.equal(t.sources[0].closed, true);
  assert.equal(t.jobs.size, 0);
});

test("explicit refresh waits out an old bootstrap then makes a new read", async () => {
  const old = deferred();
  let calls = 0;
  const t = transport(() => true, () => ++calls === 1 ? old.promise : Promise.resolve(response({ revision: 3 })));
  const fresh = t.connection.refresh(true);
  old.resolve(response({ revision: 1 }));
  await fresh;
  assert.equal(calls, 2);
  t.connection.stop();
});

test("commands capture expected_version and generate fresh IDs without optimistic acceptance", async () => {
  const c = context(), bodies = [], messages = [], refreshes = [];
  let serial = 0;
  const client = c.MANDO_OPERATIONS.createClient({
    uuid: () => `test-${++serial}`,
    fetcher: async (url, options) => { assert.equal(url, "/api/operations/command"); bodies.push(JSON.parse(options.body)); return response({ ok: true, revision: 8 }); },
    refresh: async (fresh) => { refreshes.push(fresh); }, onMessage: (...args) => messages.push(args),
  });
  const assignment = { id: "a1", version: 3, status: "offered" };
  await client.send("accept", { assignment_id: assignment.id }, assignment);
  await client.send("availability", { actor_id: "person", availability: "available" }, { version: 5 });
  assert.deepEqual(bodies.map((b) => [b.command_id, b.expected_version]), [["test-1", 3], ["test-2", 5]]);
  assert.equal(assignment.status, "offered");
  assert.deepEqual(refreshes, [true, true]);
  assert.match(messages[0][0], /no confirma entrega/);
});

test("409 refreshes and explains the conflict with no replay or newer-version substitution", async () => {
  const c = context();
  let posts = 0, refreshes = 0, message = "";
  const client = c.MANDO_OPERATIONS.createClient({
    uuid: () => "conflict-command",
    fetcher: async (_, options) => { posts += 1; assert.equal(JSON.parse(options.body).expected_version, 2); return response({ ok: false, message: "stale" }, 409); },
    refresh: async () => { refreshes += 1; }, onMessage: (m) => { message = m; },
  });
  assert.equal((await client.send("complete", { assignment_id: "a" }, { version: 2 })).error, "conflict");
  assert.equal(posts, 1);
  assert.equal(refreshes, 1);
  assert.match(message, /No se reenvió/);
});

test("network ambiguity never retries a POST; concurrent clicks cannot submit twice", async () => {
  const c = context(), pending = deferred();
  let posts = 0, message = "";
  const client = c.MANDO_OPERATIONS.createClient({
    uuid: () => "only-once", fetcher: () => { posts += 1; return pending.promise; },
    refresh: async () => {}, onMessage: (m) => { message = m; },
  });
  const sent = client.send("report", { text: "test" });
  assert.equal((await client.send("report", { text: "test" })).error, "busy");
  pending.resolve({ json: async () => { throw new Error("unknown result"); }, ok: false, status: 503 });
  await sent;
  assert.equal(posts, 1);
  const uncertain = c.MANDO_OPERATIONS.createClient({
    uuid: () => "no-retry", fetcher: async () => { throw new Error("network"); },
    refresh: async () => {}, onMessage: (m) => { message = m; },
  });
  assert.equal((await uncertain.send("report", { text: "test" })).error, "uncertain");
  assert.match(message, /Puede haberse registrado/);
});

test("grave approval binds exact hash/version and requires explicit confirmation; veto does not", () => {
  const api = context().MANDO_OPERATIONS;
  for (const kind of ["evacuate", "stop_show", "request_external", "set_zone"]) {
    const a = { id: "approval", version: 2, content_hash: "hash-2", actions: [{ kind }] };
    assert.throws(() => api.decisionFields(a, true, false, ""), /Confirma/);
    assert.equal(api.decisionFields(a, true, true, "").content_hash, "hash-2");
    assert.equal(api.decisionFields(a, false, false, "").approved, false);
  }
  assert.equal(api.decisionFields({ id: "non-grave", actions: [{ kind: "offer" }] }, true, false, "").approved, true);
});

test("assignment controls depend only on authoritative operational status, never call status", () => {
  const api = context().MANDO_OPERATIONS;
  assert.deepEqual(Array.from(api.assignmentActions("offered")), ["accept", "decline"]);
  assert.deepEqual(Array.from(api.assignmentActions("accepted")), ["eta", "arrive", "decline"]);
  assert.deepEqual(Array.from(api.assignmentActions("arrived")), ["locate"]);
  assert.deepEqual(Array.from(api.assignmentActions("located")), ["complete"]);
  for (const state of ["completed", "expired", "cancelled", "call_ended", "delivered"]) assert.equal(api.assignmentActions(state).length, 0);
});

const legacy = source("sala.js");
function section(from, to) {
  const start = legacy.indexOf(from), end = legacy.indexOf(to, start);
  assert.ok(start >= 0 && end > start);
  return legacy.slice(start, end);
}
function legacyDecision(result) {
  const calls = [], status = { textContent: "" };
  const scope = vm.createContext({
    S: { session: { id: "session-current" }, approvals: [{ id: "action", kind: "evacuate" }] },
    deciding: new Set(), armed: new Set(), notes: new Map(), signatures: new Map(), sessionEpoch: 0,
    $: () => status, post: async (...args) => { calls.push(args); return result; }, render() {}, setTimeout() {},
  });
  vm.runInContext(section("  const graveAction =", "\n\n  function resetSession"), scope);
  vm.runInContext(section("  async function decide(", "  async function runWhatif("), scope);
  return { scope, calls, status };
}

test("legacy keyboard cannot bypass grave predicate; pending signatures are not marked approved", async () => {
  const { scope, calls, status } = legacyDecision({ ok: true, pending: true, votes: 1, required: 2 });
  await scope.decide("action", true, false);
  assert.equal(calls.length, 0);
  await scope.decide("action", true, false);
  assert.equal(calls.length, 1);
  assert.equal(calls[0][1].session_id, "session-current");
  assert.match(status.textContent, /Firma registrada; esperando segunda persona \(1 de 2\)/);
  assert.doesNotMatch(status.textContent, /Aprobado/);
  assert.match(legacy, /decide\(a\.id, k === "a"\)/);
  const veto = legacyDecision({ ok: true });
  await veto.scope.decide("action", false);
  assert.equal(veto.calls.length, 1);
  assert.equal(veto.calls[0][1].ok, false);
});

test("old-session approval completion cannot repopulate signatures", async () => {
  const { scope } = legacyDecision({ ok: true, pending: true, votes: 1, required: 2 });
  const reply = deferred();
  scope.post = () => reply.promise;
  scope.armed.add("action");
  const request = scope.decide("action", true);
  scope.sessionEpoch += 1;
  reply.resolve({ ok: true, pending: true, votes: 1, required: 2 });
  await request;
  assert.equal(scope.signatures.size, 0);
});

test("holding the approval key cannot count as an explicit second confirmation", () => {
  let handler, approvals = 0;
  const scope = vm.createContext({
    document: { addEventListener: (_, fn) => { handler = fn; } },
    S: { approvals: [{ id: "a" }] }, pick() {}, decide() { approvals += 1; },
  });
  vm.runInContext(section('  document.addEventListener("keydown",', "\n})();"), scope);
  handler({ key: "a", target: { tagName: "BODY" }, repeat: false });
  handler({ key: "a", target: { tagName: "BODY" }, repeat: true });
  assert.equal(approvals, 1);
});

test("session reset clears caches and suppresses delayed session-scoped reads", async () => {
  const element = { value: "", dataset: {}, reset() {}, querySelectorAll: () => [] };
  const scope = vm.createContext({ $: () => element, tgSince: new Map([["old", 1]]), closeAll() {} });
  vm.runInContext(section("  let S =", "  // ---------------------------------------------------------------- utilidades"), scope);
  vm.runInContext('notes.set("old", "note"); armed.add("old"); agentCache.old = {}; chats = ["old"]; whatif = {};', scope);
  const request = deferred();
  scope.pending = request.promise;
  vm.runInContext('scoped(pending, (value) => { chats = value; }); resetSession();', scope);
  request.resolve(["late-old-session"]);
  await tick();
  assert.equal(vm.runInContext("notes.size + armed.size + chats.length + Object.keys(agentCache).length + tgSince.size", scope), 0);
  assert.equal(vm.runInContext("whatif", scope), null);
});

test("history details use scene IDs and render returned timeline and linked records safely", () => {
  const c = context({ window: {} });
  vm.runInContext(source("ui.js"), c);
  c.E = c.window.MANDO_UI.esc;
  c.historyDetail = {
    incident: { id: "incident", escena_id: "scene-2" },
    timeline: [{ minuto: 3, tipo: "arrive", texto: "<img src=x onerror=alert(1)>" }],
    reports: [{ text: "Aviso guardado" }], plans: [{ id: "plan" }], calls: [{ id: "call" }], decisions: [{ id: "decision" }],
  };
  vm.runInContext(section("  function historyDetailHTML()", "  // ---------------------------------------------------------------- recursos"), c);
  const html = c.historyDetailHTML();
  assert.match(html, /scene-2/);
  assert.match(html, /&lt;img/);
  assert.match(html, /Avisos \(1\)/);
  assert.match(html, /Planes \(1\)/);
  assert.match(html, /Llamadas \(1\)/);
  assert.match(html, /Decisiones \(1\)/);
  assert.match(legacy, /data-scene="\$\{E\(h\.escena_id\)\}"/);
  assert.match(legacy, /"\?escena=" \+ encodeURIComponent\(row\.dataset\.scene\)/);
  assert.doesNotMatch(legacy, /Cronología cargada:/);
});

test("stage_2 has non-overlapping geometry and reasoning fallback is separate from voice mode", () => {
  const c = context({ window: {} });
  vm.runInContext(source("sala-plano.js"), c);
  const stage = c.window.SALA_PLANO.ZONES.stage_2;
  assert.ok(stage);
  assert.match(stage.label, /ESCENARIO 2/);
  for (const [id, other] of Object.entries(c.window.SALA_PLANO.ZONES)) if (id !== "stage_2") {
    const overlaps = stage.x < other.x + other.w && stage.x + stage.w > other.x && stage.y < other.y + other.h && stage.y + stage.h > other.y;
    assert.equal(overlaps, false, id);
  }
  assert.match(legacy, /session\.cerebro_cadena \|\| cerebroMode\(\)/);
  assert.match(legacy, /session\.modo_degradado/);
  assert.match(legacy, /LLM local/);
});

test("operational code consumes only its contract endpoints and never browser storage or HTML injection", () => {
  const js = source("sala-operativa.js");
  const endpoints = [...js.matchAll(/["'](\/api\/[^"']+)["']/g)].map((m) => m[1]).sort();
  assert.deepEqual(endpoints, ["/api/operations/command", "/api/operations/state", "/api/operations/stream"]);
  assert.doesNotMatch(js, /localStorage|sessionStorage|innerHTML|insertAdjacentHTML|document\.write|eval\(/);
  assert.match(js, /\$\("staff-address"\)\.value = ""/);
  const html = source("sala-operativa.html");
  assert.match(html, /role="alert"/);
  assert.match(html, /aria-live="polite"/);
  assert.match(html, /name="address" type="password"/);
});

class Element {
  constructor(tag, document) {
    this.tagName = tag.toUpperCase(); this.document = document;
    this.children = []; this.dataset = {}; this.listeners = {};
    this.value = ""; this.disabled = false; this._text = ""; this._id = "";
  }
  set id(value) { this._id = value; this.document.ids.set(value, this); }
  get id() { return this._id; }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(""); }
  set innerHTML(_) { throw new Error("HTML injection sink used"); }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this._text = ""; this.children = children; }
  querySelectorAll(selector) {
    const result = [];
    for (const child of this.children) {
      if (selector === "button" && child.tagName === "BUTTON"
        || selector === "fieldset" && child.tagName === "FIELDSET"
        || selector === "button[type=submit]" && child.tagName === "BUTTON" && child.type === "submit") result.push(child);
      result.push(...child.querySelectorAll(selector));
    }
    return result;
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  addEventListener(name, fn) { this.listeners[name] = fn; }
  focus() { this.document.activeElement = this; }
  showModal() { this.open = true; }
  close() { this.open = false; if (this.listeners.close) this.listeners.close(); }
  reset() { this.didReset = true; }
}

function mockDocument() {
  const document = {
    ids: new Map(), activeElement: null,
    getElementById(id) { return this.ids.get(id); },
    createElement(tag) { return new Element(tag, this); },
  };
  for (const match of source("sala-operativa.html").matchAll(/<([\w-]+)[^>]*\bid="([^"]+)"/g)) {
    const el = document.createElement(match[1]); el.id = match[2];
  }
  for (const id of ["report-form", "staff-form"]) {
    const fieldset = document.createElement("fieldset");
    const button = document.createElement("button"); button.type = "submit";
    fieldset.append(button); document.getElementById(id).append(fieldset);
  }
  document.getElementById("incident-filter").value = "active";
  return document;
}

const snapshot = (revision = 1) => ({
  revision, mode: "operational", server_time: 1789848100,
  zones: [{ id: "stage_2", name: "Escenario 2" }],
  incidents: [
    { id: "i1", version: 2, priority: 9, status: "open", text: "<img src=x onerror=alert(1)>", zone: "stage_2", needs: { medico: 1 }, why_waiting: "Esperando personal", created_at: 1 },
    { id: "i2", version: 1, priority: 7, status: "open", text: "Segundo incidente", zone: null, needs: { policia: 1 }, created_at: 2 },
  ],
  actors: [{ id: "p1", version: 3, name: "Equipo de prueba", roles: ["medico"], channel: "web", availability: "available" }],
  assignments: [{ id: "a1", version: 7, incident_id: "i1", actor_id: "p1", status: "offered", role: "medico", zone: "stage_2", task_id: "t1" }],
  approvals: [{ id: "approval", version: 4, incident_id: "i2", actions: [{ kind: "evacuate", zone: "stage_2" }], status: "pending", content_hash: "hash-v4", reason: "Revisar seguridad" }],
  deliveries: [{ id: "delivery", status: "delivered", purpose: "call_ended", channel: "phone", attempts: 1, assignment_id: "a1" }],
  events: [{ id: "event", kind: "call_result", principal: "phone", summary: "Llamada terminada", occurred_at: 1789848100 }],
  channels: { mode: "simulation", phone: { ready: true, mode: "simulation", missing: [], degraded: [] }, telegram: { ready: false, missing: ["bot"] }, workflows: { sanitario: { ready: false, missing: ["workflow"] } } },
});

function mounted() {
  // El indicador de antigüedad usa reloj real en producto; el DOM de prueba controla sus timers.
  const clock = timers();
  const c = context({ setTimeout: clock.later, clearTimeout: clock.cancel }), document = mockDocument(), requests = [], pageListeners = {};
  let config, result = response({ ok: true }), serial = 0;
  c.crypto = { randomUUID: () => `dom-test-${++serial}` };
  c.fetch = async (url, options) => { requests.push({ url, body: JSON.parse(options.body) }); return result; };
  c.addEventListener = (name, fn) => { pageListeners[name] = fn; };
  c.FormData = class {
    constructor(form) { this.values = form.values || {}; }
    get(key) { const value = this.values[key]; return Array.isArray(value) ? value[0] : value || null; }
    getAll(key) { const value = this.values[key]; return Array.isArray(value) ? value : value ? [value] : []; }
    has(key) { return key in this.values; }
  };
  c.SALA_SYNC.connect = (options) => { config = options; options.onStatus("connecting"); return { refresh: async () => true, stop() {} }; };
  const app = c.MANDO_OPERATIONS.mount(document);
  const $ = (id) => document.getElementById(id);
  return {
    c, $, app, requests, pageListeners, document,
    state: (s) => config.accept(s), result: (r) => { result = r; },
    click: (id, text) => {
      const b = $(id).querySelectorAll("button").find((e) => e.textContent === text);
      assert.ok(b, `Button ${text} in ${id}`); b.onclick();
    },
    submit: async (id, values = {}) => { $(id).values = values; await $(id).onsubmit({ preventDefault() {}, currentTarget: $(id) }); },
  };
}

test("DOM mocks render simultaneous incidents, literal public text, missing channels and pending assignments", () => {
  const ui = mounted();
  assert.equal(ui.state(snapshot()), true);
  assert.equal(ui.$("incidents").children.length, 2);
  assert.match(ui.$("incidents").textContent, /<img src=x onerror=alert\(1\)>/);
  assert.equal(ui.$("incidents").children[0].children.some((child) => child.tagName === "IMG"), false);
  assert.match(ui.$("assignments").textContent, /Oferta pendiente/);
  assert.doesNotMatch(ui.$("assignments").textContent, /Aceptada explícitamente/);
  assert.match(ui.$("mode").textContent, /SIMULACIÓN/);
  assert.match(ui.$("channels").textContent, /Falta configuración/);
  assert.match(ui.$("channels").textContent, /Workflow · sanitario/);
  assert.equal(ui.c.MANDO_OPERATIONS.channelStatus({ ready: true, degraded: [], missing: [] }), "ready");
  assert.equal(ui.c.MANDO_OPERATIONS.channelStatus({ ready: true, degraded: ["provider timeout"] }), "degraded");
  assert.equal(ui.state(snapshot(0)), false);
  assert.equal(ui.state(null), false);
});

test("action dialog preserves reviewed version across SSE updates and requires reopening after 409", async () => {
  const ui = mounted();
  ui.state(snapshot());
  ui.click("assignments", "Aceptar");
  const newer = snapshot(2); newer.assignments[0].version = 8;
  ui.state(newer);
  ui.result(response({ ok: false }, 409));
  await ui.submit("command-form");
  assert.equal(ui.requests.length, 1);
  assert.equal(ui.requests[0].body.expected_version, 7);
  assert.equal(ui.$("command-submit").disabled, true);
  assert.match(ui.$("command-error").textContent, /Conflicto de versión/);
  ui.$("command-cancel").onclick();
  ui.click("assignments", "Aceptar");
  ui.result(response({ ok: true }));
  await ui.submit("command-form");
  assert.equal(ui.requests[1].body.expected_version, 8);
  assert.notEqual(ui.requests[0].body.command_id, ui.requests[1].body.command_id);
  assert.match(ui.$("assignments").textContent, /Oferta pendiente/);
  const accepted = snapshot(3); accepted.assignments[0].status = "accepted";
  ui.state(accepted);
  assert.match(ui.$("assignments").textContent, /Aceptada explícitamente/);
});

test("DOM grave confirmation cannot submit without checkbox; ETA carries exact destination", async () => {
  const ui = mounted();
  const current = snapshot(); current.assignments[0].status = "accepted";
  ui.state(current);
  ui.click("approvals", "Revisar y aprobar");
  await ui.submit("command-form");
  assert.equal(ui.requests.length, 0);
  assert.match(ui.$("command-error").textContent, /Confirma expresamente/);
  await ui.submit("command-form", { confirmed: "on", note: "Verificado" });
  assert.equal(ui.requests[0].body.content_hash, "hash-v4");
  assert.equal(ui.requests[0].body.expected_version, 4);
  ui.click("assignments", "ETA");
  await ui.submit("command-form", { eta_min: "12", destination_confirmed: "on" });
  assert.equal(ui.requests[1].body.eta_min, 12);
  assert.equal(ui.requests[1].body.destination_zone_id, "stage_2");
  assert.equal(ui.requests[1].body.destination_confirmed, true);
});

test("registration sends operator roles and contact only in POST then clears the input", async () => {
  const ui = mounted();
  ui.state(snapshot());
  ui.$("staff-address").value = "test-contact-not-a-real-number";
  await ui.submit("staff-form", { actor_id: "test-person", name: "Prueba", roles: ["medico"], channel: "telegram", address: "test-contact-not-a-real-number", availability: "unknown" });
  assert.deepEqual(ui.requests[0].body.roles, ["medico"]);
  assert.equal(ui.requests[0].body.address, "test-contact-not-a-real-number");
  assert.equal(ui.$("staff-address").value, "");
  assert.equal(ui.$("staff-form").didReset, true);
  assert.doesNotMatch(ui.$("actors").textContent, /test-contact-not-a-real-number/);
  ui.$("staff-address").value = "not-sent";
  ui.pageListeners.pagehide();
  assert.equal(ui.$("staff-address").value, "");
});
