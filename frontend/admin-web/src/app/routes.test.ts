import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { parseLocation, routeHref } from "./routes";

describe("admin routes", () => {
  it("falls back to the workbench", () => {
    assert.deepEqual(parseLocation(""), {
      name: "cases",
      ownership: "unclaimed",
      kind: "all",
      keyword: "",
    });
    assert.deepEqual(parseLocation("/"), {
      name: "cases",
      ownership: "unclaimed",
      kind: "all",
      keyword: "",
    });
  });

  it("maps legacy review lists to the filtered workbench", () => {
    assert.deepEqual(parseLocation("/reviews?ownership=mine"), {
      name: "cases",
      ownership: "mine",
      kind: "product_review",
      keyword: "",
    });
    assert.deepEqual(parseLocation("/reviews?ownership=unclaimed"), {
      name: "cases",
      ownership: "unclaimed",
      kind: "product_review",
      keyword: "",
    });
  });

  it("reads and decodes a review audit id", () => {
    assert.deepEqual(parseLocation("/reviews/1001"), { name: "review", auditId: "1001" });
    assert.deepEqual(parseLocation("/reviews/a%20b"), { name: "review", auditId: "a b" });
  });

  it("reads the workbench scope, type and keyword", () => {
    assert.deepEqual(parseLocation("/cases"), {
      name: "cases",
      ownership: "unclaimed",
      kind: "all",
      keyword: "",
    });
    assert.deepEqual(
      parseLocation("/cases?ownership=completed_all&kind=report&keyword=%E6%97%A7%E4%B9%A6"),
      {
        name: "cases",
        ownership: "completed_all",
        kind: "report",
        keyword: "旧书",
      },
    );
    assert.deepEqual(parseLocation("/cases?ownership=bogus&kind=bogus"), {
      name: "cases",
      ownership: "unclaimed",
      kind: "all",
      keyword: "",
    });
  });

  it("recognises the maintenance pages", () => {
    assert.deepEqual(parseLocation("/categories"), { name: "categories" });
    assert.deepEqual(parseLocation("/banned"), { name: "banned" });
  });

  it("builds canonical hrefs that parse back to the same route", () => {
    const routes = [
      { name: "cases", ownership: "mine", kind: "product_review", keyword: "" },
      { name: "review", auditId: "1001" },
      { name: "cases", ownership: "completed_mine", kind: "report", keyword: "旧书" },
      { name: "cases", ownership: "unclaimed", kind: "all", keyword: "" },
      { name: "case", caseId: "422", ownership: "completed_mine", kind: "report", keyword: "旧书" },
      { name: "categories" },
      { name: "banned" },
      { name: "notifications" },
      { name: "notifications", notificationId: "12" },
      {
        name: "case",
        caseId: "422",
        ownership: "mine",
        kind: "all",
        keyword: "",
        anchor: "case-action-7",
      },
    ] as const;
    for (const route of routes) {
      assert.deepEqual(parseLocation(routeHref(route)), route);
    }
  });
});
