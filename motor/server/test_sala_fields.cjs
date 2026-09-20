"use strict";

const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = readFileSync(path.join(__dirname, "static/sala-operativa.js"), "utf8");
const start = source.indexOf("    function field(");
const end = source.indexOf("    const zones =", start);
assert.ok(start >= 0 && end > start);

function element(tag) {
  const value = { tag, children: [], append(...children) { this.children.push(...children); } };
  if (tag === "textarea" || tag === "select") {
    Object.defineProperty(value, "type", { get: () => tag === "textarea" ? "textarea" : "select-one" });
  }
  return value;
}

function fields() {
  const container = element("fieldset");
  const context = vm.createContext({ node: element, $: () => container });
  vm.runInContext('"use strict";\n' + source.slice(start, end), context);
  return { field: context.field, container };
}

test("multiline proposal, update and approval fields preserve the readonly DOM type", () => {
  for (const name of ["reason", "text", "note"]) {
    const { field, container } = fields();
    const input = field(name, name, { multiline: true, value: "Revisión operativa" });
    assert.equal(input.type, "textarea");
    assert.equal(input.value, "Revisión operativa");
    assert.equal(input.rows, 3);
    assert.equal(input.required, true);
    assert.equal(container.children[0].children[0], input);
  }
});

test("select fields preserve readonly DOM type and current selection", () => {
  const input = fields().field("zone", "Zona", { choices: [["gate_a", "Puerta A"]], value: "gate_a" });
  assert.equal(input.type, "select-one");
  assert.equal(input.children[0].value, "gate_a");
  assert.equal(input.value, "gate_a");
});

test("editable input types retain explicit confirmation and ETA validation", () => {
  assert.equal(fields().field("confirmed", "Confirmar", { checkbox: true }).type, "checkbox");
  const eta = fields().field("eta", "Minutos", { number: true });
  assert.equal(eta.type, "number");
  assert.equal(eta.min, "0");
  assert.equal(eta.max, "240");
  assert.equal(fields().field("note", "Nota", { required: false }).required, false);
});
