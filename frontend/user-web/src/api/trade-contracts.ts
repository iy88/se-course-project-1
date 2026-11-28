/* --------------------------------------------------------------------- trade */

export type TradeStatus =
  | "pending_acceptance"
  | "rejected"
  | "withdrawn"
  | "closed"
  | "in_progress"
  | "disputed"
  | "abnormal"
  | "terminated"
  | "completed";

export type TradePhase = "first_agreement_pending" | "awaiting_completion";

export type TerminalReason = "completed" | "cancelled" | "admin_terminated";

export type AgreementStatus = "proposed" | "effective" | "rejected" | "withdrawn" | "superseded";

export interface TradeAccountRef {
  id: string;
  display_name: string;
  avatar_url?: string | null;
}

export interface TradeProductRef {
  id: string;
  title?: string;
  price_cents?: number;
}

export interface Agreement {
  id: string;
  base_agreement_id?: string | null;
  version_no: number;
  status: AgreementStatus;
  proposed_by: string;
  delivery_at: string;
  delivery_place_text: string;
  delivery_method: string;
  amount_cents: number;
  payment_method: string;
  payment_timing: string;
  proposed_at: string;
}

export interface TradeConfirmation {
  id: string;
  agreement_id: string;
  confirmer_id: string;
  note?: string | null;
  submitted_at: string;
}

export type CancellationMode = "direct" | "approval";
export type CancellationStatus = "pending" | "accepted" | "rejected" | "withdrawn";

export interface TradeCancellation {
  id: string;
  proposed_by: string;
  mode: CancellationMode;
  reason?: string | null;
  status: CancellationStatus;
  proposed_at: string;
}

export type DisputeStatus = "open" | "resolved" | "terminated";

export interface TradeDispute {
  id: string;
  initiator_id: string;
  statement: string;
  status: DisputeStatus;
  /** Management case created for the dispute, when the backend has one. */
  case_id?: string | null;
  opened_at: string;
  resolved_at?: string | null;
}

export interface TradeWait {
  active: boolean;
  started_at?: string | null;
  deadline_at?: string | null;
  remaining_seconds: number;
  paused: boolean;
  ended_at?: string | null;
  end_reason?: string | null;
}

export interface TradeFreezeItem {
  id: string;
  source: string;
  source_ref?: string | null;
  reason: string;
  started_at: string;
}

/** Server-computed action allow-list; the client renders exactly these. */
export type TradeAction =
  | "accept"
  | "reject"
  | "withdraw"
  | "propose_agreement"
  | "decide_agreement"
  | "submit_confirmation"
  | "propose_cancellation"
  | "decide_cancellation"
  | "open_dispute"
  | "confirm_dispute_resolution";

export interface TradeView {
  id: string;
  product: TradeProductRef;
  buyer: TradeAccountRef;
  seller: TradeAccountRef;
  status: TradeStatus;
  phase?: TradePhase | null;
  terminal_reason?: TerminalReason | null;
  request: {
    note?: string | null;
    requested_at: string;
    responded_at?: string | null;
    close_reason?: string | null;
  };
  agreement: {
    current: Agreement | null;
    pending: Agreement | null;
  };
  confirmations: {
    current: TradeConfirmation[];
    both_current: boolean;
  };
  wait: TradeWait;
  freeze: {
    active: boolean;
    items: TradeFreezeItem[];
  };
  cancellation: {
    pending: TradeCancellation | null;
  };
  dispute: {
    open: TradeDispute | null;
  };
  trade_conversation_id?: string | null;
  version: number;
  permissions: {
    allowed_actions: TradeAction[];
  };
  created_at: string;
  updated_at: string;
  agreement_history?: Agreement[];
  confirmation_history?: Record<string, unknown>[];
  state_history?: Record<string, unknown>[];
}

export interface ProposeAgreementRequest {
  delivery_at: string;
  delivery_place_text: string;
  delivery_method: string;
  amount_cents: number;
  payment_method: string;
  payment_timing: string;
  base_agreement_id?: string | null;
  expected_version: number;
}

export type DecisionKind = "accept" | "reject" | "withdraw";

export interface DecisionRequest {
  decision: DecisionKind;
  expected_version: number;
}

export interface CreatePurchaseRequest {
  note?: string;
  expected_product_version: number;
}

export interface SubmitCompletionRequest {
  note?: string;
  expected_version: number;
}

export interface ProposeCancellationRequest {
  reason?: string;
  expected_version: number;
}

export interface OpenDisputeRequest {
  statement: string;
  expected_version: number;
}

export interface TradeEnvelope {
  trade: TradeView;
}

export interface AgreementEnvelope {
  agreement: Agreement;
  trade: TradeView;
}

export interface SubmitReviewRequest {
  rating: number;
  content: string;
}

export interface TradeReview {
  review_id: string;
  trade_id: string;
  reviewer: TradeAccountRef;
  reviewee: TradeAccountRef;
  rating: number;
  /** Null or empty when the reviewer only left a rating. */
  content?: string | null;
  visible: boolean;
  created_at: string;
}

export interface SubmitReviewResult {
  review: TradeReview;
}

/** API-TRD-016 `GET /trades/{trade_id}/reviews` projection for one viewer. */
export interface TradeReviewsView {
  can_review: boolean;
  written: TradeReview | null;
  received: TradeReview | null;
}

export interface MyTradesQuery {
  role?: "all" | "buyer" | "seller";
  status?: TradeStatus[];
  page?: number;
  page_size?: number;
}
