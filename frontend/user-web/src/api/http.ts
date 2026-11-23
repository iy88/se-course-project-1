/*
 * Single HTTP seam for the user web client.
 *
 * Every call goes through `request`, which performs a real XHR through axios.
 * Views never talk to axios directly, so the call sites stay uniform. There is no
 * in-browser simulation switch: the shipped bundle always talks to the real API.
 * When a work package needs simulated dependencies during development, point the
 * dev-server proxy at a separate mock service (`API_PROXY_TARGET`), which keeps
 * the browser code free of test data.
 */
import axios, { AxiosError, AxiosHeaders } from "axios";
import type { ErrorEnvelope } from "./contracts";
import { AbortedError, ApiError } from "./errors";

export { AbortedError, ApiError } from "./errors";

export type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

const http = axios.create({
  baseURL: "/api/v1",
  adapter: "xhr",
  headers: { Accept: "application/json" },
  xsrfCookieName: "__Host-se_csrf",
  xsrfHeaderName: "X-CSRF-Token",
  withXSRFToken: ({ method = "get" }) =>
    ["get", "head", "options"].includes(method.toLowerCase()) ? false : undefined,
  timeout: 15_000,
});

export interface RequestOptions {
  /**
   * Query parameters. Repeated values are sent as repeated keys, which is how the
   * list endpoints express multi-value filters.
   */
  query?: object;
  body?: unknown;
  /** Required by every write endpoint; replayed verbatim when retrying a write. */
  idempotencyKey?: string;
  /** Verified connection id used by the realtime server to suppress self-echo. */
  originConnectionId?: string;
  signal?: AbortSignal;
}

function buildQuery(query?: object): string {
  if (!query) return "";
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(query as Record<string, unknown>)) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) {
      for (const item of value) {
        if (item === undefined || item === null || item === "") continue;
        search.append(key, String(item));
      }
      continue;
    }
    search.append(key, String(value));
  }
  const serialised = search.toString();
  return serialised ? `?${serialised}` : "";
}

function isErrorEnvelope(value: unknown): value is ErrorEnvelope {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as { error?: unknown };
  if (typeof candidate.error !== "object" || candidate.error === null) return false;
  const inner = candidate.error as { code?: unknown; message?: unknown };
  return typeof inner.code === "string" && typeof inner.message === "string";
}

function isAbort(error: unknown): boolean {
  if (error instanceof AbortedError) return true;
  if (axios.isCancel(error)) return true;
  return error instanceof DOMException && error.name === "AbortError";
}

function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error;
  if (error instanceof AxiosError) {
    const response = error.response;
    if (!response) {
      return new ApiError(0, "NETWORK_UNAVAILABLE", "网络不可用，请检查连接后重试。");
    }
    const payload: unknown = response.data;
    if (isErrorEnvelope(payload)) {
      return new ApiError(
        response.status,
        payload.error.code,
        payload.error.message,
        payload.request_id ?? null,
        payload.error.details ?? {},
      );
    }
    return new ApiError(response.status, "UNEXPECTED_RESPONSE", "服务返回了无法识别的结果。");
  }
  return new ApiError(0, "UNEXPECTED_ERROR", "请求未能完成，请稍后重试。");
}

/**
 * Perform a request against the API.
 *
 * The returned promise rejects with {@link ApiError} for every failure mode and
 * with {@link AbortedError} when the caller's signal fires.
 */
export async function request<T>(
  method: HttpMethod,
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  if (options.signal?.aborted) throw new AbortedError();

  const headers = new AxiosHeaders();
  if (options.idempotencyKey) headers.set("Idempotency-Key", options.idempotencyKey);
  if (options.originConnectionId) {
    headers.set("X-Origin-Connection-Id", options.originConnectionId);
  }

  try {
    const response = await http.request<T>({
      method,
      url: `${path}${buildQuery(options.query)}`,
      data: options.body,
      headers,
      signal: options.signal,
    });
    return response.data;
  } catch (error) {
    if (isAbort(error)) throw new AbortedError();
    throw toApiError(error);
  }
}

/** True when the failure means the current session is no longer usable. */
export function isAuthenticationFailure(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401;
}
