/* Shared administrative session state; the server remains the source of truth. */
import { defineStore } from "pinia";
import { computed, ref } from "vue";
import type { Identity } from "../api/contracts";
import { ApiError } from "../api/errors";
import { onUnauthorized } from "../api/http";
import { login as loginRequest, logout as logoutRequest, readSession } from "../api/session";

export type SessionState = "loading" | "signed-out" | "forbidden" | "signed-in" | "failed";

export const useSessionStore = defineStore("session", () => {
  const identity = ref<Identity | null>(null);
  const state = ref<SessionState>("loading");
  const failure = ref<unknown>(null);
  let unauthorizedHandlerInstalled = false;

  const displayName = computed(() => identity.value?.account.display_name ?? "");
  const isManager = computed(() => identity.value?.account.roles.includes("manager") ?? false);

  function apply(next: Identity): void {
    identity.value = next;
    state.value = next.account.roles.includes("manager") ? "signed-in" : "forbidden";
  }

  function clearIdentity(): void {
    identity.value = null;
    state.value = "signed-out";
  }

  /**
   * Register the single 401 callback once Pinia is active. App setup calls this
   * before the first session read; importing the module must not touch Pinia.
   */
  function installUnauthorizedHandler(): void {
    if (unauthorizedHandlerInstalled) return;
    unauthorizedHandlerInstalled = true;
    onUnauthorized(clearIdentity);
  }

  async function load(): Promise<void> {
    state.value = "loading";
    failure.value = null;
    try {
      apply(await readSession());
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) {
        clearIdentity();
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
    clearIdentity();
  }

  return {
    identity,
    state,
    failure,
    displayName,
    isManager,
    installUnauthorizedHandler,
    load,
    signIn,
    signOut,
  };
});
