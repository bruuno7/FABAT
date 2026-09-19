export const EVENT_TYPES = [
  "message.received", "actor.role_claimed", "actor.role_released", "actor.availability_updated",
  "incident.reported", "incident.updated", "incident.close_requested", "incident.closed",
  "question.created", "question.answered",
  "assignment.offered", "assignment.accepted", "assignment.declined", "assignment.eta_updated",
  "assignment.arrived", "assignment.located", "assignment.completed", "assignment.timed_out",
  "call.started", "call.ended", "call.failed", "delivery.updated",
  "review.requested", "review.completed", "approval.requested", "approval.decided", "deadline.elapsed",
] as const;

export type EventType = (typeof EVENT_TYPES)[number];
export type Channel = "telegram" | "phone" | "webcall" | "web" | "system";
export type Json = null | string | number | boolean | Json[] | { [key: string]: Json };
export type JsonObject = { [key: string]: Json };

export type CanonicalEvent = {
  schema_version: 2;
  event_id: string;
  event_type: EventType;
  occurred_at: string;
  received_at: string;
  channel: Channel;
  actor_id: string;
  conversation_id: string;
  correlation_id: string;
  incident_id?: string;
  assignment_id?: string;
  question_id?: string;
  causation_id?: string;
  source_message_id?: string;
  call_id?: string;
  payload: JsonObject;
};

export type PendingMessage = {
  id: string;
  recipient_id: string;
  channel: "telegram" | "phone" | "webcall";
  incident_id: string;
  assignment_id?: string;
  question_id?: string;
  purpose: "status" | "offer" | "question" | "call";
  text: string;
};

export type StateCommit = {
  event_id: string;
  expected: Record<string, number>;
  writes: { entity: string; value: JsonObject }[];
  messages: PendingMessage[];
};

export class ContractError extends Error {
  constructor(message = "invalid_payload") {
    super(message);
    this.name = "ContractError";
  }
}

const ID = /^[A-Za-z0-9][A-Za-z0-9_.~:-]{0,119}$/;
const ENTITY = /^(actor|incident|assignment|question|conversation|reservation|decision|approval)\/[A-Za-z0-9][A-Za-z0-9_.~:-]{0,119}$/;
const EVENT_KEYS = [
  "schema_version", "event_id", "event_type", "occurred_at", "received_at", "channel", "actor_id",
  "conversation_id", "correlation_id", "incident_id", "assignment_id", "question_id", "causation_id",
  "source_message_id", "call_id", "payload",
];

export function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value) ||
      ![Object.prototype, null].includes(Object.getPrototypeOf(value))) throw new ContractError();
  return value as Record<string, unknown>;
}

function exactKeys(value: Record<string, unknown>, allowed: readonly string[]): void {
  if (Object.keys(value).some((key) => !allowed.includes(key))) throw new ContractError("unknown_field");
}

export function parseId(value: unknown): string {
  if (typeof value !== "string" || !ID.test(value)) throw new ContractError("invalid_id");
  return value;
}

export function parseEntity(value: unknown): string {
  if (typeof value !== "string" || !ENTITY.test(value)) throw new ContractError("invalid_entity");
  return value;
}

function date(value: unknown): string {
  if (typeof value !== "string" || !/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,3})?Z$/.test(value) ||
      !Number.isFinite(Date.parse(value))) throw new ContractError("invalid_timestamp");
  if (new Date(value).toISOString().slice(0, 19) !== value.slice(0, 19)) throw new ContractError("invalid_timestamp");
  return value;
}

function json(value: unknown, depth = 0): Json {
  if (depth > 12) throw new ContractError("payload_too_deep");
  if (value === null || typeof value === "boolean" || typeof value === "string") return value;
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (Array.isArray(value)) return value.map((item) => json(item, depth + 1));
  const record = object(value);
  const result: JsonObject = {};
  for (const [key, item] of Object.entries(record)) {
    if (["__proto__", "constructor", "prototype"].includes(key)) throw new ContractError("invalid_key");
    result[key] = json(item, depth + 1);
  }
  return result;
}

function jsonObject(value: unknown): JsonObject {
  object(value);
  const result = json(value) as JsonObject;
  if (Buffer.byteLength(JSON.stringify(result)) > 65536) throw new ContractError("payload_too_large");
  return result;
}

function oneOf<T extends string>(value: unknown, allowed: readonly T[]): T {
  if (typeof value !== "string" || !allowed.includes(value as T)) throw new ContractError("invalid_enum");
  return value as T;
}

export function parseEvent(value: unknown): CanonicalEvent {
  const input = object(value);
  exactKeys(input, EVENT_KEYS);
  if (input.schema_version !== 2) throw new ContractError("invalid_schema_version");
  const event: CanonicalEvent = {
    schema_version: 2,
    event_id: parseId(input.event_id),
    event_type: oneOf(input.event_type, EVENT_TYPES),
    occurred_at: date(input.occurred_at),
    received_at: date(input.received_at),
    channel: oneOf(input.channel, ["telegram", "phone", "webcall", "web", "system"]),
    actor_id: parseId(input.actor_id),
    conversation_id: parseId(input.conversation_id),
    correlation_id: parseId(input.correlation_id),
    payload: jsonObject(input.payload),
  };
  for (const key of ["incident_id", "assignment_id", "question_id", "causation_id", "source_message_id", "call_id"] as const) {
    if (input[key] !== undefined) event[key] = parseId(input[key]);
  }
  if (event.event_type.startsWith("assignment.") && (!event.assignment_id || !event.incident_id)) {
    throw new ContractError("missing_assignment_reference");
  }
  if (event.event_type.startsWith("question.") && (!event.question_id || !event.incident_id)) {
    throw new ContractError("missing_question_reference");
  }
  if (event.event_type.startsWith("call.") && !event.call_id) throw new ContractError("missing_call_reference");
  return event;
}

export function unwrapEvent(value: unknown): CanonicalEvent {
  const input = object(value);
  if ("data" in input) {
    if ("schema_version" in input || "event_id" in input) throw new ContractError("ambiguous_envelope");
    return parseEvent(input.data);
  }
  return parseEvent(input);
}

export function parseSnapshotRequest(value: unknown): string[] {
  const input = object(value);
  exactKeys(input, ["entities"]);
  if (!Array.isArray(input.entities) || input.entities.length < 1 || input.entities.length > 32) throw new ContractError("invalid_entities");
  const entities = input.entities.map(parseEntity);
  if (new Set(entities).size !== entities.length) throw new ContractError("duplicate_entity");
  return entities;
}

export function parseMessage(value: unknown): PendingMessage {
  const input = object(value);
  exactKeys(input, ["id", "recipient_id", "channel", "incident_id", "assignment_id", "question_id", "purpose", "text"]);
  if (typeof input.text !== "string" || !input.text.trim() || input.text.length > 3500) throw new ContractError("invalid_text");
  const result: PendingMessage = {
    id: parseId(input.id), recipient_id: parseId(input.recipient_id),
    channel: oneOf(input.channel, ["telegram", "phone", "webcall"]),
    incident_id: parseId(input.incident_id),
    purpose: oneOf(input.purpose, ["status", "offer", "question", "call"]),
    text: input.text,
  };
  for (const key of ["assignment_id", "question_id"] as const) {
    if (input[key] !== undefined) result[key] = parseId(input[key]);
  }
  if ((result.purpose === "offer" || result.purpose === "call") && !result.assignment_id && !result.question_id) {
    throw new ContractError("missing_delivery_reference");
  }
  if (result.purpose === "question" && !result.question_id) throw new ContractError("missing_question_reference");
  return result;
}

export function parseCommit(value: unknown): StateCommit {
  const input = object(value);
  exactKeys(input, ["event_id", "expected", "writes", "messages"]);
  const expected = object(input.expected);
  if (Object.keys(expected).length > 32) throw new ContractError("too_many_entities");
  const versions: Record<string, number> = {};
  for (const [entity, version] of Object.entries(expected)) {
    parseEntity(entity);
    if (!Number.isSafeInteger(version) || (version as number) < 0 || (version as number) >= Number.MAX_SAFE_INTEGER) throw new ContractError("invalid_version");
    versions[entity] = version as number;
  }
  if (!Array.isArray(input.writes) || input.writes.length > 32 || !Array.isArray(input.messages) || input.messages.length > 16) {
    throw new ContractError("invalid_commit_batch");
  }
  const writes = input.writes.map((item) => {
    const write = object(item);
    exactKeys(write, ["entity", "value"]);
    const entity = parseEntity(write.entity);
    if (!(entity in versions)) throw new ContractError("missing_read_version");
    return { entity, value: jsonObject(write.value) };
  });
  const messages = input.messages.map(parseMessage);
  if (new Set(writes.map((write) => write.entity)).size !== writes.length ||
      new Set(messages.map((message) => message.id)).size !== messages.length) throw new ContractError("duplicate_write");
  const commit = { event_id: parseId(input.event_id), expected: versions, writes, messages };
  if (Buffer.byteLength(JSON.stringify(commit)) > 262144) throw new ContractError("commit_too_large");
  return commit;
}
