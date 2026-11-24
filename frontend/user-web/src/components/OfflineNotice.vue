<script setup lang="ts">
/*
 * Connectivity notice. `role=status` announces both the offline and recovered
 * states; retry performs a live same-origin check before reloading the route.
 */
import { computed } from "vue";
import { network } from "../app/network";

const message = computed(() => {
  if (!network.online.value) {
    return network.retryError.value || "网络已断开，当前显示已缓存的页面。请检查网络后重试。";
  }
  if (network.unavailable.value) {
    return network.retryError.value || "网络连接暂不可用，请检查网络后重试。";
  }
  if (network.recovered.value) return "网络已恢复。可重试刚才的操作。";
  return "";
});
</script>

<template>
  <div v-if="message" class="network-notice" role="status" aria-live="polite">
    <span class="network-notice__text">{{ message }}</span>
    <button
      type="button"
      class="network-notice__retry"
      :disabled="network.retrying.value"
      @click="network.retry"
    >
      {{ network.retrying.value ? "重试中…" : "重试" }}
    </button>
  </div>
</template>

<style scoped>
.network-notice {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-4);
  background: var(--warn-soft);
  border-block-end: 1px solid #ecd6ae;
  color: var(--warn);
  font-size: 0.8125rem;
}

.network-notice__text {
  min-inline-size: 0;
}

.network-notice__retry {
  flex: none;
  min-block-size: var(--control-min-block);
  padding-inline: var(--space-3);
  border: 1px solid currentColor;
  border-radius: var(--radius-sm);
  background: transparent;
  color: inherit;
  font-size: 0.8125rem;
  font-weight: 650;
  cursor: pointer;
}

.network-notice__retry:disabled {
  cursor: progress;
  opacity: 0.65;
}
</style>
