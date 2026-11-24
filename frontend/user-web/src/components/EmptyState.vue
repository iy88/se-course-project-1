<script setup lang="ts">
import ContentState from "../../../shared/ContentState.vue";

defineProps<{ title: string; description?: string }>();
</script>

<template>
  <ContentState :title="title" :description="description">
    <template v-if="$slots.default" #default><slot /></template>
  </ContentState>
</template>
