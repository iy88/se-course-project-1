/*
 * Appeal window across a ticking clock and the pending-inquiry todo scan.
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { TodoItem } from "../api/contracts";
import {
  appealOpenAt,
  appealRemainingMs,
  inquiryIdsForCase,
  shouldLoadNextPage,
} from "./case-inquiries";

function todo(kind: TodoItem["kind"], source: Record<string, unknown>, key = "k"): TodoItem {
  return {
    todo_key: key,
    kind,
    source,
    created_at: "2026-11-23T10:00:00Z",
    updated_at: "2026-11-23T10:00:00Z",
    summary: "待办",
  };
}

describe("appeal window", () => {
  const deadline = "2026-11-23T12:00:00Z";

  it("stays open before the deadline and closes exactly at it", () => {
    const before = new Date("2026-11-23T11:59:30Z").getTime();
    const at = new Date(deadline).getTime();

    assert.equal(appealOpenAt(deadline, before), true);
    assert.equal(appealOpenAt(deadline, at), false, "the entry hides at the deadline");
    assert.equal(appealOpenAt(deadline, at + 1), false);
  });

  it("reports the remaining seconds and never a negative value", () => {
    const before = new Date("2026-11-23T11:59:30Z").getTime();

    assert.equal(appealRemainingMs(deadline, before), 30_000);
    assert.equal(appealRemainingMs(deadline, new Date("2026-11-23T12:05:00Z").getTime()), 0);
  });

  it("treats a missing or malformed deadline as closed", () => {
    const now = Date.now();

    assert.equal(appealOpenAt(null, now), false);
    assert.equal(appealOpenAt("not-a-time", now), false);
    assert.equal(appealRemainingMs(null, now), 0);
  });
});

describe("pending inquiries", () => {
  it("finds the case on the second page", () => {
    const pages = [
      [todo("inquiry_response", { case_id: "6", inquiry_action_ids: ["1"] }, "a")],
      [todo("inquiry_response", { case_id: "8", inquiry_action_ids: ["5", "6"] }, "b")],
    ];

    assert.deepEqual(inquiryIdsForCase(pages, "8"), ["5", "6"]);
  });

  it("ignores other cases, other todo kinds and malformed ids", () => {
    const pages = [
      [
        todo("inquiry_response", { case_id: "9", inquiry_action_ids: ["7"] }, "a"),
        todo("request_response", { case_id: "8", inquiry_action_ids: ["8"] }, "b"),
        todo("inquiry_response", { case_id: "8", inquiry_action_ids: [null, "", "  ", 5] }, "c"),
        todo("inquiry_response", { case_id: "8", inquiry_action_ids: "5" }, "d"),
      ],
    ];

    assert.deepEqual(inquiryIdsForCase(pages, "8"), ["5"]);
  });

  it("de-duplicates an id reported by several todos", () => {
    const pages = [
      [
        todo("inquiry_response", { case_id: "8", inquiry_action_ids: ["5"] }, "a"),
        todo("inquiry_response", { case_id: "8", inquiry_action_ids: ["5", "6"] }, "b"),
      ],
    ];

    assert.deepEqual(inquiryIdsForCase(pages, "8"), ["5", "6"]);
  });

  it("pages until the case is found or the rows are exhausted", () => {
    assert.equal(
      shouldLoadNextPage({ found: false, pagesRead: 0, pageSize: 50, total: 120, maxPages: 5 }),
      true,
    );
    assert.equal(
      shouldLoadNextPage({ found: false, pagesRead: 2, pageSize: 50, total: 120, maxPages: 5 }),
      true,
      "two pages of 50 leave 20 rows",
    );
    assert.equal(
      shouldLoadNextPage({ found: false, pagesRead: 3, pageSize: 50, total: 120, maxPages: 5 }),
      false,
    );
    assert.equal(
      shouldLoadNextPage({ found: true, pagesRead: 1, pageSize: 50, total: 120, maxPages: 5 }),
      false,
    );
    assert.equal(
      shouldLoadNextPage({ found: false, pagesRead: 1, pageSize: 50, total: 20, maxPages: 5 }),
      false,
      "the only page is already read",
    );
    assert.equal(
      shouldLoadNextPage({ found: false, pagesRead: 5, pageSize: 50, total: 1000, maxPages: 5 }),
      false,
    );
  });
});
