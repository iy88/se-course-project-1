/*
 * Browser connectivity state for the offline application shell.
 *
 * Offline reads come from the service worker's precache. Writes are never
 * queued: the retry action only proves that the same-origin site is reachable
 * and then reloads the current route so the user can repeat the operation.
 */
import { readonly, ref } from "vue";

/** Emitted by the HTTP seam when a request fails before any response arrives. */
export const NETWORK_UNAVAILABLE_EVENT = "project1:network-unavailable";

const initialOnline =
  typeof navigator !== "undefined" && typeof navigator.onLine === "boolean"
    ? navigator.onLine
    : true;
const online = ref(initialOnline);
const unavailable = ref(false);
const recovered = ref(false);
const retrying = ref(false);
const retryError = ref("");
let started = false;
let recoveryTimer: number | undefined;

const RECOVERED_MESSAGE_TIMEOUT = 8_000;

function handleOnline(): void {
  const wasOffline = !online.value;
  online.value = true;
  unavailable.value = false;
  retryError.value = "";
  if (!wasOffline) return;

  recovered.value = true;
  window.clearTimeout(recoveryTimer);
  recoveryTimer = window.setTimeout(() => {
    recovered.value = false;
  }, RECOVERED_MESSAGE_TIMEOUT);
}

function handleOffline(): void {
  online.value = false;
  unavailable.value = false;
  recovered.value = false;
  retryError.value = "";
  window.clearTimeout(recoveryTimer);
}

function handleNetworkUnavailable(): void {
  if (navigator.onLine) {
    unavailable.value = true;
  } else {
    online.value = false;
  }
  recovered.value = false;
  retryError.value = "";
}

/** Attach the global listeners once, before the application mounts. */
export function startNetworkStatus(): void {
  if (started) return;
  started = true;
  window.addEventListener("online", handleOnline);
  window.addEventListener("offline", handleOffline);
  window.addEventListener(NETWORK_UNAVAILABLE_EVENT, handleNetworkUnavailable);
}

/**
 * Probe the same-origin site without touching the API or cached responses, then
 * reload so the current route can issue its requests again.
 */
export async function retryConnection(): Promise<void> {
  if (retrying.value) return;
  retrying.value = true;
  retryError.value = "";
  try {
    const response = await fetch(`/manifest.webmanifest?retry=${Date.now()}`, {
      cache: "no-store",
      credentials: "omit",
    });
    if (!response.ok) throw new Error("site is unreachable");
    window.location.reload();
  } catch {
    if (navigator.onLine) {
      unavailable.value = true;
    } else {
      online.value = false;
    }
    recovered.value = false;
    retryError.value = "仍无法连接，请检查网络后重试。";
  } finally {
    retrying.value = false;
  }
}

export const network = {
  online: readonly(online),
  unavailable: readonly(unavailable),
  recovered: readonly(recovered),
  retrying: readonly(retrying),
  retryError: readonly(retryError),
  retry: retryConnection,
};
