import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";
import { listCaseQueue } from "./cases";

const originalFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = originalFetch;
});

describe("case workbench query", () => {
  it("sends the scope, type, trimmed keyword and paging to the shared todo query", async () => {
    let url = "";
    globalThis.fetch = (async (input) => {
      url = String(input);
      return new Response(
        JSON.stringify({
          items: [],
          page: 2,
          page_size: 20,
          total: 0,
          counts_by_kind: {},
          as_of: "",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }) as typeof fetch;

    await listCaseQueue({
      ownership: "completed_all",
      kind: "all",
      keyword: "  旧书  ",
      page: 2,
      page_size: 20,
    });

    assert.equal(
      url,
      "/api/v1/management/todos?ownership=completed_all&kind=all&keyword=%E6%97%A7%E4%B9%A6&page=2&page_size=20",
    );
  });

  it("omits an empty keyword", async () => {
    let url = "";
    globalThis.fetch = (async (input) => {
      url = String(input);
      return new Response(
        JSON.stringify({
          items: [],
          page: 1,
          page_size: 20,
          total: 0,
          counts_by_kind: {},
          as_of: "",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }) as typeof fetch;

    await listCaseQueue({
      ownership: "unclaimed",
      kind: "report",
      keyword: "   ",
      page: 1,
      page_size: 20,
    });

    assert.equal(
      url,
      "/api/v1/management/todos?ownership=unclaimed&kind=report&page=1&page_size=20",
    );
  });
});
