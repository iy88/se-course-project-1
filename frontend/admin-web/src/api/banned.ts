/* Banned-scope endpoints (API-PRD-012/013). */
import { request } from "./http";
import type { BannedItemInput, BannedScopeView } from "./contracts";

export function readBannedScope(signal?: AbortSignal): Promise<BannedScopeView> {
  return request<BannedScopeView>("GET", "/banned-items", { signal });
}

export function replaceBannedScope(
  items: BannedItemInput[],
  idempotencyKey: string,
): Promise<BannedScopeView> {
  return request<BannedScopeView>("PUT", "/admin/banned-items", {
    body: { items },
    idempotencyKey,
  });
}
