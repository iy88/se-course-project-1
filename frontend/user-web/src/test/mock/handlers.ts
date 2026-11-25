/*
 * Simulated implementation of the `/api/v1` endpoints this work package
 * consumes. It exists so that the user interface can be developed and verified
 * end to end before the provider work packages publish their real endpoints,
 * exactly as the S2/S3/S4 task cards describe ("用 OpenAPI 模拟接口").
 *
 * Behaviour that matters to the UI is reproduced faithfully: write actions bump
 * versions, server-computed `permissions.allowed_actions` drives the buttons,
 * unknown or unauthorised objects answer 404, and idempotent replays return the
 * first result. Validation rules use the same error codes as the contracts.
 */
import { AbortedError, ApiError } from "../../api/errors";
import type {
  Agreement,
  CaseDetail,
  CaseMessage,
  CommentView,
  ConversationKind,
  CreateUploadResult,
  DecisionKind,
  FilePurpose,
  NotificationSummary,
  ProductDetail,
  ProductSummary,
  TradeReview,
} from "../../api/contracts";
import type { HttpMethod, RequestOptions } from "../../api/http";
import {
  accountRef,
  caseDetail,
  categoryRefs,
  categoryView,
  createSeedState,
  nextId,
  overview,
  signedImage,
  tradeView,
  unreadCount,
  type MockCase,
  type MockComment,
  type MockMessage,
  type MockProduct,
  type MockState,
  type MockTrade,
} from "./state";

let state: MockState = createSeedState();

/** Reset the simulated backend to its seed data (used by the settings drawer). */
export function resetMockState(): void {
  state = createSeedState();
}

export function mockCurrentAccountId(): string | null {
  return state.currentAccountId;
}

const PASSWORDS = new Map<string, string>();
for (const account of state.accounts) PASSWORDS.set(account.email, account.password);

type Handler = (context: RouteContext) => unknown;

interface RouteContext {
  method: HttpMethod;
  params: Record<string, string>;
  query: Record<string, unknown>;
  body: Record<string, unknown>;
  options: RequestOptions;
  accountId: string;
}

interface Route {
  method: HttpMethod;
  pattern: string[];
  handler: Handler;
  /** Routes that work without an authenticated session. */
  anonymous?: boolean;
}

/* ------------------------------------------------------------------ helpers */

function fail(status: number, code: string, message: string): never {
  throw new ApiError(status, code, message);
}

function nowIso(): string {
  return new Date().toISOString();
}

function requireString(body: Record<string, unknown>, key: string): string {
  const value = body[key];
  if (typeof value !== "string" || value.trim() === "") {
    fail(422, "INPUT_INVALID", `字段 ${key} 不能为空。`);
  }
  return value;
}

function optionalString(body: Record<string, unknown>, key: string): string | undefined {
  const value = body[key];
  return typeof value === "string" && value !== "" ? value : undefined;
}

function requireNumber(body: Record<string, unknown>, key: string): number {
  const value = body[key];
  if (typeof value !== "number" || !Number.isFinite(value)) {
    fail(422, "INPUT_INVALID", `字段 ${key} 必须是数字。`);
  }
  return value;
}

function expectVersion(body: Record<string, unknown>, current: number): void {
  const value = body.expected_version;
  if (typeof value === "number" && value !== current) {
    fail(409, "VERSION_CONFLICT", "内容已更新，请刷新后重试。");
  }
}

function asInt(value: unknown, fallback: number): number {
  const parsed = typeof value === "number" ? value : Number.parseInt(String(value ?? ""), 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function paginate<T>(
  items: T[],
  query: Record<string, unknown>,
): {
  items: T[];
  page: number;
  page_size: number;
  total: number;
} {
  const page = asInt(query.page, 1);
  const pageSize = Math.min(asInt(query.page_size, 20), 100);
  const start = (page - 1) * pageSize;
  return {
    items: items.slice(start, start + pageSize),
    page,
    page_size: pageSize,
    total: items.length,
  };
}

function currentAccountId(): string | null {
  return state.currentAccountId;
}

function accountById(accountId: string) {
  const account = state.accounts.find((item) => item.account_id === accountId);
  if (!account) fail(404, "RESOURCE_NOT_VISIBLE", "账户不存在或不可见。");
  return account;
}

function productById(productId: string): MockProduct {
  const product = state.products.find((item) => item.id === productId);
  if (!product) fail(404, "RESOURCE_NOT_VISIBLE", "商品不存在或当前不可查看。");
  return product;
}

function tradeById(tradeId: string): MockTrade {
  const trade = state.trades.find((item) => item.id === tradeId);
  if (!trade) fail(404, "RESOURCE_NOT_VISIBLE", "交易不存在或当前不可查看。");
  return trade;
}

function requireParticipant(trade: MockTrade, accountId: string): void {
  if (trade.buyer_id !== accountId && trade.seller_id !== accountId) {
    fail(404, "RESOURCE_NOT_VISIBLE", "交易不存在或当前不可查看。");
  }
}

function fileUrl(fileId: string): string {
  const file = state.files.find((item) => item.file_id === fileId);
  if (!file) fail(404, "RESOURCE_NOT_VISIBLE", "文件不存在。");
  return file.url;
}

function productSummary(product: MockProduct): ProductSummary {
  return {
    id: product.id,
    title: product.title,
    price_cents: product.price_cents,
    thumbnail: product.image_file_ids.length ? signedImage(state, product.image_file_ids[0]) : null,
    categories: categoryRefs(state, product.category_ids),
    seller: (() => {
      const ref = accountRef(state, product.seller_id);
      return { id: ref.id, display_name: ref.display_name, avatar_url: ref.avatar_url };
    })(),
    created_at: product.created_at,
  };
}

function commentView(comment: MockComment): CommentView {
  const author = accountRef(state, comment.author_id);
  return {
    id: comment.id,
    product_id: comment.product_id,
    author: {
      id: author.id,
      display_name: author.display_name,
      avatar_url: author.avatar_url,
    },
    body: comment.body,
    status: comment.removed_at
      ? "removed_by_admin"
      : comment.deleted_at
        ? "deleted_by_author"
        : "published",
    reply_to_comment_id: comment.parent_id,
    created_at: comment.created_at,
    replies: [],
  };
}

function productDetail(product: MockProduct, viewerId: string): ProductDetail {
  const isOwner = product.seller_id === viewerId;
  const detail: ProductDetail = {
    id: product.id,
    title: product.title,
    description: product.description,
    price_cents: product.price_cents,
    images: product.image_file_ids
      .map((fileId) => signedImage(state, fileId))
      .filter((image): image is NonNullable<typeof image> => Boolean(image)),
    categories: categoryRefs(state, product.category_ids),
    seller: (() => {
      const ref = accountRef(state, product.seller_id);
      return { id: ref.id, display_name: ref.display_name };
    })(),
    lifecycle_state: product.lifecycle_state,
    content_version: product.content_version,
    created_at: product.created_at,
    updated_at: product.updated_at,
  };
  if (!isOwner) return detail;

  detail.pending_review =
    product.pending_audit_id && product.pending_case_id && product.pending_submitted_at
      ? {
          audit_id: product.pending_audit_id,
          case_id: product.pending_case_id,
          submitted_at: product.pending_submitted_at,
        }
      : null;
  detail.latest_review =
    product.latest_audit_id && product.latest_review_status
      ? {
          audit_id: product.latest_audit_id,
          status: product.latest_review_status,
          reason: product.latest_review_reason,
          decided_at: product.latest_review_decided_at,
        }
      : null;
  detail.display_restrictions = product.display_restrictions;
  if (product.category_application?.status === "pending") {
    detail.category_application = {
      id: product.category_application.application_id,
      proposed_name: product.category_application.proposed_name,
      status: "pending",
    };
  }
  detail.permissions = {
    can_edit: product.lifecycle_state !== "in_trade",
    can_off_shelf: product.lifecycle_state === "public",
    can_relist:
      product.lifecycle_state === "off_shelf" && product.latest_review_status === "passed",
    can_withdraw_review: product.lifecycle_state === "pending_review",
    can_submit_review:
      product.lifecycle_state === "review_rejected" ||
      (product.lifecycle_state === "off_shelf" && product.latest_review_status === "rejected"),
  };
  return detail;
}

function addNotification(
  recipientId: string,
  eventType: string,
  summary: string,
  source: { resource_type: string; resource_id: string } | null,
): void {
  state.notifications.push({
    notification_id: nextId(state, "notifications"),
    recipient_id: recipientId,
    event_type: eventType,
    occurred_at: nowIso(),
    read_at: null,
    summary,
    source,
  });
}

function ensureTradeConversation(trade: MockTrade): string {
  if (trade.trade_conversation_id) return trade.trade_conversation_id;
  const existing = state.conversations.find(
    (item) => item.kind === "trade" && item.source_ref?.resource_id === trade.id,
  );
  if (existing) {
    trade.trade_conversation_id = existing.conversation_id;
    return existing.conversation_id;
  }
  const conversationId = nextId(state, "conversations");
  state.conversations.push({
    conversation_id: conversationId,
    kind: "trade",
    participant_ids: [trade.buyer_id, trade.seller_id],
    archived_at: null,
    created_at: nowIso(),
    source_ref: { resource_type: "trade", resource_id: trade.id },
  });
  trade.trade_conversation_id = conversationId;
  return conversationId;
}

function conversationByKey(kind: ConversationKind, conversationId: string) {
  const conversation = state.conversations.find(
    (item) => item.kind === kind && item.conversation_id === conversationId,
  );
  if (!conversation) fail(404, "PARTICIPANT_REQUIRED", "会话不存在或当前不可查看。");
  return conversation;
}

function messagesOf(kind: ConversationKind, conversationId: string): MockMessage[] {
  return state.messages
    .filter((item) => item.kind === kind && item.conversation_id === conversationId)
    .sort((left, right) => left.seq - right.seq);
}

/* ---------------------------------------------------------------- the routes */

const routes: Route[] = [
  /* -- connectivity / capabilities -- */
  {
    method: "GET",
    pattern: ["hello"],
    handler: () => ({ message: "Hello, Project1!" }),
  },
  {
    method: "GET",
    pattern: ["capabilities"],
    handler: () => ({
      config_version: "mock-2026-11-20",
      limits: {
        password_min_length: 10,
        password_max_length: 128,
        display_name_max_length: 64,
      },
    }),
  },
  {
    method: "GET",
    pattern: ["files", "upload-capabilities"],
    handler: () => ({
      rule_version: "mock-1",
      purposes: {
        product_image: {
          max_bytes: 104_857_600,
          allowed_content_types: ["image/jpeg", "image/png"],
        },
        case_evidence: {
          max_bytes: 104_857_600,
          allowed_content_types: ["image/jpeg", "image/png", "application/pdf"],
        },
        account_avatar: {
          max_bytes: 10_485_760,
          allowed_content_types: ["image/jpeg", "image/png"],
        },
      },
      upload_ttl_seconds: 900,
      read_url_ttl_seconds: 60,
    }),
  },

  /* -- account session / entry -- */
  {
    method: "GET",
    pattern: ["account", "session"],
    handler: ({ accountId }) => {
      const account = accountById(accountId);
      const avatar = account.avatar_file_id ? fileUrl(account.avatar_file_id) : null;
      return {
        account: {
          account_id: account.account_id,
          display_name: account.display_name,
          email: account.email,
          roles: account.roles,
          avatar_url: avatar,
        },
        session: {
          session_id: `mock-session-${account.account_id}`,
          issued_at: nowIso(),
          absolute_expires_at: new Date(Date.now() + 7 * 86_400_000).toISOString(),
        },
      };
    },
  },
  {
    method: "POST",
    pattern: ["account", "session"],
    anonymous: true,
    handler: ({ body }) => {
      const email = requireString(body, "email").trim().toLowerCase();
      const password = requireString(body, "password");
      const account = state.accounts.find((item) => item.email.toLowerCase() === email);
      if (!account || account.password !== password) {
        fail(401, "CREDENTIALS_INVALID", "邮箱或密码不正确。");
      }
      state.currentAccountId = account.account_id;
      const avatar = account.avatar_file_id ? fileUrl(account.avatar_file_id) : null;
      return {
        account: {
          account_id: account.account_id,
          display_name: account.display_name,
          email: account.email,
          roles: account.roles,
          avatar_url: avatar,
        },
        session: {
          session_id: `mock-session-${account.account_id}`,
          issued_at: nowIso(),
          absolute_expires_at: new Date(Date.now() + 7 * 86_400_000).toISOString(),
        },
      };
    },
  },
  {
    method: "DELETE",
    pattern: ["account", "session"],
    handler: () => {
      state.currentAccountId = null;
      return undefined;
    },
  },
  {
    method: "GET",
    pattern: ["account", "entry-context"],
    anonymous: true,
    handler: () => ({
      csrf_token: "mock-entry-csrf",
      expires_at: new Date(Date.now() + 3_600_000).toISOString(),
      limits: {
        email_code_length: 6,
        code_ttl_seconds: 600,
        resend_interval_seconds: 60,
        password_min_length: 10,
        password_max_length: 128,
        display_name_max_length: 64,
      },
    }),
  },
  {
    method: "POST",
    pattern: ["account", "email-verifications"],
    anonymous: true,
    handler: ({ body }) => {
      const purpose = requireString(body, "purpose");
      const email = requireString(body, "email");
      const expiresAt = new Date(Date.now() + 600_000).toISOString();
      // An email change sends one code to the current mailbox and one to the new one,
      // and the two tickets are distinguished by purpose rather than by order.
      const purposes =
        purpose === "email_change" ? ["email_change_old", "email_change_new"] : [purpose];
      return {
        purpose,
        requests: purposes.map((ticketPurpose, index) => ({
          verification_id: `V-${Date.now()}-${index}`,
          purpose: ticketPurpose,
          expires_at: expiresAt,
        })),
        retry_after_seconds: 60,
        email,
      };
    },
  },
  {
    method: "POST",
    pattern: ["accounts"],
    anonymous: true,
    handler: ({ body }) => {
      const email = requireString(body, "email").trim().toLowerCase();
      if (state.accounts.some((item) => item.email.toLowerCase() === email)) {
        fail(409, "EMAIL_IN_USE", "该邮箱已被注册。");
      }
      const account = {
        account_id: nextId(state, "accounts"),
        email,
        password: requireString(body, "password"),
        display_name: requireString(body, "display_name"),
        roles: ["user" as const],
        avatar_file_id: null,
        write_restricted: false,
      };
      state.accounts.push(account);
      state.currentAccountId = account.account_id;
      return {
        account_id: account.account_id,
        email: account.email,
        display_name: account.display_name,
      };
    },
  },
  {
    method: "PATCH",
    pattern: ["account", "profile"],
    handler: ({ accountId, body }) => {
      const account = accountById(accountId);
      const hasName = body.display_name !== undefined;
      const hasAvatar = Object.prototype.hasOwnProperty.call(body, "avatar_file_id");
      if (!hasName && !hasAvatar) {
        fail(422, "INPUT_INVALID", "请至少提交显示名称或头像。");
      }
      if (hasName) {
        account.display_name = requireString(body, "display_name");
      }
      if (hasAvatar) {
        const fileId = body.avatar_file_id;
        if (fileId === null) {
          // The endpoint cannot tell an explicit null from an omitted field, so a
          // null keeps the current avatar; removal is the "0" sentinel.
        } else if (fileId === "" || fileId === "0") {
          account.avatar_file_id = null;
        } else {
          const id = typeof fileId === "string" ? fileId : "";
          const file = state.files.find((item) => item.file_id === id);
          if (!file || file.owner_account_id !== accountId) {
            fail(404, "RESOURCE_NOT_VISIBLE", "文件不存在。");
          }
          if (file.purpose !== "account_avatar") {
            fail(422, "FILE_PURPOSE_MISMATCH", "该文件用途不是头像。");
          }
          if (file.state !== "verified") {
            fail(409, "FILE_NOT_REFERENCEABLE", "文件尚未完成核验。");
          }
          account.avatar_file_id = id;
        }
      }
      const avatarFile = account.avatar_file_id
        ? state.files.find((item) => item.file_id === account.avatar_file_id)
        : undefined;
      return {
        account_id: account.account_id,
        display_name: account.display_name,
        avatar_url: avatarFile?.url ?? null,
      };
    },
  },
  {
    method: "PUT",
    pattern: ["account", "password"],
    handler: ({ accountId, body }) => {
      const account = accountById(accountId);
      if (requireString(body, "current_password") !== account.password) {
        fail(422, "CURRENT_PASSWORD_INVALID", "当前密码不正确。");
      }
      account.password = requireString(body, "new_password");
      return undefined;
    },
  },
  {
    method: "POST",
    pattern: ["account", "password-resets"],
    anonymous: true,
    handler: ({ body }) => {
      const next = requireString(body, "new_password");
      const target = state.accounts[0];
      target.password = next;
      return undefined;
    },
  },
  {
    method: "PUT",
    pattern: ["account", "email"],
    handler: ({ accountId, body }) => {
      const account = accountById(accountId);
      const nextEmail = requireString(body, "new_email").trim().toLowerCase();
      if (state.accounts.some((item) => item.email.toLowerCase() === nextEmail)) {
        fail(409, "EMAIL_IN_USE", "该邮箱已被其他账户使用。");
      }
      account.email = nextEmail;
      return { account_id: account.account_id, email: account.email };
    },
  },
  /* -- files -- */
  {
    method: "POST",
    pattern: ["files", "uploads"],
    handler: ({ accountId, body }) => {
      const purpose = requireString(body, "purpose") as FilePurpose;
      const declaredSize = requireNumber(body, "declared_size");
      const declaredType = requireString(body, "declared_content_type");
      if (!["product_image", "case_evidence", "account_avatar"].includes(purpose)) {
        fail(422, "FILE_PURPOSE_MISMATCH", "不支持的文件用途。");
      }
      const fileId = nextId(state, "files");
      const file = {
        file_id: fileId,
        owner_account_id: accountId,
        purpose,
        state: "uploading" as const,
        content_type: declaredType,
        size_bytes: declaredSize,
        object_key: `dev/${purpose}/${Date.now()}`,
        expires_at: new Date(Date.now() + 900_000).toISOString(),
        verified_at: null,
        // Same-origin preview: the dev server proxies this to the mock service,
        // which answers with a generated placeholder image for the file.
        url: `/api/v1/files/${fileId}/content`,
      };
      state.files.push(file);
      const result: CreateUploadResult = {
        file_id: file.file_id,
        state: "uploading",
        expires_at: file.expires_at,
        upload: {
          // Same-origin so the browser can actually post the bytes; the dev server
          // proxies this path to the mock service, which accepts the transfer.
          method: "POST",
          url: "/api/v1/files/mock-upload",
          fields: { key: file.object_key },
        },
        limits: { max_bytes: 104_857_600, allowed_content_types: [declaredType] },
      };
      return result;
    },
  },
  {
    // Stands in for the bucket entry point: the browser posts the signed form and
    // the bytes here, and the dev server forwards it to this service.
    method: "POST",
    pattern: ["files", "mock-upload"],
    handler: () => undefined,
  },
  {
    method: "POST",
    pattern: ["files", ":fileId", "completion"],
    handler: ({ accountId, params }) => {
      const file = state.files.find((item) => item.file_id === params.fileId);
      if (!file || file.owner_account_id !== accountId) {
        fail(404, "RESOURCE_NOT_VISIBLE", "文件不存在。");
      }
      if (file.state === "verified") {
        return {
          file_id: file.file_id,
          purpose: file.purpose,
          state: "verified",
          verified_at: file.verified_at,
          metadata: { size_bytes: file.size_bytes, content_type: file.content_type },
        };
      }
      file.state = "verified";
      file.verified_at = nowIso();
      return {
        file_id: file.file_id,
        purpose: file.purpose,
        state: "verified",
        verified_at: file.verified_at,
        metadata: { size_bytes: file.size_bytes, content_type: file.content_type },
      };
    },
  },

  /* -- catalog -- */
  {
    method: "GET",
    pattern: ["categories"],
    handler: () => ({ items: state.categories.map((category) => categoryView(state, category)) }),
  },
  {
    method: "GET",
    pattern: ["banned-items"],
    handler: () => state.bannedScope,
  },
  {
    method: "GET",
    pattern: ["products"],
    handler: ({ query }) => {
      const keyword = typeof query.keyword === "string" ? query.keyword.trim().toLowerCase() : "";
      const categoryIds = Array.isArray(query.category_ids)
        ? (query.category_ids as string[])
        : query.category_ids
          ? [String(query.category_ids)]
          : [];
      const min = query.min_price_cents !== undefined ? Number(query.min_price_cents) : null;
      const max = query.max_price_cents !== undefined ? Number(query.max_price_cents) : null;
      const matches = state.products
        .filter((product) => product.lifecycle_state === "public")
        .filter((product) =>
          keyword
            ? product.title.toLowerCase().includes(keyword) ||
              product.description.toLowerCase().includes(keyword)
            : true,
        )
        .filter((product) =>
          categoryIds.length ? categoryIds.every((id) => product.category_ids.includes(id)) : true,
        )
        .filter(
          (product) =>
            (min === null || product.price_cents >= min) &&
            (max === null || product.price_cents <= max),
        )
        .sort((left, right) =>
          right.created_at === left.created_at
            ? Number(right.id) - Number(left.id)
            : right.created_at.localeCompare(left.created_at),
        );
      return paginate(matches.map(productSummary), query);
    },
  },
  {
    method: "POST",
    pattern: ["products"],
    handler: ({ accountId, body }) => {
      const account = accountById(accountId);
      if (account.write_restricted) {
        fail(403, "ACCOUNT_WRITE_RESTRICTED", "账户当前限制发布商品。");
      }
      const categoryIds = Array.isArray(body.category_ids) ? (body.category_ids as string[]) : [];
      const application = body.category_application as { proposed_name?: string } | undefined;
      if (!categoryIds.length && !application?.proposed_name) {
        fail(422, "CATEGORY_REQUIRED", "请至少选择一个分类，或提交新分类申请。");
      }
      for (const id of categoryIds) {
        const category = state.categories.find((item) => item.id === id);
        if (!category || category.disabled) {
          fail(422, "CATEGORY_NOT_SELECTABLE", "所选分类当前不可选择。");
        }
      }
      const imageIds = Array.isArray(body.image_file_ids) ? (body.image_file_ids as string[]) : [];
      for (const id of imageIds) {
        const file = state.files.find((item) => item.file_id === id);
        if (!file || file.owner_account_id !== accountId) {
          fail(422, "FILE_ACTION_NOT_ALLOWED", "图片文件不属于当前账户。");
        }
        if (file.purpose !== "product_image") {
          fail(422, "FILE_PURPOSE_MISMATCH", "图片文件用途不符。");
        }
        if (file.state !== "verified") {
          fail(409, "FILE_NOT_REFERENCEABLE", "图片尚未完成核验。");
        }
      }
      const productId = nextId(state, "products");
      const auditId = `A-${2000 + Number(productId)}`;
      const caseId = nextId(state, "cases");
      const timestamp = nowIso();
      const product: MockProduct = {
        id: productId,
        seller_id: accountId,
        title: requireString(body, "title"),
        description: requireString(body, "description"),
        price_cents: requireNumber(body, "price_cents"),
        category_ids: categoryIds,
        image_file_ids: imageIds,
        lifecycle_state: "pending_review",
        content_version: 1,
        created_at: timestamp,
        updated_at: timestamp,
        pending_audit_id: auditId,
        pending_case_id: caseId,
        pending_submitted_at: timestamp,
        latest_audit_id: auditId,
        latest_review_status: "pending",
        latest_review_reason: null,
        latest_review_decided_at: null,
        category_application: application?.proposed_name
          ? {
              application_id: nextId(state, "categoryApplications"),
              proposed_name: application.proposed_name,
              status: "pending",
            }
          : null,
        display_restrictions: [],
        edit_history: [],
      };
      state.products.push(product);
      state.cases.push({
        case_id: caseId,
        case_type: "product_review",
        status: "pending",
        reporter_id: null,
        related_ids: [accountId],
        manager_id: null,
        claimed_at: null,
        decision_kind: null,
        reason_text: `商品《${product.title}》待审核。`,
        note: null,
        archived_at: null,
        appeal_deadline_at: null,
        public_result_at: null,
        created_at: timestamp,
        updated_at: timestamp,
        supplement_count: 0,
        thread_id: null,
        actions: [{ action_kind: "submit", occurred_at: timestamp, actor_kind: "seller" }],
        enforcements: [],
        target: { target_type: "product", target_id: productId },
        public_result: null,
      });
      return productDetail(product, accountId);
    },
  },
  {
    method: "GET",
    pattern: ["products", ":productId"],
    handler: ({ accountId, params }) => {
      const product = productById(params.productId);
      if (product.lifecycle_state !== "public" && product.seller_id !== accountId) {
        fail(404, "RESOURCE_NOT_VISIBLE", "商品不存在或当前不可查看。");
      }
      return productDetail(product, accountId);
    },
  },
  {
    method: "PATCH",
    pattern: ["products", ":productId"],
    handler: ({ accountId, params, body }) => {
      const product = productById(params.productId);
      if (product.seller_id !== accountId) {
        fail(404, "RESOURCE_NOT_VISIBLE", "商品不存在或当前不可查看。");
      }
      expectVersion(body, product.content_version);
      if (product.lifecycle_state === "in_trade") {
        fail(409, "EDIT_NOT_ALLOWED_IN_TRADE", "交易中的商品不能修改关键内容。");
      }
      const before = {
        title: product.title,
        description: product.description,
        price_cents: product.price_cents,
        category_ids: [...product.category_ids],
      };
      const nextTitle = optionalString(body, "title");
      const nextDescription = optionalString(body, "description");
      if (nextTitle !== undefined) product.title = nextTitle;
      if (nextDescription !== undefined) product.description = nextDescription;
      if (typeof body.price_cents === "number") product.price_cents = body.price_cents;
      if (Array.isArray(body.category_ids)) {
        product.category_ids = body.category_ids as string[];
      }
      if (Array.isArray(body.image_file_ids)) {
        product.image_file_ids = body.image_file_ids as string[];
      }
      product.content_version += 1;
      product.updated_at = nowIso();
      product.edit_history.unshift({
        edit_id: nextId(state, "edits"),
        edited_at: product.updated_at,
        operator_kind: "seller",
        edit_kind: "edit",
        before_content: before,
        after_content: {
          title: product.title,
          description: product.description,
          price_cents: product.price_cents,
          category_ids: [...product.category_ids],
        },
        reason: null,
      });
      return productDetail(product, accountId);
    },
  },
  {
    method: "GET",
    pattern: ["products", ":productId", "edit-history"],
    handler: ({ accountId, params, query }) => {
      const product = productById(params.productId);
      if (product.seller_id !== accountId) {
        fail(404, "RESOURCE_NOT_VISIBLE", "商品不存在或当前不可查看。");
      }
      return paginate(product.edit_history, query);
    },
  },
  {
    method: "POST",
    pattern: ["products", ":productId", "review-submissions"],
    handler: ({ accountId, params, body }) => {
      const product = productById(params.productId);
      if (product.seller_id !== accountId) {
        fail(404, "RESOURCE_NOT_VISIBLE", "商品不存在或当前不可查看。");
      }
      expectVersion(body, product.content_version);
      if (
        product.lifecycle_state !== "review_rejected" &&
        !(product.lifecycle_state === "off_shelf" && product.latest_review_status === "rejected")
      ) {
        fail(409, "PRODUCT_NOT_RESUBMITTABLE", "当前状态不能重新提交审核。");
      }
      if (!product.category_ids.length && !product.category_application) {
        fail(422, "CATEGORY_REQUIRED", "请至少选择一个分类。");
      }
      const auditId = `A-${2000 + Number(product.id)}-${Date.now() % 10_000}`;
      const caseId = nextId(state, "cases");
      const timestamp = nowIso();
      product.lifecycle_state = "pending_review";
      product.pending_audit_id = auditId;
      product.pending_case_id = caseId;
      product.pending_submitted_at = timestamp;
      product.latest_audit_id = auditId;
      product.latest_review_status = "pending";
      product.latest_review_reason = null;
      product.latest_review_decided_at = null;
      product.updated_at = timestamp;
      state.cases.push({
        case_id: caseId,
        case_type: "product_review",
        status: "pending",
        reporter_id: null,
        related_ids: [accountId],
        manager_id: null,
        claimed_at: null,
        decision_kind: null,
        reason_text: `商品《${product.title}》重新提交审核。`,
        note: null,
        archived_at: null,
        appeal_deadline_at: null,
        public_result_at: null,
        created_at: timestamp,
        updated_at: timestamp,
        supplement_count: 0,
        thread_id: null,
        actions: [{ action_kind: "submit", occurred_at: timestamp, actor_kind: "seller" }],
        enforcements: [],
        target: { target_type: "product", target_id: product.id },
        public_result: null,
      });
      return {
        audit_id: auditId,
        case_id: caseId,
        lifecycle_state: product.lifecycle_state,
        content_version: product.content_version,
      };
    },
  },
  {
    method: "POST",
    pattern: ["products", ":productId", "withdrawal"],
    handler: ({ accountId, params, body }) => {
      const product = productById(params.productId);
      if (product.seller_id !== accountId) {
        fail(404, "RESOURCE_NOT_VISIBLE", "商品不存在或当前不可查看。");
      }
      expectVersion(body, product.content_version);
      if (product.lifecycle_state !== "pending_review") {
        fail(409, "STATE_CONFLICT", "只有待审核商品可以撤回。");
      }
      const reviewCase = state.cases.find((item) => item.case_id === product.pending_case_id);
      if (reviewCase?.manager_id) {
        fail(409, "REVIEW_ALREADY_CLAIMED", "审核已被认领，不能撤回。");
      }
      product.lifecycle_state = "off_shelf";
      product.latest_review_status = "withdrawn";
      product.pending_audit_id = null;
      product.pending_case_id = null;
      product.pending_submitted_at = null;
      product.updated_at = nowIso();
      return {
        lifecycle_state: product.lifecycle_state,
        audit_status: "withdrawn",
        category_application_status: product.category_application?.status ?? null,
        content_version: product.content_version,
      };
    },
  },
  {
    method: "POST",
    pattern: ["products", ":productId", "off-shelf"],
    handler: ({ accountId, params, body }) => {
      const product = productById(params.productId);
      if (product.seller_id !== accountId) {
        fail(404, "RESOURCE_NOT_VISIBLE", "商品不存在或当前不可查看。");
      }
      expectVersion(body, product.content_version);
      if (product.lifecycle_state !== "public") {
        fail(409, "STATE_CONFLICT", "只有公开商品可以主动下架。");
      }
      const locked = state.trades.some(
        (trade) => trade.product_id === product.id && trade.status === "in_progress",
      );
      if (locked) fail(409, "PRODUCT_LOCKED", "商品存在未结束占用，不能下架。");
      const pending = state.trades.filter(
        (trade) => trade.product_id === product.id && trade.status === "pending_acceptance",
      );
      for (const trade of pending) {
        trade.status = "closed";
        trade.close_reason = "商品已下架";
        trade.updated_at = nowIso();
        trade.version += 1;
        addNotification(
          trade.buyer_id,
          "trade.request_closed",
          `商品《${product.title}》已下架，你的购买请求已关闭。`,
          { resource_type: "trade", resource_id: trade.id },
        );
      }
      product.lifecycle_state = "off_shelf";
      product.updated_at = nowIso();
      return {
        product: productDetail(product, accountId),
        closed_pending_request_count: pending.length,
      };
    },
  },
  {
    method: "POST",
    pattern: ["products", ":productId", "on-shelf"],
    handler: ({ accountId, params, body }) => {
      const product = productById(params.productId);
      if (product.seller_id !== accountId) {
        fail(404, "RESOURCE_NOT_VISIBLE", "商品不存在或当前不可查看。");
      }
      expectVersion(body, product.content_version);
      if (product.lifecycle_state !== "off_shelf") {
        fail(409, "STATE_CONFLICT", "只有已下架商品可以重新上架。");
      }
      if (product.latest_review_status !== "passed") {
        fail(409, "PRODUCT_NOT_RELISTABLE", "最新审核未通过，不能上架。");
      }
      product.lifecycle_state = "public";
      product.updated_at = nowIso();
      return productDetail(product, accountId);
    },
  },

  /* -- product interaction: comments and favourites -- */
  {
    method: "GET",
    pattern: ["products", ":productId", "comments"],
    handler: ({ accountId, params, query }) => {
      const product = productById(params.productId);
      const seller = product.seller_id === accountId;
      const visible =
        product.lifecycle_state === "public" || product.lifecycle_state === "in_trade";
      const caseId = typeof query.case_id === "string" ? query.case_id : null;
      const claimed =
        caseId !== null &&
        state.cases.some(
          (item) =>
            item.case_id === caseId &&
            item.manager_id === accountId &&
            item.target?.target_type === "product" &&
            item.target.target_id === product.id,
        );
      let scope: "public" | "author" | "case" = "public";
      if (claimed) {
        scope = "case";
      } else if (!visible) {
        if (seller) {
          scope = "author";
        } else if (
          state.comments.some(
            (item) => item.product_id === product.id && item.author_id === accountId,
          )
        ) {
          scope = "author";
        } else {
          fail(404, "RESOURCE_NOT_VISIBLE", "商品不存在或当前不可查看。");
        }
      }
      const readable = (comment: MockComment): boolean => {
        if (scope === "public") return !comment.deleted_at && !comment.removed_at;
        if (scope === "author") return comment.author_id === accountId;
        return true;
      };
      const topLevel = state.comments
        .filter(
          (item) => item.product_id === product.id && item.parent_id === null && readable(item),
        )
        .sort(
          (first, second) =>
            second.created_at.localeCompare(first.created_at) || second.id.localeCompare(first.id),
        );
      const paged = paginate(topLevel, query);
      const items = paged.items.map((item) => {
        const replies = state.comments
          .filter((reply) => reply.parent_id === item.id && readable(reply))
          .sort(
            (first, second) =>
              first.created_at.localeCompare(second.created_at) ||
              first.id.localeCompare(second.id),
          )
          .map((reply) => commentView(reply));
        return { ...commentView(item), replies };
      });
      return { ...paged, items };
    },
  },
  {
    method: "POST",
    pattern: ["products", ":productId", "comments"],
    handler: ({ accountId, params, body }) => {
      const product = productById(params.productId);
      if (accountById(accountId).write_restricted) {
        fail(403, "ACCOUNT_WRITE_RESTRICTED", "账户当前受限。");
      }
      const visible =
        product.lifecycle_state === "public" || product.lifecycle_state === "in_trade";
      if (!visible && product.seller_id !== accountId) {
        fail(404, "RESOURCE_NOT_VISIBLE", "商品不存在或当前不可查看。");
      }
      if (!visible) fail(409, "COMMENT_NOT_ALLOWED", "当前商品不能发表评论。");
      const text = requireString(body, "body").trim();
      if ([...text].length > 500) fail(422, "INPUT_INVALID", "评论内容过长。");
      const comment: MockComment = {
        id: nextId(state, "comments"),
        product_id: product.id,
        author_id: accountId,
        parent_id: null,
        body: text,
        created_at: nowIso(),
        deleted_at: null,
        removed_at: null,
        removed_reason: null,
        basis_ref: null,
      };
      state.comments.push(comment);
      return commentView(comment);
    },
  },
  {
    method: "POST",
    pattern: ["products", ":productId", "comments", ":commentId", "replies"],
    handler: ({ accountId, params, body }) => {
      const product = productById(params.productId);
      if (accountById(accountId).write_restricted) {
        fail(403, "ACCOUNT_WRITE_RESTRICTED", "账户当前受限。");
      }
      if (product.seller_id !== accountId) {
        fail(403, "COMMENT_REPLY_NOT_ALLOWED", "只能由商品卖方回复评论。");
      }
      if (product.lifecycle_state !== "public" && product.lifecycle_state !== "in_trade") {
        fail(409, "COMMENT_NOT_ALLOWED", "当前商品不能回复评论。");
      }
      const parent = state.comments.find(
        (item) => item.id === params.commentId && item.product_id === product.id,
      );
      if (!parent) fail(404, "RESOURCE_NOT_VISIBLE", "评论不存在。");
      if (parent.parent_id !== null) fail(409, "STATE_CONFLICT", "只能回复已发表的顶级评论。");
      if (parent.deleted_at || parent.removed_at) fail(409, "STATE_CONFLICT", "评论已不可回复。");
      const text = requireString(body, "body").trim();
      if ([...text].length > 500) fail(422, "INPUT_INVALID", "回复内容过长。");
      const reply: MockComment = {
        id: nextId(state, "comments"),
        product_id: product.id,
        author_id: accountId,
        parent_id: parent.id,
        body: text,
        created_at: nowIso(),
        deleted_at: null,
        removed_at: null,
        removed_reason: null,
        basis_ref: null,
      };
      state.comments.push(reply);
      return commentView(reply);
    },
  },
  {
    method: "DELETE",
    pattern: ["products", ":productId", "comments", ":commentId"],
    handler: ({ accountId, params }) => {
      const comment = state.comments.find(
        (item) => item.id === params.commentId && item.product_id === params.productId,
      );
      if (!comment) fail(404, "RESOURCE_NOT_VISIBLE", "评论不存在。");
      if (accountById(accountId).write_restricted) {
        fail(403, "ACCOUNT_WRITE_RESTRICTED", "账户当前受限。");
      }
      if (comment.author_id !== accountId) fail(403, "ACTION_NOT_ALLOWED", "只能删除本人评论。");
      if (comment.removed_at) fail(409, "COMMENT_ALREADY_REMOVED", "评论已被管理员移除。");
      if (!comment.deleted_at) comment.deleted_at = nowIso();
      return undefined;
    },
  },
  {
    method: "GET",
    pattern: ["me", "favorites"],
    handler: ({ accountId, query }) => {
      const rows = state.favorites
        .filter((favorite) => favorite.account_id === accountId)
        .sort((first, second) => second.created_at.localeCompare(first.created_at))
        .map((favorite) => {
          const product = state.products.find((item) => item.id === favorite.product_id);
          if (
            product &&
            (product.lifecycle_state === "public" || product.lifecycle_state === "in_trade")
          ) {
            return {
              product_id: favorite.product_id,
              status: "valid",
              favorited_at: favorite.created_at,
              product: productSummary(product),
            };
          }
          return {
            product_id: favorite.product_id,
            status: "invalid",
            favorited_at: favorite.created_at,
            product: null,
            message: "该商品已失效",
          };
        });
      return paginate(rows, query);
    },
  },
  {
    method: "GET",
    pattern: ["me", "favorites", ":productId"],
    handler: ({ accountId, params }) => {
      const product = state.products.find((item) => item.id === params.productId);
      const valid =
        product !== undefined &&
        (product.lifecycle_state === "public" || product.lifecycle_state === "in_trade");
      const favorite = state.favorites.find(
        (item) => item.account_id === accountId && item.product_id === params.productId,
      );
      if (!favorite && !valid) fail(404, "RESOURCE_NOT_VISIBLE", "商品不存在或当前不可查看。");
      return {
        favorited: favorite !== undefined,
        valid,
        favorited_at: favorite?.created_at ?? null,
      };
    },
  },
  {
    method: "PUT",
    pattern: ["me", "favorites", ":productId"],
    handler: ({ accountId, params }) => {
      if (accountById(accountId).write_restricted) {
        fail(403, "ACCOUNT_WRITE_RESTRICTED", "账户当前受限。");
      }
      const product = state.products.find((item) => item.id === params.productId);
      const valid =
        product !== undefined &&
        (product.lifecycle_state === "public" || product.lifecycle_state === "in_trade");
      if (!valid) fail(404, "RESOURCE_NOT_VISIBLE", "商品不存在或当前不可查看。");
      let favorite = state.favorites.find(
        (item) => item.account_id === accountId && item.product_id === params.productId,
      );
      if (!favorite) {
        favorite = { account_id: accountId, product_id: params.productId, created_at: nowIso() };
        state.favorites.push(favorite);
      }
      return { favorited: true, valid: true, favorited_at: favorite.created_at };
    },
  },
  {
    method: "DELETE",
    pattern: ["me", "favorites", ":productId"],
    handler: ({ accountId, params }) => {
      if (accountById(accountId).write_restricted) {
        fail(403, "ACCOUNT_WRITE_RESTRICTED", "账户当前受限。");
      }
      state.favorites = state.favorites.filter(
        (item) => !(item.account_id === accountId && item.product_id === params.productId),
      );
      return undefined;
    },
  },

  /* -- trades -- */
  {
    method: "POST",
    pattern: ["products", ":productId", "purchase-requests"],
    handler: ({ accountId, params, body }) => {
      const product = productById(params.productId);
      if (product.lifecycle_state !== "public") {
        fail(409, "PRODUCT_NOT_AVAILABLE", "商品当前不可交易。");
      }
      if (product.seller_id === accountId) {
        fail(422, "INPUT_INVALID", "不能购买自己发布的商品。");
      }
      expectVersion(body, product.content_version);
      const duplicated = state.trades.some(
        (trade) =>
          trade.product_id === product.id &&
          trade.buyer_id === accountId &&
          trade.status === "pending_acceptance",
      );
      if (duplicated) fail(409, "STATE_CONFLICT", "你已有该商品待接受的请求。");
      const timestamp = nowIso();
      const trade: MockTrade = {
        id: nextId(state, "trades"),
        product_id: product.id,
        buyer_id: accountId,
        seller_id: product.seller_id,
        status: "pending_acceptance",
        phase: null,
        terminal_reason: null,
        request_note: optionalString(body, "note") ?? null,
        requested_at: timestamp,
        responded_at: null,
        close_reason: null,
        agreements: [],
        confirmations: [],
        wait: {
          active: false,
          started_at: null,
          deadline_at: null,
          remaining_seconds: 0,
          paused: false,
          ended_at: null,
          end_reason: null,
        },
        freeze: [],
        cancellation: null,
        dispute: null,
        trade_conversation_id: null,
        version: 1,
        created_at: timestamp,
        updated_at: timestamp,
        reviews: [],
      };
      state.trades.push(trade);
      ensureTradeConversation(trade);
      addNotification(
        trade.seller_id,
        "trade.request_created",
        `收到《${product.title}》的新购买请求。`,
        { resource_type: "trade", resource_id: trade.id },
      );
      return tradeView(state, trade, accountId);
    },
  },
  {
    method: "GET",
    pattern: ["me", "trades"],
    handler: ({ accountId, query }) => {
      const role = typeof query.role === "string" ? query.role : "all";
      const statuses = Array.isArray(query.status)
        ? (query.status as string[])
        : query.status
          ? [String(query.status)]
          : [];
      const matches = state.trades
        .filter((trade) => trade.buyer_id === accountId || trade.seller_id === accountId)
        .filter((trade) =>
          role === "buyer"
            ? trade.buyer_id === accountId
            : role === "seller"
              ? trade.seller_id === accountId
              : true,
        )
        .filter((trade) => (statuses.length ? statuses.includes(trade.status) : true))
        .sort((left, right) =>
          right.updated_at === left.updated_at
            ? Number(right.id) - Number(left.id)
            : right.updated_at.localeCompare(left.updated_at),
        );
      return paginate(
        matches.map((trade) => tradeView(state, trade, accountId)),
        query,
      );
    },
  },
  {
    method: "GET",
    pattern: ["trades", ":tradeId"],
    handler: ({ accountId, params }) => {
      const trade = tradeById(params.tradeId);
      requireParticipant(trade, accountId);
      return tradeView(state, trade, accountId);
    },
  },
  {
    method: "POST",
    pattern: ["trades", ":tradeId", "accept"],
    handler: ({ accountId, params, body }) => {
      const trade = tradeById(params.tradeId);
      requireParticipant(trade, accountId);
      expectVersion(body, trade.version);
      if (trade.seller_id !== accountId) {
        fail(403, "ACTION_NOT_ALLOWED", "只有卖方可以接受请求。");
      }
      if (trade.status !== "pending_acceptance") {
        fail(409, "STATE_CONFLICT", "该请求已结束。");
      }
      trade.status = "in_progress";
      trade.phase = "first_agreement_pending";
      trade.responded_at = nowIso();
      trade.updated_at = trade.responded_at;
      trade.version += 1;
      const product = state.products.find((item) => item.id === trade.product_id);
      if (product) {
        product.lifecycle_state = "in_trade";
        product.updated_at = nowIso();
      }
      ensureTradeConversation(trade);
      for (const other of state.trades) {
        if (
          other.id !== trade.id &&
          other.product_id === trade.product_id &&
          other.status === "pending_acceptance"
        ) {
          other.status = "closed";
          other.close_reason = "商品已被其他交易占用";
          other.updated_at = nowIso();
          other.version += 1;
          addNotification(
            other.buyer_id,
            "trade.request_closed",
            "该商品已被其他买家锁定，你的购买请求已关闭。",
            { resource_type: "trade", resource_id: other.id },
          );
        }
      }
      addNotification(
        trade.buyer_id,
        "trade.request_accepted",
        `卖家已接受你的购买请求，请提出或确认交易约定。`,
        { resource_type: "trade", resource_id: trade.id },
      );
      return tradeView(state, trade, accountId);
    },
  },
  {
    method: "POST",
    pattern: ["trades", ":tradeId", "reject"],
    handler: ({ accountId, params, body }) => {
      const trade = tradeById(params.tradeId);
      requireParticipant(trade, accountId);
      expectVersion(body, trade.version);
      if (trade.seller_id !== accountId) {
        fail(403, "ACTION_NOT_ALLOWED", "只有卖方可以拒绝请求。");
      }
      if (trade.status !== "pending_acceptance") {
        fail(409, "STATE_CONFLICT", "该请求已结束。");
      }
      trade.status = "rejected";
      trade.responded_at = nowIso();
      trade.updated_at = trade.responded_at;
      trade.version += 1;
      addNotification(trade.buyer_id, "trade.request_rejected", "卖方拒绝了你的购买请求。", {
        resource_type: "trade",
        resource_id: trade.id,
      });
      return tradeView(state, trade, accountId);
    },
  },
  {
    method: "POST",
    pattern: ["trades", ":tradeId", "withdraw"],
    handler: ({ accountId, params, body }) => {
      const trade = tradeById(params.tradeId);
      requireParticipant(trade, accountId);
      expectVersion(body, trade.version);
      if (trade.buyer_id !== accountId) {
        fail(403, "ACTION_NOT_ALLOWED", "只有买方可以撤回请求。");
      }
      if (trade.status !== "pending_acceptance") {
        fail(409, "REQUEST_ALREADY_ENDED", "该请求已结束。");
      }
      trade.status = "withdrawn";
      trade.responded_at = nowIso();
      trade.updated_at = trade.responded_at;
      trade.version += 1;
      return tradeView(state, trade, accountId);
    },
  },
  {
    method: "POST",
    pattern: ["trades", ":tradeId", "agreements"],
    handler: ({ accountId, params, body }) => {
      const trade = tradeById(params.tradeId);
      requireParticipant(trade, accountId);
      expectVersion(body, trade.version);
      if (trade.status !== "in_progress") {
        fail(409, "STATE_CONFLICT", "当前状态不能提出约定。");
      }
      const existingPending = trade.agreements.find((item) => item.status === "proposed");
      if (existingPending) {
        fail(409, "STATE_CONFLICT", "已有待回应的约定。");
      }
      const effective = trade.agreements.find((item) => item.status === "effective") ?? null;
      const management = {
        delivery_at: requireString(body, "delivery_at"),
        delivery_place_text: requireString(body, "delivery_place_text"),
        delivery_method: requireString(body, "delivery_method"),
        amount_cents: requireNumber(body, "amount_cents"),
        payment_method: requireString(body, "payment_method"),
        payment_timing: requireString(body, "payment_timing"),
      };
      const agreement: Agreement = {
        id: nextId(state, "agreements"),
        base_agreement_id: effective?.id ?? null,
        version_no: (effective?.version_no ?? 0) + 1,
        status: "proposed",
        proposed_by: accountId,
        proposed_at: nowIso(),
        ...management,
      } as Agreement;
      trade.agreements.push(agreement);
      trade.updated_at = nowIso();
      trade.version += 1;
      const counterpart = trade.buyer_id === accountId ? trade.seller_id : trade.buyer_id;
      addNotification(counterpart, "trade.agreement_proposed", "对方提出了新的交易约定，请回应。", {
        resource_type: "trade",
        resource_id: trade.id,
      });
      return { agreement, trade: tradeView(state, trade, accountId) };
    },
  },
  {
    method: "POST",
    pattern: ["trades", ":tradeId", "agreements", ":agreementId", "decisions"],
    handler: ({ accountId, params, body }) => {
      const trade = tradeById(params.tradeId);
      requireParticipant(trade, accountId);
      expectVersion(body, trade.version);
      const agreement = trade.agreements.find((item) => item.id === params.agreementId);
      if (!agreement || agreement.status !== "proposed") {
        fail(409, "STATE_CONFLICT", "该约定已处理。");
      }
      const decision = requireString(body, "decision") as DecisionKind;
      const proposedBySelf = agreement.proposed_by === accountId;
      if (decision === "withdraw") {
        if (!proposedBySelf) fail(403, "ACTION_NOT_ALLOWED", "只有提出方可以撤回。");
        agreement.status = "withdrawn";
      } else if (decision === "reject") {
        if (proposedBySelf) fail(403, "ACTION_NOT_ALLOWED", "不能拒绝自己提出的约定。");
        agreement.status = "rejected";
      } else {
        if (proposedBySelf) fail(403, "ACTION_NOT_ALLOWED", "不能同意自己提出的约定。");
        for (const other of trade.agreements) {
          if (other.status === "effective") other.status = "superseded";
        }
        agreement.status = "effective";
        trade.phase = "awaiting_completion";
        trade.confirmations = [];
        trade.wait = {
          active: false,
          started_at: null,
          deadline_at: null,
          remaining_seconds: 0,
          paused: false,
          ended_at: null,
          end_reason: null,
        };
      }
      trade.updated_at = nowIso();
      trade.version += 1;
      addNotification(
        trade.buyer_id === accountId ? trade.seller_id : trade.buyer_id,
        "trade.agreement_decided",
        decision === "accept" ? "对方已同意交易约定，约定生效。" : "对方未同意交易约定。",
        { resource_type: "trade", resource_id: trade.id },
      );
      return { agreement, trade: tradeView(state, trade, accountId) };
    },
  },
  {
    method: "POST",
    pattern: ["trades", ":tradeId", "completion-confirmations"],
    handler: ({ accountId, params, body }) => {
      const trade = tradeById(params.tradeId);
      requireParticipant(trade, accountId);
      expectVersion(body, trade.version);
      if (trade.status !== "in_progress" || trade.phase !== "awaiting_completion") {
        fail(409, "STATE_CONFLICT", "当前阶段不能提交完成确认。");
      }
      const current = trade.agreements.find((item) => item.status === "effective");
      if (!current) fail(409, "STATE_CONFLICT", "尚未形成有效约定。");
      if (trade.confirmations.some((item) => item.confirmer_id === accountId)) {
        fail(409, "STATE_CONFLICT", "你已提交过完成确认。");
      }
      const confirmation = {
        id: nextId(state, "confirmations"),
        agreement_id: current.id,
        confirmer_id: accountId,
        note: optionalString(body, "note") ?? null,
        submitted_at: nowIso(),
      };
      trade.confirmations.push(confirmation);
      if (!trade.wait.active) {
        trade.wait = {
          active: true,
          started_at: confirmation.submitted_at,
          deadline_at: new Date(Date.now() + 7 * 86_400_000).toISOString(),
          remaining_seconds: 7 * 24 * 3600,
          paused: false,
          ended_at: null,
          end_reason: null,
        };
      }
      const both = ["buyer", "seller"].every((role) => {
        const id = role === "buyer" ? trade.buyer_id : trade.seller_id;
        return trade.confirmations.some(
          (item) => item.agreement_id === current.id && item.confirmer_id === id,
        );
      });
      if (both) {
        trade.status = "completed";
        trade.phase = null;
        trade.terminal_reason = "completed";
        trade.wait = {
          ...trade.wait,
          active: false,
          ended_at: nowIso(),
          end_reason: "both_confirmed",
        };
        const product = state.products.find((item) => item.id === trade.product_id);
        if (product) product.lifecycle_state = "off_shelf";
        const conversation = state.conversations.find(
          (item) => item.kind === "trade" && item.conversation_id === trade.trade_conversation_id,
        );
        if (conversation) conversation.archived_at = nowIso();
      }
      trade.updated_at = nowIso();
      trade.version += 1;
      addNotification(
        trade.buyer_id === accountId ? trade.seller_id : trade.buyer_id,
        "trade.completion_submitted",
        "对方已提交完成确认，请核对后提交你的确认。",
        { resource_type: "trade", resource_id: trade.id },
      );
      return { confirmation, trade: tradeView(state, trade, accountId) };
    },
  },
  {
    method: "POST",
    pattern: ["trades", ":tradeId", "cancellation-proposals"],
    handler: ({ accountId, params, body }) => {
      const trade = tradeById(params.tradeId);
      requireParticipant(trade, accountId);
      expectVersion(body, trade.version);
      if (trade.status !== "in_progress") {
        fail(409, "STATE_CONFLICT", "当前状态不能取消交易。");
      }
      const effective = trade.agreements.find((item) => item.status === "effective");
      const mode = effective || trade.buyer_id === accountId ? "direct" : "approval";
      const proposal = {
        id: nextId(state, "cancellations"),
        proposed_by: accountId,
        mode: mode as "direct" | "approval",
        reason: optionalString(body, "reason") ?? null,
        status: (mode === "direct" ? "accepted" : "pending") as "accepted" | "pending",
        proposed_at: nowIso(),
      };
      trade.cancellation = proposal;
      if (mode === "direct") {
        trade.status = "terminated";
        trade.terminal_reason = "cancelled";
        trade.phase = null;
        const product = state.products.find((item) => item.id === trade.product_id);
        if (product) product.lifecycle_state = "off_shelf";
      }
      trade.updated_at = nowIso();
      trade.version += 1;
      addNotification(
        trade.buyer_id === accountId ? trade.seller_id : trade.buyer_id,
        mode === "direct" ? "trade.cancelled" : "trade.cancellation_proposed",
        mode === "direct" ? "对方已取消交易。" : "对方提出取消交易，请回应。",
        { resource_type: "trade", resource_id: trade.id },
      );
      return { cancellation: proposal, trade: tradeView(state, trade, accountId) };
    },
  },
  {
    method: "POST",
    pattern: ["trades", ":tradeId", "cancellation-proposals", ":proposalId", "decisions"],
    handler: ({ accountId, params, body }) => {
      const trade = tradeById(params.tradeId);
      requireParticipant(trade, accountId);
      expectVersion(body, trade.version);
      const proposal = trade.cancellation;
      if (!proposal || proposal.id !== params.proposalId || proposal.status !== "pending") {
        fail(409, "STATE_CONFLICT", "该取消申请已处理。");
      }
      const decision = requireString(body, "decision") as DecisionKind;
      if (decision === "withdraw") {
        if (proposal.proposed_by !== accountId)
          fail(403, "ACTION_NOT_ALLOWED", "只有提出方可以撤回。");
        proposal.status = "withdrawn";
      } else if (decision === "reject") {
        if (proposal.proposed_by === accountId)
          fail(403, "ACTION_NOT_ALLOWED", "不能拒绝自己的申请。");
        proposal.status = "rejected";
      } else {
        if (proposal.proposed_by === accountId)
          fail(403, "ACTION_NOT_ALLOWED", "不能同意自己的申请。");
        proposal.status = "accepted";
        trade.status = "terminated";
        trade.terminal_reason = "cancelled";
        trade.phase = null;
        const product = state.products.find((item) => item.id === trade.product_id);
        if (product) product.lifecycle_state = "off_shelf";
      }
      trade.updated_at = nowIso();
      trade.version += 1;
      return { cancellation: proposal, trade: tradeView(state, trade, accountId) };
    },
  },
  {
    method: "POST",
    pattern: ["trades", ":tradeId", "disputes"],
    handler: ({ accountId, params, body }) => {
      const trade = tradeById(params.tradeId);
      requireParticipant(trade, accountId);
      expectVersion(body, trade.version);
      if (trade.dispute) fail(409, "STATE_CONFLICT", "已存在未结束的争议。");
      if (!trade.agreements.some((item) => item.status === "effective")) {
        fail(409, "STATE_CONFLICT", "尚未形成有效约定，不能发起争议。");
      }
      trade.dispute = {
        id: nextId(state, "disputes"),
        initiator_id: accountId,
        statement: requireString(body, "statement"),
        status: "open",
        opened_at: nowIso(),
        resolved_at: null,
      };
      trade.status = "disputed";
      trade.updated_at = nowIso();
      trade.version += 1;
      addNotification(
        trade.buyer_id === accountId ? trade.seller_id : trade.buyer_id,
        "trade.dispute_opened",
        "对方就本笔交易发起了争议。",
        { resource_type: "trade", resource_id: trade.id },
      );
      return { dispute: trade.dispute, trade: tradeView(state, trade, accountId) };
    },
  },
  {
    method: "POST",
    pattern: ["trades", ":tradeId", "disputes", ":disputeId", "resolution-confirmations"],
    handler: ({ accountId, params, body }) => {
      const trade = tradeById(params.tradeId);
      requireParticipant(trade, accountId);
      expectVersion(body, trade.version);
      if (!trade.dispute || trade.dispute.id !== params.disputeId) {
        fail(404, "RESOURCE_NOT_VISIBLE", "争议不存在。");
      }
      if (trade.dispute.status !== "resolved") {
        fail(409, "STATE_CONFLICT", "争议尚未由管理员处理完成。");
      }
      trade.dispute.status = "terminated";
      trade.dispute.resolved_at = nowIso();
      trade.status = "in_progress";
      trade.phase = trade.agreements.some((item) => item.status === "effective")
        ? "awaiting_completion"
        : "first_agreement_pending";
      trade.confirmations = [];
      trade.updated_at = nowIso();
      trade.version += 1;
      return { dispute: trade.dispute, trade: tradeView(state, trade, accountId) };
    },
  },
  {
    method: "GET",
    pattern: ["trades", ":tradeId", "reviews"],
    handler: ({ accountId, params }) => {
      const trade = tradeById(params.tradeId);
      requireParticipant(trade, accountId);
      const written = trade.reviews.find((item) => item.reviewer_id === accountId) ?? null;
      const received = trade.reviews.find((item) => item.reviewer_id !== accountId) ?? null;
      return {
        can_review: trade.status === "completed" && written === null,
        written: written ? reviewResponse(trade, written) : null,
        received: received ? reviewResponse(trade, received) : null,
      };
    },
  },
  {
    method: "POST",
    pattern: ["trades", ":tradeId", "reviews"],
    handler: ({ accountId, params, body }) => {
      const trade = tradeById(params.tradeId);
      requireParticipant(trade, accountId);
      if (trade.status !== "completed") {
        fail(409, "TRADE_NOT_COMPLETED", "交易完成后才可以评价。");
      }
      if (trade.reviews.some((item) => item.reviewer_id === accountId)) {
        fail(409, "REVIEW_ALREADY_SUBMITTED", "你已评价过本笔交易。");
      }
      const rating = requireNumber(body, "rating");
      if (rating < 1 || rating > 5) fail(422, "INPUT_INVALID", "评分需在 1—5 之间。");
      const content = requireString(body, "content").trim();
      if (content.length > 2000) fail(422, "INPUT_INVALID", "评价内容过长。");
      const review = {
        review_id: nextId(state, "reviews"),
        reviewer_id: accountId,
        rating,
        content,
        created_at: nowIso(),
        visible: true,
      };
      trade.reviews.push(review);
      return { review: reviewResponse(trade, review) };
    },
  },
  {
    method: "GET",
    pattern: ["me", "reviews"],
    handler: ({ accountId, query }) => {
      const direction = typeof query.direction === "string" ? query.direction : "written";
      const all = state.trades.flatMap((trade) =>
        trade.reviews
          .filter((review) =>
            direction === "written"
              ? review.reviewer_id === accountId
              : review.reviewer_id !== accountId &&
                (trade.buyer_id === accountId || trade.seller_id === accountId),
          )
          .map((review) => reviewResponse(trade, review)),
      );
      return paginate(all, query);
    },
  },

  /* -- conversations -- */
  {
    method: "GET",
    pattern: ["conversations"],
    handler: ({ accountId, query }) => {
      const entries = new Map<string, ReturnType<typeof buildBranch>[]>();
      for (const conversation of state.conversations) {
        if (conversation.kind === "case") continue;
        if (!conversation.participant_ids.includes(accountId)) continue;
        const peerId = conversation.participant_ids.find((id) => id !== accountId);
        if (!peerId) continue;
        const branch = buildBranch(conversation, accountId);
        const list = entries.get(peerId) ?? [];
        list.push(branch);
        entries.set(peerId, list);
      }
      const items = [...entries.entries()]
        .map(([peerId, branches]) => ({
          peer: (() => {
            const peer = accountRef(state, peerId);
            return {
              account_id: peerId,
              display_name: peer.display_name,
              avatar_url: peer.avatar_url,
            };
          })(),
          branches: branches.sort((left, right) =>
            (right.last_message_at ?? "").localeCompare(left.last_message_at ?? ""),
          ),
        }))
        .sort((left, right) =>
          (right.branches[0]?.last_message_at ?? "").localeCompare(
            left.branches[0]?.last_message_at ?? "",
          ),
        );
      return paginate(items, query);
    },
  },
  {
    method: "POST",
    pattern: ["conversations", "private"],
    handler: ({ accountId, body }) => {
      const target = requireString(body, "target_account_id");
      if (target === accountId) fail(422, "SELF_CONVERSATION_FORBIDDEN", "不能与自己建立会话。");
      accountById(target);
      const existing = state.conversations.find(
        (item) =>
          item.kind === "chat" &&
          item.participant_ids.includes(accountId) &&
          item.participant_ids.includes(target),
      );
      const conversation =
        existing ??
        (() => {
          const created = {
            conversation_id: nextId(state, "conversations"),
            kind: "chat" as const,
            participant_ids: [accountId, target],
            archived_at: null,
            created_at: nowIso(),
            source_ref: null,
          };
          state.conversations.push(created);
          return created;
        })();
      return {
        conversation_kind: "chat",
        conversation_id: conversation.conversation_id,
        peer: (() => {
          const peer = accountRef(state, target);
          return {
            account_id: target,
            display_name: peer.display_name,
            avatar_url: peer.avatar_url,
          };
        })(),
        reused: Boolean(existing),
      };
    },
  },
  {
    method: "GET",
    pattern: ["conversations", ":kind", ":conversationId", "messages"],
    handler: ({ accountId, params, query }) => {
      const kind = params.kind as ConversationKind;
      const conversation = conversationByKey(kind, params.conversationId);
      if (!conversation.participant_ids.includes(accountId)) {
        fail(404, "PARTICIPANT_REQUIRED", "会话不存在或当前不可查看。");
      }
      const all = messagesOf(kind, conversation.conversation_id);
      const limit = Math.min(asInt(query.limit, 30), 100);
      const beforeSeq = query.before_seq !== undefined ? Number(query.before_seq) : null;
      const afterSeq = query.after_seq !== undefined ? Number(query.after_seq) : null;
      let selected = all;
      if (beforeSeq !== null) selected = all.filter((item) => item.seq < beforeSeq);
      if (afterSeq !== null) selected = all.filter((item) => item.seq > afterSeq);
      const pageItems = afterSeq !== null ? selected.slice(0, limit) : selected.slice(-limit);
      return {
        items: pageItems.map((message) => ({
          message_id: message.message_id,
          seq: message.seq,
          sender: {
            account_id: message.sender_id,
            display_name: message.sender_id
              ? accountRef(state, message.sender_id).display_name
              : "系统",
            sender_kind: message.sender_kind,
          },
          message_type: message.message_type,
          body: message.body,
          created_at: message.created_at,
          event_type: null,
          source_ref: null,
        })),
        next_after_seq: pageItems.length ? pageItems[pageItems.length - 1].seq : null,
        next_before_seq: pageItems.length ? pageItems[0].seq : null,
        branch_status: conversation.archived_at ? "archived" : "active",
        trade_id: kind === "trade" ? conversation.source_ref?.resource_id : undefined,
      };
    },
  },
  {
    method: "POST",
    pattern: ["conversations", ":kind", ":conversationId", "messages"],
    handler: ({ accountId, params, body }) => {
      const kind = params.kind as ConversationKind;
      if (kind === "case") {
        fail(403, "MESSAGE_SEND_FORBIDDEN", "事项会话请使用事项线程接口。");
      }
      const conversation = conversationByKey(kind, params.conversationId);
      if (!conversation.participant_ids.includes(accountId)) {
        fail(404, "PARTICIPANT_REQUIRED", "会话不存在或当前不可查看。");
      }
      if (conversation.archived_at) {
        fail(409, "BRANCH_ARCHIVED", "该会话已归档，不能继续发送。");
      }
      const account = accountById(accountId);
      if (account.write_restricted) {
        fail(403, "MESSAGE_SEND_FORBIDDEN", "账户当前不能发送消息。");
      }
      const text = requireString(body, "body");
      const existing = messagesOf(kind, conversation.conversation_id);
      const seq = (existing[existing.length - 1]?.seq ?? 0) + 1;
      const timestamp = nowIso();
      state.messages.push({
        message_id: nextId(state, "messages"),
        conversation_id: conversation.conversation_id,
        kind,
        seq,
        sender_id: accountId,
        sender_kind: "user",
        message_type: "text",
        body: text,
        created_at: timestamp,
      });
      const progress = state.readProgress.find(
        (item) =>
          item.account_id === accountId &&
          item.kind === kind &&
          item.conversation_id === conversation.conversation_id,
      );
      if (progress) {
        progress.last_read_seq = seq;
        progress.updated_at = timestamp;
      } else {
        state.readProgress.push({
          account_id: accountId,
          kind,
          conversation_id: conversation.conversation_id,
          last_read_seq: seq,
          updated_at: timestamp,
        });
      }
      const peerId = conversation.participant_ids.find((id) => id !== accountId) ?? null;
      return {
        message_id: state.messages[state.messages.length - 1].message_id,
        seq,
        created_at: timestamp,
        sender: { account_id: accountId, display_name: account.display_name },
        unread_count: peerId ? unreadCount(state, peerId, kind, conversation.conversation_id) : 0,
      };
    },
  },
  {
    method: "POST",
    pattern: ["conversations", ":kind", ":conversationId", "read-progress"],
    handler: ({ accountId, params, body }) => {
      const kind = params.kind as ConversationKind;
      const conversation = conversationByKey(kind, params.conversationId);
      if (!conversation.participant_ids.includes(accountId)) {
        fail(404, "PARTICIPANT_REQUIRED", "会话不存在或当前不可查看。");
      }
      const displayed = requireNumber(body, "displayed_seq");
      const head = messagesOf(kind, conversation.conversation_id).reduce(
        (max, item) => Math.max(max, item.seq),
        0,
      );
      if (displayed < 0 || displayed > head) {
        fail(422, "INPUT_INVALID", "已读位置超出范围。");
      }
      const progress = state.readProgress.find(
        (item) =>
          item.account_id === accountId &&
          item.kind === kind &&
          item.conversation_id === conversation.conversation_id,
      );
      const timestamp = nowIso();
      if (progress) {
        progress.last_read_seq = Math.max(progress.last_read_seq, displayed);
        progress.updated_at = timestamp;
      } else {
        state.readProgress.push({
          account_id: accountId,
          kind,
          conversation_id: conversation.conversation_id,
          last_read_seq: displayed,
          updated_at: timestamp,
        });
      }
      return {
        last_read_seq: progress?.last_read_seq ?? displayed,
        unread_count: unreadCount(state, accountId, kind, conversation.conversation_id),
        updated_at: timestamp,
      };
    },
  },

  /* -- notifications -- */
  {
    method: "GET",
    pattern: ["account", "notifications"],
    handler: ({ accountId, query }) => {
      const filter = typeof query.read === "string" ? query.read : "all";
      const eventType = typeof query.event_type === "string" ? query.event_type : null;
      const mine = state.notifications
        .filter((item) => item.recipient_id === accountId)
        .filter((item) =>
          filter === "unread"
            ? item.read_at === null
            : filter === "read"
              ? item.read_at !== null
              : true,
        )
        .filter((item) => (eventType ? item.event_type === eventType : true))
        .sort((left, right) =>
          right.occurred_at === left.occurred_at
            ? Number(right.notification_id) - Number(left.notification_id)
            : right.occurred_at.localeCompare(left.occurred_at),
        );
      const page = paginate(mine, query);
      return {
        ...page,
        items: page.items.map(notificationSummary),
        unread_count: state.notifications.filter(
          (item) => item.recipient_id === accountId && item.read_at === null,
        ).length,
      };
    },
  },
  {
    method: "GET",
    pattern: ["account", "notifications", ":notificationId"],
    handler: ({ accountId, params }) => {
      const item = state.notifications.find(
        (candidate) =>
          candidate.notification_id === params.notificationId &&
          candidate.recipient_id === accountId,
      );
      if (!item) fail(404, "RESOURCE_NOT_VISIBLE", "通知不存在。");
      return { ...notificationSummary(item), body: item.body };
    },
  },
  {
    method: "PUT",
    pattern: ["account", "notifications", ":notificationId", "read"],
    handler: ({ accountId, params }) => {
      const item = state.notifications.find(
        (candidate) =>
          candidate.notification_id === params.notificationId &&
          candidate.recipient_id === accountId,
      );
      if (!item) fail(404, "RESOURCE_NOT_VISIBLE", "通知不存在。");
      if (!item.read_at) item.read_at = nowIso();
      return { notification_id: item.notification_id, read_at: item.read_at };
    },
  },

  /* -- aggregation -- */
  {
    method: "GET",
    pattern: ["account", "overview"],
    handler: ({ accountId }) => overview(state, accountId),
  },
  {
    method: "GET",
    pattern: ["account", "todos"],
    handler: ({ accountId, query }) => {
      const items = buildTodos(accountId);
      const page = paginate(items, query);
      const counts: Record<string, number> = {};
      for (const item of items) counts[item.kind] = (counts[item.kind] ?? 0) + 1;
      return { ...page, counts_by_kind: counts, as_of: nowIso() };
    },
  },
  {
    method: "GET",
    pattern: ["account", "resources"],
    handler: ({ accountId, query }) => {
      const kind = String(query.kind ?? "");
      if (kind === "product") {
        const items = state.products
          .filter((product) => product.seller_id === accountId)
          .map((product) => ({
            product_id: product.id,
            title: product.title,
            lifecycle_state: product.lifecycle_state,
            updated_at: product.updated_at,
          }));
        return { ...paginate(items, query), kind, as_of: nowIso() };
      }
      if (kind === "trade") {
        const role = typeof query.role === "string" ? query.role : "all";
        const items = state.trades
          .filter((trade) => trade.buyer_id === accountId || trade.seller_id === accountId)
          .filter((trade) =>
            role === "buying"
              ? trade.buyer_id === accountId
              : role === "selling"
                ? trade.seller_id === accountId
                : true,
          )
          .map((trade) => {
            const product = state.products.find((item) => item.id === trade.product_id);
            return {
              trade_id: trade.id,
              role: trade.buyer_id === accountId ? "buyer" : "seller",
              state: trade.status,
              updated_at: trade.updated_at,
              product_summary: product ? productSummary(product) : null,
            };
          });
        return { ...paginate(items, query), kind, as_of: nowIso() };
      }
      if (kind === "report") {
        const direction = typeof query.direction === "string" ? query.direction : "written";
        const items = state.cases
          .filter((item) => item.case_type === "report")
          .filter((item) =>
            direction === "written"
              ? item.reporter_id === accountId
              : item.reporter_id !== accountId &&
                item.related_ids.includes(accountId) &&
                item.decision_kind !== null,
          )
          .map((item) => ({
            case_id: item.case_id,
            direction,
            state: item.status,
            updated_at: item.updated_at,
            summary: item.reason_text ?? "事项处理中",
          }));
        return { ...paginate(items, query), kind, as_of: nowIso() };
      }
      if (kind === "evaluation") {
        const direction = typeof query.direction === "string" ? query.direction : "written";
        const items = state.trades.flatMap((trade) =>
          trade.reviews
            .filter((review) =>
              direction === "written"
                ? review.reviewer_id === accountId
                : review.reviewer_id !== accountId &&
                  (trade.buyer_id === accountId || trade.seller_id === accountId),
            )
            .map((review) => ({
              evaluation_id: review.review_id,
              trade_id: trade.id,
              direction,
              created_at: review.created_at,
              updated_at: review.created_at,
              content: review.visible ? review.content : null,
            })),
        );
        return { ...paginate(items, query), kind, as_of: nowIso() };
      }
      return { ...paginate([], query), kind, as_of: nowIso() };
    },
  },

  /* -- cases -- */
  {
    method: "POST",
    pattern: ["cases"],
    handler: ({ accountId, body }) => {
      const account = accountById(accountId);
      if (account.write_restricted) {
        fail(403, "ACCOUNT_WRITE_RESTRICTED", "账户当前限制提交举报。");
      }
      const target = body.target as { target_type?: string; target_id?: string } | undefined;
      if (!target?.target_type || !target.target_id) {
        fail(422, "TARGET_INVALID", "举报对象不完整。");
      }
      const duplicated = state.cases.find(
        (item) =>
          item.case_type === "report" &&
          item.reporter_id === accountId &&
          item.status !== "decided" &&
          item.target?.target_type === target.target_type &&
          item.target?.target_id === target.target_id,
      );
      if (duplicated) {
        duplicated.supplement_count += 1;
        duplicated.updated_at = nowIso();
        return { case_id: duplicated.case_id, case_status: duplicated.status, reused: true };
      }
      const caseId = nextId(state, "cases");
      const timestamp = nowIso();
      state.cases.push({
        case_id: caseId,
        case_type: "report",
        status: "pending",
        reporter_id: accountId,
        related_ids: [],
        manager_id: null,
        claimed_at: null,
        decision_kind: null,
        reason_text: requireString(body, "reason"),
        note: optionalString(body, "note") ?? null,
        archived_at: null,
        appeal_deadline_at: null,
        public_result_at: null,
        created_at: timestamp,
        updated_at: timestamp,
        supplement_count: Array.isArray(body.attachments) ? 0 : 0,
        thread_id: null,
        actions: [{ action_kind: "submit", occurred_at: timestamp, actor_kind: "reporter" }],
        enforcements: [],
        target: {
          target_type: target.target_type,
          target_id: String(target.target_id),
        },
        public_result: null,
      });
      return { case_id: caseId, case_status: "pending", reused: false };
    },
  },
  {
    method: "GET",
    pattern: ["cases"],
    handler: ({ accountId, query }) => {
      const scope = typeof query.scope === "string" ? query.scope : "mine";
      const status = typeof query.status === "string" ? query.status : null;
      const archived = query.archived !== undefined ? String(query.archived) === "true" : null;
      const items = state.cases
        .filter((item) =>
          scope === "mine" ? item.reporter_id === accountId : item.related_ids.includes(accountId),
        )
        .filter((item) => (status ? item.status === status : true))
        .filter((item) =>
          archived === null
            ? true
            : archived
              ? item.archived_at !== null
              : item.archived_at === null,
        )
        .sort((left, right) => right.updated_at.localeCompare(left.updated_at))
        .map((item) => ({
          case_id: item.case_id,
          scope,
          case_status: item.status,
          decision_kind: item.decision_kind,
          archived_at: item.archived_at,
          public_result_at: item.public_result_at,
          updated_at: item.updated_at,
          thread: item.thread_id
            ? { conversation_kind: "case" as const, conversation_id: item.thread_id }
            : null,
        }));
      return paginate(items, query);
    },
  },
  {
    method: "GET",
    pattern: ["cases", ":caseId"],
    handler: ({ accountId, params }) => caseForViewer(params.caseId, accountId),
  },
  {
    method: "POST",
    pattern: ["cases", ":caseId", "supplements"],
    handler: ({ accountId, params, body }) => {
      const item = caseForOwner(params.caseId, accountId);
      if (item.archived_at) fail(409, "CASE_CLOSED", "事项已结案，不能补充材料。");
      item.supplement_count += 1;
      item.updated_at = nowIso();
      item.actions.push({
        action_kind: "supplement",
        occurred_at: item.updated_at,
        actor_kind: "reporter",
      });
      if (optionalString(body, "note")) {
        item.note = `${item.note ?? ""}\n${optionalString(body, "note")}`.trim();
      }
      return {
        case_id: item.case_id,
        supplement_count: item.supplement_count,
        updated_at: item.updated_at,
      };
    },
  },
  {
    method: "POST",
    pattern: ["cases", ":caseId", "messages"],
    handler: ({ accountId, params, body }) => {
      const item = caseForParticipant(params.caseId, accountId);
      if (item.archived_at) fail(409, "CASE_CLOSED", "事项已结案，不能再发言。");
      const kind = requireString(body, "message_kind") as CaseMessage["message_kind"];
      if (kind === "appeal" && item.appeal_deadline_at) {
        if (new Date(item.appeal_deadline_at).getTime() < Date.now()) {
          fail(409, "CASE_APPEAL_WINDOW_ENDED", "申辩期已结束。");
        }
      }
      const thread = item.thread_id;
      if (!thread) fail(404, "PARTICIPANT_REQUIRED", "该事项没有可用的沟通线程。");
      const existing = messagesOf("case", thread);
      const seq = (existing[existing.length - 1]?.seq ?? 0) + 1;
      const timestamp = nowIso();
      const messageId = nextId(state, "messages");
      state.messages.push({
        message_id: messageId,
        conversation_id: thread,
        kind: "case",
        seq,
        sender_id: accountId,
        sender_kind: "user",
        message_type: kind,
        body: requireString(body, "body"),
        created_at: timestamp,
        case_message_kind: kind,
      });
      item.actions.push({ action_kind: kind, occurred_at: timestamp, actor_kind: "peer" });
      item.updated_at = timestamp;
      return {
        case_action_id: nextId(state, "caseActions"),
        case_message_id: messageId,
        seq,
        message_kind: kind,
        created_at: timestamp,
        thread: { conversation_kind: "case", conversation_id: thread },
      };
    },
  },
  {
    method: "GET",
    pattern: ["case-results"],
    handler: ({ query }) => {
      const items = state.cases
        .filter((item) => item.public_result !== null)
        .map((item) => item.public_result!)
        .sort((left, right) => right.published_at.localeCompare(left.published_at));
      return paginate(items, query);
    },
  },

  /* -- realtime recovery (polling fallbacks used by the resync path) -- */
  {
    method: "GET",
    pattern: ["account", "events", "head"],
    handler: () => ({
      epoch: "00000000-0000-4000-8000-000000000001",
      head_seq: 0,
      replay_floor: 0,
    }),
  },
  {
    method: "GET",
    pattern: ["account", "events"],
    handler: () => ({
      items: [],
      next_cursor: { epoch: "00000000-0000-4000-8000-000000000001", after_seq: 0 },
      head_seq: 0,
      has_more: false,
    }),
  },
];

/* ------------------------------------------------------- derived view helpers */

function buildBranch(
  conversation: MockState["conversations"][number],
  accountId: string,
): {
  conversation_kind: ConversationKind;
  conversation_id: string;
  source_ref: { resource_type: string; resource_id: string } | null;
  archived_at: string | null;
  unread_count: number;
  last_message_at: string | null;
  last_message_preview: string | null;
} {
  const messages = messagesOf(conversation.kind, conversation.conversation_id);
  const last = messages[messages.length - 1] ?? null;
  return {
    conversation_kind: conversation.kind,
    conversation_id: conversation.conversation_id,
    source_ref: conversation.source_ref,
    archived_at: conversation.archived_at,
    unread_count: unreadCount(state, accountId, conversation.kind, conversation.conversation_id),
    last_message_at: last?.created_at ?? null,
    last_message_preview: last ? last.body.slice(0, 40) : null,
  };
}

function notificationSummary(item: MockState["notifications"][number]): NotificationSummary {
  return {
    notification_id: item.notification_id,
    event_type: item.event_type,
    occurred_at: item.occurred_at,
    read_at: item.read_at,
    summary: item.summary,
    subject: item.subject,
    source: item.source,
  };
}

function reviewResponse(trade: MockTrade, review: MockTrade["reviews"][number]): TradeReview {
  const isBuyer = review.reviewer_id === trade.buyer_id;
  return {
    review_id: review.review_id,
    trade_id: trade.id,
    reviewer: accountRef(state, review.reviewer_id),
    reviewee: accountRef(state, isBuyer ? trade.seller_id : trade.buyer_id),
    rating: review.rating,
    content: review.content,
    visible: review.visible,
    created_at: review.created_at,
  };
}

function buildTodos(accountId: string): {
  todo_key: string;
  kind: string;
  source: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  summary: string;
}[] {
  const items: {
    todo_key: string;
    kind: string;
    source: Record<string, unknown>;
    created_at: string;
    updated_at: string;
    summary: string;
  }[] = [];
  for (const trade of state.trades) {
    const product = state.products.find((item) => item.id === trade.product_id);
    const title = product?.title ?? `交易 ${trade.id}`;
    if (trade.seller_id === accountId && trade.status === "pending_acceptance") {
      items.push({
        todo_key: `request_response:${accountId}:${trade.id}`,
        kind: "request_response",
        source: { trade_id: trade.id },
        created_at: trade.requested_at,
        updated_at: trade.requested_at,
        summary: `《${title}》有新的购买请求待处理`,
      });
    }
    const pending = trade.agreements.find((item) => item.status === "proposed");
    if (pending && pending.proposed_by !== accountId && trade.status === "in_progress") {
      items.push({
        todo_key: `agreement_response:${accountId}:${pending.id}`,
        kind: "agreement_response",
        source: { trade_id: trade.id, agreement_id: pending.id },
        created_at: pending.proposed_at,
        updated_at: pending.proposed_at,
        summary: `《${title}》的约定等待你回应`,
      });
    }
    const currentAgreement = trade.agreements.find((item) => item.status === "effective");
    const counterpartConfirmed = trade.confirmations.some(
      (item) =>
        item.agreement_id === currentAgreement?.id &&
        item.confirmer_id !== accountId &&
        (trade.buyer_id === accountId || trade.seller_id === accountId),
    );
    const selfConfirmed = trade.confirmations.some(
      (item) => item.confirmer_id === accountId && item.agreement_id === currentAgreement?.id,
    );
    if (counterpartConfirmed && !selfConfirmed && trade.status === "in_progress") {
      items.push({
        todo_key: `completion_response:${accountId}:${currentAgreement?.id}`,
        kind: "completion_response",
        source: { trade_id: trade.id },
        created_at: trade.updated_at,
        updated_at: trade.updated_at,
        summary: `《${title}》对方已提交完成确认，等待你确认`,
      });
    }
    if (
      trade.cancellation &&
      trade.cancellation.status === "pending" &&
      trade.cancellation.proposed_by !== accountId
    ) {
      items.push({
        todo_key: `cancellation_response:${accountId}:${trade.cancellation.id}`,
        kind: "cancellation_response",
        source: { trade_id: trade.id },
        created_at: trade.cancellation.proposed_at,
        updated_at: trade.cancellation.proposed_at,
        summary: `《${title}》对方提出取消交易`,
      });
    }
  }
  for (const item of state.cases) {
    if (item.archived_at) continue;
    if (!item.related_ids.includes(accountId) && item.reporter_id !== accountId) continue;
    if (
      item.thread_id &&
      messagesOf("case", item.thread_id).some((message) => message.message_type === "inquiry")
    ) {
      items.push({
        todo_key: `inquiry_response:${accountId}:${item.case_id}`,
        kind: "inquiry_response",
        source: { case_id: item.case_id, thread: item.thread_id },
        created_at: item.created_at,
        updated_at: item.updated_at,
        summary: "有管理问询等待你回复",
      });
    }
  }
  return items.sort((left, right) => right.updated_at.localeCompare(left.updated_at));
}

function caseForParticipant(caseId: string, accountId: string): MockCase {
  const item = state.cases.find((candidate) => candidate.case_id === caseId);
  if (
    !item ||
    (item.reporter_id !== accountId &&
      !item.related_ids.includes(accountId) &&
      item.manager_id !== accountId)
  ) {
    fail(404, "RESOURCE_NOT_VISIBLE", "事项不存在或当前不可查看。");
  }
  return item;
}

function caseForOwner(caseId: string, accountId: string): MockCase {
  const item = state.cases.find((candidate) => candidate.case_id === caseId);
  if (!item || item.reporter_id !== accountId) {
    fail(404, "NOT_CASE_PARTICIPANT", "事项不存在或当前不可查看。");
  }
  return item;
}

function caseForViewer(caseId: string, accountId: string): CaseDetail {
  const item = caseForParticipant(caseId, accountId);
  const detail = caseDetail(item);
  // A reporter must not read the opposite party's thread or appeal content.
  if (item.reporter_id === accountId) detail.appeal_deadline_at = null;
  return detail;
}

/* -------------------------------------------------------------------- router */

function matchRoute(
  method: HttpMethod,
  segments: string[],
): { route: Route; params: Record<string, string> } | null {
  for (const route of routes) {
    if (route.method !== method) continue;
    if (route.pattern.length !== segments.length) continue;
    const params: Record<string, string> = {};
    let matched = true;
    for (let index = 0; index < route.pattern.length; index += 1) {
      const token = route.pattern[index];
      const segment = segments[index];
      if (token.startsWith(":")) {
        params[token.slice(1)] = decodeURIComponent(segment);
        continue;
      }
      if (token !== segment) {
        matched = false;
        break;
      }
    }
    if (matched) return { route, params };
  }
  return null;
}

/**
 * Answer one simulated request. Rejects with {@link ApiError} for every failure
 * the real endpoint would report and with {@link AbortedError} on cancellation.
 */
export async function handleMockRequest(
  method: HttpMethod,
  path: string,
  options: RequestOptions,
): Promise<unknown> {
  await Promise.resolve();
  if (options.signal?.aborted) throw new AbortedError();

  const cleanPath = path.split("?")[0].replace(/^\/+|\/+$/g, "");
  const segments = cleanPath ? cleanPath.split("/") : [];
  const match = matchRoute(method, segments);
  if (!match) {
    throw new ApiError(404, "RESOURCE_NOT_VISIBLE", `模拟数据源未提供该接口：${method} ${path}`);
  }

  const { route, params } = match;
  const accountId = currentAccountId();
  if (!route.anonymous && !accountId) {
    throw new ApiError(401, "AUTHENTICATION_REQUIRED", "请先登录。");
  }

  // Session endpoints are not idempotency scoped: replaying a cached login answer
  // would leave the client signed in as the previous account.
  const cacheable = !(cleanPath === "account/session");
  const cacheKey =
    cacheable && options.idempotencyKey ? `${method} ${cleanPath} ${options.idempotencyKey}` : null;
  if (cacheKey && state.idempotency.has(cacheKey)) {
    return state.idempotency.get(cacheKey);
  }

  const context: RouteContext = {
    method,
    params,
    query: (options.query as Record<string, unknown> | undefined) ?? {},
    body: (options.body as Record<string, unknown> | undefined) ?? {},
    options,
    accountId: accountId ?? "",
  };
  const result = route.handler(context);
  if (cacheKey) state.idempotency.set(cacheKey, result);
  return result;
}
