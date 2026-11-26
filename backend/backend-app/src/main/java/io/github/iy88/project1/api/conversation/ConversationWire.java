package io.github.iy88.project1.api.conversation;

import io.github.iy88.project1.conversation.ConversationKind;
import io.github.iy88.project1.conversation.application.ConversationViews;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * JSON shape of the conversation endpoints (API-CONV-001—005).
 *
 * Ids are decimal strings and times are UTC ISO 8601. Chat and trade messages keep the
 * {@code message_id}/{@code message_type} names; case threads use {@code case_message_id} and
 * {@code message_kind}, as the interface contract fixes per kind.
 */
final class ConversationWire {
    private ConversationWire() {
    }

    static Map<String, Object> started(ConversationViews.StartedChat started) {
        var body = new LinkedHashMap<String, Object>();
        body.put("conversation_kind", ConversationKind.CHAT.wireValue());
        body.put("conversation_id", Long.toString(started.conversationId()));
        body.put("peer", peer(started.peerAccountId(), started.peerDisplayName(), started.peerAvatarUrl()));
        body.put("reused", started.reused());
        return body;
    }

    static Map<String, Object> page(ConversationViews.Page<ConversationViews.Summary> page) {
        var body = new LinkedHashMap<String, Object>();
        body.put("items", page.items().stream().map(ConversationWire::summary).toList());
        body.put("page", page.page());
        body.put("page_size", page.pageSize());
        body.put("total", page.total());
        return body;
    }

    static Map<String, Object> messagePage(ConversationViews.MessagePage page, ConversationKind kind) {
        var body = new LinkedHashMap<String, Object>();
        body.put("items", page.items().stream().map(item -> message(item, kind)).toList());
        body.put("next_after_seq", page.nextAfterSeq());
        body.put("next_before_seq", page.nextBeforeSeq());
        body.put("branch_status", page.branchStatus());
        if (kind == ConversationKind.TRADE && page.tradeId() != null) {
            body.put("trade_id", Long.toString(page.tradeId()));
        }
        return body;
    }

    static Map<String, Object> sent(ConversationViews.ChatMessage message) {
        var body = new LinkedHashMap<String, Object>();
        body.put("message_id", Long.toString(message.messageId()));
        body.put("seq", message.seq());
        body.put("created_at", message.createdAt());
        body.put("sender", sender(message.senderAccountId(), message.senderDisplayName(), "account"));
        body.put("unread_count", message.peerUnread());
        return body;
    }

    static Map<String, Object> read(ConversationViews.ReadProgress progress) {
        var body = new LinkedHashMap<String, Object>();
        body.put("last_read_seq", progress.lastReadSeq());
        body.put("unread_count", progress.unreadCount());
        body.put("updated_at", progress.updatedAt());
        return body;
    }

    private static Map<String, Object> summary(ConversationViews.Summary summary) {
        var body = new LinkedHashMap<String, Object>();
        body.put("peer", peer(summary.peer().accountId(), summary.peer().displayName(),
                summary.peer().avatarUrl()));
        body.put("branches", summary.branches().stream().map(ConversationWire::branch).toList());
        return body;
    }

    private static Map<String, Object> branch(ConversationViews.Branch branch) {
        var body = new LinkedHashMap<String, Object>();
        body.put("conversation_kind", branch.conversationKind());
        body.put("conversation_id", Long.toString(branch.conversationId()));
        body.put("source_ref", branch.sourceRef());
        body.put("archived_at", branch.archivedAt());
        body.put("unread_count", branch.unreadCount());
        body.put("last_message_at", branch.lastMessageAt());
        body.put("last_message_preview", branch.lastMessagePreview());
        return body;
    }

    private static Map<String, Object> message(ConversationViews.Message message, ConversationKind kind) {
        var body = new LinkedHashMap<String, Object>();
        boolean caseThread = kind == ConversationKind.CASE;
        body.put(caseThread ? "case_message_id" : "message_id", Long.toString(message.messageId()));
        body.put("seq", message.seq());
        body.put("sender", sender(message.sender().accountId(), message.sender().displayName(),
                message.sender().senderKind()));
        body.put(caseThread ? "message_kind" : "message_type", message.messageType());
        body.put("body", message.body());
        body.put("created_at", message.createdAt());
        if (message.eventType() != null) {
            body.put("event_type", message.eventType());
        }
        if (message.sourceRef() != null) {
            body.put("source_ref", message.sourceRef());
        }
        return body;
    }

    private static Map<String, Object> peer(long accountId, String displayName, String avatarUrl) {
        var peer = new LinkedHashMap<String, Object>();
        peer.put("account_id", Long.toString(accountId));
        peer.put("display_name", displayName);
        peer.put("avatar_url", avatarUrl);
        return peer;
    }

    private static Map<String, Object> sender(Long accountId, String displayName, String senderKind) {
        var sender = new LinkedHashMap<String, Object>();
        sender.put("account_id", accountId == null ? null : Long.toString(accountId));
        sender.put("display_name", displayName);
        sender.put("sender_kind", senderKind);
        return sender;
    }
}
