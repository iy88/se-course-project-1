package io.github.iy88.project1.conversation.persistence;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;

/** One trade record owns exactly one trade conversation; archives are one-way. */
@Entity
@Table(name = "trade_conversation")
public class TradeConversation {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "trade_conversation_id")
    private Long id;
    private long tradeId;
    private long seqHead;
    private Instant createdAt;
    private Instant archivedAt;

    protected TradeConversation() {
    }

    TradeConversation(long tradeId, Instant createdAt) {
        if (tradeId <= 0) {
            throw new IllegalArgumentException("Trade id must be positive");
        }
        this.tradeId = tradeId;
        this.createdAt = createdAt;
    }

    public long id() {
        return id;
    }

    public long tradeId() {
        return tradeId;
    }

    public long seqHead() {
        return seqHead;
    }

    public Instant createdAt() {
        return createdAt;
    }

    public Instant archivedAt() {
        return archivedAt;
    }

    public boolean archived() {
        return archivedAt != null;
    }

    long allocateSeq() {
        if (archived()) {
            throw new IllegalStateException("Archived conversations are read-only");
        }
        return ++seqHead;
    }

    boolean archive(Instant at) {
        if (archived()) {
            return false;
        }
        archivedAt = at;
        return true;
    }
}
