import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";
import {
  ContractError,
  EVENT_TYPES,
  parseCommit,
  parseEvent,
  parseSnapshotRequest,
  unwrapEvent,
} from "./event-contract.js";

export const eventFixture = {
  schema_version: 2,
  event_id: "tg-update-42",
  event_type: "assignment.accepted",
  occurred_at: "2026-09-19T14:00:00Z",
  received_at: "2026-09-19T14:00:01Z",
  channel: "telegram",
  actor_id: "worker-1",
  conversation_id: "conversation-1",
  incident_id: "incident-1",
  assignment_id: "assignment-1",
  correlation_id: "trace-1",
  source_message_id: "42",
  payload: { eta_min: 5 },
};

export const commitFixture = {
  event_id: "tg-update-42",
  expected: { "incident/incident-1": 2, "actor/worker-1": 0 },
  writes: [
    { entity: "incident/incident-1", value: { status: "open", assignment_id: "assignment-1" } },
    { entity: "actor/worker-1", value: { active_assignment_id: "assignment-1" } },
  ],
  messages: [{
    id: "delivery-1",
    recipient_id: "reporter-1",
    channel: "telegram",
    incident_id: "incident-1",
    purpose: "status",
    text: "El equipo ha aceptado. ETA estimada: 5 minutos.",
  }],
};

describe("multichannel event contract", () => {
  it("keeps the versioned schema and runtime vocabulary aligned", () => {
    const schema = JSON.parse(readFileSync(new URL("../../../motor/happyrobot/event_contract.json", import.meta.url), "utf8"));
    assert.deepEqual(schema.properties.event_type.enum, [...EVENT_TYPES]);
    assert.equal(schema.properties.schema_version.const, 2);
  });

  it("preserves typed data through webhook and workflow inputs", () => {
    assert.deepEqual(unwrapEvent({ data: eventFixture }), parseEvent(eventFixture));
    assert.deepEqual(unwrapEvent(eventFixture).payload, { eta_min: 5 });
    const phone = parseEvent({ ...eventFixture, channel: "phone", event_id: "call-result-42" });
    assert.equal(phone.assignment_id, eventFixture.assignment_id);
  });

  it("rejects conflicting envelopes rather than concatenating their fields", () => {
    assert.throws(() => unwrapEvent({ ...eventFixture, data: eventFixture }), ContractError);
  });

  it("requires references for explicit transitions and distinguishes call end", () => {
    assert.throws(() => parseEvent({ ...eventFixture, assignment_id: undefined }), ContractError);
    assert.throws(() => parseEvent({ ...eventFixture, event_type: "question.answered" }), ContractError);
    assert.equal(parseEvent({ ...eventFixture, event_type: "call.ended", call_id: "call-1" }).event_type, "call.ended");
    assert.throws(() => parseEvent({ ...eventFixture, event_type: "call.ended" }), ContractError);
  });

  it("rejects invented types, invalid dates, namespaces and privileged envelope fields", () => {
    for (const patch of [
      { event_type: "redis.eval" }, { channel: "unknown" }, { actor_id: "../other" },
      { event_id: "{live}:incident" }, { occurred_at: "yesterday" },
      { occurred_at: "2026-99-19T14:00:00Z" }, { role: "organizador" },
      { namespace: "live" }, { callback_url: "https://example.invalid" },
    ]) assert.throws(() => parseEvent({ ...eventFixture, ...patch }), ContractError);
  });

  it("requires a read version for every write and validates message destinations", () => {
    assert.deepEqual(parseCommit(commitFixture), commitFixture);
    assert.throws(() => parseCommit({ ...commitFixture, expected: {} }), ContractError);
    assert.throws(() => parseCommit({ ...commitFixture, writes: [...commitFixture.writes, commitFixture.writes[0]] }), ContractError);
    assert.throws(() => parseCommit({ ...commitFixture, messages: [{ ...commitFixture.messages[0], to_number: "+10000000000" }] }), ContractError);
    assert.throws(() => parseCommit({ ...commitFixture, messages: [{ ...commitFixture.messages[0], channel: "phone", purpose: "call" }] }), ContractError);
  });

  it("accepts only allowlisted entities and bounded JSON objects", () => {
    assert.deepEqual(parseSnapshotRequest({ entities: ["incident/incident-1", "question/question-1"] }), ["incident/incident-1", "question/question-1"]);
    for (const entity of ["fa:seats", "secret/key", "actor/a/extra", "actor/{live}"]) {
      assert.throws(() => parseSnapshotRequest({ entities: [entity] }), ContractError);
    }
    assert.throws(() => parseCommit({ ...commitFixture, writes: [{ entity: "actor/worker-1", value: "not-an-object" }] }), ContractError);
    const malicious = JSON.parse('{"__proto__":{"role":"organizador"}}');
    assert.throws(() => parseEvent({ ...eventFixture, payload: malicious }), ContractError);
    assert.throws(() => parseEvent({ ...eventFixture, payload: { text: "x".repeat(70000) } }), ContractError);
  });
});
