<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{
  page: number;
  pageSize: number;
  total: number;
}>();

const emit = defineEmits<{ change: [page: number] }>();

const totalPages = computed(() => Math.max(1, Math.ceil(props.total / props.pageSize)));
const canGoBack = computed(() => props.page > 1);
const canGoForward = computed(() => props.page < totalPages.value);
</script>

<template>
  <nav v-if="total > pageSize" class="pager" aria-label="分页">
    <button
      type="button"
      class="btn btn--small"
      :disabled="!canGoBack"
      @click="emit('change', page - 1)"
    >
      上一页
    </button>
    <span class="muted">第 {{ page }} / {{ totalPages }} 页 · 共 {{ total }} 条</span>
    <button
      type="button"
      class="btn btn--small"
      :disabled="!canGoForward"
      @click="emit('change', page + 1)"
    >
      下一页
    </button>
  </nav>
</template>

<style scoped>
.pager {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-3);
  padding-block-start: var(--space-3);
  flex-wrap: wrap;
}
</style>
