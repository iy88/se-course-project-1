import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";
import { listCaseQueue, liftCaseEnforcement, resolveCaseAppeal, upholdCaseAppeal } from "./cases";
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

describe("appeal resolution", () => {
  it("sends the selected original and concrete replacement only for adjust", async () => {
    let url = "";
    let body = "";
    let method = "";
    globalThis.fetch = (async (input, init) => {
      url = String(input);
      method = init?.method ?? "";
      body = String(init?.body ?? "");
      return new Response(JSON.stringify({ case_action_id: "1" }), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      });
    }) as typeof fetch;

    await resolveCaseAppeal(
      "41",
      {
        appeal_action_id: "102",
        related_account_id: "21",
        submitted_at: "2026-11-24T00:00:00Z",
        original_enforcements: [],
        thread: { conversation_kind: "case", conversation_id: "71" },
      },
      "adjust",
      "enf-1",
      [
        {
          action: "adjust_trade_status",
          target_type: "trade",
          target_id: "900",
          expected_result: "terminated",
        },
      ],
      "已调整",
      "evidence:7",
      "key-1",
    );

    assert.equal(url, "/api/v1/cases/41/messages");
    assert.equal(method, "POST");
    assert.deepEqual(JSON.parse(body), {
      thread: { conversation_kind: "case", conversation_id: "71" },
      message_kind: "manager_reply",
      appeal_action_id: "102",
      resolution: "adjust",
      original_enforcement_id: "enf-1",
      replacement_enforcements: [
        {
          action: "adjust_trade_status",
          target_type: "trade",
          target_id: "900",
          expected_result: "terminated",
        },
      ],
      body: "已调整",
      basis_ref: "evidence:7",
    });
  });

  it("preserves the existing uphold wrapper body", async () => {
    let body = "";
    globalThis.fetch = (async (_input, init) => {
      body = String(init?.body ?? "");
      return new Response(JSON.stringify({ case_action_id: "1" }), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      });
    }) as typeof fetch;

    await upholdCaseAppeal(
      "41",
      {
        appeal_action_id: "102",
        related_account_id: "21",
        submitted_at: "2026-11-24T00:00:00Z",
        thread: { conversation_kind: "case", conversation_id: "71" },
      },
      "维持",
      "evidence:7",
      "key-3",
    );

    assert.deepEqual(JSON.parse(body), {
      thread: { conversation_kind: "case", conversation_id: "71" },
      message_kind: "manager_reply",
      appeal_action_id: "102",
      resolution: "uphold",
      body: "维持",
      basis_ref: "evidence:7",
    });
  });

  it("omits selection fields for uphold", async () => {
    let body = "";
    globalThis.fetch = (async (_input, init) => {
      body = String(init?.body ?? "");
      return new Response(JSON.stringify({ case_action_id: "1" }), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      });
    }) as typeof fetch;

    await resolveCaseAppeal(
      "41",
      {
        appeal_action_id: "102",
        related_account_id: "21",
        submitted_at: "2026-11-24T00:00:00Z",
        thread: { conversation_kind: "case", conversation_id: "71" },
      },
      "uphold",
      null,
      [],
      "维持",
      "evidence:7",
      "key-2",
    );

    const payload = JSON.parse(body);
    assert.equal(payload.resolution, "uphold");
    assert.equal("original_enforcement_id" in payload, false);
    assert.equal("replacement_enforcements" in payload, false);
  });
});
