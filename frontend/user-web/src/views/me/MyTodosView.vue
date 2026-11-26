<script setup lang="ts">
/*
 * Trade to-dos owned by the current account.
 *
 * Every item links back to the trade detail, which performs the actual write
 * with its own permission/version rules. Inquiry to-dos belong to the S4 case
 * screens and are intentionally not surfaced or counted here.
 */
import { computed, onMounted, ref } from "vue";
import { listMyTodos } from "../../api/aggregation";
import type { MyTodoPage, TodoItem, TodoKind } from "../../api/contracts";
import { usePagedList } from "../../app/async";
import { formatDateTime } from "../../app/format";
import { todoKindLabels } from "../../app/labels";
import EmptyState from "../../components/EmptyState.vue";
import ErrorNotice from "../../components/ErrorNotice.vue";
import LoadingBlock from "../../components/LoadingBlock.vue";
import PageHeader from "../../components/PageHeader.vue";
import PaginationBar from "../../components/PaginationBar.vue";

type TradeTodoKind = Exclude<TodoKind, "inquiry_response">;

interface TradeTodoOption {
  kind: TradeTodoKind;
  action: string;
  hint: string;
}

const tradeTodoOptions: TradeTodoOption[] = [
  {
    kind: "request_response",
    action: "处理购买请求",
    hint: "在交易详情接受或拒绝这条请求。",
  },
  {
    kind: "agreement_response",
    action: "回应交易约定",
    hint: "在交易详情同意、拒绝或撤回这次约定。",
  },
  {
    kind: "completion_response",
    action: "确认交易完成",
    hint: "核对交付与收款后，在交易详情提交完成确认。",
  },
  {
    kind: "cancellation_response",
    action: "回应取消申请",
    hint: "在交易详情同意、拒绝或撤回取消申请。",
  },
];

const kind = ref<TradeTodoKind>("request_response");
const counts = ref<Partial<Record<TodoKind, number>>>({});
const asOf = ref<string | null>(null);

function applyCounts(result: MyTodoPage): MyTodoPage {
  counts.value = result.counts_by_kind;
  asOf.value = result.as_of;
  return result;
}

const list = usePagedList<TodoItem>((page, pageSize, signal) =>
  listMyTodos({ kind: kind.value, page, page_size: pageSize }, signal).then(applyCounts),
);

const activeOption = computed(
  () => tradeTodoOptions.find((option) => option.kind === kind.value) ?? tradeTodoOptions[0],
);

const otherTodoCount = computed(() =>
  tradeTodoOptions.reduce(
    (sum, option) => (option.kind === kind.value ? sum : sum + (counts.value[option.kind] ?? 0)),
    0,
  ),
);

onMounted(async () => {
  // A small probe supplies counts for every kind without mixing S4 inquiries
  // into this page; the selected tab is then the first one that needs work.
  try {
    const probe = await listMyTodos({ page: 1, page_size: 1 });
    applyCounts(probe);
    const first = tradeTodoOptions.find((option) => (probe.counts_by_kind[option.kind] ?? 0) > 0);
    if (first) kind.value = first.kind;
  } catch {
    // The paged request below reports the authoritative failure with retry.
  }
  await list.load(1);
});

function selectKind(next: TradeTodoKind): void {
  if (kind.value === next) return;
  kind.value = next;
  void list.load(1);
}

function tradeIdOf(item: TodoItem): string {
  const value = item.source.trade_id;
  return typeof value === "string" ? value : "";
}

function actionFor(item: TodoItem): TradeTodoOption {
  return tradeTodoOptions.find((option) => option.kind === item.kind) ?? activeOption.value;
}
</script>

<template>
  <div class="stack stack--loose">
    <PageHeader
      eyebrow="我的"
      title="待处理交易"
      description="只列出当前仍需要你处理的交易事项；实际操作在交易详情中完成。"
    >
      <template #actions>
        <RouterLink to="/me/trades" class="btn btn--ghost">全部交易</RouterLink>
      </template>
    </PageHeader>

    <div class="status-filter todo-filters" role="group" aria-label="待办类型">
      <button
        v-for="option in tradeTodoOptions"
        :key="option.kind"
        type="button"
        class="status-filter__option"
        :aria-pressed="kind === option.kind"
        @click="selectKind(option.kind)"
      >
        {{ todoKindLabels[option.kind] }}
        <span v-if="(counts[option.kind] ?? 0) > 0" class="todo-count">
          {{ counts[option.kind] }}
        </span>
      </button>
    </div>

    <p v-if="otherTodoCount > 0" class="banner banner--info">
      {{ activeOption.action }}之外还有 {{ otherTodoCount }} 条交易待办，可切换上方类型查看。
    </p>

    <LoadingBlock v-if="list.isLoading.value && !list.items.value.length" label="正在加载待办…" />
    <ErrorNotice
      v-else-if="list.problem.value && !list.items.value.length"
      :error="list.error.value"
      @retry="list.load(list.paging.page)"
    />
    <EmptyState
      v-else-if="list.isEmpty.value"
      :title="`没有${todoKindLabels[activeOption.kind]}`"
      description="待办完成后会自动移出；你仍可从交易列表查看历史。"
    >
      <RouterLink to="/me/trades" class="btn btn--primary">查看我的交易</RouterLink>
    </EmptyState>
    <template v-else>
      <p v-if="list.problem.value" class="banner banner--warn" role="alert">
        刷新待办失败：{{ list.problem.value.message }}
        <button type="button" class="btn btn--small" @click="list.load(list.paging.page)">
          重试
        </button>
      </p>
      <ul class="todos" :aria-busy="list.isLoading.value">
        <li v-for="item in list.items.value" :key="item.todo_key" class="todo card">
          <div class="todo__main">
            <span class="chip">{{ todoKindLabels[item.kind] }}</span>
            <p class="todo__summary break-anywhere">{{ item.summary }}</p>
            <p class="todo__hint muted">{{ actionFor(item).hint }}</p>
            <p class="muted todo__time">更新于 {{ formatDateTime(item.updated_at) }}</p>
          </div>
          <RouterLink
            v-if="tradeIdOf(item)"
            :to="{ name: 'trade-detail', params: { tradeId: tradeIdOf(item) } }"
            class="btn btn--primary todo__action"
          >
            {{ actionFor(item).action }}
          </RouterLink>
          <span v-else class="muted todo__action">请从交易列表进入对应交易</span>
        </li>
      </ul>
      <PaginationBar
        :page="list.paging.page"
        :page-size="list.paging.pageSize"
        :total="list.paging.total"
        @change="list.load"
      />
      <p v-if="asOf" class="muted todo-asof">统计时点：{{ formatDateTime(asOf) }}</p>
    </template>
  </div>
</template>

<style scoped>
.todo-filters {
  max-inline-size: 40rem;
}

.todo-count {
  display: inline-grid;
  place-items: center;
  min-inline-size: 1.25rem;
  block-size: 1.25rem;
  margin-inline-start: var(--space-1);
  padding-inline: 0.25rem;
  border-radius: 999px;
  background: var(--brand-soft);
  color: var(--brand-ink);
  font-size: 0.6875rem;
  font-weight: 700;
}

.todos {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.todo {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.todo__main {
  display: grid;
  gap: var(--space-1);
  min-inline-size: min(100%, 24rem);
  flex: 1;
}

.todo__summary {
  margin: 0;
  font-weight: 600;
  font-size: 0.9375rem;
}

.todo__hint,
.todo__time {
  margin: 0;
  font-size: 0.8125rem;
}

.todo__time {
  font-size: 0.75rem;
}

.todo__action {
  flex: 0 0 auto;
}

.todo-asof {
  font-size: 0.75rem;
}

@media (width < 40rem) {
  .todo__action {
    inline-size: 100%;
  }
}
</style>
