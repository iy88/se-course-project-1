/* Review queue, detail, claim and decision endpoints (API-PRD-005/006, QUERY-004). */
import { request } from "./http";
import type {
  ClaimResult,
  ManagementTodoPage,
  ReviewDecisionRequest,
  ReviewDecisionResult,
  ReviewDetail,
} from "./contracts";

export function listReviewQueue(
  query: { ownership: "unclaimed" | "mine"; page: number; page_size: number },
  signal?: AbortSignal,
): Promise<ManagementTodoPage> {
  return request<ManagementTodoPage>("GET", "/management/todos", {
    query: { kind: "product_review", ...query },
    signal,
  });
}

export function readReviewDetail(auditId: string, signal?: AbortSignal): Promise<ReviewDetail> {
  return request<ReviewDetail>("GET", `/admin/product-reviews/${auditId}`, { signal });
}

export function claimCase(caseId: string, idempotencyKey: string): Promise<ClaimResult> {
  return request<ClaimResult>("POST", `/admin/cases/${caseId}/claim`, { idempotencyKey });
}

export function decideReview(
  auditId: string,
  payload: ReviewDecisionRequest,
  idempotencyKey: string,
): Promise<ReviewDecisionResult> {
  return request<ReviewDecisionResult>("POST", `/admin/product-reviews/${auditId}/decision`, {
    body: payload,
    idempotencyKey,
  });
}
