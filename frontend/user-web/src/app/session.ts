/*
 * Session state shared by the whole application.
 *
 * The server is the source of truth: the identity is re-read after every
 * security-relevant action, and a 401 anywhere clears the local view and sends
 * the user back to the login screen rather than leaving a half-authenticated UI.
 */
import { computed, readonly, ref, shallowRef } from "vue";
import { readCurrentIdentity } from "../api/account";
import { AbortedError, ApiError } from "../api/errors";
import type { AccountProfile } from "../api/contracts";
import { clearCaseScopes } from "./case-directory";

const account = shallowRef<AccountProfile | null>(null);
const resolved = ref(false);
let pending: Promise<void> | null = null;

async function load(): Promise<void> {
  try {
    const identity = await readCurrentIdentity();
    if (account.value?.account_id !== identity.account.account_id) clearCaseScopes();
    account.value = identity.account;
  } catch (error) {
    if (error instanceof AbortedError) return;
    if (error instanceof ApiError && error.status === 401) {
      clearCaseScopes();
      account.value = null;
    } else {
      // A dependency failure must not be reported as "signed out": keep the
      // previous state so the user can retry instead of being logged out.
      throw error;
    }
  } finally {
    resolved.value = true;
  }
}

/** Read the identity once per page load; concurrent callers share the request. */
export function ensureSession(): Promise<void> {
  if (resolved.value) return Promise.resolve();
  if (!pending) {
    pending = load().finally(() => {
      pending = null;
    });
  }
  return pending;
}

/** Force a re-read, e.g. after changing the display name or avatar. */
export async function refreshSession(): Promise<void> {
  resolved.value = false;
  await ensureSession();
}

export function setAccount(next: AccountProfile | null): void {
  if (account.value?.account_id !== next?.account_id) clearCaseScopes();
  account.value = next;
  resolved.value = next !== null;
}

/** Drop the local identity after logout or an authentication failure. */
export function clearSession(): void {
  clearCaseScopes();
  account.value = null;
  resolved.value = true;
}

export const session = {
  account: readonly(account),
  resolved: readonly(resolved),
  accountId: computed(() => account.value?.account_id ?? null),
  displayName: computed(() => account.value?.display_name ?? ""),
  avatarUrl: computed(() => account.value?.avatar_url ?? null),
  isAuthenticated: computed(() => account.value !== null),
  isManager: computed(() => account.value?.roles.includes("manager") ?? false),
};
