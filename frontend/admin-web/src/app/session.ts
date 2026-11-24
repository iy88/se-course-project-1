/* Shared administrative session state; the server remains the source of truth. */
import { computed, readonly, ref } from "vue";
import type { Identity } from "../api/contracts";
import { ApiError } from "../api/errors";
import { onUnauthorized } from "../api/http";
import { login as loginRequest, logout as logoutRequest, readSession } from "../api/session";

export type SessionState = "loading" | "signed-out" | "forbidden" | "signed-in" | "failed";

const identity = ref<Identity | null>(null);
const state = ref<SessionState>("loading");
const failure = ref<unknown>(null);

function apply(next: Identity): void {
  identity.value = next;
  state.value = next.account.roles.includes("manager") ? "signed-in" : "forbidden";
}

async function load(): Promise<void> {
  state.value = "loading";
  failure.value = null;
  try {
    apply(await readSession());
  } catch (caught) {
    if (caught instanceof ApiError && caught.status === 401) {
      identity.value = null;
      state.value = "signed-out";
      return;
    }
    failure.value = caught;
    state.value = "failed";
  }
}

async function signIn(email: string, password: string, idempotencyKey: string): Promise<void> {
  const next = await loginRequest(email, password, idempotencyKey);
  apply(next);
}

async function signOut(): Promise<void> {
  try {
    await logoutRequest();
  } catch {
    // A failed logout still clears the local view; the user can retry from the
    // sign-in screen and the server expires the session on its own.
  }
  identity.value = null;
  state.value = "signed-out";
}

onUnauthorized(() => {
  identity.value = null;
  state.value = "signed-out";
});

export const session = {
  identity: readonly(identity),
  state: readonly(state),
  failure: readonly(failure),
  displayName: computed(() => identity.value?.account.display_name ?? ""),
  isManager: computed(() => identity.value?.account.roles.includes("manager") ?? false),
  load,
  signIn,
  signOut,
};
