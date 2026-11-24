<script setup lang="ts">
defineProps<{
  title: string;
  description?: string;
  /** Small text above the title, e.g. the current section. */
  eyebrow?: string;
}>();
</script>

<template>
  <header class="page-header">
    <p v-if="eyebrow" class="page-header__eyebrow">{{ eyebrow }}</p>
    <div class="page-header__row">
      <div>
        <h1>{{ title }}</h1>
        <p v-if="description" class="page-header__description">{{ description }}</p>
      </div>
      <div class="page-header__actions">
        <slot name="actions" />
      </div>
    </div>
  </header>
</template>

<style scoped>
.page-header {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  margin-block-end: var(--space-4);
}

.page-header__eyebrow {
  font-size: 0.75rem;
  font-weight: 650;
  color: var(--info);
}

.page-header__row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.page-header h1 {
  font-size: 1.375rem;
  letter-spacing: -0.01em;
}

.page-header__description {
  margin-block-start: var(--space-1);
  color: var(--ink-soft);
  font-size: 0.875rem;
  max-inline-size: 62ch;
}

.page-header__actions {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
}

@media (width >= 48rem) {
  .page-header h1 {
    font-size: 1.625rem;
  }
}
</style>
