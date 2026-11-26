<script setup lang="ts">
const mark = new URL("./assets/campus-market.svg", import.meta.url).href;
</script>

<template>
  <img class="brand-mark" :src="mark" width="32" height="32" alt="" />
</template>

<style scoped>
.brand-mark {
  display: block;
  flex: 0 0 auto;
  inline-size: var(--brand-mark-size, 2rem);
  block-size: var(--brand-mark-size, 2rem);
}
</style>
