import { createHash, randomUUID } from "node:crypto";
import {
  ContractError, object, parseCommit, parseEntity, parseEvent, parseId, parseMessage, parseSnapshotRequest,
  type CanonicalEvent, type Json, type JsonObject,
} from "./event-contract.js";
import { STAFF_ROLES } from "./contract.js";
import { CLAIM_MESSAGE, COMMIT_STATE, ENQUEUE_EVENT, INGEST_TELEGRAM, SETTLE_EVENT, SETTLE_MESSAGE, withTestExpiry } from "./redis-scripts.js";

export type RedisCommand = (args: (string | number)[]) => Promise<unknown>;
export type StateSnapshot = Record<string, { version: number; value: JsonObject | null }>;
export type StoreResult = Record<string, unknown> & { status: string };

export class StateStoreError extends Error {
  constructor(message = "redis_unavailable") {
    super(message);
    this.name = "StateStoreError";
  }
}

export function upstashCommand(url: string, token: string, fetcher: typeof fetch = fetch): RedisCommand {
  let base: URL;
  try {
    base = new URL(url);
  } catch {
    throw new StateStoreError("invalid_redis_configuration");
  }
  if (base.protocol !== "https:" || !base.hostname.endsWith(".upstash.io") ||
      base.username || base.password || base.search || base.hash || base.pathname !== "/" ||
      (base.port && base.port !== "443") || !token.trim()) {
    throw new StateStoreError("invalid_redis_configuration");
  }
  return async (args) => {
    try {
      const response = await fetcher(base, {
        method: "POST",
        headers: { authorization: `Bearer ${token}`, "content-type": "application/json" },
        body: JSON.stringify(args),
        signal: AbortSignal.timeout(5000),
        redirect: "error",
      });
      if (!response.ok) throw new StateStoreError();
      const body = object(await response.json());
      if ("error" in body || !("result" in body)) throw new StateStoreError();
      return body.result;
    } catch {
      throw new StateStoreError();
    }
  };
}

function canonical(value: Json): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`).join(",")}}`;
}

function eventFingerprint(event: CanonicalEvent): string {
  const { received_at: _receivedAt, ...stable } = event;
  const fingerprinted = event.payload.timestamp_source === "received" ? { ...stable, occurred_at: null } : stable;
  return createHash("sha256").update(canonical(fingerprinted as unknown as Json)).digest("hex");
}

function decode(value: unknown): Record<string, unknown> {
  try {
    if (typeof value !== "string") throw new StateStoreError();
    return object(JSON.parse(value));
  } catch {
    throw new StateStoreError("invalid_redis_response");
  }
}

export class RedisStateStore {
  private readonly prefix: string;

  constructor(private readonly command: RedisCommand, namespace: string, private readonly clock = Date.now) {
    if (!/^(test|dev|live)-[a-z0-9][a-z0-9-]{0,47}$/.test(namespace)) throw new StateStoreError("invalid_namespace");
    this.prefix = `fa:v2:{${namespace}}:`;
  }

  private key(suffix: string): string {
    return this.prefix + suffix;
  }

  private async eval(script: string, keys: string[], args: (string | number)[]): Promise<StoreResult> {
    const scoped = this.prefix.startsWith("fa:v2:{test-") ? withTestExpiry(script) : script;
    const response = decode(await this.command(["EVAL", scoped, keys.length, ...keys, ...args]));
    if (typeof response.status !== "string" || response.status === "storage_error") throw new StateStoreError("invalid_redis_response");
    return response as StoreResult;
  }

  async enqueue(input: unknown): Promise<StoreResult> {
    const event = parseEvent(input);
    return this.eval(ENQUEUE_EVENT, [this.key(`inbox:${event.event_id}`), this.key("inbox-pending")],
      [JSON.stringify(event), eventFingerprint(event), event.not_before ? Math.max(this.clock(), Date.parse(event.not_before)) : this.clock()]);
  }

  async ingestTelegram(input: unknown, chatId: string): Promise<StoreResult> {
    const event = parseEvent(input);
    if (!/^[1-9][0-9]{0,15}$/.test(chatId) || event.actor_id !== `tg-${chatId}` ||
        event.conversation_id !== event.actor_id || event.channel !== "telegram" ||
        !["message.received", "actor.role_claimed", "actor.role_released", "assignment.accepted", "assignment.declined"].includes(event.event_type)) {
      throw new ContractError("invalid_telegram_identity");
    }
    const keys = [this.key(`inbox:${event.event_id}`), this.key("inbox-pending"), this.key(`actor/${event.actor_id}`)];
    let grant = {};
    if (event.event_type === "actor.role_claimed") {
      const role = event.payload.role;
      if (typeof role !== "string" || !(STAFF_ROLES as readonly string[]).includes(role) || event.payload.grant_id !== `grant:${event.event_id}`) {
        throw new ContractError("invalid_role_grant");
      }
      keys.push(this.key(parseEntity(`approval/${event.payload.grant_id}`)));
      grant = { kind: "role_claim", status: "approved", actor_id: event.actor_id, role,
        expires_at: new Date(this.clock() + 300000).toISOString() };
    }
    const actor = { roles: [], permissions: [], preferred_channel: "telegram",
      channels: { telegram: { verified: true, chat_id: chatId } } };
    return this.eval(INGEST_TELEGRAM, keys, [JSON.stringify(event), eventFingerprint(event), this.clock(), JSON.stringify(actor), JSON.stringify(grant)]);
  }

  async event(id: string): Promise<Record<string, unknown> | null> {
    const raw = await this.command(["GET", this.key(`inbox:${parseId(id)}`)]);
    if (raw === null) return null;
    const record = decode(raw);
    if (record.event_json !== undefined) record.event = parseEvent(decode(record.event_json));
    delete record.event_json;
    return record;
  }

  async message(id: string): Promise<Record<string, unknown> | null> {
    const raw = await this.command(["GET", this.key(`outbox:${parseId(id)}`)]);
    return raw === null ? null : decode(raw);
  }

  private receiptKey(actorId: string, providerId: string): string {
    parseId(actorId);
    if (!/^[1-9][0-9]{0,15}$/.test(providerId)) throw new ContractError("invalid_provider_message_id");
    return this.key("receipt:" + createHash("sha256").update(JSON.stringify(["telegram", actorId, providerId])).digest("hex"));
  }

  async messageForReply(actorId: string, providerId: string): Promise<Record<string, unknown> | null> {
    const id = await this.command(["GET", this.receiptKey(actorId, providerId)]);
    return id === null ? null : this.message(parseId(id));
  }

  async settleEvent(id: string, status: "rejected" | "deferred", reason: string): Promise<StoreResult> {
    if (!["rejected", "deferred"].includes(status) || typeof reason !== "string" || !/^[a-z_]{1,64}$/.test(reason)) {
      throw new ContractError("invalid_event_result");
    }
    return this.eval(SETTLE_EVENT, [this.key(`inbox:${parseId(id)}`), this.key("inbox-pending")],
      [status, reason, this.clock()]);
  }

  async snapshot(entities: string[]): Promise<StateSnapshot> {
    const names = parseSnapshotRequest({ entities });
    const values = await this.command(["MGET", ...names.map((name) => this.key(name))]);
    if (!Array.isArray(values) || values.length !== names.length) throw new StateStoreError("invalid_redis_response");
    const result: StateSnapshot = {};
    names.forEach((name, index) => {
      if (values[index] === null) {
        result[name] = { version: 0, value: null };
      } else {
        const doc = decode(values[index]);
        if (!Number.isSafeInteger(doc.version) || (doc.version as number) < 1 || !doc.value ||
            typeof doc.value !== "object" || Array.isArray(doc.value)) throw new StateStoreError("invalid_redis_response");
        result[name] = { version: doc.version as number, value: doc.value as JsonObject };
      }
    });
    return result;
  }

  async commit(input: unknown): Promise<StoreResult> {
    const commit = parseCommit(input);
    const keys = [this.key(`inbox:${commit.event_id}`), this.key("inbox-pending"), this.key("outbox-pending"), this.key("events")];
    const reads = Object.entries(commit.expected).map(([entity, version]) => {
      keys.push(this.key(parseEntity(entity)));
      return { index: keys.length, entity, version };
    });
    const indexes = new Map(reads.map((read) => [read.entity, read.index]));
    const writes = commit.writes.map((write) => ({ entity: write.entity, value_json: JSON.stringify(write.value), index: indexes.get(write.entity)! }));
    const messages = commit.messages.map((message) => {
      keys.push(this.key(`outbox:${message.id}`));
      return { index: keys.length, value: message };
    });
    const now = this.clock();
    const derived = (commit.events ?? []).map((event) => {
      keys.push(this.key(`inbox:${event.event_id}`));
      return { index: keys.length, event_id: event.event_id, due: event.not_before ? Math.max(now, Date.parse(event.not_before)) : now,
        record_json: JSON.stringify({ event, event_json: JSON.stringify(event), fingerprint: eventFingerprint(event), status: "pending" }) };
    });
    return this.eval(COMMIT_STATE, keys, [JSON.stringify({ reads, writes, messages, derived,
      writes_json: JSON.stringify(commit.writes), messages_json: JSON.stringify(commit.messages) }), now]);
  }

  async pending(queue: "inbox" | "outbox", limit = 16): Promise<string[]> {
    if (!["inbox", "outbox"].includes(queue) || !Number.isInteger(limit) || limit < 1 || limit > 32) throw new ContractError("invalid_queue_limit");
    const result = await this.command(["ZRANGEBYSCORE", this.key(`${queue}-pending`), "-inf", this.clock(), "LIMIT", 0, limit]);
    if (!Array.isArray(result)) throw new StateStoreError("invalid_redis_response");
    return result.map(parseId);
  }

  async claim(id: string): Promise<StoreResult> {
    return this.eval(CLAIM_MESSAGE, [this.key(`outbox:${parseId(id)}`), this.key("outbox-pending")],
      [this.clock(), randomUUID(), 60000]);
  }

  async settle(id: string, lease: string, status: "succeeded" | "failed" | "unknown" | "simulated" | "retry", providerMessageId = "", retryAfterMs = 5000): Promise<StoreResult> {
    parseId(id);
    if (!/^[0-9a-f-]{36}$/.test(lease) || !["succeeded", "failed", "unknown", "simulated", "retry"].includes(status) ||
        typeof providerMessageId !== "string" || providerMessageId.length > 120 ||
        !Number.isInteger(retryAfterMs) || retryAfterMs < 1000 || retryAfterMs > 300000) throw new ContractError("invalid_delivery_result");
    const keys = [this.key(`outbox:${id}`), this.key("outbox-pending")];
    if (status === "succeeded" && /^[1-9][0-9]{0,15}$/.test(providerMessageId)) {
      const record = await this.message(id);
      if (record) {
        const message = parseMessage(record.message);
        if (message.channel === "telegram") keys.push(this.receiptKey(message.recipient_id, providerMessageId));
      }
    }
    return this.eval(SETTLE_MESSAGE, keys, [lease, status, providerMessageId, this.clock(), retryAfterMs]);
  }
}
