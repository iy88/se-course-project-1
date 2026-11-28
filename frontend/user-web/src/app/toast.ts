/*
 * Transient result messages shared by every user-facing screen.
 *
 * The store keeps the queue in the app's Pinia instance; the page-level feedback
 * region in the shell renders it. Durations preserve the existing operation
 * feedback contract: success/info 4s, warning 6s and error 8s.
 */
import { defineStore } from "pinia";
import { computed, readonly, ref } from "vue";

export type ToastTone = "ok" | "warn" | "danger" | "info";

export interface Toast {
  id: number;
  tone: ToastTone;
  message: string;
}

export const useToastStore = defineStore("toast", () => {
  const items = ref<Toast[]>([]);
  let sequence = 0;

  function push(tone: ToastTone, message: string, timeoutMs: number): void {
    const id = (sequence += 1);
    items.value = [...items.value, { id, tone, message }];
    if (timeoutMs > 0) {
      globalThis.setTimeout(() => dismiss(id), timeoutMs);
    }
  }

  function dismiss(id: number): void {
    items.value = items.value.filter((item) => item.id !== id);
  }

  const toasts = computed(() => readonly(items.value));

  const notify = {
    success: (message: string) => push("ok", message, 4_000),
    info: (message: string) => push("info", message, 4_000),
    warn: (message: string) => push("warn", message, 6_000),
    error: (message: string) => push("danger", message, 8_000),
  };

  return { items, toasts, notify, dismiss };
});
