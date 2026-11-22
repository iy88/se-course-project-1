<script setup lang="ts">
defineProps<{ title: string; description?: string }>();
</script>

<template>
  <div class="empty">
    <p class="empty__title">{{ title }}</p>
    <p v-if="description" class="empty__description">{{ description }}</p>
    <div class="empty__action"><slot /></div>
  </div>
</template>

<style scoped>
.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-6) var(--space-4);
  text-align: center;
}

.empty__title {
  font-weight: 600;
  color: var(--ink-soft);
}

.empty__description {
  font-size: 0.8125rem;
  color: var(--ink-faint);
  max-inline-size: 36ch;
}

.empty__action:not(:empty) {
  margin-block-start: var(--space-2);
}
</style>
