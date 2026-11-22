<script setup lang="ts">
/*
 * Slot for the favourite control owned by the product-interaction work package
 * (S2-04, issue #76).
 *
 * Contract for the real component:
 *   props: { productId: string }
 *   reads: API-PRD-029 favourite status, API-PRD-030 add, API-PRD-031 remove
 *
 * A disabled control is rendered instead of a silent no-op so the user is not
 * told the action succeeded when the capability is not wired yet.
 */
defineProps<{ productId: string }>();
</script>

<template>
  <span class="slot-control" :title="`收藏能力由商品互动工作包提供（productId=${productId}）`">
    <button type="button" class="btn btn--ghost" disabled>收藏（待接入）</button>
  </span>
</template>

<style scoped>
.slot-control {
  display: inline-flex;
}
</style>
