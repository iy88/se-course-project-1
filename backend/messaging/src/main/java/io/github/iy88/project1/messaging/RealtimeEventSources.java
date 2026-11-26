package io.github.iy88.project1.messaging;

import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.ResourceRef;
import java.time.Instant;
import java.util.Optional;
import java.util.UUID;

/** Metadata projections supplied by the modules that own the referenced records. */
public final class RealtimeEventSources {
    private RealtimeEventSources() {}

    public interface Notifications {
        /**
         * Resolves a readable notification for the current recipient.
         * Empty means current unreadability; dependency failures must be thrown.
         */
        Optional<NotificationHint> read(ExecutionContext context, long notificationId);
    }

    public record NotificationHint(Instant readAt) {}

    public interface Conversations {
        /** False means current unreadability; dependency failures must be thrown. */
        boolean canRead(ExecutionContext context, ConversationRef conversation);

        /** Checks message membership and current conversation visibility; dependency failures must be thrown. */
        Optional<MessageHint> readMessage(ExecutionContext context, ConversationRef conversation, long messageId);
    }

    public record ConversationRef(ConversationKind kind, long id) {
        public ResourceRef resource() {
            return new ResourceRef(kind.sourceType(), id);
        }

        public ResourceRef message(long messageId) {
            return new ResourceRef(kind.messageType(), messageId);
        }
    }

    public enum ConversationKind {
        CHAT("chat", "chat_conversation"),
        TRADE("trade", "trade_conversation"),
        CASE("case", "case_conversation");

        private final String wireName;
        private final String sourceType;

        ConversationKind(String wireName, String sourceType) {
            this.wireName = wireName;
            this.sourceType = sourceType;
        }

        public String wireName() {
            return wireName;
        }

        public String sourceType() {
            return sourceType;
        }

        public String messageType() {
            return wireName + "_message";
        }
    }

    public record MessageHint(long sequence, UUID businessEventId) {}

    public interface SourceAccess {
        String sourceType();

        /** False means current unreadability; dependency failures must be thrown. */
        boolean canRead(ExecutionContext context, ResourceRef source);
    }
}
