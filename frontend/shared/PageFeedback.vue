<script setup lang="ts">
import UiIcon from "./UiIcon.vue";

defineProps<{
  messages: readonly { id: number; tone: "ok" | "info" | "warn" | "danger"; message: string }[];
}>();
defineEmits<{ dismiss: [id: number] }>();

const icons = { ok: "check", info: "info", warn: "alert", danger: "alert" } as const;
</script>

<template>
  <div class="page-feedback" aria-live="polite">
    <div
      v-for="message in messages"
      :key="message.id"
      class="page-feedback__item banner"
      :class="`banner--${message.tone}`"
    >
      <UiIcon :name="icons[message.tone]" />
      <p>{{ message.message }}</p>
      <button
        type="button"
        class="page-feedback__dismiss"
        aria-label="关闭提示"
        @click="$emit('dismiss', message.id)"
      >
        <UiIcon name="close" />
      </button>
    </div>
  </div>
</template>

<style scoped>
.page-feedback {
  inline-size: min(100%, var(--shell-max));
  margin-inline: auto;
  padding-inline: var(--shell-gutter, var(--space-4));
}

.page-feedback__item {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--space-2);
  margin-block-start: var(--space-2);
}

.page-feedback__item p {
  overflow-wrap: anywhere;
}

.page-feedback__dismiss {
  display: grid;
  place-items: center;
  inline-size: 2rem;
  block-size: 2rem;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: inherit;
  cursor: pointer;
}

.page-feedback__dismiss:hover {
  background: var(--panel);
}
</style>
