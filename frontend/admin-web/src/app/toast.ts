/* Transient operation feedback shared by every administrative screen. */
import { readonly, ref } from "vue";

export type ToastTone = "info" | "success" | "error";

export interface ToastMessage {
  id: number;
  tone: ToastTone;
  message: string;
}

const items = ref<ToastMessage[]>([]);
let sequence = 0;

function push(tone: ToastTone, message: string): void {
  const id = (sequence += 1);
  items.value = [...items.value, { id, tone, message }];
  globalThis.setTimeout(() => dismiss(id), 4500);
}

export function dismiss(id: number): void {
  items.value = items.value.filter((item) => item.id !== id);
}

export const toasts = readonly(items);

export const notify = {
  info: (message: string) => push("info", message),
  success: (message: string) => push("success", message),
  error: (message: string) => push("error", message),
};
