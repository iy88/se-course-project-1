/*
 * Daily trend planning for the management statistics page.
 *
 * The API only accepts a half-open UTC range. Build one bucket per intersected
 * UTC calendar day so the first and last buckets stay inside that range, and
 * reject ranges above the request limit before materialising any bucket.
 */

export const DAY_MS = 86_400_000;
export const TREND_DAY_LIMIT = 31;

export interface TrendBucket {
  label: string;
  start_at: string;
  end_at: string;
}

export type TrendBucketPlan =
  | { kind: "buckets"; buckets: TrendBucket[] }
  | { kind: "too-many"; utcDayCount: number; limit: number };

function utcDayStart(value: number): number {
  const date = new Date(value);
  date.setUTCHours(0, 0, 0, 0);
  return date.getTime();
}

function nextUtcDay(value: number): number {
  const date = new Date(value);
  date.setUTCHours(0, 0, 0, 0);
  date.setUTCDate(date.getUTCDate() + 1);
  return date.getTime();
}

function dayLabel(value: number): string {
  const date = new Date(value);
  return `${date.getUTCMonth() + 1}/${date.getUTCDate()}`;
}

export function buildTrendBucketPlan(startAt: string, endAt: string): TrendBucketPlan {
  const start = new Date(startAt).getTime();
  const end = new Date(endAt).getTime();
  const firstDay = utcDayStart(start);
  const utcDayCount = Math.ceil((end - firstDay) / DAY_MS);
  if (utcDayCount > TREND_DAY_LIMIT) {
    return { kind: "too-many", utcDayCount, limit: TREND_DAY_LIMIT };
  }
  const buckets: TrendBucket[] = [];
  for (let day = firstDay; day < end; day = nextUtcDay(day)) {
    buckets.push({
      label: dayLabel(day),
      start_at: new Date(Math.max(day, start)).toISOString(),
      end_at: new Date(Math.min(nextUtcDay(day), end)).toISOString(),
    });
  }
  return { kind: "buckets", buckets };
}
