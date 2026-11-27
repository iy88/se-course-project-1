import { computed, ref } from "vue";
import { AbortedError } from "../api/errors";
import {
  readStatistics,
  type ManagementStatistics,
  type StatisticsSelection,
} from "../api/statistics";
import { buildTrendBucketPlan, TREND_DAY_LIMIT } from "../app/statistics-trend";

export type TrendStatus = "idle" | "ready" | "all" | "too-many";

export interface TrendPoint {
  label: string;
  count: number;
}

export type StatisticsReader = (
  selection: StatisticsSelection,
  signal?: AbortSignal,
) => Promise<ManagementStatistics>;

/*
 * Owns the single statistics request and derives every chart from its result.
 * Each load gets a generation so a replaced or unmounted query cannot revive
 * old data.
 */
export function createStatisticsQuery(read: StatisticsReader = readStatistics) {
  const data = ref<ManagementStatistics>();
  const error = ref<unknown>();
  const loading = ref(false);
  let lastSelection: StatisticsSelection | undefined;
  let queryGeneration = 0;
  let requestController: AbortController | undefined;

  const trend = computed<TrendPoint[]>(
    () =>
      data.value?.completed_by_day.map((item) => ({
        label: dayLabel(item.day),
        count: item.completed,
      })) ?? [],
  );
  const trendPlan = computed(() => {
    const selection = data.value?.selection;
    if (
      !selection ||
      selection.time_scope !== "range" ||
      !selection.start_at ||
      !selection.end_at
    ) {
      return undefined;
    }
    return buildTrendBucketPlan(selection.start_at, selection.end_at);
  });
  const trendStatus = computed<TrendStatus>(() => {
    if (!data.value) return "idle";
    if (data.value.selection.time_scope === "all") return "all";
    return trendPlan.value?.kind === "too-many" ? "too-many" : "ready";
  });
  const trendDayCount = computed(() => {
    const plan = trendPlan.value;
    if (!plan) return 0;
    return plan.kind === "too-many"
      ? plan.utcDayCount
      : Math.min(plan.buckets.length, TREND_DAY_LIMIT);
  });

  function dayLabel(day: string): string {
    const [, month, date] = day.split("-");
    return `${Number(month)}/${Number(date)}`;
  }

  async function load(selection: StatisticsSelection): Promise<void> {
    const generation = ++queryGeneration;
    requestController?.abort();
    const controller = new AbortController();
    requestController = controller;
    lastSelection = selection;
    loading.value = true;
    error.value = undefined;
    try {
      const result = await read(selection, controller.signal);
      if (generation !== queryGeneration) return;
      data.value = result;
    } catch (caught) {
      if (generation !== queryGeneration) return;
      if (!(caught instanceof AbortedError)) error.value = caught;
    } finally {
      if (generation === queryGeneration) {
        loading.value = false;
        requestController = undefined;
      }
    }
  }

  function retry(): void {
    if (lastSelection) void load(lastSelection);
  }

  function dispose(): void {
    queryGeneration += 1;
    requestController?.abort();
    requestController = undefined;
  }

  return {
    data,
    trend,
    error,
    loading,
    trendStatus,
    trendDayCount,
    load,
    retry,
    dispose,
  };
}
