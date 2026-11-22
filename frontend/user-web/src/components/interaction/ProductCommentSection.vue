<script setup lang="ts">
/*
 * Slot for the product comment component owned by the product-interaction work
 * package (S2-04, issue #76).
 *
 * Contract for the real component:
 *   props: { productId: string; canComment: boolean }
 *   reads: API-PRD-024 list comments, API-PRD-025 create, API-PRD-026 seller
 *          reply, API-PRD-027 delete own comment
 *
 * The placeholder keeps the layout slot stable so replacing it is a local change.
 */
defineProps<{ productId: string; canComment: boolean }>();
</script>

<template>
  <section class="card slot">
    <div class="card__head">
      <h2>商品评论</h2>
      <span class="chip">待接入</span>
    </div>
    <p class="muted">
      评论与卖方回复由商品互动工作包（S2-04 / #76）提供，接入后在此处显示评论列表与发表入口。
    </p>
    <p class="muted mono">ProductCommentSection · productId={{ productId }}</p>
  </section>
</template>

<style scoped>
.slot {
  border-style: dashed;
}
</style>
