<script setup lang="ts">
/*
 * Owned products with their lifecycle state.
 *
 * The list is the aggregation projection (API-COM-QUERY-003, `kind=product`); the
 * per-product actions live on the detail page so no rule is re-implemented here.
 */
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import UiIcon from "../../../../shared/UiIcon.vue";
import { listMyResources } from "../../api/aggregation";
import type { ProductLifecycle } from "../../api/contracts";
import { usePagedList } from "../../app/async";
import { formatRelative } from "../../app/format";
import { productLifecycleLabels, productLifecycleTones, type Tone } from "../../app/labels";
import EmptyState from "../../components/EmptyState.vue";
import ErrorNotice from "../../components/ErrorNotice.vue";
import LoadingBlock from "../../components/LoadingBlock.vue";
import PageHeader from "../../components/PageHeader.vue";
import PaginationBar from "../../components/PaginationBar.vue";
import StateBadge from "../../components/StateBadge.vue";

interface OwnedProductRow {
  product_id: string;
  title: string;
  lifecycle_state: ProductLifecycle;
  updated_at: string;
}

const router = useRouter();
const activeState = ref<ProductLifecycle | "">("");

const tabs: { value: ProductLifecycle | ""; label: string }[] = [
  { value: "", label: "全部" },
  { value: "public", label: "在售" },
  { value: "pending_review", label: "待审核" },
  { value: "review_rejected", label: "审核未通过" },
  { value: "in_trade", label: "交易中" },
  { value: "off_shelf", label: "已下架" },
];

const list = usePagedList<OwnedProductRow>(async (page, pageSize, signal) => {
  const result = await listMyResources(
    {
      kind: "product",
      state: activeState.value || undefined,
      page,
      page_size: pageSize,
    },
    signal,
  );
  // `kind=product` rows are the documented projection: id, title, state, time.
  return {
    items: result.items as unknown as OwnedProductRow[],
    page: result.page,
    page_size: result.page_size,
    total: result.total,
  };
});

const rows = computed(() => list.items.value);

onMounted(() => {
  void list.load(1);
});

function selectState(value: ProductLifecycle | ""): void {
  activeState.value = value;
  void list.load(1);
}

function open(row: OwnedProductRow): void {
  void router.push({ name: "product-detail", params: { productId: row.product_id } });
}
</script>

<template>
  <div class="stack stack--loose">
    <PageHeader
      eyebrow="我的"
      title="我的商品"
      description="查看审核结果、当前状态与可执行的操作。"
    >
      <template #actions>
        <RouterLink to="/products/new" class="btn btn--primary"
          ><UiIcon name="plus" />发布商品</RouterLink
        >
      </template>
    </PageHeader>

    <div class="status-filter status-filter--six" role="group" aria-label="按商品状态筛选">
      <button
        v-for="tab in tabs"
        :key="tab.value || 'all'"
        type="button"
        class="status-filter__option"
        :aria-pressed="activeState === tab.value"
        @click="selectState(tab.value)"
      >
        {{ tab.label }}
      </button>
    </div>

    <LoadingBlock v-if="list.isLoading.value" label="正在加载商品…" />
    <ErrorNotice
      v-else-if="list.problem.value"
      :error="list.error.value"
      @retry="list.load(list.paging.page)"
    />
    <EmptyState
      v-else-if="list.isEmpty.value"
      :title="activeState ? '该状态下没有商品' : '还没有发布过商品'"
      :description="activeState ? '切换到其他状态查看。' : '发布第一件商品，通过审核后即可被找到。'"
    />
    <template v-else>
      <ul class="rows">
        <li v-for="row in rows" :key="row.product_id">
          <button type="button" class="row" @click="open(row)">
            <span class="row__main">
              <span class="row__title clamp-1">{{ row.title }}</span>
              <span class="muted">更新于 {{ formatRelative(row.updated_at) }}</span>
            </span>
            <StateBadge
              :label="productLifecycleLabels[row.lifecycle_state] ?? row.lifecycle_state"
              :tone="(productLifecycleTones[row.lifecycle_state] as Tone) ?? 'neutral'"
            />
          </button>
        </li>
      </ul>
      <PaginationBar
        :page="list.paging.page"
        :page-size="list.paging.pageSize"
        :total="list.paging.total"
        @change="list.load"
      />
    </template>
  </div>
</template>

<style scoped>
.rows {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  inline-size: 100%;
  padding: var(--space-3) var(--space-4);
  text-align: start;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  cursor: pointer;
}

.row:hover {
  border-color: var(--brand);
}

.row__main {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
  min-inline-size: 0;
}

.row__title {
  font-weight: 600;
  font-size: 0.875rem;
}
</style>
