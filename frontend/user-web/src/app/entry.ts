/*
 * Anonymous account-entry context.
 *
 * Login, registration and password reset are public write endpoints guarded by an
 * entry cookie and CSRF token (API-COM-AUTH-003). Reading the context once per
 * page load lets the anonymous screens show the configured limits and lets the
 * browser receive the entry cookie before the first public write.
 */
import { readonly, ref } from "vue";
import { readEntryContext } from "../api/account";
import type { EntryLimits } from "../api/contracts";

const limits = ref<EntryLimits | null>(null);
const ready = ref(false);
let pending: Promise<void> | null = null;

export function ensureEntryContext(): Promise<void> {
  if (ready.value) return Promise.resolve();
  if (!pending) {
    pending = readEntryContext()
      .then((context) => {
        limits.value = context.limits;
        ready.value = true;
      })
      .catch(() => {
        // The limits only tune copy; a failure must not block the form, and the
        // submit call reports the dependency failure itself.
        ready.value = true;
      })
      .finally(() => {
        pending = null;
      });
  }
  return pending;
}

export const entryLimits = readonly(limits);

/** Password rule copy built from the server-provided limits. */
export function passwordRuleText(limitsValue: EntryLimits | null): string {
  if (!limitsValue) return "使用足够长度的密码";
  return `${limitsValue.password_min_length}—${limitsValue.password_max_length} 个字符`;
}
