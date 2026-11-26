import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { parseHash, routeHref } from "./routes";

describe("admin routes", () => {
  it("falls back to the shared review pool", () => {
    assert.deepEqual(parseHash(""), { name: "reviews", ownership: "unclaimed" });
    assert.deepEqual(parseHash("#/"), { name: "reviews", ownership: "unclaimed" });
  });

  it("reads the queue ownership filter", () => {
    assert.deepEqual(parseHash("#/reviews?ownership=mine"), { name: "reviews", ownership: "mine" });
    assert.deepEqual(parseHash("#/reviews?ownership=unclaimed"), {
      name: "reviews",
      ownership: "unclaimed",
    });
  });

  it("reads and decodes a review audit id", () => {
    assert.deepEqual(parseHash("#/reviews/1001"), { name: "review", auditId: "1001" });
    assert.deepEqual(parseHash("#/reviews/a%20b"), { name: "review", auditId: "a b" });
  });

  it("reads the workbench scope, type and keyword", () => {
    assert.deepEqual(parseHash("#/cases"), {
      name: "cases",
      ownership: "unclaimed",
      kind: "all",
      keyword: "",
    });
    assert.deepEqual(
      parseHash("#/cases?ownership=completed_all&kind=report&keyword=%E6%97%A7%E4%B9%A6"),
      {
        name: "cases",
        ownership: "completed_all",
        kind: "report",
        keyword: "旧书",
      },
    );
    assert.deepEqual(parseHash("#/cases?ownership=bogus&kind=bogus"), {
      name: "cases",
      ownership: "unclaimed",
      kind: "all",
      keyword: "",
    });
  });

  it("recognises the maintenance pages", () => {
    assert.deepEqual(parseHash("#/categories"), { name: "categories" });
    assert.deepEqual(parseHash("#/banned"), { name: "banned" });
  });

  it("builds canonical hrefs that parse back to the same route", () => {
    const routes = [
      { name: "reviews", ownership: "mine" },
      { name: "review", auditId: "1001" },
      { name: "cases", ownership: "completed_mine", kind: "report", keyword: "旧书" },
      { name: "cases", ownership: "unclaimed", kind: "all", keyword: "" },
      { name: "categories" },
      { name: "banned" },
    ] as const;
    for (const route of routes) {
      assert.deepEqual(parseHash(routeHref(route)), route);
    }
  });
});
