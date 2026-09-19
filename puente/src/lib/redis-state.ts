import { createHash, randomUUID } from "node:crypto";
import {
  ContractError, object, parseCommit, parseEntity, parseEvent, parseId, parseSnapshotRequest,
  type Json, type JsonObject,
} from "./event-contract.js";
import { CLAIM_MESSAGE, COMMIT_STATE, ENQUEUE_EVENT, SETTLE_MESSAGE } from "./redis-scripts.js";

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
    const response = decode(await this.command(["EVAL", script, keys.length, ...keys, ...args]));
    if (typeof response.status !== "string" || response.status === "storage_error") throw new StateStoreError("invalid_redis_response");
    return response as StoreResult;
  }

  async enqueue(input: unknown): Promise<StoreResult> {
    const event = parseEvent(input);
    const { received_at: _receivedAt, ...stable } = event;
    const fingerprint = createHash("sha256").update(canonical(stable as unknown as Json)).digest("hex");
    return this.eval(ENQUEUE_EVENT, [this.key(`inbox:${event.event_id}`), this.key("inbox-pending")],
      [JSON.stringify(event), fingerprint, this.clock()]);
  }

  async event(id: string): Promise<Record<string, unknown> | null> {
    const raw = await this.command(["GET", this.key(`inbox:${parseId(id)}`)]);
    return raw === null ? null : decode(raw);
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
    const writes = commit.writes.map((write) => ({ ...write, index: indexes.get(write.entity)! }));
    const messages = commit.messages.map((message) => {
      keys.push(this.key(`outbox:${message.id}`));
      return { index: keys.length, value: message };
    });
    return this.eval(COMMIT_STATE, keys, [JSON.stringify({ reads, writes, messages }), this.clock()]);
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

  async settle(id: string, lease: string, status: "succeeded" | "failed" | "unknown", providerMessageId = ""): Promise<StoreResult> {
    parseId(id);
    if (!/^[0-9a-f-]{36}$/.test(lease) || !["succeeded", "failed", "unknown"].includes(status) ||
        typeof providerMessageId !== "string" || providerMessageId.length > 120) throw new ContractError("invalid_delivery_result");
    return this.eval(SETTLE_MESSAGE, [this.key(`outbox:${id}`), this.key("outbox-pending")],
      [lease, status, providerMessageId, this.clock()]);
  }
}
