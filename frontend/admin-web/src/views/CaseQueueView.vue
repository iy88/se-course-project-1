<script setup lang="ts">
/*
 * Shared case workbench (QUERY-004). Four ownership scopes, a case type filter,
 * a keyword search and paging are all resolved by the backend before paging; the
 * page only renders the authorized summaries it receives.
 */
import { computed, onMounted, ref, watch } from "vue";
import UiIcon from "../../../shared/UiIcon.vue";
import type { ManagementTodoItem, TodoKind, WorkbenchOwnership } from "../api/contracts";
import { listCaseQueue } from "../api/cases";
import { AbortedError } from "../api/errors";
import { claimCase } from "../api/reviews";
import { formatDateTime } from "../app/format";
import { IdempotencyKeys } from "../app/keys";
import {
  decisionKindLabels,
  ownershipLabels,
  todoKindLabels,
  todoKindOptions,
} from "../app/labels";
import { problemMessage } from "../app/problems";
import { navigate } from "../app/router";
import { notify } from "../app/toast";
import EmptyState from "../components/EmptyState.vue";
import ErrorNotice from "../components/ErrorNotice.vue";
import LoadingBlock from "../components/LoadingBlock.vue";
import PageHeader from "../components/PageHeader.vue";
import PaginationBar from "../components/PaginationBar.vue";

const props = defineProps<{
  ownership: WorkbenchOwnership;
  kind: TodoKind;
  keyword: string;
}>();

const items = ref<ManagementTodoItem[]>([]);
const loading = ref(false);
const error = ref<unknown>(null);
const page = ref(1);
const pageSize = 20;
const total = ref(0);
const counts = ref<Record<string, number>>({});
const claiming = ref<string | null>(null);
const keywordDraft = ref(props.keyword);
const keys = new IdempotencyKeys();
let controller: AbortController | null = null;

const scopes: WorkbenchOwnership[] = ["unclaimed", "mine", "completed_mine", "completed_all"];
const completed = computed(() => props.ownership.startsWith("completed"));
const headline = computed(() => ownershipLabels[props.ownership]);
const scopeHint = computed(() => {
  switch (props.ownership) {
    case "unclaimed":
      return "共享池按可认领资格展示；认领后由本人处理。";
    case "mine":
      return "仅列出本人认领且仍需处理的事项。";
    case "completed_mine":
      return "仅列出本人实际处理并已完成的事项，按完成时间倒序。";
    case "completed_all":
      return "列出所有管理员已完成事项的授权摘要，可按类型和关键词筛选。";
  }
});
const emptyTitle = computed(() => {
  switch (props.ownership) {
    case "unclaimed":
      return "共享池暂无可认领事项";
    case "mine":
      return "还没有认领事项";
    case "completed_mine":
      return "还没有本人已完成的事项";
    case "completed_all":
      return "还没有管理员完成记录";
  }
});
const emptyDescription = computed(() => {
  switch (props.ownership) {
    case "unclaimed":
      return "商品审核、举报和争议事项进入共享池后会显示在这里。";
    case "mine":
      return "从待认领范围认领事项后，可在此继续处理。";
    case "completed_mine":
      return "提交审核结论或结案归档后，会进入已完成范围。";
    case "completed_all":
      return "任一管理员完成事项后，授权摘要会显示在这里。";
  }
});

async function load(target = page.value): Promise<void> {
  controller?.abort();
  controller = new AbortController();
  loading.value = true;
  error.value = null;
  try {
    const result = await listCaseQueue(
      {
        ownership: props.ownership,
        kind: props.kind,
        keyword: props.keyword,
        page: target,
        page_size: pageSize,
      },
      controller.signal,
    );
    items.value = result.items;
    page.value = result.page;
    total.value = result.total;
    counts.value = result.counts_by_kind;
  } catch (caught) {
    if (caught instanceof AbortedError) return;
    error.value = caught;
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  void load(1);
});

watch(
  () => [props.ownership, props.kind, props.keyword],
  () => {
    keywordDraft.value = props.keyword;
    void load(1);
  },
);

function switchScope(ownership: WorkbenchOwnership): void {
  navigate({ name: "cases", ownership, kind: props.kind, keyword: props.keyword });
}

function switchKind(kind: TodoKind): void {
  navigate({ name: "cases", ownership: props.ownership, kind, keyword: props.keyword });
}

function submitSearch(): void {
  navigate({
    name: "cases",
    ownership: props.ownership,
    kind: props.kind,
    keyword: keywordDraft.value.trim(),
  });
}

function clearSearch(): void {
  keywordDraft.value = "";
  if (!props.keyword) return;
  navigate({ name: "cases", ownership: props.ownership, kind: props.kind, keyword: "" });
}

function kindLabel(kind: string): string {
  return todoKindLabels[kind as keyof typeof todoKindLabels] ?? kind;
}

function summaryText(item: ManagementTodoItem): string {
  if (item.summary.title) return item.summary.title;
  if (item.summary.audit_id) return `审核 #${item.summary.audit_id}`;
  if (item.summary.product_id) return `商品 #${item.summary.product_id}`;
  return "—";
}

function decisionText(item: ManagementTodoItem): string {
  if (!item.decision_kind) return "—";
  return decisionKindLabels[item.decision_kind] ?? item.decision_kind;
}

function timeText(item: ManagementTodoItem): string {
  return formatDateTime(completed.value ? (item.completed_at ?? item.updated_at) : item.updated_at);
}

function detailAuditId(item: ManagementTodoItem): string | null {
  return item.kind === "product_review" && item.summary.audit_id ? item.summary.audit_id : null;
}

function open(item: ManagementTodoItem): void {
  const auditId = detailAuditId(item);
  if (auditId) navigate({ name: "review", auditId });
}

async function claim(item: ManagementTodoItem): Promise<void> {
  if (claiming.value) return;
  claiming.value = item.case_id;
  const operation = `claim-${item.case_id}`;
  try {
    await claimCase(item.case_id, keys.current(operation));
    keys.rotate(operation);
    notify.success("已认领该事项。");
    const auditId = detailAuditId(item);
    if (auditId) {
      navigate({ name: "review", auditId });
    } else {
      await load();
    }
  } catch (caught) {
    notify.error(problemMessage(caught));
    await load();
  } finally {
    claiming.value = null;
  }
}
</script>

<template>
  <div class="stack stack--loose">
    <PageHeader
      title="事项工作台"
      description="按范围、类型和关键词处理共享池事项；详情在认领后按原权限开放。"
    >
      <template #actions>
        <span class="chip">共 {{ total }} 项</span>
      </template>
    </PageHeader>

    <div class="tabs" role="tablist" aria-label="事项范围">
      <button
        v-for="option in scopes"
        :key="option"
        type="button"
        role="tab"
        class="tab"
        :class="{ 'tab--active': props.ownership === option }"
        :aria-selected="props.ownership === option"
        @click="switchScope(option)"
      >
        {{ ownershipLabels[option] }}
      </button>
    </div>

    <form class="toolbar" role="search" @submit.prevent="submitSearch">
      <label class="field toolbar__search">
        <span class="visually-hidden">关键词</span>
        <input
          v-model="keywordDraft"
          class="input"
          type="search"
          placeholder="搜索事项编号或摘要"
          autocomplete="off"
        />
      </label>
      <button type="submit" class="btn btn--primary btn--small">
        <UiIcon name="search" />搜索
      </button>
      <button
        v-if="props.keyword"
        type="button"
        class="btn btn--ghost btn--small"
        @click="clearSearch"
      >
        清除
      </button>
    </form>

    <div class="kind-filter" role="group" aria-label="事项类型">
      <button
        v-for="option in todoKindOptions"
        :key="option.value"
        type="button"
        class="chip"
        :class="{ 'chip--active': props.kind === option.value }"
        :aria-pressed="props.kind === option.value"
        @click="switchKind(option.value)"
      >
        {{ option.label }}
        <span v-if="option.value !== 'all'" class="muted">{{ counts[option.value] ?? 0 }}</span>
      </button>
    </div>

    <p class="muted">{{ scopeHint }}</p>

    <section class="card" :aria-busy="loading">
      <LoadingBlock v-if="loading && !items.length" label="正在加载事项…" />
      <ErrorNotice v-else-if="error" :error="error" @retry="load()" />
      <EmptyState v-else-if="!items.length" :title="emptyTitle" :description="emptyDescription" />
      <template v-else>
        <div class="spread queue-head">
          <h2>{{ headline }}</h2>
          <span class="muted">共 {{ total }} 项</span>
        </div>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>事项</th>
                <th>类型</th>
                <th>摘要</th>
                <th>结论</th>
                <th>处理人</th>
                <th>{{ completed ? "完成时间" : "更新时间" }}</th>
                <th><span class="visually-hidden">操作</span></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in items" :key="item.case_id">
                <td class="mono">#{{ item.case_id }}</td>
                <td>{{ kindLabel(item.kind) }}</td>
                <td>{{ summaryText(item) }}</td>
                <td>{{ decisionText(item) }}</td>
                <td class="mono">{{ item.manager_id ? `#${item.manager_id}` : "—" }}</td>
                <td>{{ timeText(item) }}</td>
                <td class="queue-actions">
                  <button
                    v-if="props.ownership === 'unclaimed'"
                    type="button"
                    class="btn btn--primary btn--small"
                    :disabled="claiming !== null"
                    @click="claim(item)"
                  >
                    <UiIcon name="plus" />
                    {{ claiming === item.case_id ? "认领中…" : "认领" }}
                  </button>
                  <button
                    v-else-if="detailAuditId(item)"
                    type="button"
                    class="btn btn--small"
                    @click="open(item)"
                  >
                    <UiIcon name="check" />查看
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <PaginationBar :page="page" :page-size="pageSize" :total="total" @change="load" />
      </template>
    </section>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: end;
  gap: var(--space-2);
}

.toolbar__search {
  flex: 1 1 16rem;
  margin: 0;
}

.kind-filter {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.queue-head h2 {
  font-size: 0.9375rem;
}

.queue-actions {
  text-align: end;
}
</style>
