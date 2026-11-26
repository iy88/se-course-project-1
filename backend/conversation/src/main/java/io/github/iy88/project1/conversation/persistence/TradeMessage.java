package io.github.iy88.project1.conversation.persistence;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;
import java.util.UUID;

/** Trade messages hold either a participant text or a named system event snapshot. */
@Entity
@Table(name = "trade_message")
public class TradeMessage {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "trade_message_id")
    private Long id;
    private long tradeConversationId;
    private long seq;
    private String senderKind;
    private Long senderAccountId;
    private String messageType;
    private String body;
    private UUID businessEventId;
    private String eventType;
    private String sourceType;
    private Long sourceId;
    private Instant createdAt;

    protected TradeMessage() {
    }

    static TradeMessage text(long conversationId, long seq, long senderAccountId, String body, Instant createdAt) {
        var message = new TradeMessage();
        message.tradeConversationId = conversationId;
        message.seq = seq;
        message.senderKind = "account";
        message.senderAccountId = senderAccountId;
        message.messageType = "text";
        message.body = body;
        message.createdAt = createdAt;
        return message;
    }

    static TradeMessage systemEvent(long conversationId, long seq, UUID businessEventId, String eventType,
                                    String body, String sourceType, Long sourceId, Instant createdAt) {
        var message = new TradeMessage();
        message.tradeConversationId = conversationId;
        message.seq = seq;
        message.senderKind = "system";
        message.messageType = "system_event";
        message.businessEventId = businessEventId;
        message.eventType = eventType;
        message.body = body;
        message.sourceType = sourceType;
        message.sourceId = sourceId;
        message.createdAt = createdAt;
        return message;
    }

    public long id() {
        return id;
    }

    public long conversationId() {
        return tradeConversationId;
    }

    public long seq() {
        return seq;
    }

    public String senderKind() {
        return senderKind;
    }

    public Long senderAccountId() {
        return senderAccountId;
    }

    public String messageType() {
        return messageType;
    }

    public String body() {
        return body;
    }

    public UUID businessEventId() {
        return businessEventId;
    }

    public String eventType() {
        return eventType;
    }

    public String sourceType() {
        return sourceType;
    }

    public Long sourceId() {
        return sourceId;
    }

    public Instant createdAt() {
        return createdAt;
    }
}
