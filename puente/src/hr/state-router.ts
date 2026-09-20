import { createHash, timingSafeEqual } from "node:crypto";
import { Router, type Response } from "express";
import { ContractError, object, parseId, parseSnapshotRequest, unwrapEvent } from "../lib/event-contract.js";
import { RedisStateStore, StateStoreError, upstashCommand } from "../lib/redis-state.js";
import type { StateApiConfig } from "../lib/state-env.js";
import { deliver, type DeliveryConfig } from "../lib/state-delivery.js";
import { operationContext } from "../lib/operation-context.js";

function matches(expected: string, actual: string): boolean {
  const digest = (value: string) => createHash("sha256").update(value).digest();
  return timingSafeEqual(digest(expected), digest(actual));
}

function respond(res: Response, output: unknown): void {
  const status = output && typeof output === "object" && "status" in output ? output.status : undefined;
  const conflicts = ["conflict", "event_conflict", "message_conflict", "lease_conflict", "lease_expired"];
  const code = conflicts.includes(String(status)) ? 409 : status === "missing" || status === "event_missing" ? 404 : 200;
  res.status(code).json(output);
}

export function stateRouter(config: StateApiConfig = { enabled: false }, injected?: RedisStateStore, delivery: DeliveryConfig = { mode: "sink" }): Router {
  const router = Router();
  let store = injected;
  if (!store && config.enabled && config.url && config.token && config.namespace) {
    try { store = new RedisStateStore(upstashCommand(config.url, config.token), config.namespace); }
    catch { store = undefined; }
  }

  const route = (
    path: string,
    scope: "ingressSecret" | "readSecret" | "commitSecret" | "deliverySecret",
    action: (store: RedisStateStore, body: Record<string, unknown>) => Promise<unknown>,
  ) => router.post(path, async (req, res) => {
    res.set("Cache-Control", "no-store");
    const expected = config[scope];
    if (!config.enabled || !store || !expected) {
      res.status(503).json({ error: "state_unavailable" });
      return;
    }
    if (!matches(expected, req.header("x-hr-state-secret") ?? "")) {
      res.status(401).json({ error: "unauthorized" });
      return;
    }
    try {
      respond(res, await action(store, object(req.body)));
    } catch (error) {
      if (error instanceof ContractError) res.status(422).json({ error: error.message });
      else if (error instanceof StateStoreError) res.status(503).json({ error: "state_unavailable" });
      else res.status(500).json({ error: "state_error" });
    }
  });

  route("/inbox", "ingressSecret", (s, body) => s.enqueue(unwrapEvent(body)));
  route("/inbox/event", "readSecret", (s, body) => s.event(parseId(body.id)));
  route("/inbox/pending", "readSecret", (s, body) => s.pending("inbox", body.limit === undefined ? 16 : body.limit as number));
  route("/inbox/settle", "commitSecret", (s, body) => s.settleEvent(parseId(body.id), body.status as "rejected" | "deferred", body.reason as string));
  route("/snapshot", "readSecret", (s, body) => s.snapshot(parseSnapshotRequest(body)));
  route("/operations/context", "readSecret", (s, body) => operationContext(s, parseId(body.id)));
  route("/coordinator/context", "readSecret", (s, body) => {
    let extra: unknown = [];
    if (body.extra_entities_json !== undefined) {
      if (typeof body.extra_entities_json !== "string") throw new ContractError("invalid_context_references");
      try { extra = JSON.parse(body.extra_entities_json); } catch { throw new ContractError("invalid_context_references"); }
    }
    if (!Array.isArray(extra)) throw new ContractError("invalid_context_references");
    const extraEntities = extra.length ? parseSnapshotRequest({ entities: extra }) : [];
    return operationContext(s, parseId(body.id), { coordinator: true, extraEntities });
  });
  route("/inbox/batch", "readSecret", async (s) => ({ items: await s.pending("inbox", 8) }));
  route("/outbox/batch", "deliverySecret", async (s) => ({ items: await s.pending("outbox", 8) }));
  route("/inbox/status", "commitSecret", async (s, body) => {
    const id = parseId(body.id);
    const record = await s.event(id);
    const summary = { status: record?.status ?? "missing", event_id: id, event_type: record ? object(record.event).event_type : null,
      next_at: record?.next_at ?? null, reason: record?.reason ?? null, attempts: record?.attempts ?? 0 };
    return { ...summary, api_status_code: record ? 200 : 404, result_json: JSON.stringify(summary) };
  });
  route("/commit", "commitSecret", (s, body) => s.commit(body));
  route("/outbox/pending", "deliverySecret", (s, body) => s.pending("outbox", body.limit === undefined ? 16 : body.limit as number));
  route("/outbox/claim", "deliverySecret", (s, body) => s.claim(parseId(body.id)));
  route("/outbox/deliver", "deliverySecret", (s, body) => deliver(s, parseId(body.id), delivery));
  route("/outbox/settle", "deliverySecret", (s, body) => {
    if (typeof body.lease !== "string" || !["succeeded", "failed", "unknown"].includes(String(body.status))) {
      throw new ContractError("invalid_delivery_result");
    }
    return s.settle(parseId(body.id), body.lease, body.status as "succeeded" | "failed" | "unknown",
      body.provider_message_id === undefined ? "" : body.provider_message_id as string);
  });
  return router;
}
