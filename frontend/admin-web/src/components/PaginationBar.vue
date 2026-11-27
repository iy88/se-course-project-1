<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{
  page: number;
  pageSize: number;
  total: number;
  label?: string;
  showSinglePage?: boolean;
}>();
const emit = defineEmits<{ change: [page: number] }>();

const totalPages = computed(() => Math.max(1, Math.ceil(props.total / props.pageSize)));
</script>

<template>
  <nav
    v-if="total > pageSize || (showSinglePage && total > 0)"
    class="pager"
    :aria-label="label ?? '分页'"
  >
    <button
      type="button"
      class="btn btn--small"
      :disabled="page <= 1"
      @click="emit('change', page - 1)"
    >
      上一页
    </button>
    <span class="muted">第 {{ page }} / {{ totalPages }} 页 · 共 {{ total }} 条</span>
    <button
      type="button"
      class="btn btn--small"
      :disabled="page >= totalPages"
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
