/*
 * Idempotency key factory. Every administrative write sends a key that stays
 * stable across retries of the same action and is rotated after success.
 */
export function newIdempotencyKey(): string {
  const cryptoApi = globalThis.crypto;
  if (cryptoApi && typeof cryptoApi.randomUUID === "function") {
    return cryptoApi.randomUUID();
  }
  return "idem-" + Math.random().toString(36).slice(2) + Date.now().toString(36);
}

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
}
