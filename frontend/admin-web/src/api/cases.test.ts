import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";
import { listCaseQueue, liftCaseEnforcement } from "./cases";
import { ApiError } from "./errors";

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

describe("case enforcement lift", () => {
  it("posts the required reason to encoded case and enforcement ids", async () => {
    let url = "";
    let init: RequestInit | undefined;
    globalThis.fetch = (async (input, requestInit) => {
      url = String(input);
      init = requestInit;
      return new Response(
        JSON.stringify({
          enforcement_id: "enf 7",
          lifted_at: "2026-11-20T08:00:00Z",
          lifted_by: "31",
          restored_scope: ["account:21"],
          remaining_restrictions: [],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }) as typeof fetch;

    const result = await liftCaseEnforcement("41/2", "enf 7", "解除限制", "lift-key-1");

    assert.equal(url, "/api/v1/admin/cases/41%2F2/enforcements/enf%207/lift");
    assert.equal(init?.method, "POST");
    assert.equal(new Headers(init?.headers).get("Idempotency-Key"), "lift-key-1");
    assert.deepEqual(JSON.parse(String(init?.body)), { reason: "解除限制" });
    assert.deepEqual(result.restored_scope, ["account:21"]);
  });

  it("keeps the documented lift error code for the view to map", async () => {
    globalThis.fetch = (async () =>
      new Response(
        JSON.stringify({
          error: { code: "RESTRICTION_NOT_ACTIVE", message: "执行记录不在生效状态" },
        }),
        { status: 409, headers: { "Content-Type": "application/json" } },
      )) as typeof fetch;

    await assert.rejects(
      liftCaseEnforcement("41", "enf-1", "解除限制", "lift-key-2"),
      (error: unknown) =>
        error instanceof ApiError &&
        error.status === 409 &&
        error.code === "RESTRICTION_NOT_ACTIVE",
    );
  });
});
