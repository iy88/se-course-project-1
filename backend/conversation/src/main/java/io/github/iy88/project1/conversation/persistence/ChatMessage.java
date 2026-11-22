package io.github.iy88.project1.conversation.persistence;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;

/** Chat messages are immutable and belong to exactly one chat conversation. */
@Entity
@Table(name = "chat_message")
public class ChatMessage {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "chat_message_id")
    private Long id;
    private long chatConversationId;
    private long seq;
    private long senderAccountId;
    private String body;
    private Instant createdAt;

    protected ChatMessage() {
    }

    ChatMessage(long chatConversationId, long seq, long senderAccountId, String body, Instant createdAt) {
        this.chatConversationId = chatConversationId;
        this.seq = seq;
        this.senderAccountId = senderAccountId;
        this.body = body;
        this.createdAt = createdAt;
    }

    public long id() {
        return id;
    }

    public long conversationId() {
        return chatConversationId;
    }

    public long seq() {
        return seq;
    }

    public long senderAccountId() {
        return senderAccountId;
    }

    public String body() {
        return body;
    }

    public Instant createdAt() {
        return createdAt;
    }
}
