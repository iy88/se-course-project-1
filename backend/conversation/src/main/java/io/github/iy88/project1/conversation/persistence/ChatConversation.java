package io.github.iy88.project1.conversation.persistence;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;

@Entity
@Table(name = "chat_conversation")
public class ChatConversation {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "chat_conversation_id")
    private Long id;
    private long accountLowId;
    private long accountHighId;
    private long seqHead;
    private Instant createdAt;

    protected ChatConversation() {
    }

    ChatConversation(long accountLowId, long accountHighId, Instant createdAt) {
        if (accountLowId <= 0 || accountHighId <= accountLowId) {
            throw new IllegalArgumentException("Chat participants must be ordered and distinct");
        }
        this.accountLowId = accountLowId;
        this.accountHighId = accountHighId;
        this.createdAt = createdAt;
    }

    public long id() {
        return id;
    }

    public long accountLowId() {
        return accountLowId;
    }

    public long accountHighId() {
        return accountHighId;
    }

    public long seqHead() {
        return seqHead;
    }

    public Instant createdAt() {
        return createdAt;
    }

    public boolean involves(long accountId) {
        return accountId == accountLowId || accountId == accountHighId;
    }

    public long otherAccount(long accountId) {
        if (accountId == accountLowId) {
            return accountHighId;
        }
        if (accountId == accountHighId) {
            return accountLowId;
        }
        throw new IllegalArgumentException("Account does not participate in this conversation");
    }

    long allocateSeq() {
        if (seqHead == Long.MAX_VALUE) {
            throw new IllegalStateException("Conversation sequence exhausted");
        }
        return ++seqHead;
    }
}
