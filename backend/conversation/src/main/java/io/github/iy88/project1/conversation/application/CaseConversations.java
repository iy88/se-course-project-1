package io.github.iy88.project1.conversation.application;

import io.github.iy88.project1.conversation.CaseMessageKind;
import io.github.iy88.project1.conversation.MessageSenderKind;
import io.github.iy88.project1.conversation.persistence.CaseConversation;
import io.github.iy88.project1.conversation.persistence.CaseMessage;
import io.github.iy88.project1.conversation.persistence.ConversationStore;
import io.github.iy88.project1.core.WriteTransaction;
import java.time.Instant;
import java.util.Optional;
import java.util.UUID;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Service;

/**
 * Case-facing conversation capability. The case module owns the claim, inquiry and appeal rules;
 * this facade only maintains the thread attached to a case and related account.
 */
@Service
@Profile("infrastructure")
public class CaseConversations {
    private final ConversationStore store;

    public CaseConversations(ConversationStore store) {
        this.store = store;
    }

    public record Ensured(long conversationId, boolean created) {
    }

    public record Conversation(long conversationId, long caseId, long relatedAccountId, Instant archivedAt) {
    }

    public record Message(long messageId, long seq, Instant createdAt) {
    }

    public Ensured ensure(WriteTransaction transaction, long caseId, long relatedAccountId) {
        boolean existed = store.findCase(caseId, relatedAccountId).isPresent();
        var conversation = store.ensureCase(transaction, caseId, relatedAccountId);
        return new Ensured(conversation.id(), !existed);
    }

    public Optional<Conversation> find(long caseId, long relatedAccountId) {
        return store.findCase(caseId, relatedAccountId).map(CaseConversations::view);
    }

    public Conversation lock(WriteTransaction transaction, long conversationId) {
        return view(store.lockCase(transaction, conversationId));
    }

    public Conversation lockByCase(WriteTransaction transaction, long caseId, long relatedAccountId) {
        return view(store.lockCaseByCase(transaction, caseId, relatedAccountId));
    }

    public Message append(WriteTransaction transaction, long caseId, long relatedAccountId, CaseMessageKind kind,
                          MessageSenderKind senderKind, long senderAccountId, String body) {
        var conversation = store.lockCaseByCase(transaction, caseId, relatedAccountId);
        return message(store.appendCaseMessage(transaction, conversation, kind, senderKind, senderAccountId, body));
    }

    public Message appendSystemEvent(WriteTransaction transaction, long caseId, long relatedAccountId,
                                     UUID businessEventId, String eventType, String body) {
        var conversation = store.lockCaseByCase(transaction, caseId, relatedAccountId);
        return message(store.appendCaseSystemEvent(transaction, conversation, businessEventId, eventType, body));
    }

    public boolean archive(WriteTransaction transaction, long caseId, long relatedAccountId) {
        var conversation = store.lockCaseByCase(transaction, caseId, relatedAccountId);
        return store.archiveCase(transaction, conversation);
    }

    private static Conversation view(CaseConversation conversation) {
        return new Conversation(conversation.id(), conversation.caseId(), conversation.relatedAccountId(),
                conversation.archivedAt());
    }

    private static Message message(CaseMessage message) {
        return new Message(message.id(), message.seq(), message.createdAt());
    }
}
