<script setup lang="ts">
/*
 * Claimed review detail and decision. The current content, category
 * application and banned scope are read together; the decision is submitted
 * once and the page then shows the persisted result.
 */
import { computed, onMounted, ref } from "vue";
import type { ReviewDetail } from "../api/contracts";
import { AbortedError } from "../api/errors";
import { decideReview, readReviewDetail } from "../api/reviews";
import { formatCents, formatDateTime } from "../app/format";
import { IdempotencyKeys } from "../app/keys";
import { bannedGroupLabels, reviewDecisionLabels, reviewStatusLabels } from "../app/labels";
import { problemMessage } from "../app/problems";
import { routeHref } from "../app/routes";
import { notify } from "../app/toast";
import ErrorNotice from "../components/ErrorNotice.vue";
import LoadingBlock from "../components/LoadingBlock.vue";
import PageHeader from "../components/PageHeader.vue";

const props = defineProps<{ auditId: string }>();

const detail = ref<ReviewDetail | null>(null);
const loading = ref(false);
const error = ref<unknown>(null);
const decision = ref<"" | "approved" | "rejected">("");
const reason = ref("");
const categoryDecision = ref<"" | "approved" | "rejected">("");
const categoryReason = ref("");
const selectedBanned = ref<string[]>([]);
const formError = ref<string | null>(null);
const submitting = ref(false);
const keys = new IdempotencyKeys();
let controller: AbortController | null = null;

const pendingApplication = computed(() => detail.value?.category_application?.status === "pending");
const decided = computed(() => detail.value !== null && detail.value.status !== "pending");
const backHref = routeHref({ name: "reviews", ownership: "mine" });

async function load(): Promise<void> {
  controller?.abort();
  controller = new AbortController();
  loading.value = true;
  error.value = null;
  try {
    detail.value = await readReviewDetail(props.auditId, controller.signal);
    selectedBanned.value = [];
    decision.value = "";
    reason.value = "";
    categoryDecision.value = "";
    categoryReason.value = "";
    formError.value = null;
  } catch (caught) {
    if (caught instanceof AbortedError) return;
    error.value = caught;
  } finally {
    loading.value = false;
  }
}

onMounted(load);

function toggleBanned(id: string): void {
  selectedBanned.value = selectedBanned.value.includes(id)
    ? selectedBanned.value.filter((item) => item !== id)
    : [...selectedBanned.value, id];
}

async function submit(): Promise<void> {
  const review = detail.value;
  if (!review || submitting.value) return;
  formError.value = null;
  if (!decision.value) {
    formError.value = "请选择审核结论。";
    return;
  }
  if (decision.value === "rejected" && !reason.value.trim()) {
    formError.value = "不通过时必须填写审核原因。";
    return;
  }
  if (pendingApplication.value && !categoryDecision.value) {
    formError.value = "存在待审核的分类申请，请选择批准或不批准。";
    return;
  }
  if (categoryDecision.value === "rejected" && !categoryReason.value.trim()) {
    formError.value = "不批准分类申请时必须填写理由。";
    return;
  }

  submitting.value = true;
  const operation = `decision-${review.audit_id}`;
  try {
    await decideReview(
      review.audit_id,
      {
        decision: decision.value,
        reason: reason.value.trim() || undefined,
        banned_item_ids: selectedBanned.value,
        ...(pendingApplication.value
          ? {
              category_application_decision: categoryDecision.value || undefined,
              category_application_reason: categoryReason.value.trim() || undefined,
            }
          : {}),
      },
      keys.current(operation),
    );
    keys.rotate(operation);
    notify.success(decision.value === "approved" ? "审核已通过。" : "审核未通过。");
    await load();
  } catch (caught) {
    notify.error(problemMessage(caught));
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <div class="stack stack--loose">
    <PageHeader
      :eyebrow="`审核 #${auditId}`"
      :title="detail ? `审核商品 #${detail.product_id}` : '审核详情'"
      :description="
        detail
          ? `卖方 ${detail.seller.display_name} · 提交于 ${formatDateTime(detail.submitted_at)}`
          : '认领后读取当前内容、分类申请与禁发范围。'
      "
    >
      <template #actions>
        <a :href="backHref" class="btn btn--ghost">返回我的认领</a>
      </template>
    </PageHeader>

    <LoadingBlock v-if="loading && !detail" label="正在加载审核详情…" />
    <ErrorNotice v-else-if="error" :error="error" @retry="load" />

    <template v-else-if="detail">
      <div class="review-layout">
        <div class="stack stack--loose">
          <section class="card">
            <div class="card__head">
              <h2>当前内容</h2>
              <span class="chip">内容版本 {{ detail.current_content.content_version }}</span>
            </div>
            <p class="review-title">{{ detail.current_content.title }}</p>
            <p class="amount review-price">{{ formatCents(detail.current_content.price_cents) }}</p>
            <p class="inline">
              <span
                v-for="category in detail.current_content.categories"
                :key="category.id"
                class="chip"
              >
                {{ category.name }}
              </span>
              <span v-if="!detail.current_content.categories.length" class="muted">
                未选择分类
              </span>
            </p>
            <p class="review-description">{{ detail.current_content.description }}</p>
            <div v-if="detail.current_content.images.length" class="review-images">
              <figure
                v-for="image in detail.current_content.images"
                :key="image.file_id"
                class="review-image"
              >
                <img :src="image.url" :alt="`${detail.current_content.title} 的图片`" />
              </figure>
            </div>
            <p v-else class="muted">该商品没有图片。</p>
          </section>

          <section v-if="detail.category_application" class="card">
            <div class="card__head">
              <h2>分类申请</h2>
              <span class="chip">{{ detail.category_application.status }}</span>
            </div>
            <p>申请新分类：<strong>{{ detail.category_application.proposed_name }}</strong></p>
            <p class="muted">
              仅在本次商品审核通过时按结论批准公开；不批准时须先确保商品已有获认可分类。
            </p>
            <div v-if="pendingApplication" class="stack stack--tight decision-block">
              <label class="field">
                <span class="field__label">分类申请结论</span>
                <span class="inline">
                  <label class="inline"
                    ><input v-model="categoryDecision" type="radio" value="approved" /> 批准</label
                  >
                  <label class="inline"
                    ><input v-model="categoryDecision" type="radio" value="rejected" />
                    不批准</label
                  >
                </span>
              </label>
              <label class="field">
                <span class="field__label">分类申请理由</span>
                <textarea
                  v-model="categoryReason"
                  class="textarea"
                  rows="2"
                  placeholder="不批准时必填，例如：请改用已有分类"
                />
              </label>
            </div>
          </section>

          <section class="card">
            <div class="card__head">
              <h2>禁发范围</h2>
              <span class="chip">{{ detail.banned_scope.length }} 条</span>
            </div>
            <p class="muted">勾选本次审核依据的当前细目，作为结论依据保存。</p>
            <ul v-if="detail.banned_scope.length" class="banned-list">
              <li v-for="item in detail.banned_scope" :key="item.id">
                <label class="inline">
                  <input
                    type="checkbox"
                    :checked="selectedBanned.includes(item.id)"
                    :disabled="decided"
                    @change="toggleBanned(item.id)"
                  />
                  <span class="chip">{{ bannedGroupLabels[item.group] ?? item.group }}</span>
                  <span>{{ item.content }}</span>
                </label>
              </li>
            </ul>
            <p v-else class="muted">当前没有禁发细目。</p>
          </section>
        </div>

        <aside class="stack stack--loose">
          <section class="card">
            <div class="card__head">
              <h2>审核结论</h2>
              <span class="chip">{{ reviewStatusLabels[detail.status] ?? detail.status }}</span>
            </div>
            <dl class="facts">
              <dt>认领管理员</dt>
              <dd class="mono">#{{ detail.claim.manager_id }}</dd>
              <dt>认领时间</dt>
              <dd>{{ formatDateTime(detail.claim.claimed_at) }}</dd>
            </dl>

            <template v-if="!decided">
              <div class="divider" />
              <div class="stack stack--tight">
                <label class="field">
                  <span class="field__label">结论</span>
                  <span class="inline">
                    <label class="inline"
                      ><input v-model="decision" type="radio" value="approved" /> 通过</label
                    >
                    <label class="inline"
                      ><input v-model="decision" type="radio" value="rejected" /> 不通过</label
                    >
                  </span>
                </label>
                <label class="field">
                  <span class="field__label">审核原因</span>
                  <textarea
                    v-model="reason"
                    class="textarea"
                    rows="3"
                    placeholder="不通过时必填；通过时可补充说明"
                  />
                </label>
                <p v-if="formError" class="field__error" role="alert">{{ formError }}</p>
                <button
                  type="button"
                  class="btn btn--primary btn--block"
                  :disabled="submitting"
                  @click="submit"
                >
                  {{ submitting ? "正在提交…" : "提交审核结论" }}
                </button>
              </div>
            </template>

            <template v-else-if="detail.review_result">
              <div class="divider" />
              <dl class="facts">
                <dt>结论</dt>
                <dd>
                  {{
                    reviewDecisionLabels[detail.review_result.decision] ??
                    detail.review_result.decision
                  }}
                </dd>
                <dt>原因</dt>
                <dd>{{ detail.review_result.reason ?? "—" }}</dd>
                <dt>审核内容版本</dt>
                <dd>{{ detail.review_result.reviewed_content_version }}</dd>
                <dt>时间</dt>
                <dd>{{ formatDateTime(detail.review_result.decided_at) }}</dd>
              </dl>
            </template>
          </section>

          <section class="card muted">
            <p>审核结论提交后，卖方按站内通知获知结果；通过后商品进入公开可交易状态。</p>
          </section>
        </aside>
      </div>
    </template>
  </div>
</template>

<style scoped>
.review-layout {
  display: grid;
  gap: var(--space-4);
}

.review-title {
  font-size: 1.125rem;
  font-weight: 650;
  margin-block-end: var(--space-1);
}

.review-price {
  color: var(--accent);
  font-size: 1.25rem;
}

.review-description {
  margin-block-start: var(--space-3);
  color: var(--ink-soft);
  white-space: pre-line;
  overflow-wrap: anywhere;
}

.review-images {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(8rem, 1fr));
  gap: var(--space-2);
  margin-block-start: var(--space-3);
}

.review-image {
  margin: 0;
  aspect-ratio: 4 / 3;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: #f4f8f5;
}

.review-image img {
  inline-size: 100%;
  block-size: 100%;
  object-fit: contain;
}

.banned-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin-block-start: var(--space-3);
}

.decision-block {
  margin-block-start: var(--space-3);
}

.facts {
  display: grid;
  grid-template-columns: minmax(5rem, auto) 1fr;
  gap: var(--space-2) var(--space-3);
  margin: 0;
  font-size: 0.875rem;
}

.facts dt {
  color: var(--ink-faint);
}

.facts dd {
  margin: 0;
}

@media (width >= 68rem) {
  .review-layout {
    grid-template-columns: minmax(0, 1.35fr) minmax(18rem, 1fr);
    align-items: start;
  }

  .review-layout > aside {
    position: sticky;
    inset-block-start: var(--space-4);
  }
}
</style>
