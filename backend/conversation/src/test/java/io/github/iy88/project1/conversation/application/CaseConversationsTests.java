package io.github.iy88.project1.conversation.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import io.github.iy88.project1.conversation.CaseMessageKind;
import io.github.iy88.project1.conversation.MessageSenderKind;
import io.github.iy88.project1.conversation.persistence.CaseConversation;
import io.github.iy88.project1.conversation.persistence.CaseMessage;
import io.github.iy88.project1.conversation.persistence.ConversationStore;
import io.github.iy88.project1.core.WriteTransaction;
import java.time.Instant;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class CaseConversationsTests {
    private static final Instant NOW = Instant.parse("2026-11-22T10:00:00Z");

    private final ConversationStore store = mock(ConversationStore.class);
    private final CaseConversations caseConversations = new CaseConversations(store);
    private final WriteTransaction transaction = mock(WriteTransaction.class);

    @Test
    void ensureCreatesTheCaseThread() {
        when(store.findCase(9L, 7L)).thenReturn(Optional.empty());
        var conversation = mock(CaseConversation.class);
        when(conversation.id()).thenReturn(1L);
        when(conversation.caseId()).thenReturn(9L);
        when(conversation.relatedAccountId()).thenReturn(7L);
        when(conversation.archivedAt()).thenReturn(null);
        when(store.ensureCase(transaction, 9L, 7L)).thenReturn(conversation);

        var ensured = caseConversations.ensure(transaction, 9L, 7L);

        assertThat(ensured.conversationId()).isEqualTo(1L);
        assertThat(ensured.created()).isTrue();
    }

    @Test
    void findReturnsTheExistingThread() {
        var conversation = mock(CaseConversation.class);
        when(conversation.id()).thenReturn(1L);
        when(conversation.caseId()).thenReturn(9L);
        when(conversation.relatedAccountId()).thenReturn(7L);
        when(conversation.archivedAt()).thenReturn(null);
        when(store.findCase(9L, 7L)).thenReturn(Optional.of(conversation));

        var found = caseConversations.find(9L, 7L);

        assertThat(found).isPresent();
        assertThat(found.orElseThrow().caseId()).isEqualTo(9L);
    }

    @Test
    void appendLocksByCaseAndReturnsMessageIdentity() {
        var conversation = mock(CaseConversation.class);
        when(conversation.id()).thenReturn(1L);
        when(store.lockCaseByCase(transaction, 9L, 7L)).thenReturn(conversation);
        var message = mock(CaseMessage.class);
        when(message.id()).thenReturn(5L);
        when(message.seq()).thenReturn(1L);
        when(message.createdAt()).thenReturn(NOW);
        when(store.appendCaseMessage(transaction, conversation, CaseMessageKind.STATEMENT,
                MessageSenderKind.ACCOUNT, 7L, "说明")).thenReturn(message);

        var appended = caseConversations.append(transaction, 9L, 7L, CaseMessageKind.STATEMENT,
                MessageSenderKind.ACCOUNT, 7L, "说明");

        assertThat(appended.messageId()).isEqualTo(5L);
        assertThat(appended.seq()).isEqualTo(1L);
    }

    @Test
    void appendSystemEventLocksByCase() {
        var conversation = mock(CaseConversation.class);
        when(conversation.id()).thenReturn(1L);
        when(store.lockCaseByCase(transaction, 9L, 7L)).thenReturn(conversation);
        var eventId = UUID.randomUUID();
        var message = mock(CaseMessage.class);
        when(message.id()).thenReturn(6L);
        when(message.seq()).thenReturn(2L);
        when(message.createdAt()).thenReturn(NOW);
        when(store.appendCaseSystemEvent(transaction, conversation, eventId, "case_closed", "已结案"))
                .thenReturn(message);

        var appended = caseConversations.appendSystemEvent(transaction, 9L, 7L, eventId, "case_closed", "已结案");

        assertThat(appended.messageId()).isEqualTo(6L);
    }

    @Test
    void archiveLocksByCase() {
        var conversation = mock(CaseConversation.class);
        when(conversation.id()).thenReturn(1L);
        when(store.lockCaseByCase(transaction, 9L, 7L)).thenReturn(conversation);
        when(store.archiveCase(transaction, conversation)).thenReturn(true);

        assertThat(caseConversations.archive(transaction, 9L, 7L)).isTrue();
        verify(store).archiveCase(transaction, conversation);
    }
}
