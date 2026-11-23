/*
 * Single HTTP seam for the administration client.
 *
 * Requests use the same-origin `/api/v1` prefix, the shared session cookie and
 * the readable CSRF cookie. Writes carry an `Idempotency-Key`; a 401 notifies
 * the session module so every screen returns to the sign-in view.
 */
import { AbortedError, ApiError } from "./errors";

export type HttpMethod = "GET" | "POST" | "PATCH" | "PUT" | "DELETE";

const CSRF_COOKIE = "__Host-se_csrf";
const UNSAFE_METHODS = new Set<HttpMethod>(["POST", "PATCH", "PUT", "DELETE"]);

export interface RequestOptions {
  query?: Record<string, string | number | boolean | null | undefined>;
  body?: unknown;
  idempotencyKey?: string;
  signal?: AbortSignal;
}

let unauthorizedHandler: (() => void) | null = null;

/** Register the one callback that clears the local identity on a 401. */
export function onUnauthorized(handler: () => void): void {
  unauthorizedHandler = handler;
}

function readCsrfToken(): string | null {
  const cookie = globalThis.document?.cookie ?? "";
  for (const part of cookie.split(";")) {
    const trimmed = part.trim();
    if (trimmed.startsWith(`${CSRF_COOKIE}=`)) {
      return decodeURIComponent(trimmed.slice(CSRF_COOKIE.length + 1));
    }
  }
  return null;
}

function buildQuery(query: RequestOptions["query"]): string {
  if (!query) return "";
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") continue;
    search.append(key, String(value));
  }
  const serialised = search.toString();
  return serialised ? `?${serialised}` : "";
}

function isErrorEnvelope(value: unknown): value is {
  error: { code: string; message: string; details?: Record<string, unknown> };
  request_id?: string | null;
} {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as { error?: unknown };
  if (typeof candidate.error !== "object" || candidate.error === null) return false;
  const inner = candidate.error as { code?: unknown; message?: unknown };
  return typeof inner.code === "string" && typeof inner.message === "string";
}

export async function request<T>(
  method: HttpMethod,
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  if (options.signal?.aborted) throw new AbortedError();

  const headers = new Headers({ Accept: "application/json" });
  if (options.body !== undefined) headers.set("Content-Type", "application/json");
  if (options.idempotencyKey) headers.set("Idempotency-Key", options.idempotencyKey);
  if (UNSAFE_METHODS.has(method)) {
    const token = readCsrfToken();
    if (token) headers.set("X-CSRF-Token", token);
  }

  let response: Response;
  try {
    response = await fetch(`/api/v1${path}${buildQuery(options.query)}`, {
      method,
      headers,
      credentials: "same-origin",
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: options.signal,
    });
  } catch (caught) {
    if (caught instanceof DOMException && caught.name === "AbortError") {
      throw new AbortedError();
    }
    throw new ApiError(0, "NETWORK_UNAVAILABLE", "网络不可用，请检查连接后重试。");
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    if (isErrorEnvelope(payload)) {
      const failure = new ApiError(
        response.status,
        payload.error.code,
        payload.error.message,
        payload.request_id ?? null,
        payload.error.details ?? {},
      );
      if (response.status === 401) unauthorizedHandler?.();
      throw failure;
    }
    throw new ApiError(response.status, "UNEXPECTED_RESPONSE", "服务返回了无法识别的结果。");
  }
  return payload as T;
}
