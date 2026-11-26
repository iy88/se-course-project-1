/* Account session endpoints shared by both front-end applications. */
import { ApiError } from "./errors";
import { request, setEntryCsrfToken } from "./http";
import type { Identity } from "./contracts";

interface EntryContext {
  csrf_token: string;
  expires_at: string;
}

/** Refreshes the token a little before the server expiry so a slow form still posts. */
const ENTRY_SKEW_MS = 30_000;

let entryTicket: { token: string; expiresAt: number } | null = null;

async function ensureEntryTicket(force = false): Promise<string> {
  if (!force && entryTicket && entryTicket.expiresAt - Date.now() > ENTRY_SKEW_MS) {
    return entryTicket.token;
  }
  const context = await request<EntryContext>("GET", "/account/entry-context");
  entryTicket = { token: context.csrf_token, expiresAt: Date.parse(context.expires_at) };
  setEntryCsrfToken(entryTicket.token);
  return entryTicket.token;
}

export function readSession(signal?: AbortSignal): Promise<Identity> {
  return request<Identity>("GET", "/account/session", { signal });
}

/**
 * Signs in with the shared account endpoint. A session cookie does not exist
 * before the first login, so the entry token is fetched and replayed once when
 * the server rejects it as stale.
 */
export async function login(
  email: string,
  password: string,
  idempotencyKey: string,
): Promise<Identity> {
  const csrfToken = await ensureEntryTicket();
  try {
    return await request<Identity>("POST", "/account/session", {
      body: { email, password },
      idempotencyKey,
      csrfToken,
    });
  } catch (caught) {
    if (!(caught instanceof ApiError) || caught.code !== "CSRF_INVALID") throw caught;
    const refreshedToken = await ensureEntryTicket(true);
    return request<Identity>("POST", "/account/session", {
      body: { email, password },
      idempotencyKey,
      csrfToken: refreshedToken,
    });
  }
}

export async function logout(): Promise<void> {
  try {
    await request<void>("DELETE", "/account/session");
  } finally {
    entryTicket = null;
    setEntryCsrfToken(null);
  }
}
