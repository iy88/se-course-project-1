<script setup lang="ts">
/*
 * Modal confirmation used before irreversible or broadly visible actions.
 * Built on <dialog> so focus handling and the escape key follow the platform.
 */
import { onBeforeUnmount, ref, watch } from "vue";

const props = withDefaults(
  defineProps<{
    open: boolean;
    title: string;
    description?: string;
    confirmLabel?: string;
    cancelLabel?: string;
    tone?: "primary" | "danger";
  }>(),
  {
    description: "",
    confirmLabel: "确认",
    cancelLabel: "取消",
    tone: "primary",
  },
);

const emit = defineEmits<{ confirm: []; cancel: [] }>();
const dialog = ref<HTMLDialogElement | null>(null);

watch(
  () => props.open,
  (open) => {
    const element = dialog.value;
    if (!element) return;
    if (open && !element.open) element.showModal();
    if (!open && element.open) element.close();
  },
);

function close(): void {
  emit("cancel");
}

onBeforeUnmount(() => {
  if (dialog.value?.open) dialog.value.close();
});
</script>

<template>
  <dialog ref="dialog" class="dialog" @cancel.prevent="close" @close="close">
    <form method="dialog" class="dialog__body">
      <h2 class="dialog__title">{{ title }}</h2>
      <p v-if="description" class="dialog__description">{{ description }}</p>
      <slot />
      <div class="dialog__actions">
        <button type="button" class="btn" @click="close">{{ cancelLabel }}</button>
        <button
          type="button"
          class="btn"
          :class="tone === 'danger' ? 'btn--danger' : 'btn--primary'"
          @click="emit('confirm')"
        >
          {{ confirmLabel }}
        </button>
      </div>
    </form>
  </dialog>
</template>

<style scoped>
.dialog {
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 0;
  max-inline-size: min(30rem, calc(100vw - 2rem));
  box-shadow: var(--shadow);
}

.dialog::backdrop {
  background: rgb(24 36 32 / 42%);
}

.dialog__body {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-5);
}

.dialog__title {
  font-size: 1rem;
}

.dialog__description {
  color: var(--ink-soft);
  font-size: 0.875rem;
}

.dialog__actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
}
</style>
