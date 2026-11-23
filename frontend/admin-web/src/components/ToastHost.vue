<script setup lang="ts">
import { dismiss, toasts } from "../app/toast";
</script>

<template>
  <div class="toast-host" aria-live="polite">
    <div
      v-for="item in toasts"
      :key="item.id"
      class="toast"
      :class="`toast--${item.tone}`"
      role="status"
    >
      <span>{{ item.message }}</span>
      <button type="button" class="toast__close" aria-label="关闭提示" @click="dismiss(item.id)">
        ×
      </button>
    </div>
  </div>
</template>

<style scoped>
.toast-host {
  position: fixed;
  inset-block-end: var(--space-5);
  inset-inline-end: var(--space-5);
  z-index: 50;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  inline-size: min(22rem, calc(100vw - 2rem));
}

.toast {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-2);
  padding: var(--space-3);
  border-radius: var(--radius-sm);
  border: 1px solid var(--line-strong);
  background: var(--panel);
  box-shadow: var(--shadow);
  font-size: 0.875rem;
}

.toast--success {
  border-color: var(--ok);
  background: var(--ok-soft);
  color: var(--ok);
}

.toast--error {
  border-color: var(--danger);
  background: var(--danger-soft);
  color: var(--danger);
}

.toast__close {
  border: 0;
  background: none;
  color: inherit;
  font-size: 1rem;
  line-height: 1;
  cursor: pointer;
}
</style>
