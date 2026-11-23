import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { formatCents } from "./format";

describe("administrative formatting", () => {
  it("renders integer cents as yuan amounts", () => {
    assert.equal(formatCents(0), "¥0.00");
    assert.equal(formatCents(1234), "¥12.34");
  });

  it("uses a placeholder for unusable amounts", () => {
    assert.equal(formatCents(Number.NaN), "—");
  });
});
