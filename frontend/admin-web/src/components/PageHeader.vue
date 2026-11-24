<script setup lang="ts">
defineProps<{ title: string; description?: string; eyebrow?: string }>();
</script>

<template>
  <header class="page-head">
    <div>
      <p v-if="eyebrow" class="page-head__eyebrow">{{ eyebrow }}</p>
      <h1>{{ title }}</h1>
      <p v-if="description" class="page-head__description">{{ description }}</p>
    </div>
    <div class="page-head__actions">
      <slot name="actions" />
    </div>
  </header>
</template>

<style scoped>
.page-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--space-4);
  flex-wrap: wrap;
  padding-block-end: var(--space-4);
  border-block-end: 1px solid var(--line);
}

.page-head h1 {
  font-size: clamp(1.25rem, 2.6vi, 1.625rem);
}

.page-head__eyebrow {
  margin-block-end: var(--space-1);
  color: var(--brand-ink);
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.04em;
}

.page-head__description {
  margin-block-start: var(--space-2);
  color: var(--ink-soft);
  font-size: 0.875rem;
  max-inline-size: 46rem;
}

.page-head__actions {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
}
</style>
