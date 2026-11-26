package io.github.iy88.project1.conversation.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import io.github.iy88.project1.conversation.CaseMessageKind;
import io.github.iy88.project1.conversation.MessageSenderKind;
import io.github.iy88.project1.conversation.persistence.CaseConversation;
import io.github.iy88.project1.conversation.persistence.CaseMessage;
import io.github.iy88.project1.conversation.persistence.CaseReadProgress;
import io.github.iy88.project1.conversation.persistence.ConversationStore;
import io.github.iy88.project1.core.BusinessError;
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

    @Test
    void relatedAccountReadLocksTheThreadAndReportsActualProgress() {
        var conversation = mock(CaseConversation.class);
        when(conversation.id()).thenReturn(1L);
        when(conversation.caseId()).thenReturn(9L);
        when(conversation.relatedAccountId()).thenReturn(7L);
        when(store.lockCase(transaction, 1L)).thenReturn(conversation);
        var participation = mock(CaseParticipation.class);
        when(participation.canAccess(9L, 7L, 7L)).thenReturn(true);
        var progress = mock(CaseReadProgress.class);
        when(progress.lastReadSeq()).thenReturn(4L);
        when(progress.lastReadAt()).thenReturn(NOW);
        when(store.advanceCaseRead(transaction, conversation, 7L, 4L))
                .thenReturn(new ConversationStore.CaseReadAdvance(progress, true));
        when(store.caseUnread(conversation, 7L)).thenReturn(2L);

        var read = caseConversations.advanceRead(transaction, 1L, 7L, 4L, participation);

        assertThat(read.lastReadSeq()).isEqualTo(4L);
        assertThat(read.unreadCount()).isEqualTo(2L);
        assertThat(read.updatedAt()).isEqualTo(NOW);
        assertThat(read.advanced()).isTrue();
        verify(store).lockCase(transaction, 1L);
        verify(participation).canAccess(9L, 7L, 7L);
    }

    @Test
    void currentClaimantManagerReadsAndPersistsUnderTheManagerAccount() {
        var conversation = mock(CaseConversation.class);
        when(conversation.id()).thenReturn(1L);
        when(conversation.caseId()).thenReturn(9L);
        when(conversation.relatedAccountId()).thenReturn(7L);
        when(store.lockCase(transaction, 1L)).thenReturn(conversation);
        var participation = mock(CaseParticipation.class);
        when(participation.canAccess(9L, 7L, 31L)).thenReturn(true);
        var progress = mock(CaseReadProgress.class);
        when(progress.lastReadSeq()).thenReturn(2L);
        when(progress.lastReadAt()).thenReturn(NOW);
        when(store.advanceCaseRead(transaction, conversation, 31L, 2L))
                .thenReturn(new ConversationStore.CaseReadAdvance(progress, false));
        when(store.caseUnread(conversation, 31L)).thenReturn(0L);

        var read = caseConversations.advanceRead(transaction, 1L, 31L, 2L, participation);

        assertThat(read.lastReadSeq()).isEqualTo(2L);
        assertThat(read.advanced()).isFalse();
        verify(store).advanceCaseRead(transaction, conversation, 31L, 2L);
    }

    @Test
    void readRejectsAnAccountThatNoLongerPassesTheCaseQualification() {
        var conversation = mock(CaseConversation.class);
        when(conversation.id()).thenReturn(1L);
        when(conversation.caseId()).thenReturn(9L);
        when(conversation.relatedAccountId()).thenReturn(7L);
        when(store.lockCase(transaction, 1L)).thenReturn(conversation);
        var participation = mock(CaseParticipation.class);
        when(participation.canAccess(9L, 7L, 31L)).thenReturn(false);

        assertThatThrownBy(() -> caseConversations.advanceRead(transaction, 1L, 31L, 2L, participation))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("PARTICIPANT_REQUIRED"));
        verify(store, never()).advanceCaseRead(any(), any(), anyLong(), anyLong());
    }

    @Test
    void archivedThreadStillAdvancesTheReadersOwnProgress() {
        var conversation = mock(CaseConversation.class);
        when(conversation.id()).thenReturn(1L);
        when(conversation.caseId()).thenReturn(9L);
        when(conversation.relatedAccountId()).thenReturn(7L);
        when(conversation.archived()).thenReturn(true);
        when(store.lockCase(transaction, 1L)).thenReturn(conversation);
        var participation = mock(CaseParticipation.class);
        when(participation.canAccess(9L, 7L, 7L)).thenReturn(true);
        var progress = mock(CaseReadProgress.class);
        when(progress.lastReadSeq()).thenReturn(5L);
        when(progress.lastReadAt()).thenReturn(NOW);
        when(store.advanceCaseRead(transaction, conversation, 7L, 5L))
                .thenReturn(new ConversationStore.CaseReadAdvance(progress, true));
        when(store.caseUnread(conversation, 7L)).thenReturn(0L);

        var read = caseConversations.advanceRead(transaction, 1L, 7L, 5L, participation);

        assertThat(read.lastReadSeq()).isEqualTo(5L);
        verify(store).advanceCaseRead(transaction, conversation, 7L, 5L);
    }
}
