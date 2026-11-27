<script setup lang="ts">
/*
 * Own cases: reports I submitted and cases where I received an enforcement.
 *
 * The `received` scope only lists cases with an actual decision, so an inquiry
 * that has not led to an enforcement is not presented as "我收到的事项".
 */
import { onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { listMyCases } from "../../api/cases";
import type { CaseScope, CaseStatus, MyCaseItem } from "../../api/contracts";
import { usePagedList } from "../../app/async";
import { rememberCaseScope } from "../../app/case-directory";
import { formatRelative } from "../../app/format";
import { caseDecisionLabels, caseStatusLabels, caseStatusTones } from "../../app/labels";
import EmptyState from "../../components/EmptyState.vue";
import ErrorNotice from "../../components/ErrorNotice.vue";
import LoadingBlock from "../../components/LoadingBlock.vue";
import PageHeader from "../../components/PageHeader.vue";
import PaginationBar from "../../components/PaginationBar.vue";
import StateBadge from "../../components/StateBadge.vue";

const router = useRouter();
const scope = ref<CaseScope>("mine");
const status = ref<CaseStatus | "">("");
const archived = ref<"all" | "open" | "closed">("all");

const list = usePagedList<MyCaseItem>((page, pageSize, signal) =>
  listMyCases(
    {
      scope: scope.value,
      status: status.value || undefined,
      archived: archived.value === "all" ? undefined : archived.value === "closed",
      page,
      page_size: pageSize,
    },
    signal,
  ),
);

const scopes: { value: CaseScope; label: string }[] = [
  { value: "mine", label: "我提交的" },
  { value: "received", label: "我收到的" },
];

const statuses: { value: CaseStatus | ""; label: string }[] = [
  { value: "", label: "全部状态" },
  { value: "pending", label: caseStatusLabels.pending },
  { value: "claimed", label: caseStatusLabels.claimed },
  { value: "decided", label: caseStatusLabels.decided },
];

onMounted(() => {
  void list.load(1);
});

watch(
  () => list.items.value,
  (items) => {
    for (const item of items) rememberCaseScope(item.case_id, item.scope);
  },
);

function selectScope(next: CaseScope): void {
  scope.value = next;
  void list.load(1);
}

/**
 * Remember the scope for case responses that predate the viewpoint projection.
 */
function open(item: MyCaseItem): void {
  rememberCaseScope(item.case_id, item.scope);
  void router.push({ name: "case-detail", params: { caseId: item.case_id } });
}
</script>

<template>
  <div class="stack stack--loose">
    <PageHeader
      eyebrow="我的"
      title="我的事项"
      description="举报进度、管理问询与申辩都在事项详情中处理。"
    >
      <template #actions>
        <RouterLink :to="{ name: 'case-results' }" class="btn btn--ghost">公开结果</RouterLink>
      </template>
    </PageHeader>

    <div class="inline">
      <button
        v-for="option in scopes"
        :key="option.value"
        type="button"
        class="chip chip--action"
        :class="{ 'chip--active': scope === option.value }"
        @click="selectScope(option.value)"
      >
        {{ option.label }}
      </button>
    </div>

    <div class="form-row">
      <div class="field">
        <label class="field__label" for="case-status">状态</label>
        <select id="case-status" v-model="status" class="select" @change="list.load(1)">
          <option v-for="option in statuses" :key="option.value || 'all'" :value="option.value">
            {{ option.label }}
          </option>
        </select>
      </div>
      <div class="field">
        <label class="field__label" for="case-archived">结案</label>
        <select id="case-archived" v-model="archived" class="select" @change="list.load(1)">
          <option value="all">全部</option>
          <option value="open">未结案</option>
          <option value="closed">已结案</option>
        </select>
      </div>
    </div>

    <LoadingBlock v-if="list.isLoading.value" label="正在加载事项…" />
    <ErrorNotice
      v-else-if="list.problem.value"
      :error="list.error.value"
      @retry="list.load(list.paging.page)"
    />
    <EmptyState
      v-else-if="list.isEmpty.value"
      :title="scope === 'mine' ? '还没有提交过举报' : '没有收到处置的事项'"
      :description="
        scope === 'mine'
          ? '请从商品、评论、评价或消息旁的举报入口发起。'
          : '发生实际处置后，相关事项会出现在这里。'
      "
    />
    <template v-else>
      <ul class="rows">
        <li v-for="item in list.items.value" :key="item.case_id">
          <button type="button" class="row" @click="open(item)">
            <span class="row__main">
              <span class="row__title">事项 #{{ item.case_id }}</span>
              <span v-if="item.decision_kind" class="muted">
                结论：{{ caseDecisionLabels[item.decision_kind] }}
              </span>
              <span class="muted">更新于 {{ formatRelative(item.updated_at) }}</span>
            </span>
            <span class="inline">
              <StateBadge
                :label="item.archived_at ? '已结案' : caseStatusLabels[item.case_status]"
                :tone="item.archived_at ? 'neutral' : caseStatusTones[item.case_status]"
              />
            </span>
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
