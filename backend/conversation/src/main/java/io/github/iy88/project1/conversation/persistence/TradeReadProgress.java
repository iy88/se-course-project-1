package io.github.iy88.project1.conversation.persistence;

import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.IdClass;
import jakarta.persistence.Table;
import java.io.Serializable;
import java.time.Instant;
import java.util.Objects;

/** Account-level read cursor for one trade conversation; it only moves forward. */
@Entity
@Table(name = "trade_read_progress")
@IdClass(TradeReadProgress.Key.class)
public class TradeReadProgress {
    @Id
    private long tradeConversationId;
    @Id
    private long accountId;
    private long lastReadSeq;
    private Instant lastReadAt;

    protected TradeReadProgress() {
    }

    TradeReadProgress(long tradeConversationId, long accountId) {
        this.tradeConversationId = tradeConversationId;
        this.accountId = accountId;
    }

    public long conversationId() {
        return tradeConversationId;
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
        private long tradeConversationId;
        private long accountId;

        public Key() {
        }

        public Key(long tradeConversationId, long accountId) {
            this.tradeConversationId = tradeConversationId;
            this.accountId = accountId;
        }

        @Override
        public boolean equals(Object other) {
            return other instanceof Key key && key.tradeConversationId == tradeConversationId
                    && key.accountId == accountId;
        }

        @Override
        public int hashCode() {
            return Objects.hash(tradeConversationId, accountId);
        }
    }
}
