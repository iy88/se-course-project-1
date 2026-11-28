/* Transient operation feedback shared by every administrative screen. */
import { defineStore } from "pinia";
import { computed, readonly, ref } from "vue";

export type ToastTone = "info" | "ok" | "danger";

export interface ToastMessage {
  id: number;
  tone: ToastTone;
  message: string;
}

export const useToastStore = defineStore("toast", () => {
  const items = ref<ToastMessage[]>([]);
  let sequence = 0;

  function push(tone: ToastTone, message: string): void {
    const id = (sequence += 1);
    items.value = [...items.value, { id, tone, message }];
    globalThis.setTimeout(() => dismiss(id), 4500);
  }

  function dismiss(id: number): void {
    items.value = items.value.filter((item) => item.id !== id);
  }

  const toasts = computed(() => readonly(items.value));

  const notify = {
    info: (message: string) => push("info", message),
    success: (message: string) => push("ok", message),
    error: (message: string) => push("danger", message),
  };

  return { items, toasts, notify, dismiss };
});
