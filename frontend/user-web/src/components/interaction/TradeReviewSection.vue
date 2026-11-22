<script setup lang="ts">
/*
 * Slot for the evaluation component owned by the interaction work package.
 *
 * Contract for the real component:
 *   props: { tradeId: string; canReview: boolean; revieweeName: string }
 *   reads: API-TRD-012 submit review
 *
 * Review eligibility and its entry point belong to the conversation work package
 * (#80); the trade view exposes no `submit_review` allowed action, so `canReview`
 * currently only reflects that the trade is completed.
 *
 * Issue #79 delivers the entry point only; the record and its management UI
 * belong to the S2-04 / S3-04 work packages.
 */
defineProps<{ tradeId: string; canReview: boolean; revieweeName: string }>();
</script>

<template>
  <section class="card slot">
    <div class="card__head">
      <h2>评价</h2>
      <span class="chip">待接入</span>
    </div>
    <p class="muted">成交评价由互动工作包提供；交易完成后可在此评价 {{ revieweeName }}。</p>
    <p class="muted mono">TradeReviewSection · tradeId={{ tradeId }} · canReview={{ canReview }}</p>
  </section>
</template>

<style scoped>
.slot {
  border-style: dashed;
}
</style>
