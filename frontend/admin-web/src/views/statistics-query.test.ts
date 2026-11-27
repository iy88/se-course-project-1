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

function statistics(selection: StatisticsSelection, completed = 0): ManagementStatistics {
  return {
    as_of: "2026-11-27T00:00:00.000Z",
    selection: {
      time_scope: "range",
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
  it("keeps a failed trend separate from the valid summary and retries it", async () => {
    let calls = 0;
    const read: StatisticsReader = () => {
      calls += 1;
      if (calls === 1) return Promise.resolve(statistics(SHORT_RANGE, 7));
      if (calls === 2) return Promise.reject(new Error("trend down"));
      return Promise.resolve(statistics(SHORT_RANGE, 0));
    };
    const query = createStatisticsQuery(read);

    await query.load(range("2026-11-20T10:00:00.000Z", "2026-11-21T18:00:00.000Z"));
    await flush();

    assert.equal(query.data.value?.completed_in_selection, 7);
    assert.equal(query.error.value, undefined);
    assert.equal(query.trendStatus.value, "error");
    assert.ok(query.trendError.value instanceof Error);
    assert.equal(query.trend.value.length, 0);

    query.retryTrend();
    await flush();

    assert.equal(query.trendStatus.value, "ready");
    assert.deepEqual(
      query.trend.value.map((point) => point.count),
      [0, 0],
    );
    assert.equal(query.data.value?.completed_in_selection, 7);
  });

  it("skips every trend request above 31 UTC day buckets", async () => {
    const { calls, read } = queuedReader();
    const query = createStatisticsQuery(read);
    const loaded = query.load(LONG_RANGE);
    assert.equal(calls.length, 1);

    calls[0].resolve(statistics(LONG_RANGE, 5));
    await loaded;
    await flush();

    assert.equal(calls.length, 1);
    assert.equal(query.trendStatus.value, "too-many");
    assert.equal(query.trendDayCount.value, 32);
    assert.deepEqual(query.trend.value, []);
  });

  it("does not request a daily trend for all time", async () => {
    const { calls, read } = queuedReader();
    const query = createStatisticsQuery(read);
    const loaded = query.load({ time_scope: "all" });
    assert.equal(calls.length, 1);

    calls[0].resolve(statistics({ time_scope: "all" }, 6));
    await loaded;
    await flush();

    assert.equal(calls.length, 1);
    assert.equal(query.trendStatus.value, "all");
    assert.deepEqual(query.trend.value, []);
  });

  it("loads 31 buckets and keeps a successful zero", async () => {
    const { calls, read } = queuedReader();
    const query = createStatisticsQuery(read);
    const loaded = query.load(range("2026-01-01T00:00:00.000Z", "2026-02-01T00:00:00.000Z"));
    calls[0].resolve(statistics(LONG_RANGE, 0));
    await loaded;
    await flush();

    assert.equal(calls.length, 32);
    for (const call of calls.slice(1)) call.resolve(statistics(call.selection, 0));
    await flush();

    assert.equal(query.trendStatus.value, "ready");
    assert.equal(query.trend.value.length, 31);
    assert.ok(query.trend.value.every((point) => point.count === 0));
  });

  it("does not write a stale summary response after a newer query starts", async () => {
    const { calls, read } = queuedReader();
    const query = createStatisticsQuery(read);
    const first = query.load(SHORT_RANGE);
    const second = query.load(LONG_RANGE);
    const currentSummary = () => query.data.value;

    assert.equal(calls[0].signal?.aborted, true);
    calls[0].resolve(statistics(SHORT_RANGE, 11));
    await flush();

    assert.equal(currentSummary(), undefined);
    assert.equal(query.loading.value, true);

    calls[1].resolve(statistics(LONG_RANGE, 22));
    await second;
    await flush();
    await first;

    assert.equal(currentSummary()?.completed_in_selection, 22);
    assert.equal(query.trendStatus.value, "too-many");
  });

  it("does not write a stale bucket response after switching to a long range", async () => {
    const { calls, read } = queuedReader();
    const query = createStatisticsQuery(read);
    const first = query.load(SHORT_RANGE);
    calls[0].resolve(statistics(SHORT_RANGE, 3));
    await first;
    await flush();
    assert.equal(calls.length, 2);

    const second = query.load(LONG_RANGE);
    assert.equal(calls[1].signal?.aborted, true);
    calls[1].resolve(statistics(SHORT_RANGE, 99));
    await flush();

    assert.equal(query.data.value?.completed_in_selection, 3);
    assert.deepEqual(query.trend.value, []);
    assert.equal(query.trendStatus.value, "idle");

    calls[2].resolve(statistics(LONG_RANGE, 4));
    await second;
    await flush();

    assert.equal(query.trendStatus.value, "too-many");
    assert.equal(query.trendDayCount.value, 32);
    assert.deepEqual(query.trend.value, []);
  });

  it("does not write a stale bucket response after switching to all time", async () => {
    const { calls, read } = queuedReader();
    const query = createStatisticsQuery(read);
    const first = query.load(SHORT_RANGE);
    calls[0].resolve(statistics(SHORT_RANGE, 3));
    await first;
    await flush();
    assert.equal(calls.length, 2);

    const second = query.load({ time_scope: "all" });
    assert.equal(calls[1].signal?.aborted, true);
    calls[1].resolve(statistics(SHORT_RANGE, 99));
    await flush();

    assert.equal(query.trendStatus.value, "idle");
    assert.deepEqual(query.trend.value, []);

    calls[2].resolve(statistics({ time_scope: "all" }, 4));
    await second;
    await flush();

    assert.equal(query.trendStatus.value, "all");
    assert.deepEqual(query.trend.value, []);
    assert.equal(query.data.value?.completed_in_selection, 4);
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
