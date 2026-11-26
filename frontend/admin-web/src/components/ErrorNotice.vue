<script setup lang="ts">
import { computed } from "vue";
import ContentState from "../../../shared/ContentState.vue";
import { describeProblem } from "../app/problems";

const props = defineProps<{ error: unknown }>();
const emit = defineEmits<{ retry: [] }>();
const problem = computed(() => describeProblem(props.error));
</script>

<template>
  <ContentState kind="error" :title="problem.message">
    <template v-if="problem.retryable" #default>
      <button type="button" class="btn" @click="emit('retry')">重试</button>
    </template>
  </ContentState>
</template>
