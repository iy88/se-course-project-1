import type { RouteLocationRaw } from "vue-router";

export interface BackRouteMeta {
  backLabel?: string;
  backParams?: readonly string[];
  backTo?: string;
}

type RouteParams = Record<string, string | string[]>;

/** Build the deterministic in-app parent used when no browser history exists. */
export function backFallbackFor(meta: BackRouteMeta, params: RouteParams): RouteLocationRaw | null {
  if (!meta.backTo) return null;
  const fallbackParams: Record<string, string> = {};
  for (const key of meta.backParams ?? []) {
    const value = params[key];
    if (typeof value === "string") fallbackParams[key] = value;
  }
  return { name: meta.backTo, params: fallbackParams };
}

/** Vue Router records the previous in-app route in `history.state.back`. */
export function hasBackEntry(state: unknown): boolean {
  if (state === null || typeof state !== "object") return false;
  return typeof (state as { back?: unknown }).back === "string";
}
