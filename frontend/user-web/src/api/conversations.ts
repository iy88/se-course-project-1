/*
 * Conversations and messages. Paths follow
 * docs/design/detailed-design/interfaces/会话与处置事项.md (API-CONV-001—005).
 */
import { request } from "./http";
import type {
  ConversationEntry,
  ConversationKind,
  ConversationMessagesPage,
  Page,
  ReadProgressResult,
  SendMessageRequest,
  SendMessageResult,
} from "./contracts";

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
  peer: { account_id: string; display_name: string };
  reused: boolean;
}> {
  return request("POST", "/conversations/private", {
    body: { target_account_id: targetAccountId },
    idempotencyKey,
  });
}

export function listMessages(
  kind: ConversationKind,
  conversationId: string,
  query: { after_seq?: number; before_seq?: number; limit?: number },
  signal?: AbortSignal,
): Promise<ConversationMessagesPage> {
  return request<ConversationMessagesPage>(
    "GET",
    `/conversations/${kind}/${conversationId}/messages`,
    { query, signal },
  );
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
