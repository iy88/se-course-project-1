/* Administrative response contracts. Field names follow the API's snake_case wire format. */

export interface Page<TItem> {
  items: TItem[];
  page: number;
  page_size: number;
  total: number;
}

export interface AccountProfile {
  account_id: string;
  email: string;
  display_name: string;
  roles: string[];
  avatar_url: string | null;
}

export interface SessionView {
  session_id: string;
  issued_at: string;
  absolute_expires_at: string;
}

export interface Identity {
  account: AccountProfile;
  session: SessionView;
}

export interface CategoryNameView {
  category_name_id: string;
  name: string;
  kind: "main" | "alias";
  active: boolean;
}

export interface CategoryDetail {
  id: string;
  state: "active" | "disabled";
  main_name: string;
  names: CategoryNameView[];
  associated_product_count: number;
  created_at: string;
  disabled_at: string | null;
}

export type BannedGroupKey =
  | "legal_prohibited"
  | "dangerous_controlled"
  | "live_animals"
  | "medicine_device"
  | "account_virtual"
  | "service_promotion"
  | "other";

export interface BannedItemView {
  id: string;
  content: string;
  display_order: number;
}

export interface BannedGroupView {
  group: BannedGroupKey;
  items: BannedItemView[];
}

export interface BannedScopeView {
  updated_at: string | null;
  groups: BannedGroupView[];
}

export interface BannedItemInput {
  banned_item_id?: string;
  group: BannedGroupKey;
  content: string;
  display_order: number;
}

export interface ManagementTodoItem {
  case_id: string;
  kind: string;
  created_at: string;
  updated_at: string;
  summary: {
    audit_id: string;
    product_id: string;
  };
}

export interface ManagementTodoPage extends Page<ManagementTodoItem> {
  counts_by_kind: Record<string, number>;
  as_of: string;
}

export interface ClaimResult {
  case_id: string;
  case_status: string;
  claimed_manager_id: string;
  claimed_at: string;
  already_claimed: boolean;
}

export interface ReviewImage {
  file_id: string;
  url: string;
  expires_at: string;
}

export interface ReviewCategory {
  id: string;
  name: string;
}

export interface ReviewContent {
  title: string;
  description: string;
  images: ReviewImage[];
  price_cents: number;
  categories: ReviewCategory[];
  content_version: number;
}

export interface ReviewCategoryApplication {
  application_id: string;
  proposed_name: string;
  status: "pending" | "approved" | "rejected" | "withdrawn";
}

export interface ReviewBannedItem {
  id: string;
  group: BannedGroupKey;
  content: string;
}

export interface ReviewResultView {
  decision: string;
  reason: string | null;
  reviewed_content_version: number;
  decided_at: string;
  decided_by: string;
}

export interface ReviewDetail {
  audit_id: string;
  product_id: string;
  case_id: string;
  status: "pending" | "passed" | "rejected" | "withdrawn";
  submitted_at: string;
  seller: { id: string; display_name: string };
  claim: { manager_id: string; claimed_at: string };
  current_content: ReviewContent;
  category_application: ReviewCategoryApplication | null;
  banned_scope: ReviewBannedItem[];
  review_result: ReviewResultView | null;
}

export interface ReviewDecisionRequest {
  decision: "approved" | "rejected";
  reason?: string;
  category_application_decision?: "approved" | "rejected";
  category_application_reason?: string;
  banned_item_ids?: string[];
}

export interface ReviewDecisionResult {
  audit_id: string;
  status: string;
  case_id: string;
  case_status: string;
  product: {
    id: string;
    lifecycle_state: string;
    content_version: number;
  };
  category_application: ReviewCategoryApplication | null;
  reviewed_content_version: number;
  decided_at: string;
}
