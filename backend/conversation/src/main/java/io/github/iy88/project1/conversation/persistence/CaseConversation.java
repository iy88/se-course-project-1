package io.github.iy88.project1.conversation.persistence;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;

/** One thread per case and related account; the claimed manager is validated at read time. */
@Entity
@Table(name = "case_conversation")
public class CaseConversation {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "case_conversation_id")
    private Long id;
    private long caseId;
    private long relatedAccountId;
    private long seqHead;
    private Instant createdAt;
    private Instant archivedAt;

    protected CaseConversation() {
    }

    CaseConversation(long caseId, long relatedAccountId, Instant createdAt) {
        if (caseId <= 0 || relatedAccountId <= 0) {
            throw new IllegalArgumentException("Case and related account must be positive");
        }
        this.caseId = caseId;
        this.relatedAccountId = relatedAccountId;
        this.createdAt = createdAt;
    }

    public long id() {
        return id;
    }

    public long caseId() {
        return caseId;
    }

    public long relatedAccountId() {
        return relatedAccountId;
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
