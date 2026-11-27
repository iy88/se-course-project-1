import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { buildTrendBucketPlan, TREND_DAY_LIMIT } from "./statistics-trend";

function bucketsOf(startAt: string, endAt: string) {
  const plan = buildTrendBucketPlan(startAt, endAt);
  assert.equal(plan.kind, "buckets");
  if (plan.kind !== "buckets") throw new Error("expected daily buckets");
  return plan.buckets;
}

describe("management statistics UTC day buckets", () => {
  it("clips both ends to the half-open query range", () => {
    assert.deepEqual(bucketsOf("2026-11-20T10:30:00.000Z", "2026-11-21T18:00:00.000Z"), [
      { label: "11/20", start_at: "2026-11-20T10:30:00.000Z", end_at: "2026-11-21T00:00:00.000Z" },
      { label: "11/21", start_at: "2026-11-21T00:00:00.000Z", end_at: "2026-11-21T18:00:00.000Z" },
    ]);
  });

  it("keeps one bucket when the range stays inside a UTC day", () => {
    assert.deepEqual(bucketsOf("2026-11-20T18:00:00.000Z", "2026-11-20T18:01:00.000Z"), [
      { label: "11/20", start_at: "2026-11-20T18:00:00.000Z", end_at: "2026-11-20T18:01:00.000Z" },
    ]);
  });

  it("does not add an empty bucket when the range ends exactly at UTC midnight", () => {
    assert.deepEqual(bucketsOf("2026-11-20T10:30:00.000Z", "2026-11-21T00:00:00.000Z"), [
      { label: "11/20", start_at: "2026-11-20T10:30:00.000Z", end_at: "2026-11-21T00:00:00.000Z" },
    ]);
  });

  it("splits across month and year boundaries using UTC calendar days", () => {
    assert.deepEqual(bucketsOf("2026-12-31T23:00:00.000Z", "2027-01-01T01:00:00.000Z"), [
      { label: "12/31", start_at: "2026-12-31T23:00:00.000Z", end_at: "2027-01-01T00:00:00.000Z" },
      { label: "1/1", start_at: "2027-01-01T00:00:00.000Z", end_at: "2027-01-01T01:00:00.000Z" },
    ]);
  });

  it("allows exactly 31 intersected UTC days", () => {
    const buckets = bucketsOf("2026-01-01T00:00:00.000Z", "2026-02-01T00:00:00.000Z");
    assert.equal(buckets.length, TREND_DAY_LIMIT);
    assert.deepEqual(buckets[0], {
      label: "1/1",
      start_at: "2026-01-01T00:00:00.000Z",
      end_at: "2026-01-02T00:00:00.000Z",
    });
    assert.deepEqual(buckets[buckets.length - 1], {
      label: "1/31",
      start_at: "2026-01-31T00:00:00.000Z",
      end_at: "2026-02-01T00:00:00.000Z",
    });
  });

  it("rejects 32 intersected UTC days before building a bucket list", () => {
    const plan = buildTrendBucketPlan("2026-01-01T00:00:00.000Z", "2026-02-02T00:00:00.000Z");
    assert.deepEqual(plan, { kind: "too-many", utcDayCount: 32, limit: TREND_DAY_LIMIT });
  });

  it("counts a partial extra day as an additional bucket", () => {
    const plan = buildTrendBucketPlan("2026-01-01T00:00:00.000Z", "2026-02-01T00:00:00.001Z");
    assert.deepEqual(plan, { kind: "too-many", utcDayCount: 32, limit: TREND_DAY_LIMIT });
  });

  it("rejects a very large range without enumerating its days", () => {
    const plan = buildTrendBucketPlan("0001-01-01T00:00:00.000Z", "9999-12-31T00:00:00.000Z");
    assert.equal(plan.kind, "too-many");
    if (plan.kind !== "too-many") return;
    assert.equal(plan.limit, TREND_DAY_LIMIT);
    assert.ok(plan.utcDayCount > 3_000_000);
  });
});
