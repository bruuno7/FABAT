/**
 * In-memory rate limiter for the Telegram bot.
 * Limits incident reports (free-text) per chat_id to avoid spam.
 * Commands (/rol, /estado, etc.) are not rate-limited.
 */

type Bucket = {
  count: number;
  windowStart: number; // ms timestamp
};

export type RateLimitConfig = {
  maxRequests: number; // default 8 (una conversación pregunta-respuesta necesita varios mensajes por minuto)
  windowMs: number;   // default 60_000 (1 min)
};

const DEFAULT_CONFIG: RateLimitConfig = {
  maxRequests: 8,
  windowMs: 60_000,
};

export class RateLimiter {
  private buckets = new Map<string, Bucket>();
  private config: RateLimitConfig;

  constructor(config: Partial<RateLimitConfig> = {}) {
    this.config = { ...DEFAULT_CONFIG, ...config };
  }

  /**
   * Returns true if the chat is allowed to send another report.
   * Mutates internal state (increments counter).
   */
  allow(chatId: string): boolean {
    const now = Date.now();
    const bucket = this.buckets.get(chatId);

    if (!bucket || now - bucket.windowStart > this.config.windowMs) {
      // New window
      this.buckets.set(chatId, { count: 1, windowStart: now });
      return true;
    }

    if (bucket.count < this.config.maxRequests) {
      bucket.count++;
      return true;
    }

    return false;
  }

  /**
   * Seconds remaining until the chat window resets.
   */
  secondsUntilReset(chatId: string): number {
    const bucket = this.buckets.get(chatId);
    if (!bucket) return 0;
    const elapsed = Date.now() - bucket.windowStart;
    const remaining = this.config.windowMs - elapsed;
    return Math.max(0, Math.ceil(remaining / 1000));
  }

  /** Purge stale entries to prevent unbounded memory growth. */
  prune(): void {
    const now = Date.now();
    for (const [id, bucket] of this.buckets) {
      if (now - bucket.windowStart > this.config.windowMs * 2) {
        this.buckets.delete(id);
      }
    }
  }
}

/** Singleton limiter (shared across requests in the same process). */
export const globalRateLimiter = new RateLimiter();
