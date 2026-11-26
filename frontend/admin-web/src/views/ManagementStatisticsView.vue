<script setup lang="ts">
import { computed, onUnmounted, ref } from "vue";
import { AbortedError } from "../api/errors";
import {
  readStatistics,
  type ManagementStatistics,
  type StatisticsSelection,
} from "../api/statistics";
import { formatDateTime } from "../app/format";
import ErrorNotice from "../components/ErrorNotice.vue";
import LoadingBlock from "../components/LoadingBlock.vue";
import PageHeader from "../components/PageHeader.vue";

const scope = ref<"" | "all" | "range">("");
const start = ref("");
const end = ref("");
const endInput = ref<HTMLInputElement>();
const data = ref<ManagementStatistics>();
const error = ref<unknown>();
const loading = ref(false);
let lastSelection: StatisticsSelection | undefined;
let pending: AbortController | undefined;

const groups = computed(() => {
  const result = data.value;
  if (!result) return [];
  const states = result.products_by_state;
  return [
    {
      title: "账户",
      rows: [
        ["账户总数", result.accounts.total],
        ["封禁账户", result.accounts.banned],
      ],
    },
    {
      title: "商品",
      rows: [
        ["待审核", states.pending_review],
        ["审核驳回", states.review_rejected],
        ["公开", states.public],
        ["交易中", states.in_trade],
        ["已下架", states.off_shelf],
      ],
    },
    {
      title: "待处理事项",
      rows: [
        ["商品审核", result.pending.reviews],
        ["举报", result.pending.reports],
      ],
    },
    {
      title: "交易",
      rows: [
        ["已完成", result.trades.completed],
        ["已终止", result.trades.terminated],
        ["有争议", result.trades.disputed],
      ],
    },
  ];
});

function clearRangeError(): void {
  endInput.value?.setCustomValidity("");
}

async function load(selection: StatisticsSelection): Promise<void> {
  pending?.abort();
  const controller = new AbortController();
  pending = controller;
  lastSelection = selection;
  loading.value = true;
  error.value = undefined;
  try {
    const result = await readStatistics(selection, controller.signal);
    if (pending === controller) data.value = result;
  } catch (caught) {
    if (pending === controller && !(caught instanceof AbortedError)) error.value = caught;
  } finally {
    if (pending === controller) loading.value = false;
  }
}

function submit(): void {
  if (scope.value === "all") {
    void load({ time_scope: "all" });
  } else if (scope.value === "range") {
    const startTime = new Date(start.value + "Z");
    const endTime = new Date(end.value + "Z");
    if (!(startTime.getTime() < endTime.getTime())) {
      endInput.value?.setCustomValidity("结束时间须晚于开始时间。");
      endInput.value?.reportValidity();
      return;
    }
    void load({
      time_scope: "range",
      start_at: startTime.toISOString(),
      end_at: endTime.toISOString(),
    });
  }
}

function retry(): void {
  if (lastSelection) void load(lastSelection);
}

onUnmounted(() => pending?.abort());
</script>

<template>
  <div class="stack stack--loose">
    <PageHeader title="管理统计" />
    <form class="card stack" aria-labelledby="statistics-filter" @submit.prevent="submit">
      <h2 id="statistics-filter">查询范围</h2>
      <label class="field">
        <span>完成交易统计范围</span>
        <select v-model="scope" name="time_scope" class="select" required @change="clearRangeError">
          <option value="" disabled>请选择</option>
          <option value="all">全部时间</option>
          <option value="range">指定时间范围</option>
        </select>
      </label>
      <div v-if="scope === 'range'" class="range-fields">
        <label class="field">
          <span>开始时间（UTC，含）</span>
          <input
            v-model="start"
            name="start_at"
            class="input"
            type="datetime-local"
            required
            @input="clearRangeError"
          />
        </label>
        <label class="field">
          <span>结束时间（UTC，不含）</span>
          <input
            ref="endInput"
            v-model="end"
            name="end_at"
            class="input"
            type="datetime-local"
            required
            @input="clearRangeError"
          />
        </label>
      </div>
      <div>
        <button type="submit" class="btn btn--primary" :disabled="loading">
          {{ loading ? "查询中…" : "查询" }}
        </button>
      </div>
    </form>

    <LoadingBlock v-if="loading" label="正在读取统计…" />
    <ErrorNotice v-else-if="error" :error="error" @retry="retry" />
    <template v-else-if="data">
      <section class="card stack" aria-labelledby="selected-total">
        <h2 id="selected-total">所选范围完成交易</h2>
        <strong class="count">{{ data.completed_in_selection.toLocaleString() }}</strong>
        <p v-if="data.selection.time_scope === 'range'" class="muted">
          {{ data.selection.start_at }} 至 {{ data.selection.end_at }}
        </p>
        <p v-else class="muted">全部时间</p>
      </section>
      <section class="stack" aria-labelledby="current-statistics">
        <h2 id="current-statistics">当前状态</h2>
        <p class="muted">统计时点 {{ formatDateTime(data.as_of) }}（本地时间）</p>
        <div class="summary-grid">
          <section v-for="group in groups" :key="group.title" class="card stack">
            <h3>{{ group.title }}</h3>
            <dl>
              <div v-for="[label, count] in group.rows" :key="label" class="spread">
                <dt>{{ label }}</dt>
                <dd>{{ count.toLocaleString() }}</dd>
              </div>
            </dl>
          </section>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.range-fields,
.summary-grid {
  display: grid;
  gap: var(--space-3);
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 14rem), 1fr));
}
.count {
  font-size: 1.5rem;
}
dl {
  margin: 0;
}
dd {
  margin: 0;
  font-variant-numeric: tabular-nums;
}
</style>
