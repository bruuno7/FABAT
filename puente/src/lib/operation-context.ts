import { createHash } from "node:crypto";
import { ContractError, parseEntity, parseEvent, parseId, type JsonObject } from "./event-contract.js";
import type { RedisStateStore, StateSnapshot } from "./redis-state.js";

export type OperationContext = { status: string; event_id: string; event_json: string; snapshot_json: string; api_status_code: number };

function reservation(kind: "actor" | "task" | "role", id: unknown): string {
  const joined = `${kind}:${parseId(id)}`;
  return `reservation/${joined.length <= 120 ? joined : `${kind}:${createHash("sha256").update(joined).digest("hex").slice(0, 32)}`}`;
}

export async function operationContext(store: Pick<RedisStateStore, "event" | "snapshot">, id: string,
  options: { coordinator?: boolean; extraEntities?: string[] } = {}): Promise<OperationContext> {
  parseId(id);
  const record = await store.event(id);
  if (!record) return { status: "missing", event_id: id, event_json: "null", snapshot_json: "{}", api_status_code: 404 };
  const event = parseEvent(record.event);
  if (event.event_id !== id) throw new ContractError("invalid_context_event");
  const result = { status: String(record.status), event_id: id, event_json: JSON.stringify(event), snapshot_json: "{}", api_status_code: 200 };
  if (record.status !== "pending") return result;
  const names = new Set<string>();
  const add = (entity: string) => {
    names.add(parseEntity(entity));
    if (names.size > 32) throw new ContractError("context_entity_limit");
  };
  const ref = (kind: string, value: unknown) => { if (value !== undefined && value !== null) add(`${kind}/${parseId(value)}`); };
  const list = (value: unknown): unknown[] => {
    if (value === undefined) return [];
    if (!Array.isArray(value) || value.length > 16) throw new ContractError("invalid_context_references");
    return value;
  };
  ref("actor", event.actor_id);
  ref("conversation", event.conversation_id);
  ref("incident", event.incident_id);
  ref("assignment", event.assignment_id);
  ref("question", event.question_id);
  ref("actor", event.payload.recipient_id);
  ref("approval", event.payload.grant_id);
  if (event.payload.task_id !== undefined) add(reservation("task", event.payload.task_id));
  if (event.payload.role !== undefined) add(reservation("role", event.payload.role));
  for (const entity of options.extraEntities ?? []) add(entity);
  if (options.coordinator) {
    ref("actor", "service-coordinator");
    for (const role of ["medico", "bomberos", "policia", "staff_entradas", "organizador"]) add(reservation("role", role));
  }
  const discover = (key: string, value: JsonObject) => {
    if (key.startsWith("incident/")) {
      ref("actor", value.reporter_id);
      for (const id of list(value.assignment_ids)) ref("assignment", id);
      for (const id of list(value.question_ids)) ref("question", id);
      ref("conversation", value.conversation_id);
    } else if (key.startsWith("assignment/")) {
      ref("actor", value.actor_id);
      if (value.task_id !== undefined) add(reservation("task", value.task_id));
    } else if (key.startsWith("actor/")) {
      add(reservation("actor", key.slice("actor/".length)));
      if (key === `actor/${event.actor_id}`) {
        for (const role of list(value.roles)) add(reservation("role", role));
        for (const id of list(value.incident_ids)) ref("incident", id);
        for (const id of list(value.pending_question_ids)) ref("question", id);
      }
    } else if (key.startsWith("question/")) {
      ref("actor", value.requester_id);
      ref("actor", value.recipient_id);
      ref("assignment", value.assignment_id);
      ref("incident", value.incident_id);
    } else if (key === `conversation/${event.conversation_id}`) {
      if (value.actor_id !== event.actor_id) throw new ContractError("conversation_for_other_actor");
      for (const id of list(value.incident_ids)) ref("incident", id);
    } else if (options.coordinator && key.startsWith("reservation/role:")) {
      ref("actor", value.actor_id);
    }
  };
  for (let round = 0; round < 8; round++) {
    const requested = [...names];
    const snapshot: StateSnapshot = await store.snapshot(requested);
    if (Object.keys(snapshot).length !== requested.length || requested.some((key) => !(key in snapshot))) {
      throw new ContractError("incomplete_context_snapshot");
    }
    for (const [key, doc] of Object.entries(snapshot)) if (doc.value) discover(key, doc.value);
    if (names.size === requested.length) return { ...result, snapshot_json: JSON.stringify(snapshot) };
  }
  throw new ContractError("context_did_not_stabilize");
}
