package io.github.iy88.project1.conversation.application;

import java.time.Instant;
import java.util.List;

/** Transport-neutral projections returned by the conversation use cases. */
public final class ConversationViews {
    private ConversationViews() {
    }

    public record StartedChat(long conversationId, long peerAccountId, String peerDisplayName,
                              String peerAvatarUrl, boolean reused) {
        public StartedChat(long conversationId, long peerAccountId, String peerDisplayName, boolean reused) {
            this(conversationId, peerAccountId, peerDisplayName, null, reused);
        }
    }

    public record ChatMessage(long messageId, long seq, long senderAccountId, String senderDisplayName,
                              String body, Instant createdAt, long peerUnread) {
    }

    public record ReadProgress(long lastReadSeq, long unreadCount, Instant updatedAt) {
    }

    public record Peer(long accountId, String displayName, String avatarUrl) {
        public Peer(long accountId, String displayName) {
            this(accountId, displayName, null);
        }
    }

    public record Branch(String conversationKind, long conversationId, String sourceRef, Instant archivedAt,
                         long unreadCount, Instant lastMessageAt, String lastMessagePreview) {
    }

    public record Summary(Peer peer, List<Branch> branches) {
        public Summary {
            branches = List.copyOf(branches);
        }
    }

    public record Sender(Long accountId, String displayName, String senderKind) {
    }

    public record Message(long messageId, long seq, Sender sender, String messageType, String body,
                          Instant createdAt, String eventType, String sourceRef) {
    }

    public record MessagePage(List<Message> items, Long nextAfterSeq, Long nextBeforeSeq, String branchStatus,
                              Long tradeId) {
        public MessagePage {
            items = List.copyOf(items);
        }
    }

    public record Page<T>(List<T> items, int page, int pageSize, long total) {
        public Page {
            items = List.copyOf(items);
        }
    }
}
