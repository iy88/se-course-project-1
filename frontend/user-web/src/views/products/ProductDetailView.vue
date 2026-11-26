<script setup lang="ts">
/*
 * Product detail for both roles.
 *
 * The seller sees the review outcome, the display restrictions and the actions
 * the server says are currently allowed; a visitor sees the public content plus
 * the available actions. Buttons are
 * rendered from `permissions` rather than guessed from the lifecycle state so the
 * interface cannot offer an action the backend would reject.
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import UiIcon from "../../../../shared/UiIcon.vue";
import {
  getProduct,
  resubmitForReview,
  takeOffShelf,
  putOnShelf,
  withdrawPendingProduct,
} from "../../api/products";
import { createPurchaseRequest } from "../../api/trades";
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
import StateBadge from "../../components/StateBadge.vue";
import ProductCommentSection from "../../components/interaction/ProductCommentSection.vue";
import ProductFavoriteControl from "../../components/interaction/ProductFavoriteControl.vue";
import StartChatButton from "../../components/interaction/StartChatButton.vue";

const route = useRoute();
const router = useRouter();
const productId = computed(() => String(route.params.productId ?? ""));

const product = useAsyncData<ProductDetail>((signal) => getProduct(productId.value, signal));
const keys = new IdempotencyKeys();

const purchaseNote = ref("");
const purchaseOpen = ref(false);
const cancelOpen = ref(false);
const relistOpen = ref(false);
const relistPending = ref(false);
const relistError = ref<string | null>(null);
const purchaseError = ref<string | null>(null);
const purchasePending = ref(false);

const isOwner = computed(
  () => product.data.value !== null && product.data.value.seller.id === session.accountId.value,
);
const permissions = computed(() => product.data.value?.permissions ?? null);
const activeImageIndex = ref(0);
const galleryTrack = ref<HTMLDivElement | null>(null);
const images = computed(() => product.data.value?.images ?? []);
const activeImage = computed(() => images.value[activeImageIndex.value] ?? null);
let galleryFrame = 0;
const canComment = computed(() => {
  const state = product.data.value?.lifecycle_state;
  return !isOwner.value && (state === "public" || state === "in_trade");
});
const ownerGuidance = computed(() => {
  switch (product.data.value?.lifecycle_state) {
    case "pending_review":
      return "当前为仅你可见的预览，审核结论以最新保存内容为准。";
    case "review_rejected":
      return "根据审核意见修改内容后，可以重新提交审核。";
    case "public":
      return "商品正在列表中公开展示。";
    case "in_trade":
      return "交易进行中，商品关键内容暂不可修改。";
    case "off_shelf":
      return "商品当前不在公开展示中，可按可用操作重新上架或提交审核。";
    default:
      return "";
  }
});

watch(productId, () => {
  relistOpen.value = false;
  activeImageIndex.value = 0;
  void product.run();
});

watch(
  () => product.data.value?.id,
  () => {
    activeImageIndex.value = 0;
    void nextTick(() => {
      galleryTrack.value?.scrollTo({ left: 0 });
    });
  },
);

onMounted(() => {
  void product.run();
});

onBeforeUnmount(() => {
  if (galleryFrame) cancelAnimationFrame(galleryFrame);
});

function onGalleryScroll(): void {
  if (galleryFrame) return;
  galleryFrame = requestAnimationFrame(() => {
    galleryFrame = 0;
    const track = galleryTrack.value;
    if (!track || track.clientWidth === 0) return;
    const index = Math.round(track.scrollLeft / track.clientWidth);
    if (index >= 0 && index < images.value.length) {
      activeImageIndex.value = index;
    }
  });
}

function selectImage(index: number): void {
  activeImageIndex.value = index;
  const track = galleryTrack.value;
  if (!track) return;
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  track.scrollTo({
    left: index * track.clientWidth,
    behavior: reduceMotion ? "auto" : "smooth",
  });
}

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
    if (trade.trade_conversation_id) {
      await router.push({
        name: "conversation",
        params: { kind: "trade", conversationId: trade.trade_conversation_id },
      });
    } else {
      await router.push({ name: "trade-detail", params: { tradeId: trade.id } });
    }
  } catch (caught) {
    purchaseError.value = problemMessage(caught);
  } finally {
    purchasePending.value = false;
  }
}

function openRelist(): void {
  relistError.value = null;
  relistOpen.value = true;
}

async function confirmRelist(): Promise<void> {
  const detail = product.data.value;
  if (!relistOpen.value || relistPending.value || detail?.id !== productId.value) return;
  if (!detail.permissions?.can_relist) return;

  relistPending.value = true;
  relistError.value = null;
  try {
    await runAction("on-shelf", async () => {
      await putOnShelf(detail.id, detail.content_version, keys.current("on-shelf"));
      relistOpen.value = false;
      notify.success("商品已重新上架。");
    });
  } catch (caught) {
    relistError.value = problemMessage(caught);
  } finally {
    relistPending.value = false;
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
      <div class="product-page">
        <header class="product-head">
          <div class="product-head__copy">
            <p class="product-head__eyebrow">{{ isOwner ? "我的商品" : "商品详情" }}</p>
            <h1 id="product-title">{{ product.data.value.title }}</h1>
            <p v-if="!isOwner" class="product-head__meta">
              由 {{ product.data.value.seller.display_name }} 发布
            </p>
          </div>
          <RouterLink v-if="isOwner" to="/me/products" class="btn btn--ghost product-head__back">
            <UiIcon name="chevron-right" />
            返回我的商品
          </RouterLink>
          <RouterLink v-else to="/" class="btn btn--ghost product-head__back">
            <UiIcon name="chevron-right" />
            返回列表
          </RouterLink>
        </header>

        <section class="product-hero" aria-labelledby="product-title">
          <div class="gallery">
            <div class="gallery__main">
              <div
                v-if="images.length"
                ref="galleryTrack"
                class="gallery__track"
                role="group"
                aria-roledescription="carousel"
                :aria-label="`${product.data.value.title} 商品图片`"
                tabindex="0"
                @scroll.passive="onGalleryScroll"
              >
                <div
                  v-for="(image, index) in images"
                  :key="image.file_id"
                  class="gallery__slide"
                  role="group"
                  aria-roledescription="slide"
                  :aria-label="`第 ${index + 1} 张，共 ${images.length} 张`"
                >
                  <img
                    :src="image.url"
                    :alt="`${product.data.value.title}，第 ${index + 1} 张`"
                    class="gallery__image"
                    :fetchpriority="index === 0 ? 'high' : 'auto'"
                    :loading="index === 0 ? 'eager' : 'lazy'"
                    decoding="async"
                  />
                </div>
              </div>
              <span v-if="images.length > 1" class="gallery__count">
                {{ activeImageIndex + 1 }} / {{ images.length }}
              </span>
              <span v-else-if="!activeImage" class="gallery__placeholder">
                <UiIcon name="box" />
                <span>卖家未上传商品图片</span>
              </span>
              <p class="visually-hidden" role="status" aria-live="polite">
                {{
                  images.length
                    ? `正在查看第 ${activeImageIndex + 1} 张，共 ${images.length} 张`
                    : ""
                }}
              </p>
            </div>
            <div v-if="images.length > 1" class="gallery__thumbs">
              <button
                v-for="(image, index) in images"
                :key="image.file_id"
                type="button"
                class="gallery__thumb"
                :class="{ 'gallery__thumb--active': index === activeImageIndex }"
                :aria-label="`查看第 ${index + 1} 张商品图片`"
                :aria-pressed="index === activeImageIndex"
                @click="selectImage(index)"
              >
                <img :src="image.url" :alt="`商品图片 ${index + 1}`" />
              </button>
            </div>
          </div>

          <div class="summary">
            <div class="summary__status">
              <StateBadge
                :label="productLifecycleLabels[product.data.value.lifecycle_state]"
                :tone="productLifecycleTones[product.data.value.lifecycle_state]"
              />
              <span>发布于 {{ formatRelative(product.data.value.created_at) }}</span>
            </div>
            <p class="summary__price amount">{{ formatCents(product.data.value.price_cents) }}</p>
            <p class="summary__categories">
              <span
                v-for="category in product.data.value.categories"
                :key="category.id"
                class="tag"
              >
                {{ category.name }}
              </span>
              <span
                v-if="
                  !product.data.value.categories.length &&
                  product.data.value.category_application?.status === 'pending'
                "
                class="tag"
              >
                {{ product.data.value.category_application.proposed_name }} · 审核中
              </span>
              <span
                v-else-if="!product.data.value.categories.length"
                class="summary__uncategorized"
              >
                未分类
              </span>
            </p>

            <div class="seller">
              <AvatarBadge
                :display-name="product.data.value.seller.display_name"
                :url="product.data.value.seller.avatar_url"
                size="sm"
              />
              <span class="seller__copy">
                <span>卖家</span>
                <strong>{{ product.data.value.seller.display_name }}</strong>
              </span>
            </div>
            <div v-if="!isOwner" class="seller-contact">
              <p class="muted">有疑问可直接私聊卖家；这里不会自动发送消息或创建购买请求。</p>
              <StartChatButton
                :target-account-id="product.data.value.seller.id"
                :target-name="product.data.value.seller.display_name"
                label="联系卖家"
                variant="ghost"
              />
            </div>

            <div class="summary__description">
              <h2>商品描述</h2>
              <p class="pre-line break-anywhere">{{ product.data.value.description }}</p>
            </div>

            <div v-if="isOwner" class="summary__owner-note">
              <strong>当前状态</strong>
              <p>{{ ownerGuidance }}</p>
            </div>

            <div v-if="!isOwner" class="summary__actions">
              <button
                type="button"
                class="btn btn--primary summary__buy"
                :disabled="product.data.value.lifecycle_state !== 'public'"
                @click="purchaseOpen = true"
              >
                发起购买请求
              </button>
              <ProductFavoriteControl :product-id="product.data.value.id" />
              <RouterLink
                :to="{
                  name: 'report',
                  query: { target_type: 'product', target_id: product.data.value.id },
                }"
                class="btn btn--ghost"
              >
                举报商品
              </RouterLink>
            </div>
            <p
              v-if="!isOwner && product.data.value.lifecycle_state !== 'public'"
              class="banner banner--warn"
            >
              该商品当前不可发起新的购买请求。
            </p>
          </div>
        </section>

        <div class="product-body">
          <section v-if="isOwner" class="card owner-card">
            <div class="owner-card__head">
              <div>
                <h2>审核与状态</h2>
                <p>{{ ownerGuidance }}</p>
              </div>
              <StateBadge
                :label="productLifecycleLabels[product.data.value.lifecycle_state]"
                :tone="productLifecycleTones[product.data.value.lifecycle_state]"
              />
            </div>
            <dl class="facts">
              <template v-if="product.data.value.pending_review">
                <dt>待审核</dt>
                <dd>
                  于 {{ formatDateTime(product.data.value.pending_review.submitted_at) }} 提交
                </dd>
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
              <button
                v-if="permissions?.can_relist"
                type="button"
                class="btn btn--primary"
                :disabled="relistPending"
                @click="openRelist"
              >
                重新上架
              </button>
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
        </div>
      </div>
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
      :open="relistOpen"
      title="重新上架该商品？"
      description="确认后，商品将重新公开展示，其他用户可以浏览并发起购买请求。"
      :confirm-label="relistPending ? '正在上架…' : '确认上架'"
      :confirm-disabled="relistPending"
      @cancel="relistOpen = false"
      @confirm="confirmRelist"
    >
      <p v-if="relistError" class="field__error" role="alert">{{ relistError }}</p>
    </ConfirmDialog>

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
.product-page {
  container: product-page / inline-size;
  display: grid;
  gap: var(--space-5);
}

.product-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.product-head__copy {
  display: grid;
  gap: var(--space-1);
  min-inline-size: 0;
}

.product-head__eyebrow {
  color: var(--brand);
  font-size: 0.75rem;
  font-weight: 700;
}

.product-head h1 {
  max-inline-size: 42rem;
  font-size: clamp(1.5rem, 1.2rem + 1.5cqi, 2.25rem);
  letter-spacing: -0.025em;
  text-wrap: balance;
}

.product-head__meta {
  color: var(--ink-soft);
  font-size: 0.875rem;
}

.product-head__back {
  flex: 0 0 auto;
  color: var(--ink-soft);
}

.product-head__back svg {
  inline-size: 1rem;
  block-size: 1rem;
  rotate: 180deg;
}

.product-hero {
  display: grid;
  overflow: clip;
  border: 1px solid var(--line);
  border-radius: calc(var(--radius) + 4px);
  background: var(--panel);
  box-shadow: var(--shadow-soft);
}

.gallery {
  min-inline-size: 0;
  padding: clamp(0.75rem, 2cqi, 1.25rem);
  background:
    radial-gradient(circle at 15% 10%, rgb(255 255 255 / 80%), transparent 38%), var(--panel-soft);
}

.gallery__main {
  position: relative;
  aspect-ratio: 4 / 3;
  min-block-size: 0;
  border-radius: var(--radius-sm);
  overflow: clip;
  background: rgb(255 255 255 / 72%);
}

.gallery__track {
  display: flex;
  align-items: stretch;
  inline-size: 100%;
  block-size: 100%;
  min-block-size: 0;
  overflow-x: auto;
  overflow-y: clip;
  overscroll-behavior-x: contain;
  scroll-snap-type: x mandatory;
  scrollbar-width: none;
  touch-action: manipulation;
}

.gallery__track::-webkit-scrollbar {
  display: none;
}

.gallery__track:focus-visible {
  outline-offset: -3px;
}

.gallery__slide {
  display: grid;
  flex: 0 0 100%;
  place-items: center;
  min-inline-size: 0;
  min-block-size: 0;
  block-size: 100%;
  overflow: clip;
  scroll-snap-align: start;
  scroll-snap-stop: always;
}

.gallery__image {
  display: block;
  inline-size: 100%;
  block-size: 100%;
  min-block-size: 0;
  max-block-size: 100%;
  object-fit: contain;
}

.gallery__placeholder {
  display: grid;
  justify-items: center;
  gap: var(--space-2);
  font-size: 0.875rem;
  color: var(--ink-faint);
}

.gallery__placeholder svg {
  inline-size: 2rem;
  block-size: 2rem;
}

.gallery__count {
  position: absolute;
  inset-inline-end: var(--space-3);
  inset-block-end: var(--space-3);
  padding: 0.1875rem var(--space-2);
  border-radius: 999px;
  background: rgb(24 36 32 / 72%);
  color: #fff;
  font-size: 0.6875rem;
  font-variant-numeric: tabular-nums;
}

.gallery__thumbs {
  display: flex;
  gap: var(--space-2);
  margin-block-start: var(--space-3);
  padding-block-end: 0.125rem;
  overflow-x: auto;
  overflow-y: clip;
  overscroll-behavior-x: contain;
  scroll-snap-type: x proximity;
  scrollbar-width: none;
}

.gallery__thumbs::-webkit-scrollbar {
  display: none;
}

.gallery__thumb {
  flex: 0 0 auto;
  inline-size: 3.75rem;
  block-size: 3.75rem;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  overflow: hidden;
  padding: 0;
  background: var(--panel);
  cursor: pointer;
  scroll-snap-align: start;
  transition:
    border-color 150ms ease-out,
    scale 150ms ease-out;
}

.gallery__thumb--active {
  border-color: var(--brand);
  box-shadow: 0 0 0 2px var(--brand-soft);
}

.gallery__thumb img {
  display: block;
  inline-size: 100%;
  block-size: 100%;
  object-fit: cover;
}

.summary {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  min-inline-size: 0;
  padding: clamp(1.25rem, 3cqi, 2rem);
  border-block-start: 1px solid var(--line);
}

.summary__status {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
  color: var(--ink-soft);
  font-size: 0.75rem;
}

.summary__price {
  font-size: clamp(2rem, 1.4rem + 2.4cqi, 3rem);
  font-weight: 750;
  letter-spacing: -0.035em;
  line-height: 1.1;
  color: var(--accent);
}

.summary__categories {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.summary__uncategorized {
  color: var(--ink-faint);
  font-size: 0.8125rem;
}

.summary__description {
  display: grid;
  gap: var(--space-2);
  padding-block-start: var(--space-4);
  border-block-start: 1px solid var(--line);
}

.summary__description h2 {
  color: var(--ink-soft);
  font-size: 0.75rem;
  font-weight: 700;
}

.summary__description p {
  color: var(--ink-soft);
  font-size: 0.9375rem;
  line-height: 1.75;
  overflow-wrap: anywhere;
}

.summary__owner-note {
  display: grid;
  gap: var(--space-1);
  margin-block-start: auto;
  padding: var(--space-3);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--brand-soft);
  color: var(--brand-ink);
  font-size: 0.8125rem;
}

.summary__owner-note strong {
  font-size: 0.75rem;
}

.summary__owner-note p {
  color: var(--ink-soft);
}

.summary__actions {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
  margin-block-start: auto;
  border-block-start: 1px solid var(--line);
  padding-block-start: var(--space-4);
}

.summary__buy {
  flex: 1 1 11rem;
}

.seller {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--panel-soft);
}

.seller__copy {
  display: grid;
  gap: 0.0625rem;
  min-inline-size: 0;
}

.seller__copy > span {
  color: var(--ink-faint);
  font-size: 0.6875rem;
}

.seller__copy strong {
  overflow: hidden;
  font-size: 0.875rem;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.seller-contact {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  flex-wrap: wrap;
  font-size: 0.8125rem;
}

.seller-contact p {
  max-inline-size: 34ch;
  margin: 0;
}

.product-body {
  display: grid;
  gap: var(--space-4);
}

.owner-card {
  display: grid;
  gap: var(--space-4);
}

.owner-card__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.owner-card__head > div {
  display: grid;
  gap: var(--space-1);
}

.owner-card__head h2 {
  font-size: 1rem;
}

.owner-card__head p {
  color: var(--ink-soft);
  font-size: 0.8125rem;
}

.facts {
  display: grid;
  grid-template-columns: minmax(5.5rem, auto) 1fr;
  gap: var(--space-3) var(--space-4);
  margin: 0;
  padding: var(--space-3);
  border-radius: var(--radius-sm);
  background: var(--panel-soft);
  font-size: 0.875rem;
}

.facts dt {
  color: var(--ink-faint);
}

.facts dd {
  margin: 0;
}

.owner-actions {
  border-block-start: 1px solid var(--line);
  padding-block-start: var(--space-4);
}

@container product-page (inline-size >= 56rem) {
  .product-hero {
    grid-template-columns: minmax(0, 1.35fr) minmax(19rem, 0.8fr);
  }

  .summary {
    border-block-start: 0;
    border-inline-start: 1px solid var(--line);
  }
}

@media (width < 48rem) {
  .product-head__back {
    display: none;
  }
}

@media (hover: hover) {
  .gallery__thumb:hover {
    border-color: var(--brand);
    scale: 1.03;
  }
}

@media (prefers-reduced-motion: no-preference) {
  .gallery__track {
    scroll-behavior: smooth;
  }
}

@media (prefers-reduced-motion: reduce) {
  .gallery__thumb {
    transition: none;
  }

  .gallery__thumb:hover {
    scale: 1;
  }
}
</style>
