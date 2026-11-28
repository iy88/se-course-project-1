/*
 * Provisional frontend contracts.
 *
 * These types mirror the agreed interface design in
 * docs/design/detailed-design/interfaces/*.md for the endpoints this work
 * package consumes. `frontend/shared/openapi.json` currently publishes only the
 * connectivity probe, so the types below are hand-written and will be replaced
 * by the generated `operations[...]` lookups in `frontend/shared/api-types.ts`
 * once each provider publishes its own OpenAPI entries.
 *
 * Field naming follows the shared conventions: JSON snake_case, ids are decimal
 * strings, money is integer cents, timestamps are UTC ISO 8601.
 */

/** C1 error envelope returned by every `/api/v1` endpoint. */
export interface ErrorEnvelope {
  error: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
  };
  request_id: string;
  operation_id?: string | null;
}

export interface Page<TItem> {
  items: TItem[];
  page: number;
  page_size: number;
  total: number;
}

/** Reference to an owning object, used by files, notifications and cases. */
export interface ResourceRef {
  resource_type: string;
  resource_id: string;
}

/* ------------------------------------------------------------------ account */

export type AccountRole = "user" | "manager";

export interface AccountProfile {
  account_id: string;
  display_name: string;
  email: string;
  roles: AccountRole[];
  write_restricted?: boolean;
  avatar_url?: string | null;
}

export interface SessionInfo {
  session_id: string;
  issued_at: string;
  absolute_expires_at: string;
}

/** API-COM-AUTH-001 `GET /account/session`. */
export interface CurrentIdentity {
  account: AccountProfile;
  session: SessionInfo;
}

/** API-COM-AUTH-003 `GET /account/entry-context`. */
export interface EntryContext {
  csrf_token: string;
  expires_at: string;
  limits: EntryLimits;
}

export interface EntryLimits {
  email_code_length: number;
  code_ttl_seconds: number;
  resend_interval_seconds: number;
  password_min_length: number;
  password_max_length: number;
  display_name_max_length: number;
}

export type VerificationPurpose =
  | "registration"
  | "password_reset"
  | "email_change"
  /** Ticket for the current mailbox in an email change; pairs with `email_change_new`. */
  | "email_change_old"
  /** Ticket for the new mailbox in an email change. */
  | "email_change_new";

/** API-COM-MAIL-001 `POST /account/email-verifications`. */
export interface EmailVerificationRequest {
  purpose: VerificationPurpose;
  email: string;
}

export interface EmailVerificationTicket {
  verification_id: string;
  purpose: VerificationPurpose;
  expires_at: string;
}

export interface EmailVerificationAccepted {
  purpose: VerificationPurpose;
  requests: EmailVerificationTicket[];
  retry_after_seconds: number;
}

export interface RegisterRequest {
  email: string;
  display_name: string;
  password: string;
  verification_id: string;
  code: string;
}

export interface RegisterResult {
  account_id: string;
  email: string;
  display_name: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface ChangePasswordRequest {
  current_password: string;
  new_password: string;
}

export interface ResetPasswordRequest {
  verification_id: string;
  code: string;
  new_password: string;
}

export interface ChangeEmailRequest {
  new_email: string;
  old_verification_id: string;
  old_code: string;
  new_verification_id: string;
  new_code: string;
}

/**
 * API-COM-AUTH-009 `PATCH /account/profile` (design 0.2.6, renamed to
 * 修改个人资料). At least one field must be sent and an omitted field keeps its
 * current value. An explicit `avatar_file_id: null` removes the avatar; a
 * non-empty positive file id attaches a verified `account_avatar`; `"0"` is
 * rejected as `INPUT_INVALID`.
 */
export interface UpdateProfileRequest {
  display_name?: string;
  /**
   * Avatar binding: a verified `account_avatar` file id replaces the avatar, an
   * explicit `null` removes it, and omitting the field keeps the current avatar.
   */
  avatar_file_id?: string | null;
}

export interface UpdateProfileResult {
  account_id: string;
  display_name: string;
  /** Short-lived signed URL for the current avatar; null shows the default. */
  avatar_url: string | null;
}

/* -------------------------------------------------------------------- files */

export type FilePurpose = "product_image" | "case_evidence" | "account_avatar";

export interface FilePurposeRule {
  max_bytes: number;
  allowed_content_types: string[];
}

/** API-COM-FILE-003 `GET /files/upload-capabilities`. */
export interface UploadCapabilities {
  rule_version: string;
  purposes: Record<FilePurpose, FilePurposeRule>;
  upload_ttl_seconds: number;
  read_url_ttl_seconds: number;
}

/** API-COM-FILE-001 `POST /files/uploads`. */
export interface CreateUploadRequest {
  purpose: FilePurpose;
  declared_size: number;
  declared_content_type: string;
  /** Omitted when the server derives the target from the session or the upload is staged. */
  target?: ResourceRef | null;
}

export interface CreateUploadResult {
  file_id: string;
  state: "uploading";
  expires_at: string;
  upload: {
    method: "POST";
    url: string;
    fields: Record<string, string>;
  };
  limits: FilePurposeRule;
}

/** API-COM-FILE-002 `POST /files/{file_id}/completion`. */
export interface CompleteUploadResult {
  file_id: string;
  purpose: FilePurpose;
  state: "verified";
  verified_at: string;
  metadata: {
    size_bytes: number;
    content_type: string;
  };
}

/* ------------------------------------------------------------------ catalog */

export interface SignedImage {
  file_id: string;
  url: string;
  expires_at: string;
}

export interface CategoryView {
  id: string;
  main_name: string;
  aliases: string[];
  selectable: boolean;
  has_public_products: boolean;
}

export interface SellerRef {
  id: string;
  display_name: string;
  avatar_url?: string | null;
}

export interface CategoryRef {
  id: string;
  name: string;
}

/** `ProductSummary` used by search results and aggregation lists. */
export interface ProductSummary {
  id: string;
  title: string;
  price_cents: number;
  thumbnail: SignedImage | null;
  categories: CategoryRef[];
  seller: SellerRef;
  created_at: string;
}

export type ProductLifecycle =
  | "pending_review"
  | "review_rejected"
  | "public"
  | "in_trade"
  | "off_shelf";

export type ReviewStatus = "pending" | "passed" | "rejected" | "withdrawn";

export interface PendingReviewRef {
  audit_id: string;
  case_id: string;
  submitted_at: string;
}

export interface LatestReviewRef {
  audit_id: string;
  status: ReviewStatus;
  reason?: string | null;
  decided_at?: string | null;
}

export interface DisplayRestriction {
  source_type: string;
  reason: string;
  created_at: string;
  released_at?: string | null;
}

export interface CategoryApplicationRef {
  id: string;
  proposed_name: string;
  status: "pending";
}

export interface ProductPermissions {
  can_edit: boolean;
  can_off_shelf: boolean;
  can_relist: boolean;
  can_withdraw_review: boolean;
  can_submit_review: boolean;
}

/** `ProductDetail` — the seller-facing projection adds the optional blocks. */
export interface ProductDetail {
  id: string;
  title: string;
  description: string;
  price_cents: number;
  images: SignedImage[];
  categories: CategoryRef[];
  seller: SellerRef;
  lifecycle_state: ProductLifecycle;
  content_version: number;
  created_at: string;
  updated_at: string;
  pending_review?: PendingReviewRef | null;
  latest_review?: LatestReviewRef | null;
  display_restrictions?: DisplayRestriction[] | null;
  permissions?: ProductPermissions | null;
  category_application?: CategoryApplicationRef | null;
}

export interface CategoryApplicationInput {
  proposed_name: string;
}

export interface CreateProductRequest {
  title: string;
  description: string;
  image_file_ids: string[];
  price_cents: number;
  category_ids: string[];
  category_application?: CategoryApplicationInput;
}

export interface UpdateProductRequest {
  title?: string;
  description?: string;
  image_file_ids?: string[];
  price_cents?: number;
  category_ids?: string[];
  category_application?: CategoryApplicationInput;
  expected_version: number;
}

export interface SearchProductsQuery {
  keyword?: string;
  category_ids?: string[];
  min_price_cents?: number;
  max_price_cents?: number;
  page?: number;
  page_size?: number;
}

export interface ProductEditSnapshot {
  edit_id: string;
  edited_at: string;
  operator_kind: string;
  edit_kind: string;
  before_content: Record<string, unknown>;
  after_content: Record<string, unknown>;
  reason?: string | null;
}

export type CommentStatus = "published" | "deleted_by_author" | "removed_by_admin";

export interface CommentAuthor {
  id: string;
  display_name: string;
  avatar_url?: string | null;
}

/** One product comment or seller reply; replies only appear on top-level comments. */
export interface CommentView {
  id: string;
  product_id: string;
  author: CommentAuthor;
  body?: string | null;
  status: CommentStatus;
  reply_to_comment_id?: string | null;
  created_at: string;
  replies?: CommentView[];
}

export interface CommentPage extends Page<CommentView> {}

export type FavoriteItemStatus = "valid" | "invalid";

/** A favourite in the personal list; an invalid item never carries product content. */
export interface FavoriteItem {
  product_id: string;
  status: FavoriteItemStatus;
  favorited_at: string;
  product?: ProductSummary | null;
  message?: string | null;
}

export interface FavoritePage extends Page<FavoriteItem> {}

export interface FavoriteStatus {
  favorited: boolean;
  valid: boolean;
  favorited_at?: string | null;
}

export type BannedGroup =
  | "legal_prohibited"
  | "dangerous_controlled"
  | "live_animals"
  | "medicine_device"
  | "account_virtual"
  | "service_promotion"
  | "other";

export interface BannedScopeGroup {
  group: BannedGroup;
  items: { id: string; content: string; display_order: number }[];
}

/** API-PRD-012 `GET /banned-items`. */
export interface BannedScopeView {
  updated_at: string;
  groups: BannedScopeGroup[];
}

/* --------------------------------------------------------------------- trade */

export type {
  TradeStatus,
  TradePhase,
  TerminalReason,
  AgreementStatus,
  TradeAccountRef,
  TradeProductRef,
  Agreement,
  TradeConfirmation,
  CancellationMode,
  CancellationStatus,
  TradeCancellation,
  DisputeStatus,
  TradeDispute,
  TradeWait,
  TradeFreezeItem,
  TradeAction,
  TradeView,
  ProposeAgreementRequest,
  DecisionKind,
  DecisionRequest,
  CreatePurchaseRequest,
  SubmitCompletionRequest,
  ProposeCancellationRequest,
  OpenDisputeRequest,
  TradeEnvelope,
  AgreementEnvelope,
  SubmitReviewRequest,
  TradeReview,
  SubmitReviewResult,
  TradeReviewsView,
  MyTradesQuery,
} from "./trade-contracts";

/* ------------------------------------------------------------- conversations */

export type ConversationKind = "chat" | "trade" | "case";

export interface ConversationRef {
  conversation_kind: ConversationKind;
  conversation_id: string;
}

export interface ConversationPeer {
  account_id: string;
  display_name: string;
  avatar_url?: string | null;
}

export interface ConversationBranch {
  conversation_kind: ConversationKind;
  conversation_id: string;
  source_ref?: ResourceRef | string | null;
  archived_at?: string | null;
  unread_count: number;
  last_message_at?: string | null;
  last_message_preview?: string | null;
}

export interface ConversationEntry {
  peer: ConversationPeer;
  branches: ConversationBranch[];
}

export type MessageSenderKind = "user" | "system" | "manager" | "peer";

export interface ConversationMessage {
  message_id: string;
  seq: number;
  sender: {
    account_id: string | null;
    display_name: string;
    sender_kind: MessageSenderKind;
  };
  message_type: string;
  body: string;
  created_at: string;
  event_type?: string | null;
  source_ref?: ResourceRef | null;
}

export interface ConversationMessagesPage {
  items: ConversationMessage[];
  trade_id?: string;
  next_after_seq?: number | null;
  next_before_seq?: number | null;
  branch_status: "active" | "archived";
}

export interface SendMessageRequest {
  body: string;
}

export interface SendMessageResult {
  message_id: string;
  seq: number;
  created_at: string;
  sender: {
    account_id: string;
    display_name: string;
  };
  unread_count: number;
}

export interface ReadProgressResult {
  last_read_seq: number;
  unread_count: number;
  updated_at: string;
}

/* -------------------------------------------------------------- notifications */

export interface NotificationSummary {
  notification_id: string;
  event_type: string;
  occurred_at: string;
  read_at?: string | null;
  summary: string;
  source?: ResourceRef | null;
  subject?: string;
}

export interface NotificationDetail extends NotificationSummary {
  body?: string;
  comment_id?: string;
  case_message_id?: string;
}

export type NotificationReadFilter = "all" | "unread" | "read";

export interface ListNotificationsQuery {
  page?: number;
  page_size?: number;
  read?: NotificationReadFilter;
  event_type?: string;
}

export interface NotificationPage extends Page<NotificationSummary> {
  unread_count: number;
}

export interface MarkNotificationReadResult {
  notification_id: string;
  read_at: string;
}

/* --------------------------------------------------------------------- cases */

export type CaseKind = "report" | "product_review" | "trade_abnormal";
export type CaseStatus = "pending" | "claimed" | "decided";
export type CaseDecisionKind = "no_action" | "not_actionable" | "violation";
export type CaseScope = "mine" | "received";

export type ReportTargetType = "product" | "comment" | "message" | "evaluation" | "account";

export interface ReportTarget {
  target_type: ReportTargetType;
  source_product_id?: string;
  target_id: string;
  conversation_kind?: ConversationKind;
  conversation_id?: string;
}

export interface CaseThread extends ConversationRef {}

export interface SubmitReportRequest {
  target: ReportTarget;
  reason: string;
  note?: string;
  attachments?: { file_id: string }[];
}

export interface SubmitReportResult {
  case_id: string;
  case_status: CaseStatus;
  reused: boolean;
}

export interface SupplementReportRequest {
  note?: string;
  attachments?: { file_id: string }[];
}

export interface SupplementReportResult {
  case_id: string;
  supplement_count: number;
  updated_at: string;
}

export interface MyCaseItem {
  case_id: string;
  scope: CaseScope;
  case_status: CaseStatus;
  decision_kind?: CaseDecisionKind | null;
  archived_at?: string | null;
  public_result_at?: string | null;
  updated_at: string;
  thread?: CaseThread | null;
}

export interface ListMyCasesQuery {
  scope: CaseScope;
  status?: CaseStatus;
  archived?: boolean;
  page?: number;
  page_size?: number;
}

export type CaseMessageKind = "inquiry" | "statement" | "appeal" | "manager_reply" | "system";

export interface CaseMessage {
  case_message_id: string;
  seq: number;
  message_kind: CaseMessageKind;
  body: string;
  sender: {
    account_id: string | null;
    display_name: string;
    sender_kind: MessageSenderKind;
  };
  created_at: string;
}

export interface PostCaseMessageRequest {
  thread: CaseThread;
  message_kind: CaseMessageKind;
  body: string;
  inquiry_action_id?: string;
  appeal_action_id?: string;
  resolution?: "uphold" | "revoke" | "adjust";
}

export interface PostCaseMessageResult {
  case_action_id: string;
  case_message_id: string;
  seq: number;
  message_kind: CaseMessageKind;
  created_at: string;
  thread: CaseThread;
}

export interface CaseActionView {
  action_kind: string;
  occurred_at: string;
  actor_kind: string;
}

export interface CaseEnforcementView {
  action: string;
  current_state: string;
}

/** API-CASE-010 `GET /cases/{case_id}` — projected by the reader's viewpoint. */
export type CaseViewpoint = "reporter" | "related_account" | "manager";

export interface PendingInquiry {
  inquiry_action_id: string;
  asked_at?: string | null;
  scope_text?: string | null;
  related_account_id?: string | null;
}

export interface CaseDetail {
  reported_reason?: string | null;
  report_materials?: {
    original_note?: string | null;
    product?: { id: string; title: string; description?: string | null };
    supplements: { action_id: string; note: string; occurred_at: string }[];
    attachments: { evidence_id: string; submitted_at: string; content_type?: string }[];
  };
  case_id: string;
  case_type: CaseKind;
  case_status: CaseStatus;
  decision_kind?: CaseDecisionKind | null;
  archived_at?: string | null;
  reason_text?: string | null;
  thread?: CaseThread | null;
  appeal_deadline_at?: string | null;
  actions: CaseActionView[];
  enforcements: CaseEnforcementView[];
  /**
   * How the server sees the caller on this case. `reporter` drives the supplement
   * entry; when the field is absent the client falls back to the list scope.
   */
  viewpoint?: CaseViewpoint | null;
  /**
   * Actions the server allows for the current viewer. An array is authoritative and
   * an empty array means no write entry is available; a missing field means the
   * backend does not project the capability yet, so the client keeps its own rules.
   */
  available_actions?: string[] | null;
  /**
   * Inquiries this viewer may answer, each carrying the id the statement must send.
   * Absent means the backend does not project it yet, so the client reads the todo
   * projection instead.
   */
  pending_inquiries?: PendingInquiry[] | null;
  public_result_at?: string | null;
}

export interface PublicCaseResult {
  case_id: string;
  decision_kind: CaseDecisionKind;
  public_summary: string;
  public_reason: string;
  published_at: string;
}

/* ------------------------------------------------------ aggregation & realtime */

/** API-COM-QUERY-001 `GET /account/overview`. */
export interface MyOverview {
  as_of: string;
  products: { total: number; by_state: Record<string, number> };
  trades: { total: number; buying: number; selling: number; by_state: Record<string, number> };
  favorites: { total: number; valid: number; invalid: number };
  evaluations: { written: number; received: number };
  reports: { submitted: number; received: number };
  todo_count: number;
}

export type TodoKind =
  | "request_response"
  | "agreement_response"
  | "completion_response"
  | "cancellation_response"
  | "inquiry_response";

export interface TodoItem {
  todo_key: string;
  kind: TodoKind;
  source: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  summary: string;
}

export interface MyTodoPage extends Page<TodoItem> {
  counts_by_kind: Partial<Record<TodoKind, number>>;
  as_of: string;
}

export type MyResourceKind = "product" | "trade" | "favorite" | "evaluation" | "report";

export interface MyResourceQuery {
  kind: MyResourceKind;
  state?: string;
  role?: "all" | "buying" | "selling";
  direction?: "written" | "received";
  page?: number;
  page_size?: number;
}

export interface MyResourcePage extends Page<Record<string, unknown>> {
  kind: MyResourceKind;
  as_of: string;
}

/** `GET /capabilities` (published by the realtime work package). */
export interface Capabilities {
  config_version: string;
  limits: {
    password_min_length: number;
    password_max_length: number;
    display_name_max_length: number;
  };
}

export interface EventHead {
  epoch: string;
  head_seq: number;
  replay_floor: number;
}

export interface RealtimeEventFrame {
  type: "event";
  epoch: string;
  event_id: string;
  account_seq: number;
  schema_version: 1;
  occurred_at: string;
  event_type:
    | "message_created"
    | "message_read"
    | "conversation_archived"
    | "notification_created"
    | "notification_read"
    | "source_changed";
  data: Record<string, unknown>;
}

export interface CursorAdvanceFrame {
  type: "cursor_advance";
  epoch: string;
  from_seq: number;
  through_seq: number;
}

export type RealtimeFrame = RealtimeEventFrame | CursorAdvanceFrame;

export interface EventPage {
  items: RealtimeFrame[];
  next_cursor: { epoch: string; after_seq: number };
  head_seq: number;
  has_more: boolean;
}
