<script setup lang="ts">
withDefaults(defineProps<{ label?: string }>(), { label: "正在加载…" });
</script>

<template>
  <div class="loading" role="status" aria-live="polite">
    <span class="loading__dot" aria-hidden="true" />
    <span class="muted">{{ label }}</span>
  </div>
</template>

<style scoped>
.loading {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-4) 0;
}

.loading__dot {
  inline-size: 0.5rem;
  block-size: 0.5rem;
  border-radius: 50%;
  background: var(--brand);
  animation: pulse 1s ease-in-out infinite;
}

@keyframes pulse {
  0%,
  100% {
    opacity: 0.35;
  }

  50% {
    opacity: 1;
  }
}
</style>
