<script setup lang="ts">
/*
 * Product detail for both roles.
 *
 * The seller sees the review outcome, the display restrictions and the actions
 * the server says are currently allowed; a visitor sees the public content plus
 * the ways to start a purchase request or a private conversation. Buttons are
 * rendered from `permissions` rather than guessed from the lifecycle state so the
 * interface cannot offer an action the backend would reject.
 */
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  getProduct,
  resubmitForReview,
  takeOffShelf,
  putOnShelf,
  withdrawPendingProduct,
} from "../../api/products";
import { createPurchaseRequest } from "../../api/trades";
import { ensurePrivateConversation } from "../../api/conversations";
import type { ProductDetail } from "../../api/contracts";
import { useAsyncData } from "../../app/async";
import { formatCents, formatDateTime, formatRelative } from "../../app/format";
import { productLifecycleLabels, productLifecycleTones } from "../../app/labels";
import { IdempotencyKeys } from "../../app/keys";
import { problemMessage } from "../../app/problems";
import { notify } from "../../app/toast";
import { refreshBadges } from "../../app/badges";
import { session } from "../../app/session";
import ActionButton from "../../components/ActionButton.vue";
import AvatarBadge from "../../components/AvatarBadge.vue";
import ConfirmDialog from "../../components/ConfirmDialog.vue";
import EmptyState from "../../components/EmptyState.vue";
import ErrorNotice from "../../components/ErrorNotice.vue";
import LoadingBlock from "../../components/LoadingBlock.vue";
import PageHeader from "../../components/PageHeader.vue";
import StateBadge from "../../components/StateBadge.vue";
import ProductCommentSection from "../../components/interaction/ProductCommentSection.vue";
import ProductFavoriteControl from "../../components/interaction/ProductFavoriteControl.vue";

const route = useRoute();
const router = useRouter();
const productId = computed(() => String(route.params.productId ?? ""));

const product = useAsyncData<ProductDetail>((signal) => getProduct(productId.value, signal));
const keys = new IdempotencyKeys();

const purchaseNote = ref("");
const purchaseOpen = ref(false);
const cancelOpen = ref(false);
const purchaseError = ref<string | null>(null);
const purchasePending = ref(false);
const contactPending = ref(false);

const isOwner = computed(
  () => product.data.value !== null && product.data.value.seller.id === session.accountId.value,
);
const permissions = computed(() => product.data.value?.permissions ?? null);
const activeImageIndex = ref(0);
const images = computed(() => product.data.value?.images ?? []);
const activeImage = computed(() => images.value[activeImageIndex.value] ?? null);
const canComment = computed(() => {
  const state = product.data.value?.lifecycle_state;
  return !isOwner.value && (state === "public" || state === "in_trade");
});

watch(productId, () => {
  activeImageIndex.value = 0;
  void product.run();
});

watch(
  () => product.data.value?.id,
  () => {
    activeImageIndex.value = 0;
  },
);

onMounted(() => {
  void product.run();
});

async function reload(): Promise<void> {
  await product.run();
  void refreshBadges();
}

async function runAction(operation: string, task: () => Promise<void>): Promise<void> {
  await task();
  keys.rotate(operation);
  await reload();
}

async function submitPurchase(): Promise<void> {
  const detail = product.data.value;
  if (!detail || purchasePending.value) return;
  purchaseError.value = null;
  purchasePending.value = true;
  try {
    const trade = await createPurchaseRequest(
      detail.id,
      {
        note: purchaseNote.value.trim() || undefined,
        expected_product_version: detail.content_version,
      },
      keys.current("purchase"),
    );
    keys.rotate("purchase");
    purchaseOpen.value = false;
    notify.success("购买请求已提交，等待卖方接受。");
    await router.push({ name: "trade-detail", params: { tradeId: trade.id } });
  } catch (caught) {
    purchaseError.value = problemMessage(caught);
  } finally {
    purchasePending.value = false;
  }
}

async function contactSeller(): Promise<void> {
  const detail = product.data.value;
  if (!detail || contactPending.value) return;
  contactPending.value = true;
  try {
    const conversation = await ensurePrivateConversation(detail.seller.id, keys.current("contact"));
    keys.rotate("contact");
    await router.push({
      name: "conversation",
      params: {
        kind: conversation.conversation_kind,
        conversationId: conversation.conversation_id,
      },
    });
  } catch (caught) {
    notify.error(problemMessage(caught));
  } finally {
    contactPending.value = false;
  }
}

async function confirmOffShelf(): Promise<void> {
  const detail = product.data.value;
  if (!detail) return;
  cancelOpen.value = false;
  await runAction("off-shelf", async () => {
    const result = await takeOffShelf(detail.id, detail.content_version, keys.current("off-shelf"));
    notify.success(
      result.closed_pending_request_count > 0
        ? `商品已下架，${result.closed_pending_request_count} 条待接受请求已关闭。`
        : "商品已下架。",
    );
  });
}
</script>

<template>
  <div class="stack stack--loose">
    <LoadingBlock v-if="product.isLoading.value && !product.data.value" label="正在加载商品…" />
    <ErrorNotice
      v-else-if="product.problem.value"
      :error="product.error.value"
      @retry="product.run"
    />
    <template v-else-if="product.data.value">
      <PageHeader
        :eyebrow="isOwner ? '我的商品' : '商品详情'"
        :title="product.data.value.title"
        :description="!isOwner ? `${product.data.value.seller.display_name} 发布` : undefined"
      >
        <template #actions>
          <RouterLink v-if="isOwner" to="/me/products" class="btn btn--ghost">
            返回我的商品
          </RouterLink>
          <RouterLink v-else to="/" class="btn btn--ghost">返回列表</RouterLink>
        </template>
      </PageHeader>

      <div class="detail">
        <section class="card gallery">
          <div class="gallery__main">
            <img
              v-if="activeImage"
              :src="activeImage.url"
              :alt="product.data.value.title"
              class="gallery__image"
            />
            <span v-else class="gallery__placeholder">该商品暂无图片</span>
          </div>
          <div v-if="images.length > 1" class="gallery__thumbs">
            <button
              v-for="(image, index) in images"
              :key="image.file_id"
              type="button"
              class="gallery__thumb"
              :class="{ 'gallery__thumb--active': index === activeImageIndex }"
              @click="activeImageIndex = index"
            >
              <img :src="image.url" :alt="`商品图片 ${index + 1}`" />
            </button>
          </div>
        </section>

        <section class="card summary">
          <div class="inline">
            <StateBadge
              :label="productLifecycleLabels[product.data.value.lifecycle_state]"
              :tone="productLifecycleTones[product.data.value.lifecycle_state]"
            />
            <span class="muted">发布于 {{ formatRelative(product.data.value.created_at) }}</span>
          </div>
          <p class="summary__price amount">{{ formatCents(product.data.value.price_cents) }}</p>
          <p class="inline">
            <span v-for="category in product.data.value.categories" :key="category.id" class="tag">
              {{ category.name }}
            </span>
            <span v-if="!product.data.value.categories.length" class="muted">未分类</span>
          </p>
          <div class="seller">
            <AvatarBadge :display-name="product.data.value.seller.display_name" size="sm" />
            <span>{{ product.data.value.seller.display_name }}</span>
          </div>
          <p class="summary__description pre-line break-anywhere">
            {{ product.data.value.description }}
          </p>

          <div v-if="!isOwner" class="summary__actions">
            <button
              type="button"
              class="btn btn--primary"
              :disabled="product.data.value.lifecycle_state !== 'public'"
              @click="purchaseOpen = true"
            >
              发起购买请求
            </button>
            <button type="button" class="btn" :disabled="contactPending" @click="contactSeller">
              {{ contactPending ? "正在打开会话…" : "咨询卖方" }}
            </button>
            <ProductFavoriteControl :product-id="product.data.value.id" />
          </div>
          <p
            v-if="!isOwner && product.data.value.lifecycle_state !== 'public'"
            class="banner banner--warn"
          >
            该商品当前不可发起新的购买请求。
          </p>
        </section>
      </div>

      <section v-if="isOwner" class="card">
        <div class="card__head"><h2>审核与状态</h2></div>
        <dl class="facts">
          <dt>当前状态</dt>
          <dd>
            <StateBadge
              :label="productLifecycleLabels[product.data.value.lifecycle_state]"
              :tone="productLifecycleTones[product.data.value.lifecycle_state]"
            />
          </dd>
          <template v-if="product.data.value.pending_review">
            <dt>待审核</dt>
            <dd>于 {{ formatDateTime(product.data.value.pending_review.submitted_at) }} 提交</dd>
          </template>
          <template v-if="product.data.value.latest_review">
            <dt>最近审核</dt>
            <dd class="stack stack--tight">
              <span>
                {{ product.data.value.latest_review.status === "passed" ? "已通过" : "" }}
                {{ product.data.value.latest_review.status === "rejected" ? "未通过" : "" }}
                {{ product.data.value.latest_review.status === "withdrawn" ? "已撤回" : "" }}
                {{ product.data.value.latest_review.status === "pending" ? "待审核" : "" }}
                <span v-if="product.data.value.latest_review.decided_at" class="muted">
                  · {{ formatDateTime(product.data.value.latest_review.decided_at) }}
                </span>
              </span>
              <span v-if="product.data.value.latest_review.reason" class="banner banner--warn">
                拒绝原因：{{ product.data.value.latest_review.reason }}
              </span>
            </dd>
          </template>
          <template v-if="product.data.value.display_restrictions?.length">
            <dt>展示限制</dt>
            <dd class="stack stack--tight">
              <span
                v-for="restriction in product.data.value.display_restrictions"
                :key="`${restriction.source_type}-${restriction.created_at}`"
                class="banner banner--warn"
              >
                {{ restriction.reason }}（{{ formatDateTime(restriction.created_at) }}）
              </span>
            </dd>
          </template>
        </dl>

        <div class="inline owner-actions">
          <RouterLink
            v-if="permissions?.can_edit"
            :to="{ name: 'product-edit', params: { productId: product.data.value.id } }"
            class="btn"
          >
            编辑内容
          </RouterLink>
          <ActionButton
            v-if="permissions?.can_off_shelf"
            label="主动下架"
            variant="ghost"
            :task="
              async () => {
                cancelOpen = true;
              }
            "
          />
          <ActionButton
            v-if="permissions?.can_relist"
            label="重新上架"
            variant="primary"
            :task="
              async () => {
                await runAction('on-shelf', async () => {
                  await putOnShelf(
                    product.data.value!.id,
                    product.data.value!.content_version,
                    keys.current('on-shelf'),
                  );
                  notify.success('商品已重新上架。');
                });
              }
            "
          />
          <ActionButton
            v-if="permissions?.can_submit_review"
            label="重新提交审核"
            variant="primary"
            :task="
              async () => {
                await runAction('resubmit', async () => {
                  await resubmitForReview(
                    product.data.value!.id,
                    product.data.value!.content_version,
                    keys.current('resubmit'),
                  );
                  notify.success('已重新提交审核。');
                });
              }
            "
          />
          <ActionButton
            v-if="permissions?.can_withdraw_review"
            label="撤回待审商品"
            variant="ghost"
            :task="
              async () => {
                await runAction('withdraw', async () => {
                  await withdrawPendingProduct(
                    product.data.value!.id,
                    product.data.value!.content_version,
                    keys.current('withdraw'),
                  );
                  notify.success('商品已撤回，状态为已下架。');
                });
              }
            "
          />
        </div>
      </section>

      <ProductCommentSection
        :product-id="product.data.value.id"
        :can-comment="canComment"
        :seller-id="product.data.value.seller.id"
      />
    </template>

    <EmptyState
      v-else
      title="没有找到该商品"
      description="它可能已下架、被撤回，或你当前无权查看。"
    >
      <RouterLink to="/" class="btn">返回逛逛</RouterLink>
    </EmptyState>

    <ConfirmDialog
      :open="cancelOpen"
      title="主动下架该商品？"
      description="下架后商品不再出现在搜索结果中，该商品上的待接受请求会被关闭并通知买方。"
      confirm-label="确认下架"
      tone="danger"
      @cancel="cancelOpen = false"
      @confirm="confirmOffShelf"
    />

    <ConfirmDialog
      :open="purchaseOpen"
      title="发起购买请求"
      description="卖方接受后商品将锁定给你，其他待接受请求会关闭。"
      confirm-label="提交请求"
      @cancel="purchaseOpen = false"
      @confirm="submitPurchase"
    >
      <div class="field">
        <label class="field__label" for="purchase-note">给卖方的说明（可选）</label>
        <textarea
          id="purchase-note"
          v-model="purchaseNote"
          class="textarea"
          maxlength="500"
          placeholder="例如：今晚可以自取，六点后方便"
        />
        <span class="field__hint">{{ purchaseNote.length }}/500</span>
      </div>
      <p v-if="purchaseError" class="field__error" role="alert">{{ purchaseError }}</p>
      <p v-if="purchasePending" class="muted">正在提交…</p>
    </ConfirmDialog>
  </div>
</template>

<style scoped>
.detail {
  display: grid;
  gap: var(--space-4);
}

.gallery__main {
  display: grid;
  place-items: center;
  aspect-ratio: 4 / 3;
  border-radius: var(--radius-sm);
  overflow: hidden;
  background: #f4f8f5;
}

.gallery__image {
  inline-size: 100%;
  block-size: 100%;
  object-fit: contain;
}

.gallery__placeholder {
  font-size: 0.875rem;
  color: var(--ink-faint);
}

.gallery__thumbs {
  display: flex;
  gap: var(--space-2);
  margin-block-start: var(--space-3);
  flex-wrap: wrap;
}

.gallery__thumb {
  inline-size: 3.5rem;
  block-size: 3.5rem;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  overflow: hidden;
  padding: 0;
  background: none;
  cursor: pointer;
}

.gallery__thumb--active {
  border-color: var(--brand);
  outline: 2px solid var(--brand-soft);
}

.gallery__thumb img {
  inline-size: 100%;
  block-size: 100%;
  object-fit: cover;
}

.summary {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.summary__price {
  font-size: 1.75rem;
  color: var(--accent);
}

.summary__description {
  color: var(--ink-soft);
  font-size: 0.875rem;
}

.summary__actions {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
  border-block-start: 1px solid var(--line);
  padding-block-start: var(--space-3);
}

.seller {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: 0.875rem;
}

.facts {
  display: grid;
  grid-template-columns: minmax(5.5rem, auto) 1fr;
  gap: var(--space-2) var(--space-4);
  margin: 0;
  font-size: 0.875rem;
}

.facts dt {
  color: var(--ink-faint);
}

.facts dd {
  margin: 0;
}

.owner-actions {
  margin-block-start: var(--space-4);
  border-block-start: 1px solid var(--line);
  padding-block-start: var(--space-3);
}

@media (width >= 48rem) {
  .detail {
    grid-template-columns: minmax(0, 1.1fr) minmax(0, 1fr);
    align-items: start;
  }
}
</style>
