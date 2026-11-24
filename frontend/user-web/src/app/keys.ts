/*
 * Idempotency key factory.
 *
 * Every write endpoint requires `Idempotency-Key`. A key must be stable across
 * retries of the same user-initiated operation and different for a new intent,
 * so views keep one key per form submission and mint a fresh one afterwards.
 */
export function newIdempotencyKey(): string {
  const cryptoApi = globalThis.crypto;
  if (cryptoApi && typeof cryptoApi.randomUUID === "function") {
    return cryptoApi.randomUUID();
  }
  // Fallback for non-secure contexts where randomUUID is unavailable.
  return "idem-" + Math.random().toString(36).slice(2) + Date.now().toString(36);
}

/**
 * Holds one key per logical operation and rotates it once the operation
 * succeeds, so a retry after a transport failure replays the original request.
 */
export class IdempotencyKeys {
  private readonly keys = new Map<string, string>();

  current(operation: string): string {
    const existing = this.keys.get(operation);
    if (existing) return existing;
    const created = newIdempotencyKey();
    this.keys.set(operation, created);
    return created;
  }

  rotate(operation: string): void {
    this.keys.delete(operation);
  }

  reset(): void {
    this.keys.clear();
  }
}
