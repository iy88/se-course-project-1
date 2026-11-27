import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { ManagementStatistics, StatisticsSelection } from "../api/statistics";
import { createStatisticsQuery, type StatisticsReader } from "./statistics-query";

interface Deferred<T> {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (error: unknown) => void;
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function flush(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

function range(startAt: string, endAt: string): StatisticsSelection {
  return { time_scope: "range", start_at: startAt, end_at: endAt };
}

function statistics(
  selection: StatisticsSelection,
  completed = 0,
  completedByDay: ManagementStatistics["completed_by_day"] = [],
): ManagementStatistics {
  return {
    as_of: "2026-11-27T00:00:00.000Z",
    selection: {
      time_scope: selection.time_scope,
      start_at: selection.time_scope === "range" ? selection.start_at : null,
      end_at: selection.time_scope === "range" ? selection.end_at : null,
    },
    accounts: { total: 0, banned: 0 },
    products_by_state: {
      pending_review: 0,
      review_rejected: 0,
      public: 0,
      in_trade: 0,
      off_shelf: 0,
    },
    pending: { reviews: 0, reports: 0 },
    trades: { completed: 0, terminated: 0, disputed: 0 },
    completed_in_selection: completed,
    completed_by_day: completedByDay,
  };
}

interface PendingCall {
  selection: StatisticsSelection;
  signal?: AbortSignal;
  resolve: (value: ManagementStatistics) => void;
  reject: (error: unknown) => void;
}

function queuedReader(): { calls: PendingCall[]; read: StatisticsReader } {
  const calls: PendingCall[] = [];
  const read: StatisticsReader = (selection, signal) => {
    const pending = deferred<ManagementStatistics>();
    calls.push({ selection, signal, ...pending });
    return pending.promise;
  };
  return { calls, read };
}

const SHORT_RANGE = range("2026-11-20T10:00:00.000Z", "2026-11-20T18:00:00.000Z");
const LONG_RANGE = range("2026-01-01T00:00:00.000Z", "2026-02-02T00:00:00.000Z");

describe("management statistics query lifecycle", () => {
  it("loads the summary and daily trend from one response", async () => {
    const { calls, read } = queuedReader();
    const query = createStatisticsQuery(read);
    const loaded = query.load(SHORT_RANGE);

    assert.equal(calls.length, 1);
    calls[0].resolve(statistics(SHORT_RANGE, 7, [{ day: "2026-11-20", completed: 7 }]));
    await loaded;

    assert.equal(calls.length, 1);
    assert.equal(query.data.value?.completed_in_selection, 7);
    assert.deepEqual(query.trend.value, [{ label: "11/20", count: 7 }]);
    assert.equal(query.trendStatus.value, "ready");
    assert.equal(query.trendDayCount.value, 1);
  });

  it("does not request a daily trend for all time", async () => {
    const { calls, read } = queuedReader();
    const query = createStatisticsQuery(read);
    const loaded = query.load({ time_scope: "all" });

    assert.equal(calls.length, 1);
    calls[0].resolve(statistics({ time_scope: "all" }, 6));
    await loaded;

    assert.equal(calls.length, 1);
    assert.equal(query.trendStatus.value, "all");
    assert.deepEqual(query.trend.value, []);
  });

  it("uses one summary request for a range above 31 UTC days", async () => {
    const { calls, read } = queuedReader();
    const query = createStatisticsQuery(read);
    const loaded = query.load(LONG_RANGE);

    assert.equal(calls.length, 1);
    calls[0].resolve(statistics(LONG_RANGE, 5));
    await loaded;

    assert.equal(calls.length, 1);
    assert.equal(query.trendStatus.value, "too-many");
    assert.equal(query.trendDayCount.value, 32);
    assert.deepEqual(query.trend.value, []);
  });

  it("does not write a stale response after a newer query starts", async () => {
    const { calls, read } = queuedReader();
    const query = createStatisticsQuery(read);
    const first = query.load(SHORT_RANGE);
    const second = query.load(LONG_RANGE);
    const currentSummary = () => query.data.value;

    assert.equal(calls.length, 2);
    assert.equal(calls[0].signal?.aborted, true);
    calls[0].resolve(statistics(SHORT_RANGE, 11));
    await flush();

    assert.equal(currentSummary(), undefined);
    assert.equal(query.loading.value, true);

    calls[1].resolve(statistics(LONG_RANGE, 22));
    await second;
    await first;

    assert.equal(currentSummary()?.completed_in_selection, 22);
    assert.equal(query.trendStatus.value, "too-many");
  });

  it("retries a failed request and renders only the successful result", async () => {
    const { calls, read } = queuedReader();
    const query = createStatisticsQuery(read);
    const first = query.load(SHORT_RANGE);

    calls[0].reject(new Error("statistics down"));
    await first;
    assert.ok(query.error.value instanceof Error);

    query.retry();
    assert.equal(calls.length, 2);
    calls[1].resolve(statistics(SHORT_RANGE, 3, [{ day: "2026-11-20", completed: 3 }]));
    await flush();

    assert.equal(query.error.value, undefined);
    assert.equal(query.data.value?.completed_in_selection, 3);
    assert.deepEqual(query.trend.value, [{ label: "11/20", count: 3 }]);
  });

  it("ignores a pending response after dispose", async () => {
    const { calls, read } = queuedReader();
    const query = createStatisticsQuery(read);
    void query.load(SHORT_RANGE);
    query.dispose();

    assert.equal(calls[0].signal?.aborted, true);
    calls[0].resolve(statistics(SHORT_RANGE, 8));
    await flush();

    assert.equal(query.data.value, undefined);
    assert.deepEqual(query.trend.value, []);
  });
});
