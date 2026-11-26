import type { BannedGroupKey } from "../api/contracts";

export const BANNED_ROWS_PER_GROUP = 5;

export interface BannedGroupPage<T> {
  rows: T[];
  total: number;
  page: number;
  pageSize: number;
}

export function lastBannedGroupPage(total: number): number {
  return Math.max(1, Math.ceil(total / BANNED_ROWS_PER_GROUP));
}

export function pageBannedGroup<T extends { group: BannedGroupKey }>(
  rows: T[],
  group: BannedGroupKey,
  requestedPage: number,
): BannedGroupPage<T> {
  const allRows = rows.filter((row) => row.group === group);
  const page = Math.min(Math.max(1, requestedPage), lastBannedGroupPage(allRows.length));
  const start = (page - 1) * BANNED_ROWS_PER_GROUP;
  return {
    rows: allRows.slice(start, start + BANNED_ROWS_PER_GROUP),
    total: allRows.length,
    page,
    pageSize: BANNED_ROWS_PER_GROUP,
  };
}
