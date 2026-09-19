import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { buildAck } from "./telegram-map.js";
import { RateLimiter } from "./rate-limit.js";

describe("ack neutro y límite de mensajes", () => {
  it("el ack no presupone que el texto sea un aviso nuevo", () => {
    const ack = buildAck("tg-123-987654", "foso", "en 10 min");
    assert.match(ack, /Recibido \(ref 987654\)/);
    assert.doesNotMatch(ack, /Aviso recibido|Zona|🔴|🟡|🟢/);
  });

  it("permite una conversación de varios mensajes por minuto", () => {
    const rl = new RateLimiter();
    for (let i = 0; i < 8; i++) assert.equal(rl.allow("c1"), true);
    assert.equal(rl.allow("c1"), false);
  });
});
