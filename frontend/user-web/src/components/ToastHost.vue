<script setup lang="ts">
import { toasts, dismiss } from "../app/toast";
</script>

<template>
  <div class="toast-host" aria-live="polite" aria-atomic="false">
    <div v-for="toast in toasts" :key="toast.id" class="toast" :class="`toast--${toast.tone}`">
      <p class="toast__message">{{ toast.message }}</p>
      <button type="button" class="toast__close" aria-label="关闭提示" @click="dismiss(toast.id)">
        ×
      </button>
    </div>
  </div>
</template>

<style scoped>
.toast-host {
  position: fixed;
  inset-block-end: 4.75rem;
  inset-inline: 0;
  z-index: 30;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2);
  padding-inline: var(--space-4);
  pointer-events: none;
}

.toast {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  inline-size: 100%;
  max-inline-size: 32rem;
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-sm);
  border: 1px solid var(--line);
  background: var(--panel);
  box-shadow: var(--shadow);
  font-size: 0.8125rem;
  pointer-events: auto;
}

.toast--ok {
  border-color: #cbe3d4;
  color: var(--ok);
}

.toast--info {
  border-color: #cfe0ee;
  color: var(--info);
}

.toast--warn {
  border-color: #ecd9b4;
  color: var(--warn);
}

.toast--danger {
  border-color: #e6c9c6;
  color: var(--danger);
}

.toast__message {
  flex: 1;
}

.toast__close {
  border: 0;
  background: none;
  color: inherit;
  cursor: pointer;
  font-size: 1rem;
  line-height: 1;
}

@media (width >= 48rem) {
  .toast-host {
    inset-block-end: var(--space-5);
  }
}
</style>
