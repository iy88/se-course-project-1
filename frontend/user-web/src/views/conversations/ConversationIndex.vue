<template>
  <EmptyState
    class="placeholder"
    title="选择一个会话"
    description="从左侧选择对手方与具体分支，历史消息与已读进度会在这里显示。"
  />
</template>

<script setup lang="ts">
import EmptyState from "../../components/EmptyState.vue";
</script>

<style scoped>
.placeholder {
  margin-block-start: var(--space-4);
}
</style>
