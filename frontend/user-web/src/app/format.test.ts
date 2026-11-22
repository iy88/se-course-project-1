import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  formatCents,
  formatCentsAsYuanInput,
  formatDateTime,
  formatRemaining,
  fromLocalInputValue,
  initialOf,
  parseYuanToCents,
  toLocalInputValue,
  truncate,
} from "./format";

describe("money formatting", () => {
  it("renders integer cents as a yuan amount", () => {
    assert.equal(formatCents(4500), "¥45.00");
    assert.equal(formatCents(1), "¥0.01");
    assert.equal(formatCents(0), "¥0.00");
  });

  it("parses a yuan input into integer cents", () => {
    assert.equal(parseYuanToCents("45"), 4500);
    assert.equal(parseYuanToCents("45.5"), 4550);
    assert.equal(parseYuanToCents("0.01"), 1);
    assert.equal(parseYuanToCents(" 12.30 "), 1230);
  });

  it("rejects unusable price input", () => {
    for (const input of ["", "-1", "1.234", "abc", "1,5", "."]) {
      assert.equal(parseYuanToCents(input), null, `expected null for ${JSON.stringify(input)}`);
    }
  });

  it("round-trips cents into the editable yuan form", () => {
    assert.equal(formatCentsAsYuanInput(4500), "45.00");
    assert.equal(formatCentsAsYuanInput(null), "");
    assert.equal(formatCentsAsYuanInput(undefined), "");
  });
});

describe("time formatting", () => {
  it("formats a missing or invalid timestamp as a dash", () => {
    assert.equal(formatDateTime(null), "—");
    assert.equal(formatDateTime(undefined), "—");
    assert.equal(formatDateTime("not-a-date"), "—");
  });

  it("formats a valid timestamp with localised digits", () => {
    const formatted = formatDateTime("2026-11-20T09:00:00Z");
    assert.match(formatted, /\d{4}/);
    assert.match(formatted, /\d{2}:\d{2}/);
  });

  it("round-trips a datetime-local value", () => {
    const local = toLocalInputValue("2026-11-20T09:30:00Z");
    assert.match(local, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/);
    const back = fromLocalInputValue(local);
    assert.ok(back !== null);
    assert.equal(new Date(back).getTime(), new Date("2026-11-20T09:30:00Z").getTime());
  });

  it("rejects an empty datetime-local value", () => {
    assert.equal(fromLocalInputValue(""), null);
    assert.equal(toLocalInputValue(null), "");
  });

  it("describes a countdown in days, hours or minutes", () => {
    assert.equal(formatRemaining(0), "已到期");
    assert.equal(formatRemaining(-5), "已到期");
    assert.equal(formatRemaining(6 * 86_400 + 4 * 3_600), "6 天 4 小时");
    assert.equal(formatRemaining(3 * 3_600 + 30 * 60), "3 小时 30 分");
    assert.equal(formatRemaining(45), "1 分钟");
  });
});

describe("text helpers", () => {
  it("truncates long text with an ellipsis", () => {
    assert.equal(truncate("abcdef", 6), "abcdef");
    assert.equal(truncate("abcdefg", 6), "abcde…");
  });

  it("uses the first character of a display name for the avatar fallback", () => {
    assert.equal(initialOf("林同学"), "林");
    assert.equal(initialOf("  zhao "), "Z");
    assert.equal(initialOf("   "), "?");
  });
});
