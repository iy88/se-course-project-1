/*
 * Thin bridge for notifications raised outside component setup.
 *
 * The router guard exists before the app shell, so this module must not resolve
 * the store at load time. The bootstrap installs the app's Pinia instance here
 * and notify resolves the store through it on demand.
 */
import type { Pinia } from "pinia";
import { useToastStore } from "./toast";

let appPinia: Pinia | null = null;

export function installToastBridge(pinia: Pinia): void {
  appPinia = pinia;
}

function toastStore() {
  if (!appPinia) {
    throw new Error("Toast bridge used before the app Pinia instance was installed.");
  }
  return useToastStore(appPinia);
}

export const notify = {
  success: (message: string) => toastStore().notify.success(message),
  info: (message: string) => toastStore().notify.info(message),
  warn: (message: string) => toastStore().notify.warn(message),
  error: (message: string) => toastStore().notify.error(message),
};
