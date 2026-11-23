/* Account session endpoints shared by both front-end applications. */
import { request } from "./http";
import type { Identity } from "./contracts";

export function readSession(signal?: AbortSignal): Promise<Identity> {
  return request<Identity>("GET", "/account/session", { signal });
}

export function login(email: string, password: string, idempotencyKey: string): Promise<Identity> {
  return request<Identity>("POST", "/account/session", {
    body: { email, password },
    idempotencyKey,
  });
}

export function logout(): Promise<void> {
  return request<void>("DELETE", "/account/session");
}
