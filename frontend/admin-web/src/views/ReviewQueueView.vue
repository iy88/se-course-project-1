<script setup lang="ts">
/* Shared review pool and the current manager's claimed reviews. */
import { computed, onMounted, ref, watch } from "vue";
import UiIcon from "../../../shared/UiIcon.vue";
import type { ManagementTodoItem } from "../api/contracts";
import { AbortedError } from "../api/errors";
import { claimCase, listReviewQueue } from "../api/reviews";
import { formatDateTime } from "../app/format";
import { IdempotencyKeys } from "../app/keys";
import { ownershipLabels } from "../app/labels";
import { problemMessage } from "../app/problems";
import { navigate } from "../app/router";
import { notify } from "../app/toast";
import EmptyState from "../components/EmptyState.vue";
import ErrorNotice from "../components/ErrorNotice.vue";
import LoadingBlock from "../components/LoadingBlock.vue";
import PageHeader from "../components/PageHeader.vue";
import PaginationBar from "../components/PaginationBar.vue";

const props = defineProps<{ ownership: "unclaimed" | "mine" }>();

const items = ref<ManagementTodoItem[]>([]);
const loading = ref(false);
const error = ref<unknown>(null);
const page = ref(1);
const pageSize = 20;
const total = ref(0);
const counts = ref<Record<string, number>>({});
const claiming = ref<string | null>(null);
const keys = new IdempotencyKeys();
let controller: AbortController | null = null;

const headline = computed(() => (props.ownership === "unclaimed" ? "共享待处理池" : "我的认领"));
const ownership = computed(() => props.ownership);

async function load(target = page.value): Promise<void> {
  controller?.abort();
  controller = new AbortController();
  loading.value = true;
  error.value = null;
  try {
    const result = await listReviewQueue(
      { ownership: props.ownership, page: target, page_size: pageSize },
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
  () => props.ownership,
  () => {
    void load(1);
  },
);

function switchOwnership(ownership: "unclaimed" | "mine"): void {
  navigate({ name: "reviews", ownership });
}

function open(item: ManagementTodoItem): void {
  if (item.summary.audit_id) navigate({ name: "review", auditId: item.summary.audit_id });
}

async function claim(item: ManagementTodoItem): Promise<void> {
  if (claiming.value) return;
  claiming.value = item.case_id;
  const operation = `claim-${item.case_id}`;
  try {
    await claimCase(item.case_id, keys.current(operation));
    keys.rotate(operation);
    notify.success("已认领该审核事项。");
    if (item.summary.audit_id) navigate({ name: "review", auditId: item.summary.audit_id });
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
      title="商品审核"
      description="待审商品进入共享池；认领后由本人核查并提交结论。审核详情只在认领后开放。"
    >
      <template #actions>
        <span class="chip">待处理 {{ counts.product_review ?? total }} 项</span>
      </template>
    </PageHeader>

    <div class="tabs" role="tablist" aria-label="审核队列">
      <button
        v-for="option in ['unclaimed', 'mine'] as const"
        :key="option"
        type="button"
        role="tab"
        class="tab"
        :class="{ 'tab--active': props.ownership === option }"
        :aria-selected="props.ownership === option"
        @click="switchOwnership(option)"
      >
        {{ ownershipLabels[option] }}
      </button>
    </div>

    <section class="card" :aria-busy="loading">
      <LoadingBlock v-if="loading && !items.length" label="正在加载审核队列…" />
      <ErrorNotice v-else-if="error" :error="error" @retry="load()" />
      <EmptyState
        v-else-if="!items.length"
        :title="ownership === 'unclaimed' ? '共享池暂无可认领审核' : '还没有认领审核'"
        :description="
          ownership === 'unclaimed'
            ? '卖方提交或重新提交审核后，待审事项会出现在这里。'
            : '从待认领列表认领事项后，可在此继续处理。'
        "
      />
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
                <th>商品 / 审核</th>
                <th>提交时间</th>
                <th>更新时间</th>
                <th><span class="visually-hidden">操作</span></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in items" :key="item.case_id">
                <td class="mono">#{{ item.case_id }}</td>
                <td>
                  <span class="mono">商品 #{{ item.summary.product_id }}</span>
                  <div class="muted mono">审核 #{{ item.summary.audit_id }}</div>
                </td>
                <td>{{ formatDateTime(item.created_at) }}</td>
                <td>{{ formatDateTime(item.updated_at) }}</td>
                <td class="queue-actions">
                  <button
                    v-if="ownership === 'unclaimed'"
                    type="button"
                    class="btn btn--primary btn--small"
                    :disabled="claiming !== null"
                    @click="claim(item)"
                  >
                    <UiIcon name="plus" />
                    {{ claiming === item.case_id ? "认领中…" : "认领" }}
                  </button>
                  <button v-else type="button" class="btn btn--small" @click="open(item)">
                    <UiIcon name="check" />
                    审核
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
.queue-head h2 {
  font-size: 0.9375rem;
}

.queue-actions {
  text-align: end;
}
</style>
