import { ref } from "vue";
import { AbortedError } from "../api/errors";
import {
  readStatistics,
  type ManagementStatistics,
  type StatisticsSelection,
} from "../api/statistics";
import { buildTrendBucketPlan } from "../app/statistics-trend";

export type TrendStatus = "idle" | "loading" | "ready" | "all" | "too-many" | "error";

export interface TrendPoint {
  label: string;
  count: number;
}

export type StatisticsReader = (
  selection: StatisticsSelection,
  signal?: AbortSignal,
) => Promise<ManagementStatistics>;

/*
 * Owns the summary and daily-trend requests. Each load gets a generation; every
 * asynchronous write checks it so a replaced or unmounted query cannot revive
 * old data.
 */
export function createStatisticsQuery(read: StatisticsReader = readStatistics) {
  const data = ref<ManagementStatistics>();
  const trend = ref<TrendPoint[]>([]);
  const error = ref<unknown>();
  const loading = ref(false);
  const trendStatus = ref<TrendStatus>("idle");
  const trendError = ref<unknown>();
  const trendLoading = ref(false);
  const trendDayCount = ref(0);
  let lastSelection: StatisticsSelection | undefined;
  let queryGeneration = 0;
  let trendGeneration = 0;
  let summaryController: AbortController | undefined;
  let trendControllers: AbortController[] = [];

  function abortSummary(): void {
    summaryController?.abort();
    summaryController = undefined;
  }

  function abortTrend(): void {
    trendGeneration += 1;
    for (const controller of trendControllers) controller.abort();
    trendControllers = [];
  }

  function resetTrend(): void {
    abortTrend();
    trend.value = [];
    trendStatus.value = "idle";
    trendError.value = undefined;
    trendLoading.value = false;
    trendDayCount.value = 0;
  }

  async function loadTrend(selection: StatisticsSelection, generation: number): Promise<void> {
    if (generation !== queryGeneration) return;
    abortTrend();
    const trendRun = trendGeneration;
    const current = (): boolean => generation === queryGeneration && trendRun === trendGeneration;
    trend.value = [];
    trendStatus.value = "idle";
    trendError.value = undefined;
    trendLoading.value = false;
    trendDayCount.value = 0;

    if (selection.time_scope !== "range") {
      trendStatus.value = "all";
      return;
    }

    const plan = buildTrendBucketPlan(selection.start_at, selection.end_at);
    if (plan.kind === "too-many") {
      trendStatus.value = "too-many";
      trendDayCount.value = plan.utcDayCount;
      return;
    }

    const buckets = plan.buckets;
    trendStatus.value = "loading";
    trendLoading.value = true;
    const controllers = buckets.map(() => new AbortController());
    trendControllers = controllers;
    try {
      const results = await Promise.all(
        buckets.map((bucket, index) =>
          read(
            { time_scope: "range", start_at: bucket.start_at, end_at: bucket.end_at },
            controllers[index].signal,
          ),
        ),
      );
      if (!current()) return;
      trend.value = buckets.map((bucket, index) => ({
        label: bucket.label,
        count: results[index].completed_in_selection,
      }));
      trendStatus.value = "ready";
    } catch (caught) {
      if (!current()) return;
      controllers.forEach((controller) => controller.abort());
      trend.value = [];
      if (caught instanceof AbortedError) {
        trendStatus.value = "idle";
      } else {
        trendError.value = caught;
        trendStatus.value = "error";
      }
    } finally {
      if (current()) {
        trendLoading.value = false;
        trendControllers = [];
      }
    }
  }

  async function load(selection: StatisticsSelection): Promise<void> {
    const generation = ++queryGeneration;
    abortSummary();
    resetTrend();
    const controller = new AbortController();
    summaryController = controller;
    lastSelection = selection;
    loading.value = true;
    error.value = undefined;
    try {
      const result = await read(selection, controller.signal);
      if (generation !== queryGeneration) return;
      data.value = result;
      void loadTrend(selection, generation);
    } catch (caught) {
      if (generation !== queryGeneration) return;
      if (!(caught instanceof AbortedError)) error.value = caught;
    } finally {
      if (generation === queryGeneration) loading.value = false;
    }
  }

  function retry(): void {
    if (lastSelection) void load(lastSelection);
  }

  function retryTrend(): void {
    if (lastSelection && !loading.value) void loadTrend(lastSelection, queryGeneration);
  }

  function dispose(): void {
    queryGeneration += 1;
    abortSummary();
    abortTrend();
  }

  return {
    data,
    trend,
    error,
    loading,
    trendStatus,
    trendError,
    trendLoading,
    trendDayCount,
    load,
    retry,
    retryTrend,
    dispose,
  };
}
