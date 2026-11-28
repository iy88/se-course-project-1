import type { Page, Route, WebSocketRoute } from "@playwright/test";

import type {
  ManagementTodoItem,
  ManagementTodoPage,
  ReviewDecisionRequest,
  ReviewDetail,
} from "../../admin-web/src/api/contracts";
import type {
  AccountProfile,
  BannedScopeView,
  CategoryView,
  CurrentIdentity,
  EntryContext,
  ProductDetail,
  ProductSummary,
} from "../../user-web/src/api/contracts";
import type { TradeView } from "../../user-web/src/api/trade-contracts";

const ENTRY_TOKEN = "entry-csrf-token";
const NOW = "2026-03-01T09:00:00Z";
const FUTURE = "2030-01-01T00:00:00Z";

function buyerAccount(): AccountProfile {
  return {
    account_id: "100",
    email: "buyer@campus.test",
    display_name: "林小满",
    roles: ["user"],
    avatar_url: null,
  };
}

export function sellerAccount(): AccountProfile {
  return {
    account_id: "200",
    email: "seller@campus.test",
    display_name: "陈师兄",
    roles: ["user"],
    avatar_url: null,
  };
}

export function adminAccount(): AccountProfile {
  return {
    account_id: "1",
    email: "admin@campus.test",
    display_name: "管理员小周",
    roles: ["manager"],
    avatar_url: null,
  };
}

function productFixture(overrides: Partial<ProductDetail> = {}): ProductDetail {
  return {
    id: "1001",
    title: "九成新机械键盘",
    description: "自用一年，轴体正常，附原装键帽和包装盒。",
    price_cents: 12900,
    images: [],
    categories: [{ id: "10", name: "数码" }],
    seller: { id: "200", display_name: "陈师兄", avatar_url: null },
    lifecycle_state: "public",
    content_version: 4,
    created_at: NOW,
    updated_at: NOW,
    pending_review: null,
    latest_review: null,
    display_restrictions: [],
    permissions: null,
    category_application: null,
    ...overrides,
  };
}

function productSummary(product: ProductDetail): ProductSummary {
  return {
    id: product.id,
    title: product.title,
    price_cents: product.price_cents,
    thumbnail: null,
    categories: product.categories,
    seller: product.seller,
    created_at: product.created_at,
  };
}

function pendingTradeFixture(): TradeView {
  return {
    id: "2001",
    product: { id: "1001", title: "九成新机械键盘", price_cents: 12900 },
    buyer: { id: "100", display_name: "林小满", avatar_url: null },
    seller: { id: "200", display_name: "陈师兄", avatar_url: null },
    status: "pending_acceptance",
    phase: null,
    terminal_reason: null,
    request: {
      note: "今晚六点自提",
      requested_at: NOW,
      responded_at: null,
      close_reason: null,
    },
    agreement: { current: null, pending: null },
    confirmations: { current: [], both_current: false },
    wait: {
      active: false,
      started_at: null,
      deadline_at: null,
      remaining_seconds: 0,
      paused: false,
      ended_at: null,
      end_reason: null,
    },
    freeze: { active: false, items: [] },
    cancellation: { pending: null },
    dispute: { open: null },
    trade_conversation_id: null,
    version: 3,
    permissions: { allowed_actions: ["accept", "reject"] },
    created_at: NOW,
    updated_at: NOW,
    agreement_history: [],
    confirmation_history: [],
    state_history: [],
  };
}

function reviewFixture(): ReviewDetail {
  return {
    audit_id: "9001",
    product_id: "1001",
    case_id: "7001",
    status: "pending",
    submitted_at: NOW,
    seller: { id: "200", display_name: "陈师兄" },
    claim: { manager_id: "1", claimed_at: NOW },
    current_content: {
      title: "九成新机械键盘",
      description: "自用一年，轴体正常，附原装键帽和包装盒。",
      images: [],
      price_cents: 12900,
      categories: [{ id: "10", name: "数码" }],
      content_version: 4,
    },
    category_application: {
      application_id: "app-1",
      proposed_name: "键盘外设",
      status: "pending",
    },
    banned_scope: [
      { id: "banned-1", group: "service_promotion", content: "代写作业" },
      { id: "banned-2", group: "legal_prohibited", content: "伪造证件" },
    ],
    review_result: null,
  };
}

function queueFixture(): ManagementTodoItem {
  return {
    case_id: "7001",
    kind: "product_review",
    case_type: "product_review",
    decision_kind: null,
    manager_id: null,
    completed_at: null,
    created_at: NOW,
    updated_at: NOW,
    summary: {
      audit_id: "9001",
      product_id: "1001",
      title: "九成新机械键盘",
    },
  };
}

interface MockSession {
  account: AccountProfile;
  signedIn: boolean;
}

interface Deferred<T> {
  readonly promise: Promise<T>;
  resolve(value: T): void;
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

interface HeldRequest {
  readonly reached: Promise<void>;
  readonly settled: Promise<void>;
  release(): void;
}

interface RequestHold {
  operation: string;
  matches: (url: URL) => boolean;
  reached: Deferred<void>;
  released: Deferred<void>;
  settled: Deferred<void>;
}

interface NetworkFailure {
  operation: string;
  matches: (url: URL) => boolean;
}

interface RealtimeConnection {
  readonly socket: WebSocketRoute;
  readonly frames: Record<string, unknown>[];
}

export class MockRealtime {
  readonly connections: RealtimeConnection[] = [];

  async install(page: Page): Promise<void> {
    await page.routeWebSocket("**/api/v1/realtime", (socket) => {
      const connection: RealtimeConnection = { socket, frames: [] };
      this.connections.push(connection);
      socket.onMessage((message) => {
        const frame = JSON.parse(String(message)) as Record<string, unknown>;
        connection.frames.push(frame);
        if (frame.type === "hello") {
          socket.send(
            JSON.stringify({
              type: "hello_ok",
              epoch: "epoch-e2e",
              head_seq: 0,
              replay_floor: 0,
              heartbeat_seconds: 60,
            }),
          );
        } else if (frame.type === "ping") {
          socket.send(JSON.stringify({ type: "pong", nonce: frame.nonce }));
        }
      });
    });
  }

  async disconnect(index = this.connections.length - 1, code = 1006): Promise<void> {
    const connection = this.connections[index];
    if (!connection) throw new Error(`No realtime connection at index ${index}`);
    await connection.socket.close({ code, reason: "E2E network drop" });
  }

  emitEvent(accountSeq: number, eventType = "notification_created"): void {
    const connection = this.connections[this.connections.length - 1];
    if (!connection) throw new Error("No active realtime connection");
    connection.socket.send(
      JSON.stringify({
        type: "event",
        epoch: "epoch-e2e",
        event_id: `event-${accountSeq}`,
        account_seq: accountSeq,
        schema_version: 1,
        occurred_at: NOW,
        event_type: eventType,
        data: { notification_id: String(accountSeq) },
      }),
    );
  }
}

export class MockApi {
  readonly requests: string[] = [];
  readonly unhandled: string[] = [];
  readonly entryToken = ENTRY_TOKEN;
  readonly realtime = new MockRealtime();

  private readonly primarySession: MockSession = {
    account: buyerAccount(),
    signedIn: false,
  };

  private readonly products = new Map<string, ProductDetail>([["1001", productFixture()]]);
  private trade = pendingTradeFixture();
  private review = reviewFixture();
  private claimed = false;
  private readonly holds: RequestHold[] = [];
  private readonly networkFailures: NetworkFailure[] = [];

  unreadCount = 2;

  get account(): AccountProfile {
    return this.primarySession.account;
  }

  set account(account: AccountProfile) {
    this.primarySession.account = account;
  }

  get signedIn(): boolean {
    return this.primarySession.signedIn;
  }

  set signedIn(signedIn: boolean) {
    this.primarySession.signedIn = signedIn;
  }

  async install(page: Page, baseURL: string): Promise<void> {
    await this.installSession(page, baseURL, this.primarySession);
  }

  async installAs(page: Page, baseURL: string, session: Partial<MockSession>): Promise<void> {
    await this.installSession(page, baseURL, {
      account: session.account ?? this.account,
      signedIn: session.signedIn ?? this.signedIn,
    });
  }

  private async installSession(
    page: Page,
    baseURL: string,
    pageSession: MockSession,
  ): Promise<void> {
    await this.realtime.install(page);
    await page.route("**/*", async (route) => {
      const url = new URL(route.request().url());
      if (url.origin !== baseURL) {
        await route.abort("blockedbyclient");
      } else if (url.pathname.startsWith("/api/v1/")) {
        await this.handle(route, url, pageSession);
      } else {
        await route.continue();
      }
    });
  }

  holdNext(operation: string, matches: (url: URL) => boolean = () => true): HeldRequest {
    const hold: RequestHold = {
      operation,
      matches,
      reached: deferred(),
      released: deferred(),
      settled: deferred(),
    };
    this.holds.push(hold);
    return {
      reached: hold.reached.promise,
      settled: hold.settled.promise,
      release: () => hold.released.resolve(),
    };
  }

  failNext(operation: string, matches: (url: URL) => boolean = () => true): void {
    this.networkFailures.push({ operation, matches });
  }

  private identity(account: AccountProfile): CurrentIdentity {
    return {
      account,
      session: { session_id: "session-test", issued_at: NOW, absolute_expires_at: FUTURE },
    };
  }

  private sessionHeaders(): Record<string, string> {
    return {
      "Set-Cookie": `__Host-se_csrf=${ENTRY_TOKEN}; Path=/; Secure; SameSite=Lax`,
    };
  }

  private async handle(route: Route, url: URL, session: MockSession): Promise<void> {
    const request = route.request();
    const operation = `${request.method()} ${url.pathname.slice("/api/v1".length)}`;
    this.requests.push(operation);

    const failureIndex = this.networkFailures.findIndex(
      (failure) => failure.operation === operation && failure.matches(url),
    );
    if (failureIndex >= 0) {
      this.networkFailures.splice(failureIndex, 1);
      await route.abort("internetdisconnected");
      return;
    }

    const holdIndex = this.holds.findIndex(
      (candidate) => candidate.operation === operation && candidate.matches(url),
    );
    const hold = holdIndex >= 0 ? this.holds.splice(holdIndex, 1)[0] : null;
    if (hold) {
      hold.reached.resolve();
      await hold.released.promise;
    }

    try {
      await this.handleOperation(route, url, session);
    } catch (error) {
      await route.fulfill({
        status: 500,
        json: {
          error: {
            code: "MOCK_HANDLER_FAILED",
            message: error instanceof Error ? error.message : String(error),
          },
        },
      });
    } finally {
      hold?.settled.resolve();
    }
  }

  private async handleOperation(route: Route, url: URL, session: MockSession): Promise<void> {
    const request = route.request();
    const operation = `${request.method()} ${url.pathname.slice("/api/v1".length)}`;

    switch (operation) {
      case "GET /account/session":
        return session.signedIn
          ? route.fulfill({ headers: this.sessionHeaders(), json: this.identity(session.account) })
          : route.fulfill({
              status: 401,
              json: { error: { code: "AUTHENTICATION_REQUIRED", message: "请先登录。" } },
            });
      case "POST /account/session":
        if (request.postDataJSON().password === "wrong-password") {
          return route.fulfill({
            status: 401,
            json: { error: { code: "CREDENTIALS_INVALID", message: "邮箱或密码不正确。" } },
          });
        }
        session.signedIn = true;
        return route.fulfill({
          headers: this.sessionHeaders(),
          json: this.identity(session.account),
        });
      case "DELETE /account/session":
        session.signedIn = false;
        return route.fulfill({ status: 204 });
      case "GET /account/entry-context":
        return route.fulfill({
          json: {
            csrf_token: ENTRY_TOKEN,
            expires_at: FUTURE,
            limits: {
              email_code_length: 6,
              code_ttl_seconds: 600,
              resend_interval_seconds: 60,
              password_min_length: 8,
              password_max_length: 72,
              display_name_max_length: 24,
            },
          } satisfies EntryContext,
        });
      case "GET /account/events/head":
        return route.fulfill({
          json: { epoch: "epoch-e2e", head_seq: 0, replay_floor: 0 },
        });
      case "GET /account/notifications":
        return route.fulfill({
          json: {
            items: [],
            page: 1,
            page_size: 1,
            total: 0,
            unread_count: this.unreadCount,
          },
        });
      case "GET /account/overview":
        return route.fulfill({
          json: {
            as_of: NOW,
            products: { total: 1, by_state: { public: 1 } },
            trades: { total: 0, buying: 0, selling: 0, by_state: {} },
            favorites: { total: 0, valid: 0, invalid: 0 },
            evaluations: { written: 0, received: 0 },
            reports: { submitted: 0, received: 0 },
            todo_count: 0,
          },
        });
      case "GET /categories":
        return route.fulfill({
          json: {
            items: [
              {
                id: "10",
                main_name: "数码",
                aliases: ["电子产品"],
                selectable: true,
                has_public_products: true,
              },
            ] satisfies CategoryView[],
          },
        });
      case "GET /banned-items":
        return route.fulfill({
          json: {
            updated_at: NOW,
            groups: [
              {
                group: "service_promotion",
                items: [{ id: "banned-1", content: "代写作业", display_order: 1 }],
              },
            ],
          } satisfies BannedScopeView,
        });
      case "GET /files/upload-capabilities":
        return route.fulfill({
          json: {
            rule_version: "e2e-v1",
            purposes: {
              product_image: {
                max_bytes: 10 * 1024 * 1024,
                allowed_content_types: ["image/jpeg", "image/png"],
              },
              case_evidence: {
                max_bytes: 10 * 1024 * 1024,
                allowed_content_types: ["image/jpeg", "image/png"],
              },
              account_avatar: {
                max_bytes: 5 * 1024 * 1024,
                allowed_content_types: ["image/jpeg", "image/png"],
              },
            },
            upload_ttl_seconds: 600,
            read_url_ttl_seconds: 600,
          },
        });
      case "GET /products": {
        const keyword = url.searchParams.get("keyword");
        let products = [...this.products.values()].map(productSummary);
        if (keyword === "old") {
          products = [productSummary(productFixture({ id: "3001", title: "旧搜索结果" }))];
        } else if (keyword === "new") {
          products = [productSummary(productFixture({ id: "3002", title: "新搜索结果" }))];
        }
        return route
          .fulfill({
            json: { items: products, page: 1, page_size: 20, total: products.length },
          })
          .catch(() => undefined);
      }
      case "POST /products": {
        const payload = request.postDataJSON() as {
          title: string;
          description: string;
          price_cents: number;
          category_ids: string[];
          image_file_ids: string[];
          category_application?: { proposed_name: string };
        };
        const created = productFixture({
          id: "1002",
          title: payload.title,
          description: payload.description,
          price_cents: payload.price_cents,
          categories: [{ id: "10", name: "数码" }],
          seller: {
            id: session.account.account_id,
            display_name: session.account.display_name,
            avatar_url: session.account.avatar_url ?? null,
          },
          lifecycle_state: "pending_review",
          content_version: 1,
          pending_review: { audit_id: "9002", case_id: "7002", submitted_at: NOW },
          permissions: {
            can_edit: true,
            can_off_shelf: false,
            can_relist: false,
            can_withdraw_review: true,
            can_submit_review: false,
          },
        });
        this.products.set(created.id, created);
        return route.fulfill({ status: 201, json: created });
      }
      case "GET /products/1001":
      case "GET /products/1002": {
        const product = this.products.get(operation.slice("GET /products/".length));
        if (!product) break;
        return route.fulfill({ json: product });
      }
      case "GET /products/1001/comments":
      case "GET /products/1002/comments":
        return route.fulfill({ json: { items: [], page: 1, page_size: 20, total: 0 } });
      case "GET /me/favorites/1001":
        return route.fulfill({ json: { favorited: false, valid: true, favorited_at: null } });
      case "POST /products/1001/purchase-requests":
        this.trade = {
          ...this.trade,
          request: { requested_at: NOW, note: request.postDataJSON().note },
          version: 1,
          permissions: { allowed_actions: ["withdraw"] },
        };
        return route.fulfill({ status: 201, json: this.trade });
      case "GET /trades/2001":
        return route.fulfill({ json: this.tradeFor(session.account) });
      case "POST /trades/2001/accept": {
        const expectedVersion = request.postDataJSON().expected_version;
        if (expectedVersion !== this.trade.version) {
          return route.fulfill({
            status: 409,
            json: {
              error: { code: "VERSION_CONFLICT", message: "会话状态已更新，请刷新后重试。" },
            },
          });
        }
        this.trade = {
          ...this.trade,
          status: "in_progress",
          phase: "first_agreement_pending",
          request: { ...this.trade.request, responded_at: NOW },
          version: this.trade.version + 1,
          permissions: {
            allowed_actions: ["propose_agreement", "propose_cancellation", "open_dispute"],
          },
        };
        return route.fulfill({ json: this.trade });
      }
      case "GET /management/todos": {
        const items = this.claimed ? [] : [queueFixture()];
        const result: ManagementTodoPage = {
          items,
          page: 1,
          page_size: 20,
          total: items.length,
          counts_by_kind: { product_review: items.length },
          as_of: NOW,
        };
        return route.fulfill({ json: result });
      }
      case "GET /admin/categories":
        return route.fulfill({ json: { items: [], page: 1, page_size: 100, total: 0 } });
      case "POST /admin/cases/7001/claim":
        this.claimed = true;
        return route.fulfill({
          json: {
            case_id: this.review.case_id,
            case_status: "claimed",
            claimed_manager_id: this.account.account_id,
            claimed_at: NOW,
            already_claimed: false,
          },
        });
      case "GET /admin/product-reviews/9001":
        if (this.claimed) return route.fulfill({ json: this.review });
        break;
      case "POST /admin/product-reviews/9001/decision": {
        const payload: ReviewDecisionRequest = request.postDataJSON();
        const version = this.review.current_content.content_version;
        this.review = {
          ...this.review,
          status: "rejected",
          category_application: {
            application_id: "app-1",
            proposed_name: "键盘外设",
            status: "rejected",
          },
          review_result: {
            decision: payload.decision,
            reason: payload.reason ?? null,
            reviewed_content_version: version,
            decided_at: NOW,
            decided_by: this.account.account_id,
          },
        };
        return route.fulfill({
          json: {
            audit_id: this.review.audit_id,
            status: this.review.status,
            case_id: this.review.case_id,
            case_status: "decided",
            product: {
              id: this.review.product_id,
              lifecycle_state: "review_rejected",
              content_version: version,
            },
          },
        });
      }
    }

    this.unhandled.push(operation);
    await route.fulfill({
      status: 501,
      json: { error: { code: "UNMOCKED_REQUEST", message: operation } },
    });
  }

  private tradeFor(account: AccountProfile): TradeView {
    if (this.trade.status !== "pending_acceptance") return this.trade;
    const actions: TradeView["permissions"]["allowed_actions"] =
      account.account_id === this.trade.seller.id ? ["accept", "reject"] : ["withdraw"];
    return {
      ...this.trade,
      permissions: { allowed_actions: actions },
    };
  }
}
