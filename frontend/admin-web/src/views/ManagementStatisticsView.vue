<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
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

type Scope = "7d" | "all" | "custom";

const DAY_MS = 86_400_000;
const TREND_DAYS = 7;

const scope = ref<Scope>("7d");
const start = ref("");
const end = ref("");
const endInput = ref<HTMLInputElement>();
const data = ref<ManagementStatistics>();
const trend = ref<{ label: string; count: number }[]>([]);
const error = ref<unknown>();
const loading = ref(false);
const trendLoading = ref(false);
let lastSelection: StatisticsSelection | undefined;
let pending: AbortController | undefined;

const dayStart = (value: Date): Date =>
  new Date(Date.UTC(value.getUTCFullYear(), value.getUTCMonth(), value.getUTCDate()));
const toInput = (value: Date): string => value.toISOString().slice(0, 16);
const dayLabel = (value: Date): string => `${value.getUTCMonth() + 1}/${value.getUTCDate()}`;

const selectionLabel = computed(() => {
  const current = data.value?.selection;
  if (!current) return "";
  if (current.time_scope === "all") return "全部时间";
  return `${formatDateTime(current.start_at ?? "")} 起至 ${formatDateTime(current.end_at ?? "")}`;
});

const productStates = computed(() => {
  const states = data.value?.products_by_state;
  if (!states) return [];
  return [
    { label: "待审核", count: states.pending_review, color: "var(--color-warning, #b7791f)" },
    { label: "审核驳回", count: states.review_rejected, color: "var(--color-danger, #c53030)" },
    { label: "公开", count: states.public, color: "var(--color-success, #2f855a)" },
    { label: "交易中", count: states.in_trade, color: "var(--color-accent, #2b6cb0)" },
    { label: "已下架", count: states.off_shelf, color: "var(--color-muted, #718096)" },
  ];
});

const productTotal = computed(() => productStates.value.reduce((sum, item) => sum + item.count, 0));

const donutSegments = computed(() => {
  const total = productTotal.value;
  let offset = 0;
  return productStates.value
    .filter((item) => item.count > 0)
    .map((item) => {
      const fraction = total === 0 ? 0 : item.count / total;
      const segment = {
        ...item,
        percent: Math.round(fraction * 100),
        dash: `${fraction * 100} ${100 - fraction * 100}`,
        offset,
      };
      offset += fraction * 100;
      return segment;
    });
});

const tradeParts = computed(() => {
  const trades = data.value?.trades;
  if (!trades) return [];
  return [
    { label: "已完成", count: trades.completed, color: "var(--color-success, #2f855a)" },
    { label: "已终止", count: trades.terminated, color: "var(--color-danger, #c53030)" },
    { label: "有争议", count: trades.disputed, color: "var(--color-warning, #b7791f)" },
  ];
});

const tradeTotal = computed(() => tradeParts.value.reduce((sum, item) => sum + item.count, 0));

const pendingParts = computed(() => {
  const pendingItems = data.value?.pending;
  if (!pendingItems) return [];
  return [
    { label: "商品审核", count: pendingItems.reviews, color: "var(--color-accent, #2b6cb0)" },
    { label: "举报", count: pendingItems.reports, color: "var(--color-danger, #c53030)" },
  ];
});

const pendingTotal = computed(() => pendingParts.value.reduce((sum, item) => sum + item.count, 0));

const bannedShare = computed(() => {
  const accounts = data.value?.accounts;
  if (!accounts || accounts.total === 0) return 0;
  return Math.round((accounts.banned / accounts.total) * 100);
});

const trendMax = computed(() => Math.max(1, ...trend.value.map((item) => item.count)));

const trendPoints = computed(() => {
  const width = 320;
  const height = 96;
  const step = trend.value.length > 1 ? width / (trend.value.length - 1) : width;
  return trend.value.map((item, index) => ({
    x: 8 + index * step,
    y: height - 16 - (item.count / trendMax.value) * (height - 32),
    height: (item.count / trendMax.value) * (height - 32),
  }));
});

function clearRangeError(): void {
  endInput.value?.setCustomValidity("");
}

function defaultSelection(): StatisticsSelection {
  const now = new Date();
  const first = new Date(dayStart(now).getTime() - (TREND_DAYS - 1) * DAY_MS);
  return { time_scope: "range", start_at: first.toISOString(), end_at: now.toISOString() };
}

async function loadTrend(selection: StatisticsSelection): Promise<void> {
  if (selection.time_scope !== "range") {
    trend.value = [];
    return;
  }
  const from = new Date(selection.start_at);
  const to = new Date(selection.end_at);
  const buckets: { label: string; start: Date; end: Date }[] = [];
  for (
    let cursor = dayStart(from);
    cursor.getTime() < to.getTime() && buckets.length < 31;
    cursor = new Date(cursor.getTime() + DAY_MS)
  ) {
    const bucketEnd = new Date(Math.min(cursor.getTime() + DAY_MS, to.getTime()));
    buckets.push({ label: dayLabel(cursor), start: cursor, end: bucketEnd });
  }
  trendLoading.value = true;
  try {
    const results = await Promise.all(
      buckets.map((bucket) =>
        readStatistics({
          time_scope: "range",
          start_at: bucket.start.toISOString(),
          end_at: bucket.end.toISOString(),
        })
          .then((value) => value.completed_in_selection)
          .catch(() => 0),
      ),
    );
    trend.value = buckets.map((bucket, index) => ({
      label: bucket.label,
      count: results[index] ?? 0,
    }));
  } finally {
    trendLoading.value = false;
  }
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
    if (pending === controller) {
      data.value = result;
      void loadTrend(selection);
    }
  } catch (caught) {
    if (pending === controller && !(caught instanceof AbortedError)) error.value = caught;
  } finally {
    if (pending === controller) loading.value = false;
  }
}

function submit(): void {
  if (scope.value === "all") {
    void load({ time_scope: "all" });
    return;
  }
  if (scope.value === "7d") {
    void load(defaultSelection());
    return;
  }
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

function onScopeChange(): void {
  clearRangeError();
  if (scope.value === "custom") {
    const now = new Date();
    start.value = toInput(new Date(now.getTime() - TREND_DAYS * DAY_MS));
    end.value = toInput(now);
  }
}

function retry(): void {
  if (lastSelection) void load(lastSelection);
}

onMounted(() => {
  void load(defaultSelection());
});
onUnmounted(() => pending?.abort());
</script>

<template>
  <div class="stack stack--loose statistics">
    <PageHeader title="管理统计" />

    <form class="card filter-bar" aria-label="统计查询条件" @submit.prevent="submit">
      <label class="filter-item">
        <span>完成交易范围</span>
        <select v-model="scope" name="time_scope" class="select" @change="onScopeChange">
          <option value="7d">近 7 天</option>
          <option value="all">全部时间</option>
          <option value="custom">自定义范围</option>
        </select>
      </label>
      <template v-if="scope === 'custom'">
        <label class="filter-item">
          <span>开始（UTC，含）</span>
          <input
            v-model="start"
            name="start_at"
            class="input"
            type="datetime-local"
            required
            @input="clearRangeError"
          />
        </label>
        <label class="filter-item">
          <span>结束（UTC，不含）</span>
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
      </template>
      <button type="submit" class="btn btn--primary filter-submit" :disabled="loading">
        {{ loading ? "查询中…" : "查询" }}
      </button>
      <span v-if="data" class="filter-meta">统计时点 {{ formatDateTime(data.as_of) }}</span>
    </form>

    <LoadingBlock v-if="loading" label="正在读取统计…" />
    <ErrorNotice v-else-if="error" :error="error" @retry="retry" />
    <template v-else-if="data">
      <section class="kpi-row" aria-label="关键指标">
        <article class="card kpi kpi--primary">
          <p class="kpi-label">所选范围完成交易</p>
          <strong class="kpi-value">{{ data.completed_in_selection.toLocaleString() }}</strong>
          <p class="muted kpi-note">{{ selectionLabel }}</p>
        </article>
        <article class="card kpi">
          <p class="kpi-label">账户总数 / 封禁</p>
          <strong class="kpi-value">{{ data.accounts.total.toLocaleString() }}</strong>
          <p class="muted kpi-note">封禁 {{ data.accounts.banned }}（{{ bannedShare }}%）</p>
        </article>
        <article class="card kpi">
          <p class="kpi-label">待处理事项</p>
          <strong class="kpi-value">{{ pendingTotal.toLocaleString() }}</strong>
          <p class="muted kpi-note">
            审核 {{ data.pending.reviews }} · 举报 {{ data.pending.reports }}
          </p>
        </article>
        <article class="card kpi">
          <p class="kpi-label">交易总数</p>
          <strong class="kpi-value">{{ tradeTotal.toLocaleString() }}</strong>
          <p class="muted kpi-note">
            完成 {{ data.trades.completed }} · 终止 {{ data.trades.terminated }} · 争议
            {{ data.trades.disputed }}
          </p>
        </article>
      </section>

      <div class="chart-grid">
        <section class="card chart-card" aria-labelledby="trend-title">
          <header class="chart-head">
            <h2 id="trend-title">完成交易趋势</h2>
            <span class="muted">{{ trendLoading ? "读取中…" : `${trend.length} 天` }}</span>
          </header>
          <svg
            v-if="trend.length"
            class="trend"
            viewBox="0 0 336 112"
            role="img"
            :aria-label="`完成交易趋势：${trend.map((item) => `${item.label} ${item.count}`).join('，')}`"
          >
            <line x1="8" y1="96" x2="328" y2="96" class="axis" />
            <g v-for="(point, index) in trendPoints" :key="trend[index].label">
              <rect
                :x="point.x - 8"
                :y="point.y"
                width="16"
                :height="Math.max(2, point.height)"
                rx="3"
                class="bar"
              />
              <text :x="point.x" y="108" text-anchor="middle" class="axis-label">
                {{ trend[index].label }}
              </text>
              <text :x="point.x" :y="point.y - 4" text-anchor="middle" class="value-label">
                {{ trend[index].count }}
              </text>
            </g>
          </svg>
          <p v-else class="muted">全部时间不绘制按日趋势。</p>
        </section>

        <section class="card chart-card" aria-labelledby="products-title">
          <header class="chart-head">
            <h2 id="products-title">商品状态分布</h2>
            <span class="muted">共 {{ productTotal }} 件</span>
          </header>
          <div class="donut-row">
            <svg
              class="donut"
              viewBox="0 0 42 42"
              role="img"
              :aria-label="`商品状态：${productStates.map((item) => `${item.label} ${item.count}`).join('，')}`"
            >
              <circle
                cx="21"
                cy="21"
                r="15.915"
                fill="none"
                stroke="var(--card-border, #e2e8f0)"
                stroke-width="6"
              />
              <circle
                v-for="segment in donutSegments"
                :key="segment.label"
                cx="21"
                cy="21"
                r="15.915"
                fill="none"
                :stroke="segment.color"
                stroke-width="6"
                :stroke-dasharray="segment.dash"
                :stroke-dashoffset="100 - segment.offset"
                transform="rotate(-90 21 21)"
              />
              <text x="21" y="22" text-anchor="middle" class="donut-total">{{ productTotal }}</text>
            </svg>
            <ul class="legend">
              <li v-for="item in productStates" :key="item.label">
                <span class="dot" :style="{ background: item.color }" />
                <span class="legend-label">{{ item.label }}</span>
                <span class="legend-value">{{ item.count }}</span>
              </li>
            </ul>
          </div>
        </section>

        <section class="card chart-card" aria-labelledby="trades-title">
          <header class="chart-head">
            <h2 id="trades-title">交易结果</h2>
            <span class="muted">共 {{ tradeTotal }} 笔</span>
          </header>
          <div
            class="stack-bar"
            role="img"
            :aria-label="`交易结果：${tradeParts.map((item) => `${item.label} ${item.count}`).join('，')}`"
          >
            <span
              v-for="item in tradeParts"
              :key="item.label"
              :style="{
                width: tradeTotal === 0 ? '0%' : `${(item.count / tradeTotal) * 100}%`,
                background: item.color,
              }"
            />
          </div>
          <ul class="legend legend--inline">
            <li v-for="item in tradeParts" :key="item.label">
              <span class="dot" :style="{ background: item.color }" />
              <span class="legend-label">{{ item.label }}</span>
              <span class="legend-value">{{ item.count }}</span>
            </li>
          </ul>
        </section>

        <section class="card chart-card" aria-labelledby="pending-title">
          <header class="chart-head">
            <h2 id="pending-title">待处理事项</h2>
            <span class="muted">共 {{ pendingTotal }} 项</span>
          </header>
          <div
            class="stack-bar"
            role="img"
            :aria-label="`待处理事项：${pendingParts.map((item) => `${item.label} ${item.count}`).join('，')}`"
          >
            <span
              v-for="item in pendingParts"
              :key="item.label"
              :style="{
                width: pendingTotal === 0 ? '0%' : `${(item.count / pendingTotal) * 100}%`,
                background: item.color,
              }"
            />
          </div>
          <ul class="legend legend--inline">
            <li v-for="item in pendingParts" :key="item.label">
              <span class="dot" :style="{ background: item.color }" />
              <span class="legend-label">{{ item.label }}</span>
              <span class="legend-value">{{ item.count }}</span>
            </li>
          </ul>
        </section>
      </div>
    </template>
  </div>
</template>

<style scoped>
.filter-bar {
  align-items: end;
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  padding-block: var(--space-2);
}
.filter-item {
  display: grid;
  flex: 1 1 12rem;
  gap: 2px;
}
.filter-item > span {
  color: var(--color-muted, #4a5568);
  font-size: 0.75rem;
}
.filter-submit {
  flex: 0 0 auto;
}
.filter-meta {
  color: var(--color-muted, #4a5568);
  font-size: 0.75rem;
  margin-left: auto;
  padding-bottom: 6px;
}
.kpi-row {
  display: grid;
  gap: var(--space-3);
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 11rem), 1fr));
}
.kpi {
  display: grid;
  gap: 2px;
  padding: var(--space-3);
}
.kpi-label {
  color: var(--color-muted, #4a5568);
  font-size: 0.75rem;
  margin: 0;
}
.kpi-value {
  font-size: 1.5rem;
  font-variant-numeric: tabular-nums;
  line-height: 1.2;
}
.kpi-note {
  font-size: 0.75rem;
  margin: 0;
}
.kpi--primary .kpi-value {
  color: var(--color-primary, #2f855a);
}
.chart-grid {
  display: grid;
  gap: var(--space-3);
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 20rem), 1fr));
}
.chart-card {
  display: grid;
  gap: var(--space-2);
  padding: var(--space-3);
}
.chart-head {
  align-items: baseline;
  display: flex;
  gap: var(--space-2);
  justify-content: space-between;
}
.chart-head h2 {
  font-size: 0.95rem;
  margin: 0;
}
.trend {
  height: auto;
  width: 100%;
}
.trend .axis {
  stroke: var(--card-border, #cbd5e0);
  stroke-width: 1;
}
.trend .bar {
  fill: var(--color-primary, #2f855a);
}
.axis-label,
.value-label,
.donut-total {
  fill: var(--color-muted, #4a5568);
  font-size: 8px;
}
.value-label {
  fill: var(--color-text, #1a202c);
  font-size: 7px;
}
.donut-total {
  fill: var(--color-text, #1a202c);
  font-size: 7px;
  font-weight: 600;
}
.donut-row {
  align-items: center;
  display: flex;
  gap: var(--space-3);
}
.donut {
  flex: 0 0 6.5rem;
  height: auto;
  width: 6.5rem;
}
.legend {
  display: grid;
  gap: 2px;
  list-style: none;
  margin: 0;
  padding: 0;
}
.legend--inline {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}
.legend li {
  align-items: center;
  display: flex;
  font-size: 0.75rem;
  gap: 4px;
}
.dot {
  border-radius: 50%;
  display: inline-block;
  height: 8px;
  width: 8px;
}
.legend-value {
  font-variant-numeric: tabular-nums;
  font-weight: 600;
  margin-left: auto;
}
.legend--inline .legend-value {
  margin-left: 0;
}
.stack-bar {
  background: var(--card-border, #e2e8f0);
  border-radius: 999px;
  display: flex;
  height: 12px;
  overflow: hidden;
  width: 100%;
}
.stack-bar span {
  display: block;
  height: 100%;
}
</style>
