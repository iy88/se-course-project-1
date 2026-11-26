package io.github.iy88.project1.conversation.persistence;

import io.github.iy88.project1.conversation.CaseMessageKind;
import io.github.iy88.project1.conversation.MessageSenderKind;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;
import java.util.UUID;

/** Case messages keep the speaking role and the case thread projection. */
@Entity
@Table(name = "case_message")
public class CaseMessage {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "case_message_id")
    private Long id;
    private long caseConversationId;
    private long seq;
    private String messageKind;
    private String senderKind;
    private Long senderAccountId;
    private String body;
    private UUID businessEventId;
    private String eventType;
    private Instant createdAt;

    protected CaseMessage() {
    }

    static CaseMessage participant(long conversationId, long seq, CaseMessageKind kind, MessageSenderKind senderKind,
                                   long senderAccountId, String body, Instant createdAt) {
        var message = new CaseMessage();
        message.caseConversationId = conversationId;
        message.seq = seq;
        message.messageKind = kind.name().toLowerCase(java.util.Locale.ROOT);
        message.senderKind = senderKind.name().toLowerCase(java.util.Locale.ROOT);
        message.senderAccountId = senderAccountId;
        message.body = body;
        message.createdAt = createdAt;
        return message;
    }

    static CaseMessage systemNotice(long conversationId, long seq, UUID businessEventId, String eventType,
                                    String body, Instant createdAt) {
        var message = new CaseMessage();
        message.caseConversationId = conversationId;
        message.seq = seq;
        message.messageKind = "system_notice";
        message.senderKind = "system";
        message.businessEventId = businessEventId;
        message.eventType = eventType;
        message.body = body;
        message.createdAt = createdAt;
        return message;
    }

    public long id() {
        return id;
    }

    public long conversationId() {
        return caseConversationId;
    }

    public long seq() {
        return seq;
    }

    public String messageKind() {
        return messageKind;
    }

    public String senderKind() {
        return senderKind;
    }

    public Long senderAccountId() {
        return senderAccountId;
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

    public Instant createdAt() {
        return createdAt;
    }
}
