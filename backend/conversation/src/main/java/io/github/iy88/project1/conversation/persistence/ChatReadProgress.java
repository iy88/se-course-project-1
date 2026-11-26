package io.github.iy88.project1.conversation.persistence;

import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.IdClass;
import jakarta.persistence.Table;
import java.io.Serializable;
import java.time.Instant;
import java.util.Objects;

/** Account-level read cursor; it only moves forward. */
@Entity
@Table(name = "chat_read_progress")
@IdClass(ChatReadProgress.Key.class)
public class ChatReadProgress {
    @Id
    private long chatConversationId;
    @Id
    private long accountId;
    private long lastReadSeq;
    private Instant lastReadAt;

    protected ChatReadProgress() {
    }

    ChatReadProgress(long chatConversationId, long accountId) {
        this.chatConversationId = chatConversationId;
        this.accountId = accountId;
    }

    public long conversationId() {
        return chatConversationId;
    }

    public long accountId() {
        return accountId;
    }

    public long lastReadSeq() {
        return lastReadSeq;
    }

    public Instant lastReadAt() {
        return lastReadAt;
    }

    long advanceTo(long displayedSeq, Instant at) {
        if (displayedSeq > lastReadSeq) {
            lastReadSeq = displayedSeq;
            lastReadAt = at;
        }
        return lastReadSeq;
    }

    public static class Key implements Serializable {
        private static final long serialVersionUID = 1L;
        private long chatConversationId;
        private long accountId;

        public Key() {
        }

        public Key(long chatConversationId, long accountId) {
            this.chatConversationId = chatConversationId;
            this.accountId = accountId;
        }

        @Override
        public boolean equals(Object other) {
            return other instanceof Key key && key.chatConversationId == chatConversationId
                    && key.accountId == accountId;
        }

        @Override
        public int hashCode() {
            return Objects.hash(chatConversationId, accountId);
        }
    }
}
