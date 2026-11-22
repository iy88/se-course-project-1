/*
 * Transient result messages.
 *
 * Views report the outcome of an action through a toast so the affected panel
 * does not have to own a banner; failures stay inline next to the control that
 * produced them.
 */
import { readonly, ref } from "vue";

export type ToastTone = "ok" | "warn" | "danger" | "info";

export interface Toast {
  id: number;
  tone: ToastTone;
  message: string;
}

const items = ref<Toast[]>([]);
let nextId = 1;

function push(tone: ToastTone, message: string, timeoutMs: number): void {
  const id = nextId++;
  items.value = [...items.value, { id, tone, message }];
  if (timeoutMs > 0) {
    window.setTimeout(() => dismiss(id), timeoutMs);
  }
}

export function dismiss(id: number): void {
  items.value = items.value.filter((item) => item.id !== id);
}

export const toasts = readonly(items);

export const notify = {
  success: (message: string) => push("ok", message, 4_000),
  info: (message: string) => push("info", message, 4_000),
  warn: (message: string) => push("warn", message, 6_000),
  error: (message: string) => push("danger", message, 8_000),
};
