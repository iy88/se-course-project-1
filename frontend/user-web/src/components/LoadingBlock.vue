<script setup lang="ts">
import ContentState from "../../../shared/ContentState.vue";

withDefaults(defineProps<{ label?: string }>(), { label: "正在加载…" });
</script>

<template>
  <ContentState kind="loading" :title="label" />
</template>
