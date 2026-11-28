<script setup lang="ts">
/*
 * Trade reviews for the completed deal.
 *
 * Eligibility comes only from the server projection (`can_review`); the screen
 * never derives it from the trade status. Both the review written by the viewer
 * and the one received from the counterparty are shown so a refresh or another
 * device sees the same state.
 */
import { computed, onMounted, reactive, ref, watch } from "vue";
import { ApiError } from "../../api/errors";
import type { TradeReview, TradeReviewsView } from "../../api/contracts";
import { getTradeReviews, submitTradeReview } from "../../api/trades";
import { useAsyncData } from "../../app/async";
import { formatDateTime } from "../../app/format";
import { IdempotencyKeys } from "../../app/keys";
import { problemMessage } from "../../app/problems";
import { useToastStore } from "../../app/toast";
import AvatarBadge from "../AvatarBadge.vue";
import ErrorNotice from "../ErrorNotice.vue";
import LoadingBlock from "../LoadingBlock.vue";

const { notify } = useToastStore();

const props = defineProps<{ tradeId: string; revieweeName: string }>();

const review = useAsyncData<TradeReviewsView>((signal) => getTradeReviews(props.tradeId, signal));
const keys = new IdempotencyKeys();
const form = reactive({ rating: 0, content: "" });
const pending = ref(false);
const formError = ref<string | null>(null);

const ratingOptions = [
  { value: 5, label: "5 分 · 非常满意" },
  { value: 4, label: "4 分 · 满意" },
  { value: 3, label: "3 分 · 一般" },
  { value: 2, label: "2 分 · 不满意" },
  { value: 1, label: "1 分 · 很不满意" },
] as const;

const writtenReview = computed(() => review.data.value?.written ?? null);
const receivedReview = computed(() => review.data.value?.received ?? null);
const canReview = computed(() => review.data.value?.can_review ?? false);
const hasAnyReview = computed(() => Boolean(writtenReview.value || receivedReview.value));

function resetForm(): void {
  form.rating = 0;
  form.content = "";
  formError.value = null;
}

function reviewContent(value: TradeReview): string | null {
  const text = value.content?.trim();
  return text ? text : null;
}

async function load(): Promise<void> {
  await review.run();
}

async function submit(): Promise<void> {
  if (pending.value) return;
  formError.value = null;
  const content = form.content.trim();
  if (form.rating < 1 || form.rating > 5) {
    formError.value = "请选择 1—5 分的评分。";
    return;
  }
  if (content.length < 1 || content.length > 2000) {
    formError.value = "请填写 1—2000 个字符的评价内容。";
    return;
  }
  pending.value = true;
  try {
    const result = await submitTradeReview(
      props.tradeId,
      { rating: form.rating, content },
      keys.current("submit-review"),
    );
    keys.rotate("submit-review");
    if (review.data.value) {
      review.data.value = {
        ...review.data.value,
        can_review: false,
        written: result.review,
      };
    }
    resetForm();
    notify.success("评价已提交。");
    await load();
  } catch (caught) {
    formError.value = problemMessage(caught);
    // Another device may have submitted first; reload the authoritative state
    // while this form keeps its values if the failure was not "already reviewed".
    if (
      caught instanceof ApiError &&
      (caught.status === 409 || caught.code === "REVIEW_ALREADY_SUBMITTED")
    ) {
      void load();
    }
  } finally {
    pending.value = false;
  }
}

watch(
  () => props.tradeId,
  () => {
    resetForm();
    void load();
  },
);

onMounted(load);
</script>

<template>
  <section class="card review-section" aria-labelledby="trade-review-title">
    <div class="card__head">
      <h2 id="trade-review-title">评价</h2>
      <span v-if="canReview" class="chip chip--active">待评价</span>
      <span v-else-if="writtenReview" class="chip">已评价</span>
    </div>

    <LoadingBlock v-if="review.isLoading.value && !review.data.value" label="正在加载评价…" />
    <ErrorNotice v-else-if="review.problem.value" :error="review.error.value" @retry="load" />
    <template v-else-if="review.data.value">
      <div v-if="hasAnyReview" class="review-list">
        <article v-if="receivedReview" class="review">
          <div class="review__head">
            <AvatarBadge
              :display-name="receivedReview.reviewer.display_name"
              :url="receivedReview.reviewer.avatar_url"
              size="sm"
            />
            <p class="review__people">
              <strong>{{ receivedReview.reviewer.display_name }}</strong>
              <span class="muted">写给你</span>
            </p>
            <span class="chip">收到的评价</span>
          </div>
          <p class="review__rating">评分 {{ receivedReview.rating }}/5</p>
          <p v-if="reviewContent(receivedReview)" class="review__body pre-line break-anywhere">
            {{ reviewContent(receivedReview) }}
          </p>
          <time class="muted review__time" :datetime="receivedReview.created_at">
            {{ formatDateTime(receivedReview.created_at) }}
          </time>
        </article>

        <article v-if="writtenReview" class="review">
          <div class="review__head">
            <AvatarBadge
              :display-name="writtenReview.reviewer.display_name"
              :url="writtenReview.reviewer.avatar_url"
              size="sm"
            />
            <p class="review__people">
              <strong>{{ writtenReview.reviewer.display_name }}</strong>
              <span class="muted"> 评价 {{ writtenReview.reviewee.display_name }} </span>
            </p>
            <span class="chip chip--active">我写的评价</span>
          </div>
          <p class="review__rating">评分 {{ writtenReview.rating }}/5</p>
          <p v-if="reviewContent(writtenReview)" class="review__body pre-line break-anywhere">
            {{ reviewContent(writtenReview) }}
          </p>
          <time class="muted review__time" :datetime="writtenReview.created_at">
            {{ formatDateTime(writtenReview.created_at) }}
          </time>
        </article>
      </div>

      <form
        v-if="canReview"
        class="review-form"
        aria-labelledby="review-form-title"
        @submit.prevent="submit"
      >
        <h3 id="review-form-title">评价与 {{ revieweeName }} 的交易</h3>
        <fieldset class="rating-group">
          <legend>评分</legend>
          <div class="rating-options">
            <label
              v-for="option in ratingOptions"
              :key="option.value"
              class="rating-option"
              :for="`review-rating-${option.value}`"
            >
              <input
                :id="`review-rating-${option.value}`"
                v-model.number="form.rating"
                type="radio"
                name="rating"
                :value="option.value"
                required
              />
              <span>{{ option.label }}</span>
            </label>
          </div>
        </fieldset>
        <div class="field">
          <label class="field__label" for="review-content">评价内容</label>
          <textarea
            id="review-content"
            v-model="form.content"
            class="textarea"
            name="content"
            rows="4"
            minlength="1"
            maxlength="2000"
            required
            :aria-describedby="
              formError ? 'review-content-hint review-form-error' : 'review-content-hint'
            "
          />
          <span id="review-content-hint" class="field__hint">
            {{ form.content.length }}/2000，将作为普通文本显示
          </span>
        </div>
        <p v-if="formError" id="review-form-error" class="field__error" role="alert">
          {{ formError }}
        </p>
        <div class="inline">
          <button type="submit" class="btn btn--primary" :disabled="pending">
            {{ pending ? "正在提交…" : "提交评价" }}
          </button>
        </div>
      </form>

      <p v-else-if="!hasAnyReview" class="muted">本次交易暂无可展示的评价。</p>
      <p v-else-if="!writtenReview" class="muted">
        评价已完成或当前不可提交，刷新后仍会显示已有评价。
      </p>
    </template>
  </section>
</template>

<style scoped>
.review-section {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.review-list {
  display: grid;
  gap: var(--space-3);
}

.review {
  display: grid;
  gap: var(--space-2);
  padding: var(--space-3);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--panel-soft);
}

.review__head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.review__people {
  display: flex;
  gap: var(--space-1);
  align-items: baseline;
  min-inline-size: 0;
  margin: 0;
  font-size: 0.875rem;
}

.review__people .muted {
  font-size: 0.75rem;
}

.review__head .chip {
  margin-inline-start: auto;
}

.review__rating {
  margin: 0;
  color: var(--accent);
  font-size: 0.875rem;
  font-weight: 650;
}

.review__body {
  margin: 0;
  color: var(--ink-soft);
  font-size: 0.9375rem;
}

.review__time {
  font-size: 0.75rem;
}

.review-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  border-block-start: 1px solid var(--line);
  padding-block-start: var(--space-4);
}

.review-form h3 {
  font-size: 1rem;
}

.rating-group {
  display: grid;
  gap: var(--space-2);
  margin: 0;
  padding: 0;
  border: 0;
}

.rating-group legend {
  margin-block-end: var(--space-2);
  color: var(--ink-soft);
  font-size: 0.8125rem;
  font-weight: 650;
}

.rating-options {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.rating-option {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  min-block-size: var(--control-min-block);
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--panel);
  font-size: 0.8125rem;
  cursor: pointer;
}

.rating-option:has(input:checked) {
  border-color: var(--brand);
  background: var(--brand-soft);
}

.rating-option:has(input:focus-visible) {
  outline: 2px solid var(--brand);
  outline-offset: 2px;
}

.rating-option input {
  accent-color: var(--brand);
  inline-size: 1rem;
  block-size: 1rem;
}
</style>
