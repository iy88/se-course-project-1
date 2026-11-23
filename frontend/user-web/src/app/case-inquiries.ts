/*
 * Appeal window and pending-inquiry projection.
 *
 * Both rules are pure so the view can recompute them from a ticking clock instead of
 * reading `Date.now()` inside a computed (which would freeze while the page stays
 * open) and so the todo scan can page until it finds the current case.
 */
import type { TodoItem } from "../api/contracts";

/** Milliseconds left before the appeal deadline, never negative. */
export function appealRemainingMs(deadline: string | null, now: number): number {
  if (!deadline) return 0;
  const at = new Date(deadline).getTime();
  if (Number.isNaN(at)) return 0;
  return Math.max(0, at - now);
}

/** Whether the appeal entry is still open at `now`. */
export function appealOpenAt(deadline: string | null, now: number): boolean {
  return appealRemainingMs(deadline, now) > 0;
}

export const INQUIRY_TODO_KIND = "inquiry_response" as const;

/**
 * Inquiry action ids of one case across the todo pages already read.
 *
 * The todo projection is global, so entries of other cases and malformed payloads are
 * ignored; ids are de-duplicated because one case may appear in several todos.
 */
export function inquiryIdsForCase(pages: readonly TodoItem[][], caseId: string): string[] {
  const ids = new Set<string>();
  for (const page of pages) {
    for (const todo of page) {
      if (todo.kind !== INQUIRY_TODO_KIND) continue;
      const source = todo.source as { case_id?: unknown; inquiry_action_ids?: unknown };
      if (String(source.case_id ?? "") !== caseId) continue;
      if (!Array.isArray(source.inquiry_action_ids)) continue;
      for (const value of source.inquiry_action_ids) {
        if (value === null || value === undefined) continue;
        const id = String(value).trim();
        if (id !== "") ids.add(id);
      }
    }
  }
  return [...ids];
}

/**
 * Whether another todo page must be read.
 *
 * Stops once the case was found, when the server reports no further rows, or when the
 * page guard is reached so a misbehaving server cannot keep the loop running.
 */
export function shouldLoadNextPage(options: {
  found: boolean;
  pagesRead: number;
  pageSize: number;
  total: number;
  maxPages: number;
}): boolean {
  if (options.found) return false;
  if (options.pagesRead >= options.maxPages) return false;
  return options.pagesRead * options.pageSize < options.total;
}
