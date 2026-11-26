/*
 * Conversations and messages. Paths follow
 * docs/design/detailed-design/interfaces/会话与处置事项.md (API-CONV-001—005).
 */
import { request } from "./http";
import type {
  ConversationEntry,
  ConversationPeer,
  ConversationMessage,
  ConversationKind,
  ConversationMessagesPage,
  Page,
  ReadProgressResult,
  SendMessageRequest,
  SendMessageResult,
} from "./contracts";
import type { ResourceRef } from "./contracts";

export function listConversations(
  page: number,
  pageSize: number,
  signal?: AbortSignal,
): Promise<Page<ConversationEntry>> {
  return request<Page<ConversationEntry>>("GET", "/conversations", {
    query: { page, page_size: pageSize },
    signal,
  });
}

export function ensurePrivateConversation(
  targetAccountId: string,
  idempotencyKey: string,
): Promise<{
  conversation_kind: ConversationKind;
  conversation_id: string;
  peer: ConversationPeer;
  reused: boolean;
}> {
  return request("POST", "/conversations/private", {
    body: { target_account_id: targetAccountId },
    idempotencyKey,
  });
}

/**
 * Raw message shape as the design allows both naming sets: trade threads answer
 * `message_id`／`message_type` and case threads answer `case_message_id`／
 * `message_kind` (API-CONV-003). The normaliser keeps one internal shape so views
 * do not branch on the conversation kind.
 */
interface RawMessage {
  message_id?: string | null;
  case_message_id?: string | null;
  seq: number;
  sender: ConversationMessage["sender"];
  message_type?: string | null;
  message_kind?: string | null;
  body: string;
  created_at: string;
  event_type?: string | null;
  source_ref?: ResourceRef | null;
}

interface RawMessagesPage {
  items: RawMessage[];
  trade_id?: ConversationMessagesPage["trade_id"];
  next_after_seq?: number | null;
  next_before_seq?: number | null;
  branch_status: "active" | "archived";
}

function normalizeMessage(raw: RawMessage): ConversationMessage {
  return {
    message_id: raw.message_id ?? raw.case_message_id ?? "",
    seq: raw.seq,
    sender: raw.sender,
    message_type: raw.message_type ?? raw.message_kind ?? "statement",
    body: raw.body,
    created_at: raw.created_at,
    event_type: raw.event_type ?? null,
    source_ref: raw.source_ref ?? null,
  };
}

export function normalizeMessagesPage(page: RawMessagesPage): ConversationMessagesPage {
  return {
    items: page.items.map(normalizeMessage),
    trade_id: page.trade_id,
    next_after_seq: page.next_after_seq ?? null,
    next_before_seq: page.next_before_seq ?? null,
    branch_status: page.branch_status,
  };
}

export function listMessages(
  kind: ConversationKind,
  conversationId: string,
  query: { after_seq?: number; before_seq?: number; limit?: number },
  signal?: AbortSignal,
): Promise<ConversationMessagesPage> {
  return request<RawMessagesPage>("GET", `/conversations/${kind}/${conversationId}/messages`, {
    query,
    signal,
  }).then(normalizeMessagesPage);
}

export function sendMessage(
  kind: ConversationKind,
  conversationId: string,
  payload: SendMessageRequest,
  idempotencyKey: string,
): Promise<SendMessageResult> {
  return request<SendMessageResult>("POST", `/conversations/${kind}/${conversationId}/messages`, {
    body: payload,
    idempotencyKey,
  });
}

export function advanceReadProgress(
  kind: ConversationKind,
  conversationId: string,
  displayedSeq: number,
  idempotencyKey: string,
): Promise<ReadProgressResult> {
  return request<ReadProgressResult>(
    "POST",
    `/conversations/${kind}/${conversationId}/read-progress`,
    { body: { displayed_seq: displayedSeq }, idempotencyKey },
  );
}
