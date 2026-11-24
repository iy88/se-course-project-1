<script setup lang="ts">
import UiIcon from "./UiIcon.vue";

withDefaults(
  defineProps<{
    title: string;
    description?: string;
    kind?: "empty" | "loading" | "error";
  }>(),
  { kind: "empty" },
);
</script>

<template>
  <div class="content-state" :class="`content-state--${kind}`">
    <span class="content-state__icon" aria-hidden="true">
      <UiIcon v-if="kind === 'error'" name="alert" />
      <UiIcon v-else-if="kind === 'empty'" name="inbox" />
      <span v-else class="content-state__spinner" />
    </span>
    <div class="content-state__copy" :role="kind === 'error' ? 'alert' : undefined">
      <p class="content-state__title">{{ title }}</p>
      <p v-if="description" class="content-state__description">{{ description }}</p>
    </div>
    <div v-if="$slots.default" class="content-state__actions">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.content-state {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
  min-inline-size: 0;
  padding: var(--space-4);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--panel);
}

:global(.card > .content-state) {
  padding: 0;
  border: 0;
  background: transparent;
}

.content-state__icon {
  display: grid;
  place-items: center;
  flex: 0 0 2.5rem;
  block-size: 2.5rem;
  border-radius: var(--radius-sm);
  background: var(--panel-soft);
  color: var(--brand-ink);
}

.content-state__copy {
  flex: 1 1 10rem;
  min-inline-size: 0;
  overflow-wrap: anywhere;
}

.content-state__title {
  color: var(--ink);
  font-weight: 650;
}

.content-state__description {
  margin-block-start: var(--space-1);
  color: var(--ink-soft);
  font-size: 0.875rem;
}

.content-state__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.content-state--loading .content-state__title {
  color: var(--ink-soft);
  font-weight: 500;
}

.content-state__spinner {
  inline-size: 1rem;
  block-size: 1rem;
  border: 2px solid currentColor;
  border-inline-end-color: transparent;
  border-radius: 50%;
}

@media (prefers-reduced-motion: no-preference) {
  .content-state__spinner {
    animation: spin 900ms linear infinite;
  }
}

@keyframes spin {
  to {
    transform: rotate(1turn);
  }
}

.content-state--error .content-state__icon {
  background: var(--danger-soft);
  color: var(--danger);
}
</style>
