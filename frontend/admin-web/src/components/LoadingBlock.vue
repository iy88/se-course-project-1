<script setup lang="ts">
defineProps<{ label: string }>();
</script>

<template>
  <div class="loading" role="status">
    <span class="loading__dot" aria-hidden="true" />
    <span>{{ label }}</span>
  </div>
</template>

<style scoped>
.loading {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--ink-faint);
  font-size: 0.875rem;
  padding-block: var(--space-3);
}

.loading__dot {
  inline-size: 0.625rem;
  block-size: 0.625rem;
  border-radius: 50%;
  background: var(--brand);
  animation: pulse 900ms ease-in-out infinite alternate;
}

@keyframes pulse {
  from {
    opacity: 0.35;
  }

  to {
    opacity: 1;
  }
}
</style>
