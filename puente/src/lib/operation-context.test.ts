import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { operationContext } from "./operation-context.js";
import type { StateSnapshot } from "./redis-state.js";
const eventFixture = { schema_version: 2, event_id: "tg-update-42", event_type: "assignment.accepted",
  occurred_at: "2026-09-19T14:00:00Z", received_at: "2026-09-19T14:00:01Z", channel: "telegram",
  actor_id: "worker-1", conversation_id: "conversation-1", incident_id: "incident-1", assignment_id: "assignment-1",
  correlation_id: "trace-1", payload: {} };

describe("bounded operation snapshot", () => {
  it("loads linked actors, assignments and reservations without making a decision", async () => {
    const docs: StateSnapshot = {
      "actor/worker-1": { version: 1, value: { roles: ["medico"] } },
      "actor/reporter": { version: 1, value: { roles: [] } },
      "incident/incident-1": { version: 2, value: { reporter_id: "reporter", assignment_ids: ["assignment-1"] } },
      "assignment/assignment-1": { version: 1, value: { actor_id: "worker-1", task_id: "task-1" } },
    };
    const calls: string[][] = [];
    const result = await operationContext({
      event: async () => ({ status: "pending", event: eventFixture }),
      snapshot: async (names) => { calls.push(names); return Object.fromEntries(names.map((key) => [key, docs[key] ?? { version: 0, value: null }])); },
    }, eventFixture.event_id);
    assert.equal(result.status, "pending");
    const snapshot = JSON.parse(result.snapshot_json);
    assert.deepEqual(snapshot["actor/reporter"], docs["actor/reporter"]);
    assert.deepEqual(snapshot["reservation/task:task-1"], { version: 0, value: null });
    assert.deepEqual(snapshot["reservation/actor:worker-1"], { version: 0, value: null });
    assert.ok(calls.length <= 8);
    assert.ok(calls.every((names) => names.length <= 32));
    assert.deepEqual(docs["incident/incident-1"].value?.assignment_ids, ["assignment-1"]);
  });

  it("does not read snapshots for already applied or missing events", async () => {
    for (const event of [null, { status: "applied", event: eventFixture }]) {
      const result = await operationContext({ event: async () => event, snapshot: async () => { throw new Error("must not read"); } }, eventFixture.event_id);
      assert.equal(result.status, event ? "applied" : "missing");
    }
  });

  it("does not follow malformed references or unbounded assignment sets", async () => {
    for (const ids of [["../private"], Array.from({ length: 40 }, (_, i) => `a${i}`)]) {
      await assert.rejects(() => operationContext({
        event: async () => ({ status: "pending", event: eventFixture }),
        snapshot: async (names) => Object.fromEntries(names.map((key) => [key, { version: 1,
          value: key.startsWith("incident/") ? { assignment_ids: ids } : {} }])),
      }, eventFixture.event_id));
    }
  });

  it("rejects a conversation owned by another actor", async () => {
    await assert.rejects(() => operationContext({
      event: async () => ({ status: "pending", event: eventFixture }),
      snapshot: async (names) => Object.fromEntries(names.map((key) => [key, key.startsWith("conversation/")
        ? { version: 1, value: { actor_id: "other" } } : { version: 0, value: null }])),
    }, eventFixture.event_id), /conversation_for_other_actor/);
  });

  it("reads roster availability without traversing other workers' unrelated incidents", async () => {
    const requested = new Set<string>();
    const docs: StateSnapshot = {
      "reservation/role:medico": { version: 1, value: { actor_id: "other" } },
      "actor/other": { version: 1, value: { roles: ["medico"], incident_ids: ["unrelated"] } },
    };
    const result = await operationContext({
      event: async () => ({ status: "pending", event: eventFixture }),
      snapshot: async (names) => Object.fromEntries(names.map((key) => {
        requested.add(key);
        return [key, docs[key] ?? { version: 0, value: null }];
      })),
    }, eventFixture.event_id, { coordinator: true, extraEntities: ["decision/new-plan"] });
    assert.equal(result.status, "pending");
    assert.ok(requested.has("actor/other"));
    assert.ok(requested.has("reservation/actor:other"));
    assert.ok(requested.has("decision/new-plan"));
    assert.ok(!requested.has("incident/unrelated"));
  });

  it("requires a complete final MGET rather than merging snapshots from different reads", async () => {
    let count = 0;
    const result = await operationContext({
      event: async () => ({ status: "pending", event: eventFixture }),
      snapshot: async (names) => {
        count++;
        return Object.fromEntries(names.map((key) => [key, { version: count,
          value: key.startsWith("incident/") ? { reporter_id: "reporter" } : key.startsWith("conversation/") ? { actor_id: eventFixture.actor_id } : {} }]));
      },
    }, eventFixture.event_id);
    assert.ok(count > 1);
    assert.ok(Object.values(JSON.parse(result.snapshot_json)).every((doc) => (doc as { version: number }).version === count));
  });
});
