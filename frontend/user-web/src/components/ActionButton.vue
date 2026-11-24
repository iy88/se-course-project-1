<script setup lang="ts">
/*
 * Button that owns the pending and error state of one write action.
 *
 * It runs the supplied task, ignores a second click while the first call is in
 * flight, and renders the mapped failure sentence right under the control so the
 * reason appears where the user acted.
 */
import { computed, ref } from "vue";
import { describeProblem } from "../app/problems";

const props = withDefaults(
  defineProps<{
    label: string;
    task: () => Promise<void>;
    pendingLabel?: string;
    variant?: "primary" | "ghost" | "danger" | "default";
    disabled?: boolean;
    block?: boolean;
    small?: boolean;
    /** Let the caller render the failure itself instead of the inline slot. */
    silentFailure?: boolean;
  }>(),
  {
    pendingLabel: "处理中…",
    variant: "default",
    disabled: false,
    block: false,
    small: false,
    silentFailure: false,
  },
);

const emit = defineEmits<{ succeeded: []; failed: [error: unknown] }>();

const pending = ref(false);
const error = ref<unknown>(null);

const classes = computed(() => {
  const list = ["btn"];
  if (props.variant === "primary") list.push("btn--primary");
  if (props.variant === "ghost") list.push("btn--ghost");
  if (props.variant === "danger") list.push("btn--danger");
  if (props.block) list.push("btn--block");
  if (props.small) list.push("btn--small");
  return list;
});

async function execute(): Promise<void> {
  if (pending.value || props.disabled) return;
  pending.value = true;
  error.value = null;
  try {
    await props.task();
    emit("succeeded");
  } catch (caught) {
    error.value = caught;
    emit("failed", caught);
  } finally {
    pending.value = false;
  }
}
</script>

<template>
  <span class="action">
    <button
      :class="classes"
      type="button"
      :disabled="disabled || pending"
      :aria-busy="pending"
      @click="execute"
    >
      {{ pending ? pendingLabel : label }}
    </button>
    <span v-if="error && !silentFailure" class="field__error">
      {{ describeProblem(error).message }}
    </span>
  </span>
</template>

<style scoped>
.action {
  display: inline-flex;
  flex-direction: column;
  gap: var(--space-1);
}
</style>
