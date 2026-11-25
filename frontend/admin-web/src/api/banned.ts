/* Banned-scope endpoints (API-PRD-012/013). */
import { request } from "./http";
import type {
  BannedItemInput,
  BannedItemMutation,
  BannedItemPayload,
  BannedScopeMutation,
  BannedScopeView,
} from "./contracts";

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

export function createBannedItem(
  item: BannedItemPayload,
  idempotencyKey: string,
): Promise<BannedItemMutation> {
  return request<BannedItemMutation>("POST", "/admin/banned-items", {
    body: item,
    idempotencyKey,
  });
}

export function updateBannedItem(
  itemId: string,
  item: BannedItemPayload,
  idempotencyKey: string,
): Promise<BannedItemMutation> {
  return request<BannedItemMutation>("PATCH", `/admin/banned-items/${itemId}`, {
    body: item,
    idempotencyKey,
  });
}

export function deleteBannedItem(
  itemId: string,
  idempotencyKey: string,
): Promise<BannedScopeMutation> {
  return request<BannedScopeMutation>("DELETE", `/admin/banned-items/${itemId}`, {
    idempotencyKey,
  });
}
