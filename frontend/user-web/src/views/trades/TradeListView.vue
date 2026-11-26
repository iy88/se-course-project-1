<script setup lang="ts">
/*
 * Own trade list (US-05/06/12).
 *
 * The buyer/seller role tabs mirror the aggregation endpoint's `role` filter, and
 * every row links to the detail screen, which owns the stage actions.
 */
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { listMyTrades } from "../../api/trades";
import type { TradeStatus, TradeView } from "../../api/contracts";
import { usePagedList } from "../../app/async";
import { formatCents, formatRelative } from "../../app/format";
import { tradeStageLabel, tradeStatusLabels, tradeStatusTones } from "../../app/labels";
import { session } from "../../app/session";
import EmptyState from "../../components/EmptyState.vue";
import ErrorNotice from "../../components/ErrorNotice.vue";
import LoadingBlock from "../../components/LoadingBlock.vue";
import PageHeader from "../../components/PageHeader.vue";
import PaginationBar from "../../components/PaginationBar.vue";
import StateBadge from "../../components/StateBadge.vue";

const router = useRouter();
const role = ref<"all" | "buyer" | "seller">("all");
const status = ref<TradeStatus | "">("");

const roles: { value: "all" | "buyer" | "seller"; label: string }[] = [
  { value: "all", label: "全部" },
  { value: "buyer", label: "我买到的" },
  { value: "seller", label: "我卖出的" },
];

const statusOptions: { value: TradeStatus | ""; label: string }[] = [
  { value: "", label: "全部状态" },
  { value: "pending_acceptance", label: tradeStatusLabels.pending_acceptance },
  { value: "in_progress", label: tradeStatusLabels.in_progress },
  { value: "disputed", label: tradeStatusLabels.disputed },
  { value: "completed", label: tradeStatusLabels.completed },
  { value: "terminated", label: tradeStatusLabels.terminated },
];

const list = usePagedList<TradeView>((page, pageSize, signal) =>
  listMyTrades(
    {
      role: role.value,
      status: status.value ? [status.value] : undefined,
      page,
      page_size: pageSize,
    },
    signal,
  ),
);

const rows = computed(() => list.items.value);

onMounted(() => {
  void list.load(1);
});

function selectRole(next: "all" | "buyer" | "seller"): void {
  role.value = next;
  void list.load(1);
}

function counterparty(trade: TradeView) {
  return trade.buyer.id === session.accountId.value ? trade.seller : trade.buyer;
}

function open(trade: TradeView): void {
  void router.push({ name: "trade-detail", params: { tradeId: trade.id } });
}
</script>

<template>
  <div class="stack stack--loose">
    <PageHeader
      eyebrow="我的"
      title="我的交易"
      description="购买请求、约定、完成确认与争议都在交易详情中处理。"
    >
      <template #actions>
        <RouterLink to="/" class="btn btn--ghost">去逛逛</RouterLink>
      </template>
    </PageHeader>

    <div class="inline">
      <button
        v-for="option in roles"
        :key="option.value"
        type="button"
        class="chip chip--action"
        :class="{ 'chip--active': role === option.value }"
        @click="selectRole(option.value)"
      >
        {{ option.label }}
      </button>
    </div>

    <div class="field status-select">
      <label class="field__label" for="trade-status">状态</label>
      <select id="trade-status" v-model="status" class="select" @change="list.load(1)">
        <option v-for="option in statusOptions" :key="option.value || 'all'" :value="option.value">
          {{ option.label }}
        </option>
      </select>
    </div>

    <LoadingBlock v-if="list.isLoading.value" label="正在加载交易…" />
    <ErrorNotice
      v-else-if="list.problem.value"
      :error="list.error.value"
      @retry="list.load(list.paging.page)"
    />
    <EmptyState
      v-else-if="list.isEmpty.value"
      title="没有符合条件的交易"
      description="在商品详情页发起购买请求后，交易会出现在这里。"
    >
      <RouterLink to="/" class="btn btn--primary">去逛逛</RouterLink>
    </EmptyState>
    <template v-else>
      <ul class="rows">
        <li v-for="trade in rows" :key="trade.id">
          <button type="button" class="row" @click="open(trade)">
            <span class="row__main">
              <span class="row__title clamp-1">
                {{ trade.product.title ?? `商品 ${trade.product.id}` }}
              </span>
              <span class="muted">
                {{ trade.buyer.id === session.accountId.value ? "卖家" : "买家" }}
                {{ counterparty(trade).display_name }} ·
                {{ formatRelative(trade.updated_at) }}
              </span>
              <span class="muted">
                {{ tradeStageLabel(trade.status, trade.phase) }}
                <template v-if="trade.product.price_cents">
                  · {{ formatCents(trade.product.price_cents) }}
                </template>
              </span>
            </span>
            <StateBadge
              :label="tradeStatusLabels[trade.status]"
              :tone="tradeStatusTones[trade.status]"
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
.status-select {
  max-inline-size: 14rem;
}

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
