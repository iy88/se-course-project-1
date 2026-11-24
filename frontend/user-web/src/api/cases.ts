/*
 * Report, inquiry, appeal and own-case use cases.
 * Paths follow docs/design/detailed-design/interfaces/会话与处置事项.md
 * (API-CASE-001—003, 006, 009, 010).
 */
import { request } from "./http";
import type {
  CaseDetail,
  ListMyCasesQuery,
  MyCaseItem,
  Page,
  PostCaseMessageRequest,
  PostCaseMessageResult,
  PublicCaseResult,
  SubmitReportRequest,
  SubmitReportResult,
  SupplementReportRequest,
  SupplementReportResult,
} from "./contracts";

export function submitReport(
  payload: SubmitReportRequest,
  idempotencyKey: string,
): Promise<SubmitReportResult> {
  return request<SubmitReportResult>("POST", "/cases", { body: payload, idempotencyKey });
}

export function supplementReport(
  caseId: string,
  payload: SupplementReportRequest,
  idempotencyKey: string,
): Promise<SupplementReportResult> {
  return request<SupplementReportResult>("POST", `/cases/${caseId}/supplements`, {
    body: payload,
    idempotencyKey,
  });
}

export function listMyCases(
  query: ListMyCasesQuery,
  signal?: AbortSignal,
): Promise<Page<MyCaseItem>> {
  return request<Page<MyCaseItem>>("GET", "/cases", {
    query,
    signal,
  });
}

export function getCase(caseId: string, signal?: AbortSignal): Promise<CaseDetail> {
  return request<CaseDetail>("GET", `/cases/${caseId}`, { signal });
}

export function postCaseMessage(
  caseId: string,
  payload: PostCaseMessageRequest,
  idempotencyKey: string,
): Promise<PostCaseMessageResult> {
  return request<PostCaseMessageResult>("POST", `/cases/${caseId}/messages`, {
    body: payload,
    idempotencyKey,
  });
}

export function listPublicCaseResults(
  query: { target_type?: string; target_id?: string; page?: number; page_size?: number },
  signal?: AbortSignal,
): Promise<Page<PublicCaseResult>> {
  return request<Page<PublicCaseResult>>("GET", "/case-results", {
    query,
    signal,
  });
}
