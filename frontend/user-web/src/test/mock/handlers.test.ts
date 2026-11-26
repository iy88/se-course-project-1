/*
 * Behaviour tests for the simulated data source.
 *
 * They exercise the same request/response contract the screens use, so a broken
 * state transition, error code or permission check fails here before it reaches
 * the interface. Each test drives the fixture through `handleMockRequest`, which
 * is exactly the seam the HTTP layer switches on.
 */
import assert from "node:assert/strict";
import { beforeEach, describe, it } from "node:test";
import { handleMockRequest, resetMockState } from "./handlers";
import { ApiError } from "../../api/errors";
import type { HttpMethod } from "../../api/http";

async function call<T>(
  method: HttpMethod,
  path: string,
  options: { query?: Record<string, unknown>; body?: unknown; idempotencyKey?: string } = {},
): Promise<T> {
  return (await handleMockRequest(method, path, options)) as T;
}

async function loginAs(email: string): Promise<void> {
  await call("POST", "/account/session", {
    body: { email, password: "Campus#2026" },
    idempotencyKey: `login-${email}`,
  });
}

async function expectFailure(
  method: HttpMethod,
  path: string,
  options: { body?: unknown; idempotencyKey?: string } = {},
  code: string,
): Promise<void> {
  await assert.rejects(
    () => handleMockRequest(method, path, options),
    (error: unknown) => {
      assert.ok(error instanceof ApiError, `expected ApiError, got ${String(error)}`);
      assert.equal(error.code, code);
      return true;
    },
  );
}

interface Identity {
  account: { account_id: string; display_name: string; roles: string[]; avatar_url: string | null };
}

interface TradeViewShape {
  id: string;
  status: string;
  phase: string | null;
  version: number;
  permissions: { allowed_actions: string[] };
  confirmations: { current: unknown[]; both_current: boolean };
  product: { id: string; title?: string };
}

describe("account and entry", () => {
  beforeEach(() => {
    resetMockState();
  });

  it("returns the seeded identity for the signed-in account", async () => {
    const identity = await call<Identity>("GET", "/account/session");
    assert.equal(identity.account.account_id, "1");
    assert.equal(identity.account.display_name, "林同学");
    assert.deepEqual(identity.account.roles, ["user"]);
    assert.equal(identity.account.avatar_url, null);
  });

  it("rejects a wrong password without revealing which field failed", async () => {
    await expectFailure(
      "POST",
      "/account/session",
      { body: { email: "lin@campus.example.edu", password: "wrong" } },
      "CREDENTIALS_INVALID",
    );
  });

  it("answers 401 on a protected read once signed out", async () => {
    await call("DELETE", "/account/session");
    await expectFailure("GET", "/account/session", {}, "AUTHENTICATION_REQUIRED");
  });

  it("refuses a duplicate registration email", async () => {
    await expectFailure(
      "POST",
      "/accounts",
      {
        body: {
          email: "lin@campus.example.edu",
          display_name: "另一个林",
          password: "Campus#2026",
          verification_id: "V-1",
          code: "123456",
        },
      },
      "EMAIL_IN_USE",
    );
  });

  it("changes the display name and re-reads it", async () => {
    const updated = await call<{ display_name: string }>("PATCH", "/account/profile", {
      body: { display_name: "林同学（已改）" },
      idempotencyKey: "profile-1",
    });
    assert.equal(updated.display_name, "林同学（已改）");
    const identity = await call<Identity>("GET", "/account/session");
    assert.equal(identity.account.display_name, "林同学（已改）");
  });

  it("rejects a password change with the wrong current password", async () => {
    await expectFailure(
      "PUT",
      "/account/password",
      { body: { current_password: "nope", new_password: "Another#2026" } },
      "CURRENT_PASSWORD_INVALID",
    );
  });
});

describe("catalogue", () => {
  beforeEach(() => {
    resetMockState();
  });

  it("lists categories with their selectability and filter entry", async () => {
    const result = await call<{ items: { main_name: string; selectable: boolean }[] }>(
      "GET",
      "/categories",
    );
    assert.ok(result.items.length >= 5);
    const disabled = result.items.find((item) => item.main_name === "乐器");
    assert.ok(disabled);
    assert.equal(disabled.selectable, false);
  });

  it("returns the banned scope grouped by category", async () => {
    const scope = await call<{ groups: { group: string; items: unknown[] }[] }>(
      "GET",
      "/banned-items",
    );
    const total = scope.groups.reduce((sum, group) => sum + group.items.length, 0);
    assert.ok(total >= 6);
  });

  it("only returns publicly listed products in search", async () => {
    const page = await call<{ items: { id: string; title: string }[]; total: number }>(
      "GET",
      "/products",
    );
    const ids = page.items.map((item) => item.id);
    assert.ok(ids.includes("1"));
    assert.ok(!ids.includes("3"), "a product awaiting review must not be listed");
    assert.ok(!ids.includes("5"), "an off-shelf product must not be listed");
  });

  it("matches keyword, category and price filters together", async () => {
    const page = await call<{ items: { id: string }[] }>("GET", "/products", {
      query: { keyword: "高数", category_ids: ["1"], max_price_cents: 5000 },
    });
    assert.equal(
      page.items.some((item) => item.id === "1"),
      false,
      "the seeded title contains 高等数学, not 高数",
    );
    const byKeyword = await call<{ items: { id: string }[] }>("GET", "/products", {
      query: { keyword: "高等数学" },
    });
    assert.ok(byKeyword.items.some((item) => item.id === "1"));
    const tooExpensive = await call<{ items: { id: string }[] }>("GET", "/products", {
      query: { keyword: "高等数学", max_price_cents: 1000 },
    });
    assert.equal(tooExpensive.items.length, 0);
  });

  it("hides a pending product from other accounts", async () => {
    await loginAs("zhao@campus.example.edu");
    await expectFailure("GET", "/products/3", {}, "RESOURCE_NOT_VISIBLE");
  });
});

describe("publishing and review state", () => {
  beforeEach(() => {
    resetMockState();
  });

  it("creates a product in pending_review with a review case", async () => {
    const created = await call<{
      id: string;
      lifecycle_state: string;
      content_version: number;
      pending_review: { audit_id: string; case_id: string } | null;
    }>("POST", "/products", {
      body: {
        title: "台灯",
        description: "宿舍台灯，九成新",
        price_cents: 2500,
        category_ids: ["3"],
        image_file_ids: [],
      },
      idempotencyKey: "create-1",
    });
    assert.equal(created.lifecycle_state, "pending_review");
    assert.ok(created.pending_review);
    assert.ok(created.pending_review.audit_id.startsWith("A-"));
  });

  it("requires a category or a category application", async () => {
    await expectFailure(
      "POST",
      "/products",
      {
        body: { title: "无分类", description: "说明", price_cents: 100, category_ids: [] },
        idempotencyKey: "create-2",
      },
      "CATEGORY_REQUIRED",
    );
  });

  it("rejects a stale expected_version when editing", async () => {
    await expectFailure(
      "PATCH",
      "/products/1",
      { body: { title: "新标题", expected_version: 1 }, idempotencyKey: "edit-1" },
      "VERSION_CONFLICT",
    );
  });

  it("blocks editing key content while the product is in trade", async () => {
    await expectFailure(
      "PATCH",
      "/products/2",
      { body: { title: "新标题", expected_version: 1 }, idempotencyKey: "edit-2" },
      "EDIT_NOT_ALLOWED_IN_TRADE",
    );
  });

  it("refuses withdrawal once the review has been claimed", async () => {
    await expectFailure(
      "POST",
      "/products/3/withdrawal",
      { body: { expected_version: 1 }, idempotencyKey: "withdraw-1" },
      "REVIEW_ALREADY_CLAIMED",
    );
  });

  it("refuses to re-list a product whose latest review failed", async () => {
    await expectFailure(
      "POST",
      "/products/8/on-shelf",
      { body: { expected_version: 2 }, idempotencyKey: "onshelf-1" },
      "PRODUCT_NOT_RELISTABLE",
    );
  });

  it("refuses to re-list a product that is not off shelf", async () => {
    await expectFailure(
      "POST",
      "/products/4/on-shelf",
      { body: { expected_version: 3 }, idempotencyKey: "onshelf-2" },
      "STATE_CONFLICT",
    );
  });

  it("refuses to take down a product that is not publicly listed", async () => {
    await expectFailure(
      "POST",
      "/products/2/off-shelf",
      { body: { expected_version: 1 }, idempotencyKey: "offshelf-1" },
      "STATE_CONFLICT",
    );
  });

  it("replays the first result for a repeated idempotency key", async () => {
    const body = {
      title: "重复提交",
      description: "同一键重放",
      price_cents: 500,
      category_ids: ["1"],
      image_file_ids: [],
    };
    const first = await call<{ id: string }>("POST", "/products", {
      body,
      idempotencyKey: "same-key",
    });
    const second = await call<{ id: string }>("POST", "/products", {
      body,
      idempotencyKey: "same-key",
    });
    assert.equal(first.id, second.id);
  });
});

describe("trade lifecycle", () => {
  beforeEach(() => {
    resetMockState();
  });

  it("rejects a purchase request on an unavailable product", async () => {
    await loginAs("zhao@campus.example.edu");
    await expectFailure(
      "POST",
      "/products/3/purchase-requests",
      { body: { expected_product_version: 1 }, idempotencyKey: "req-0" },
      "PRODUCT_NOT_AVAILABLE",
    );
  });

  it("rejects buying your own product", async () => {
    await expectFailure(
      "POST",
      "/products/1/purchase-requests",
      { body: { expected_product_version: 2 }, idempotencyKey: "req-self" },
      "INPUT_INVALID",
    );
  });

  it("hides a trade from an unrelated account", async () => {
    await loginAs("qian@campus.example.edu");
    await expectFailure("GET", "/trades/1", {}, "RESOURCE_NOT_VISIBLE");
  });

  it("runs the full flow from request to completion", async () => {
    // Buyer creates the request.
    await loginAs("zhao@campus.example.edu");
    const created = await call<TradeViewShape>("POST", "/products/1/purchase-requests", {
      body: { note: "今晚可以自取", expected_product_version: 2 },
      idempotencyKey: "req-1",
    });
    assert.equal(created.status, "pending_acceptance");
    assert.ok(created.permissions.allowed_actions.includes("withdraw"));
    assert.ok(!created.permissions.allowed_actions.includes("accept"));

    // Seller accepts and the product becomes unavailable for other requests.
    await loginAs("lin@campus.example.edu");
    const accepted = await call<TradeViewShape>("POST", `/trades/${created.id}/accept`, {
      body: { expected_version: created.version },
      idempotencyKey: "accept-1",
    });
    assert.equal(accepted.status, "in_progress");
    assert.equal(accepted.phase, "first_agreement_pending");
    assert.ok(accepted.permissions.allowed_actions.includes("propose_agreement"));

    // Seller proposes the terms.
    const proposal = await call<{ agreement: { id: string }; trade: TradeViewShape }>(
      "POST",
      `/trades/${created.id}/agreements`,
      {
        body: {
          delivery_at: "2026-11-22T10:00:00Z",
          delivery_place_text: "三号宿舍楼下",
          delivery_method: "自提",
          amount_cents: 4500,
          payment_method: "当面支付",
          payment_timing: "交付时",
          base_agreement_id: null,
          expected_version: accepted.version,
        },
        idempotencyKey: "agreement-1",
      },
    );
    assert.equal(proposal.trade.permissions.allowed_actions.includes("decide_agreement"), true);

    // Buyer accepts the terms, which starts the completion stage.
    await loginAs("zhao@campus.example.edu");
    const agreed = await call<{ agreement: { status: string }; trade: TradeViewShape }>(
      "POST",
      `/trades/${created.id}/agreements/${proposal.agreement.id}/decisions`,
      {
        body: { decision: "accept", expected_version: proposal.trade.version },
        idempotencyKey: "agreement-decide-1",
      },
    );
    assert.equal(agreed.agreement.status, "effective");
    assert.equal(agreed.trade.phase, "awaiting_completion");
    assert.equal(agreed.trade.status, "in_progress");

    // Buyer confirms; the trade is not complete until both sides confirm.
    const firstConfirm = await call<{ trade: TradeViewShape }>(
      "POST",
      `/trades/${created.id}/completion-confirmations`,
      { body: { expected_version: agreed.trade.version }, idempotencyKey: "completion-1" },
    );
    assert.equal(firstConfirm.trade.status, "in_progress");
    assert.equal(firstConfirm.trade.confirmations.current.length, 1);
    assert.equal(firstConfirm.trade.confirmations.both_current, false);

    // Seller confirms; the trade completes and the product leaves the shelf.
    await loginAs("lin@campus.example.edu");
    const done = await call<{ trade: TradeViewShape }>(
      "POST",
      `/trades/${created.id}/completion-confirmations`,
      { body: { expected_version: firstConfirm.trade.version }, idempotencyKey: "completion-2" },
    );
    assert.equal(done.trade.status, "completed");
    assert.equal(done.trade.confirmations.both_current, true);
    const product = await call<{ lifecycle_state: string }>("GET", "/products/1");
    assert.equal(product.lifecycle_state, "off_shelf");

    // The per-trade conversation is archived once the trade reaches a final state.
    const archivedTrade = await call<{
      trade_conversation_id: string | null;
    }>("GET", `/trades/${created.id}`);
    assert.ok(archivedTrade.trade_conversation_id);
    await expectFailure(
      "POST",
      `/conversations/trade/${archivedTrade.trade_conversation_id}/messages`,
      { body: { body: "还在吗" }, idempotencyKey: "msg-after-complete" },
      "BRANCH_ARCHIVED",
    );
  });

  it("closes the other pending requests when one is accepted", async () => {
    await loginAs("zhao@campus.example.edu");
    const first = await call<TradeViewShape>("POST", "/products/1/purchase-requests", {
      body: { expected_product_version: 2 },
      idempotencyKey: "req-a",
    });
    // A second buyer requests the same product.
    await loginAs("qian@campus.example.edu");
    const second = await call<TradeViewShape>("POST", "/products/1/purchase-requests", {
      body: { expected_product_version: 2 },
      idempotencyKey: "req-b",
    });
    // The seller accepts the second request.
    await loginAs("lin@campus.example.edu");
    await call("POST", `/trades/${second.id}/accept`, {
      body: { expected_version: second.version },
      idempotencyKey: "accept-b",
    });
    await loginAs("zhao@campus.example.edu");
    const closed = await call<TradeViewShape>("GET", `/trades/${first.id}`);
    assert.equal(closed.status, "closed");
    assert.ok(!closed.permissions.allowed_actions.includes("withdraw"));
  });

  it("records a direct cancellation made before the agreement takes effect", async () => {
    await loginAs("qian@campus.example.edu");
    const trade = await call<TradeViewShape>("GET", "/trades/2");
    assert.equal(trade.status, "in_progress");
    assert.ok(trade.permissions.allowed_actions.includes("propose_cancellation"));
    const cancelled = await call<{ trade: TradeViewShape }>(
      "POST",
      `/trades/2/cancellation-proposals`,
      {
        body: { reason: "临时不需要了", expected_version: trade.version },
        idempotencyKey: "cancel-1",
      },
    );
    assert.equal(cancelled.trade.status, "terminated");
  });

  it("refuses an agreement decision from the proposing side", async () => {
    const trade = await call<TradeViewShape>("GET", "/trades/2");
    const current = trade.version;
    await expectFailure(
      "POST",
      "/trades/2/agreements/2/decisions",
      { body: { decision: "accept", expected_version: current }, idempotencyKey: "self-accept" },
      "ACTION_NOT_ALLOWED",
    );
  });
});

describe("trade reviews", () => {
  beforeEach(() => {
    resetMockState();
  });

  it("projects the viewer's received review and eligibility from the server", async () => {
    const reviews = await call<{
      can_review: boolean;
      written: { review_id: string } | null;
      received: { rating: number; content: string | null } | null;
    }>("GET", "/trades/3/reviews");
    assert.equal(reviews.can_review, true);
    assert.equal(reviews.written, null);
    assert.equal(reviews.received?.rating, 5);
    assert.ok(reviews.received?.content);
  });

  it("turns off further reviews after the second side submits", async () => {
    const submitted = await call<{ review: { review_id: string } }>("POST", "/trades/3/reviews", {
      body: { rating: 4, content: " 包装仔细，交易顺利。 " },
      idempotencyKey: "review-1",
    });
    assert.ok(submitted.review.review_id);
    const reviews = await call<{
      can_review: boolean;
      written: { review_id: string; content: string | null } | null;
      received: { review_id: string } | null;
    }>("GET", "/trades/3/reviews");
    assert.equal(reviews.can_review, false);
    assert.equal(reviews.written?.review_id, submitted.review.review_id);
    assert.equal(reviews.written?.content, "包装仔细，交易顺利。");
    assert.ok(reviews.received);
  });

  it("does not expose the review projection to an account outside the trade", async () => {
    await loginAs("qian@campus.example.edu");
    await expectFailure("GET", "/trades/3/reviews", {}, "RESOURCE_NOT_VISIBLE");
  });
});

describe("conversations and notifications", () => {
  beforeEach(() => {
    resetMockState();
  });

  it("returns unread counts per branch without advancing them", async () => {
    const before = await call<{ items: { branches: { unread_count: number }[] }[] }>(
      "GET",
      "/conversations",
    );
    const total = before.items.reduce(
      (sum, entry) =>
        sum + entry.branches.reduce((inner, branch) => inner + branch.unread_count, 0),
      0,
    );
    assert.ok(total > 0);
    const again = await call<{ items: { branches: { unread_count: number }[] }[] }>(
      "GET",
      "/conversations",
    );
    assert.equal(
      again.items.reduce(
        (sum, entry) =>
          sum + entry.branches.reduce((inner, branch) => inner + branch.unread_count, 0),
        0,
      ),
      total,
      "listing conversations must not mark them read",
    );
  });

  it("advances read progress monotonically", async () => {
    const advanced = await call<{ last_read_seq: number; unread_count: number }>(
      "POST",
      "/conversations/chat/1/read-progress",
      { body: { displayed_seq: 3 }, idempotencyKey: "read-1" },
    );
    assert.equal(advanced.last_read_seq, 3);
    const backwards = await call<{ last_read_seq: number }>(
      "POST",
      "/conversations/chat/1/read-progress",
      { body: { displayed_seq: 1 }, idempotencyKey: "read-2" },
    );
    assert.equal(backwards.last_read_seq, 3, "read progress must not move backwards");
  });

  it("refuses read progress beyond the branch head", async () => {
    await expectFailure(
      "POST",
      "/conversations/chat/1/read-progress",
      { body: { displayed_seq: 99 }, idempotencyKey: "read-3" },
      "INPUT_INVALID",
    );
  });

  it("keeps a conversation invisible to an account outside it", async () => {
    await loginAs("qian@campus.example.edu");
    await expectFailure(
      "POST",
      "/conversations/trade/1/messages",
      { body: { body: "还在吗" }, idempotencyKey: "msg-1" },
      "PARTICIPANT_REQUIRED",
    );
  });

  it("marks a notification read once and keeps the first timestamp", async () => {
    const first = await call<{ notification_id: string; read_at: string }>(
      "PUT",
      "/account/notifications/2/read",
      { idempotencyKey: "read-notify-1" },
    );
    assert.ok(first.read_at);
    const second = await call<{ read_at: string }>("PUT", "/account/notifications/2/read", {
      idempotencyKey: "read-notify-2",
    });
    assert.equal(second.read_at, first.read_at);
  });

  it("keeps another account's notification invisible", async () => {
    await loginAs("zhao@campus.example.edu");
    await expectFailure("GET", "/account/notifications/1", {}, "RESOURCE_NOT_VISIBLE");
  });

  it("reports the unread total separately from the filtered page", async () => {
    const unread = await call<{ unread_count: number; total: number }>(
      "GET",
      "/account/notifications",
      { query: { read: "unread" } },
    );
    const all = await call<{ unread_count: number; total: number }>(
      "GET",
      "/account/notifications",
      { query: { read: "all" } },
    );
    assert.equal(unread.unread_count, all.unread_count);
    assert.ok(unread.total <= all.total);
  });
});

describe("cases", () => {
  beforeEach(() => {
    resetMockState();
  });

  it("creates a report and lists it under the mine scope", async () => {
    const created = await call<{ case_id: string; reused: boolean }>("POST", "/cases", {
      body: {
        target: { target_type: "product", target_id: "7" },
        reason: "疑似代写服务推广",
        note: "描述中出现代写联系方式",
      },
      idempotencyKey: "report-1",
    });
    assert.equal(created.reused, false);
    const mine = await call<{ items: { case_id: string; scope: string }[] }>("GET", "/cases", {
      query: { scope: "mine" },
    });
    assert.ok(mine.items.some((item) => item.case_id === created.case_id));
  });

  it("reuses an open report for the same target", async () => {
    const body = {
      target: { target_type: "product", target_id: "7" },
      reason: "重复举报",
    };
    const first = await call<{ case_id: string }>("POST", "/cases", {
      body,
      idempotencyKey: "report-2a",
    });
    const second = await call<{ case_id: string; reused: boolean }>("POST", "/cases", {
      body,
      idempotencyKey: "report-2b",
    });
    assert.equal(second.reused, true);
    assert.equal(second.case_id, first.case_id);
  });

  it("hides a case from an account outside it", async () => {
    await loginAs("qian@campus.example.edu");
    await expectFailure("GET", "/cases/5", {}, "RESOURCE_NOT_VISIBLE");
  });

  it("keeps the reporter's view free of the appeal deadline", async () => {
    const detail = await call<{ appeal_deadline_at: string | null }>("GET", "/cases/5");
    assert.equal(detail.appeal_deadline_at, null);
  });

  it("refuses a supplement after the case is closed", async () => {
    await expectFailure(
      "POST",
      "/cases/7/supplements",
      { body: { note: "补充" }, idempotencyKey: "supplement-closed" },
      "NOT_CASE_PARTICIPANT",
    );
  });

  it("accepts an inquiry reply on the case thread", async () => {
    const posted = await call<{ case_message_id: string; seq: number }>(
      "POST",
      "/cases/6/messages",
      {
        body: {
          thread: { conversation_kind: "case", conversation_id: "1" },
          message_kind: "statement",
          body: "该台灯为本人自用，三档亮度。",
        },
        idempotencyKey: "case-reply-1",
      },
    );
    assert.ok(posted.seq > 0);
    const detail = await call<{ actions: { action_kind: string }[] }>("GET", "/cases/6");
    assert.ok(detail.actions.some((action) => action.action_kind === "statement"));
  });
});

describe("aggregation", () => {
  beforeEach(() => {
    resetMockState();
  });

  it("counts owned products and trades for the signed-in account", async () => {
    const overview = await call<{
      products: { total: number };
      trades: { total: number; selling: number };
      reports: { submitted: number };
    }>("GET", "/account/overview");
    assert.equal(overview.products.total, 6);
    assert.equal(overview.trades.selling, overview.trades.total);
    assert.ok(overview.reports.submitted >= 1);
  });

  it("returns to-do entries that point at the owning source", async () => {
    await loginAs("qian@campus.example.edu");
    const todos = await call<{ items: { kind: string; source: Record<string, unknown> }[] }>(
      "GET",
      "/account/todos",
    );
    const agreementTodo = todos.items.find((item) => item.kind === "agreement_response");
    assert.ok(agreementTodo, "a pending agreement addressed to this account must be listed");
    assert.equal(agreementTodo.source.trade_id, "2");
  });

  it("projects the owned product list with lifecycle states", async () => {
    const page = await call<{ items: { product_id: string; lifecycle_state: string }[] }>(
      "GET",
      "/account/resources",
      { query: { kind: "product" } },
    );
    assert.ok(page.items.length >= 5);
    assert.ok(page.items.some((item) => item.lifecycle_state === "pending_review"));
  });

  it("filters the owned trade list by role", async () => {
    const buying = await call<{ items: unknown[] }>("GET", "/account/resources", {
      query: { kind: "trade", role: "buying" },
    });
    assert.equal(buying.items.length, 0, "the seeded seller has no purchases");
  });
});

describe("file uploads", () => {
  beforeEach(() => {
    resetMockState();
  });

  it("authorises, verifies and references an avatar through the profile endpoint", async () => {
    const created = await call<{ file_id: string; state: string }>("POST", "/files/uploads", {
      body: {
        purpose: "account_avatar",
        declared_size: 1024,
        declared_content_type: "image/png",
        target: null,
      },
      idempotencyKey: "upload-1",
    });
    assert.equal(created.state, "uploading");
    const verified = await call<{ state: string }>("POST", `/files/${created.file_id}/completion`, {
      body: {},
      idempotencyKey: "complete-1",
    });
    assert.equal(verified.state, "verified");
    const profile = await call<{ display_name: string; avatar_url: string | null }>(
      "PATCH",
      "/account/profile",
      { body: { avatar_file_id: created.file_id }, idempotencyKey: "avatar-1" },
    );
    assert.ok(profile.avatar_url);
    assert.equal(profile.display_name, "林同学", "an omitted name keeps its value");
    const identity = await call<Identity>("GET", "/account/session");
    assert.equal(identity.account.avatar_url, profile.avatar_url);

    // An explicit null is indistinguishable from an omitted field, so it keeps the
    // avatar; the "0" sentinel is the removal signal the deployed endpoint uses.
    const kept = await call<{ display_name: string; avatar_url: string | null }>(
      "PATCH",
      "/account/profile",
      { body: { avatar_file_id: null }, idempotencyKey: "avatar-2" },
    );
    assert.equal(kept.avatar_url, profile.avatar_url);

    // Removing the avatar reports the default state and keeps the name.
    const removed = await call<{ display_name: string; avatar_url: string | null }>(
      "PATCH",
      "/account/profile",
      { body: { avatar_file_id: "0" }, idempotencyKey: "avatar-3" },
    );
    assert.equal(removed.avatar_url, null);
    assert.equal(removed.display_name, "林同学");
  });

  it("refuses a file whose purpose is not the avatar purpose", async () => {
    await expectFailure(
      "PATCH",
      "/account/profile",
      { body: { avatar_file_id: "11" }, idempotencyKey: "avatar-3" },
      "FILE_PURPOSE_MISMATCH",
    );
  });

  it("refuses an avatar file owned by another account", async () => {
    await expectFailure(
      "PATCH",
      "/account/profile",
      { body: { avatar_file_id: "14" }, idempotencyKey: "avatar-4" },
      "RESOURCE_NOT_VISIBLE",
    );
  });

  it("refuses a profile update that changes nothing", async () => {
    await expectFailure(
      "PATCH",
      "/account/profile",
      { body: {}, idempotencyKey: "avatar-5" },
      "INPUT_INVALID",
    );
  });
});

interface CommentShape {
  id: string;
  status: string;
  body: string;
  reply_to_comment_id: string | null;
  author: { id: string; display_name: string };
  replies: CommentShape[];
}

interface CommentPageShape {
  items: CommentShape[];
  page: number;
  page_size: number;
  total: number;
}

interface FavoritePageShape {
  items: {
    product_id: string;
    status: string;
    favorited_at: string;
    product: { id: string; title: string } | null;
    message: string | null;
  }[];
  total: number;
}

interface FavoriteStatusShape {
  favorited: boolean;
  valid: boolean;
  favorited_at: string | null;
}

describe("product interaction", () => {
  beforeEach(() => {
    resetMockState();
  });

  it("lists published comments with the seller reply inside the thread", async () => {
    await loginAs("zhao@campus.example.edu");

    const page = await call<CommentPageShape>("GET", "/products/1/comments", {
      query: { page: 1, page_size: 20 },
    });

    assert.equal(page.total, 2);
    assert.equal(page.items[0].id, "3");
    const thread = page.items.find((item) => item.id === "1");
    assert.ok(thread);
    assert.equal(thread.replies.length, 1);
    assert.equal(thread.replies[0].author.display_name, "林同学");
    assert.equal(thread.replies[0].reply_to_comment_id, "1");
  });

  it("publishes a comment and hides comments of an off-shelf product", async () => {
    await loginAs("zhao@campus.example.edu");

    const created = await call<CommentShape>("POST", "/products/1/comments", {
      body: { body: "  周末可以自取  " },
      idempotencyKey: "comment-create-1",
    });
    assert.equal(created.status, "published");
    assert.equal(created.body, "周末可以自取");

    await expectFailure(
      "POST",
      "/products/8/comments",
      { body: { body: "还在吗" }, idempotencyKey: "comment-create-2" },
      "RESOURCE_NOT_VISIBLE",
    );
    await expectFailure("GET", "/products/8/comments", {}, "RESOURCE_NOT_VISIBLE");
  });

  it("scopes hidden-product comments to the reader's own thread", async () => {
    await loginAs("zhao@campus.example.edu");
    await expectFailure("GET", "/products/8/comments", {}, "RESOURCE_NOT_VISIBLE");

    await loginAs("qian@campus.example.edu");
    const page = await call<CommentPageShape>("GET", "/products/8/comments", {});
    assert.equal(page.total, 1);
    assert.equal(page.items[0].id, "4");
  });

  it("allows the seller to reply once to a top-level comment", async () => {
    await loginAs("lin@campus.example.edu");

    const reply = await call<CommentShape>("POST", "/products/1/comments/1/replies", {
      body: { body: "还在的" },
      idempotencyKey: "comment-reply-1",
    });
    assert.equal(reply.reply_to_comment_id, "1");

    await expectFailure(
      "POST",
      `/products/1/comments/${reply.id}/replies`,
      { body: { body: "再回复一层" }, idempotencyKey: "comment-reply-2" },
      "STATE_CONFLICT",
    );

    await loginAs("zhao@campus.example.edu");
    await expectFailure(
      "POST",
      "/products/1/comments/1/replies",
      { body: { body: "非卖方回复" }, idempotencyKey: "comment-reply-3" },
      "COMMENT_REPLY_NOT_ALLOWED",
    );
  });

  it("removes the author's comment from the public list", async () => {
    await loginAs("zhao@campus.example.edu");

    await call("DELETE", "/products/1/comments/1", { idempotencyKey: "comment-delete-1" });
    const page = await call<CommentPageShape>("GET", "/products/1/comments", {});
    assert.equal(page.total, 1);
    assert.equal(page.items[0].id, "3");

    await expectFailure(
      "DELETE",
      "/products/1/comments/3",
      { idempotencyKey: "comment-delete-2" },
      "ACTION_NOT_ALLOWED",
    );
  });

  it("keeps the first favourite time and marks hidden products invalid", async () => {
    await loginAs("lin@campus.example.edu");

    const before = await call<FavoritePageShape>("GET", "/me/favorites", {});
    assert.equal(before.total, 2);
    const valid = before.items.find((item) => item.product_id === "7");
    const invalid = before.items.find((item) => item.product_id === "8");
    assert.ok(valid && invalid);
    assert.equal(valid.status, "valid");
    assert.ok(valid.product);
    assert.equal(invalid.status, "invalid");
    assert.equal(invalid.product, null);
    assert.equal(invalid.message, "该商品已失效");

    const added = await call<FavoriteStatusShape>("PUT", "/me/favorites/7", {
      idempotencyKey: "favorite-add-1",
    });
    assert.equal(added.favorited, true);
    assert.equal(added.favorited_at, valid.favorited_at);

    await expectFailure(
      "PUT",
      "/me/favorites/8",
      { idempotencyKey: "favorite-add-2" },
      "RESOURCE_NOT_VISIBLE",
    );
    await call("DELETE", "/me/favorites/8", { idempotencyKey: "favorite-remove-1" });
    const after = await call<FavoritePageShape>("GET", "/me/favorites", {});
    assert.equal(after.total, 1);
  });

  it("answers favourite status only for visible or already favourited products", async () => {
    await loginAs("lin@campus.example.edu");

    const status = await call<FavoriteStatusShape>("GET", "/me/favorites/7");
    assert.equal(status.favorited, true);
    assert.equal(status.valid, true);

    await loginAs("qian@campus.example.edu");
    await expectFailure("GET", "/me/favorites/8", {}, "RESOURCE_NOT_VISIBLE");
    const unfavorited = await call<FavoriteStatusShape>("GET", "/me/favorites/7");
    assert.equal(unfavorited.favorited, false);
    assert.equal(unfavorited.valid, true);
  });
});
