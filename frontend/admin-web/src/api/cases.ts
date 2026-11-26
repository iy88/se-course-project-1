/* Shared case workbench query (API-COM-QUERY-004). */
import { request } from "./http";
import type { ManagementTodoPage, TodoKind, WorkbenchOwnership } from "./contracts";

export interface CaseQueueQuery {
  ownership: WorkbenchOwnership;
  kind: TodoKind;
  keyword?: string;
  page: number;
  page_size: number;
}

/** Four ownership scopes, type filter, keyword and paging are all applied before paging. */
export function listCaseQueue(
  query: CaseQueueQuery,
  signal?: AbortSignal,
): Promise<ManagementTodoPage> {
  return request<ManagementTodoPage>("GET", "/management/todos", {
    query: {
      ownership: query.ownership,
      kind: query.kind,
      keyword: query.keyword?.trim() || undefined,
      page: query.page,
      page_size: query.page_size,
    },
    signal,
  });
}

export interface ManagementCaseThread {
  conversation_kind: "case";
  conversation_id: string;
  related_account_id: string;
}

export interface PendingCaseAppeal {
  appeal_action_id: string;
  related_account_id: string;
  submitted_at: string;
  thread: Pick<ManagementCaseThread, "conversation_kind" | "conversation_id">;
}

export interface ManagementCaseDetail {
  case_id: string;
  case_type: "report" | "dispute" | "exception";
  case_status: "pending" | "claimed" | "decided";
  decision_kind: CaseDecision | null;
  reported_reason?: string | null;
  reason_text?: string | null;
  archived_at: string | null;
  public_result_at: string | null;
  available_actions?: string[];
  threads?: ManagementCaseThread[];
  pending_appeals?: PendingCaseAppeal[];
  evidence?: { evidence_id: string; file_id: string | null }[];
  actions: { action_kind: string; occurred_at: string; actor_kind: string }[];
  enforcements: {
    enforcement_id: string;
    action: string;
    result_status: string;
    current_state: string | null;
    /** Management viewpoint only; true when API-CASE-008 can lift this enforcement. */
    can_lift?: boolean;
  }[];
}

export interface LiftEnforcementResult {
  enforcement_id: string;
  lifted_at: string;
  lifted_by: string;
  restored_scope: string[];
  remaining_restrictions: string[];
}

export type CaseDecision = "no_action" | "not_actionable" | "violation";
export interface CaseEnforcementInput {
  action: string;
  target_type: string;
  target_id: string;
  expected_result?: string;
}

export interface CaseThreadPage {
  items: {
    case_message_id: string;
    message_kind: string;
    body: string;
    sender: { display_name: string };
    created_at: string;
  }[];
  next_before_seq: number | null;
}

export function readCase(caseId: string, signal?: AbortSignal): Promise<ManagementCaseDetail> {
  return request("GET", `/cases/${encodeURIComponent(caseId)}`, { signal });
}

/** Same-origin read route for one verified case evidence attachment. */
export function caseEvidenceFileHref(caseId: string, evidenceId: string): string {
  return `/api/v1/admin/cases/${encodeURIComponent(caseId)}/evidence/${encodeURIComponent(evidenceId)}/file`;
}

export function readCaseThread(
  conversationId: string,
  beforeSeq?: number,
  signal?: AbortSignal,
): Promise<CaseThreadPage> {
  return request("GET", `/conversations/case/${encodeURIComponent(conversationId)}/messages`, {
    query: { before_seq: beforeSeq, limit: 20 },
    signal,
  });
}

export interface CaseManagementWrites {
  inquiries: { peer_account_id: string; scope_text: string };
  decisions: {
    decision_kind: CaseDecision;
    reason: string;
    basis_refs: string[];
    enforcements: CaseEnforcementInput[];
  };
  close: undefined;
  "publish-result": { public_summary: string; public_reason: string };
}

export function upholdCaseAppeal(
  caseId: string,
  appeal: PendingCaseAppeal,
  body: string,
  basisRef: string,
  idempotencyKey: string,
): Promise<unknown> {
  return request("POST", `/cases/${encodeURIComponent(caseId)}/messages`, {
    body: {
      thread: appeal.thread,
      message_kind: "manager_reply",
      appeal_action_id: appeal.appeal_action_id,
      resolution: "uphold",
      body,
      basis_ref: basisRef,
    },
    idempotencyKey,
  });
}

export function writeCase<T extends keyof CaseManagementWrites>(
  caseId: string,
  operation: T,
  body: CaseManagementWrites[T],
  idempotencyKey: string,
): Promise<unknown> {
  return request("POST", `/admin/cases/${encodeURIComponent(caseId)}/${operation}`, {
    body,
    idempotencyKey,
  });
}

/** API-CASE-008: explicitly lifts one applied enforcement of the current manager's case. */
export function liftCaseEnforcement(
  caseId: string,
  enforcementId: string,
  reason: string,
  idempotencyKey: string,
): Promise<LiftEnforcementResult> {
  return request(
    "POST",
    `/admin/cases/${encodeURIComponent(caseId)}/enforcements/${encodeURIComponent(enforcementId)}/lift`,
    { body: { reason }, idempotencyKey },
  );
}
