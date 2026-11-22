package io.github.iy88.project1.conversation.application;

import java.time.Instant;

/** Transport-neutral projections returned by the conversation use cases. */
public final class ConversationViews {
    private ConversationViews() {
    }

    public record StartedChat(long conversationId, long peerAccountId, String peerDisplayName, boolean reused) {
    }

    public record ChatMessage(long messageId, long seq, long senderAccountId, String senderDisplayName,
                              String body, Instant createdAt, long peerUnread) {
    }

    public record ReadProgress(long lastReadSeq, long unreadCount, Instant updatedAt) {
    }
}
