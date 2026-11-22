<script setup lang="ts">
import { computed } from "vue";
import { describeProblem } from "../app/problems";

const props = defineProps<{ error: unknown }>();
const emit = defineEmits<{ retry: [] }>();

const problem = computed(() => describeProblem(props.error));
</script>

<template>
  <div class="notice" role="alert">
    <p class="notice__message">{{ problem.message }}</p>
    <button v-if="problem.retryable" type="button" class="btn btn--small" @click="emit('retry')">
      重试
    </button>
  </div>
</template>

<style scoped>
.notice {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border: 1px solid #e6c9c6;
  border-radius: var(--radius-sm);
  background: var(--danger-soft);
  color: var(--danger);
  flex-wrap: wrap;
}

.notice__message {
  font-size: 0.8125rem;
}
</style>
