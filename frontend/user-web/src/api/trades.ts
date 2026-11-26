/*
 * Trade lifecycle use cases. Signatures match the published trade contract in
 * `frontend/shared/openapi.json` on the S3-01 work branch (API-TRD-001—014).
 */
import { request } from "./http";
import type {
  Agreement,
  AgreementEnvelope,
  CreatePurchaseRequest,
  DecisionRequest,
  DecisionKind,
  MyTradesQuery,
  OpenDisputeRequest,
  Page,
  ProposeAgreementRequest,
  ProposeCancellationRequest,
  SubmitCompletionRequest,
  SubmitReviewRequest,
  SubmitReviewResult,
  TradeCancellation,
  TradeConfirmation,
  TradeDispute,
  TradeReview,
  TradeReviewsView,
  TradeView,
} from "./contracts";

export function createPurchaseRequest(
  productId: string,
  payload: CreatePurchaseRequest,
  idempotencyKey: string,
): Promise<TradeView> {
  return request<TradeView>("POST", `/products/${productId}/purchase-requests`, {
    body: payload,
    idempotencyKey,
  });
}

export function listMyTrades(query: MyTradesQuery, signal?: AbortSignal): Promise<Page<TradeView>> {
  return request<Page<TradeView>>("GET", "/me/trades", {
    query,
    signal,
  });
}

export function getTrade(tradeId: string, signal?: AbortSignal): Promise<TradeView> {
  return request<TradeView>("GET", `/trades/${tradeId}`, { signal, query: {} });
}

function tradeAction(
  tradeId: string,
  action: "accept" | "reject" | "withdraw",
  expectedVersion: number,
  idempotencyKey: string,
): Promise<TradeView> {
  return request<TradeView>("POST", `/trades/${tradeId}/${action}`, {
    body: { expected_version: expectedVersion },
    idempotencyKey,
  });
}

export function acceptTrade(
  tradeId: string,
  expectedVersion: number,
  idempotencyKey: string,
): Promise<TradeView> {
  return tradeAction(tradeId, "accept", expectedVersion, idempotencyKey);
}

export function rejectTrade(
  tradeId: string,
  expectedVersion: number,
  idempotencyKey: string,
): Promise<TradeView> {
  return tradeAction(tradeId, "reject", expectedVersion, idempotencyKey);
}

export function withdrawTrade(
  tradeId: string,
  expectedVersion: number,
  idempotencyKey: string,
): Promise<TradeView> {
  return tradeAction(tradeId, "withdraw", expectedVersion, idempotencyKey);
}

export function proposeAgreement(
  tradeId: string,
  payload: ProposeAgreementRequest,
  idempotencyKey: string,
): Promise<AgreementEnvelope> {
  return request<AgreementEnvelope>("POST", `/trades/${tradeId}/agreements`, {
    body: payload,
    idempotencyKey,
  });
}

export function decideAgreement(
  tradeId: string,
  agreementId: string,
  decision: DecisionKind,
  expectedVersion: number,
  idempotencyKey: string,
): Promise<AgreementEnvelope> {
  return request<AgreementEnvelope>(
    "POST",
    `/trades/${tradeId}/agreements/${agreementId}/decisions`,
    { body: { decision, expected_version: expectedVersion }, idempotencyKey },
  );
}

export function submitCompletionConfirmation(
  tradeId: string,
  payload: SubmitCompletionRequest,
  idempotencyKey: string,
): Promise<{ confirmation: TradeConfirmation; trade: TradeView }> {
  return request("POST", `/trades/${tradeId}/completion-confirmations`, {
    body: payload,
    idempotencyKey,
  });
}

export function proposeCancellation(
  tradeId: string,
  payload: ProposeCancellationRequest,
  idempotencyKey: string,
): Promise<{ cancellation: TradeCancellation; trade: TradeView }> {
  return request("POST", `/trades/${tradeId}/cancellation-proposals`, {
    body: payload,
    idempotencyKey,
  });
}

export function decideCancellation(
  tradeId: string,
  proposalId: string,
  decision: DecisionKind,
  expectedVersion: number,
  idempotencyKey: string,
): Promise<{ cancellation: TradeCancellation; trade: TradeView }> {
  return request("POST", `/trades/${tradeId}/cancellation-proposals/${proposalId}/decisions`, {
    body: { decision, expected_version: expectedVersion },
    idempotencyKey,
  });
}

export function openDispute(
  tradeId: string,
  payload: OpenDisputeRequest,
  idempotencyKey: string,
): Promise<{ dispute: TradeDispute; trade: TradeView }> {
  return request("POST", `/trades/${tradeId}/disputes`, {
    body: payload,
    idempotencyKey,
  });
}

export function confirmDisputeResolution(
  tradeId: string,
  disputeId: string,
  expectedVersion: number,
  idempotencyKey: string,
): Promise<{ dispute: TradeDispute; trade: TradeView }> {
  return request("POST", `/trades/${tradeId}/disputes/${disputeId}/resolution-confirmations`, {
    body: { expected_version: expectedVersion },
    idempotencyKey,
  });
}

export function getTradeReviews(tradeId: string, signal?: AbortSignal): Promise<TradeReviewsView> {
  return request<TradeReviewsView>("GET", `/trades/${tradeId}/reviews`, {
    query: {},
    signal,
  });
}

export function submitTradeReview(
  tradeId: string,
  payload: SubmitReviewRequest,
  idempotencyKey: string,
): Promise<SubmitReviewResult> {
  return request<SubmitReviewResult>("POST", `/trades/${tradeId}/reviews`, {
    body: payload,
    idempotencyKey,
  });
}

export function listMyReviews(
  direction: "written" | "received",
  page: number,
  pageSize: number,
  signal?: AbortSignal,
): Promise<Page<TradeReview>> {
  return request<Page<TradeReview>>("GET", "/me/reviews", {
    query: { direction, page, page_size: pageSize },
    signal,
  });
}

export type { Agreement, DecisionRequest };
