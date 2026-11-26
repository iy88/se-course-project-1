package io.github.iy88.project1.api.cases;

import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import io.github.iy88.project1.casemanagement.CaseVocabulary;
import io.github.iy88.project1.casemanagement.application.CaseRecords;
import io.github.iy88.project1.casemanagement.persistence.CaseLifecycleStore;
import io.github.iy88.project1.conversation.CaseMessageKind;
import io.github.iy88.project1.conversation.MessageSenderKind;
import io.github.iy88.project1.conversation.application.CaseParticipation;
import io.github.iy88.project1.conversation.persistence.CaseConversation;
import io.github.iy88.project1.conversation.persistence.CaseMessage;
import io.github.iy88.project1.conversation.persistence.ConversationStore;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteTransaction;
import java.time.Instant;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class CaseThreadAdapterTests {
    private static final long CASE_ID = 41L;
    private static final long RELATED = 21L;
    private static final long MANAGER = 31L;
    private static final long THREAD_ID = 5L;
    private static final long MESSAGE_ID = 77L;
    private static final Instant NOW = Instant.parse("2026-11-26T00:00:00Z");

    private final ConversationStore conversations = mock(ConversationStore.class);
    private final CaseLifecycleStore store = mock(CaseLifecycleStore.class);
    private final CaseParticipation participation = mock(CaseParticipation.class);
    private final WriteTransaction transaction = mock(WriteTransaction.class);
    private final CaseConversation conversation = mock(CaseConversation.class);
    private final CaseMessage message = mock(CaseMessage.class);
    private final CaseHttpConfiguration.CaseThreadAdapter adapter =
            new CaseHttpConfiguration.CaseThreadAdapter(conversations, store, participation);

    @Test
    void accountMessageNotifiesTheRelatedAccountAndTheCurrentClaimantManager() {
        threadAndMessage();
        when(store.find(CASE_ID)).thenReturn(Optional.of(claimedBy(MANAGER)));
        when(participation.canAccess(CASE_ID, RELATED, MANAGER)).thenReturn(true);
        when(conversations.appendCaseMessage(transaction, conversation, CaseMessageKind.STATEMENT,
                MessageSenderKind.ACCOUNT, RELATED, "说明")).thenReturn(message);

        adapter.append(transaction, CASE_ID, RELATED, CaseVocabulary.KIND_STATEMENT,
                CaseVocabulary.ACTOR_ACCOUNT, RELATED, "说明");

        verify(transaction).addEventIntent(Set.of(RELATED, MANAGER), "message_created", 1,
                new ResourceRef("case_conversation", THREAD_ID), "message_created:case:" + MESSAGE_ID,
                new ResourceRef("case_message", MESSAGE_ID), null);
    }

    @Test
    void messageDoesNotReachAClaimantWhoNoLongerPassesTheCurrentCaseRole() {
        threadAndMessage();
        when(store.find(CASE_ID)).thenReturn(Optional.of(claimedBy(MANAGER)));
        when(participation.canAccess(CASE_ID, RELATED, MANAGER)).thenReturn(false);
        when(conversations.appendCaseMessage(transaction, conversation, CaseMessageKind.INQUIRY,
                MessageSenderKind.MANAGER, MANAGER, "请说明")).thenReturn(message);

        adapter.append(transaction, CASE_ID, RELATED, CaseVocabulary.KIND_INQUIRY,
                CaseVocabulary.ACTOR_MANAGER, MANAGER, "请说明");

        verify(transaction).addEventIntent(Set.of(RELATED), "message_created", 1,
                new ResourceRef("case_conversation", THREAD_ID), "message_created:case:" + MESSAGE_ID,
                new ResourceRef("case_message", MESSAGE_ID), null);
    }

    @Test
    void systemNoticeIsAlsoRegisteredWithoutAnyBodyOrReporterData() {
        threadAndMessage();
        when(store.find(CASE_ID)).thenReturn(Optional.of(claimedBy(MANAGER)));
        when(participation.canAccess(CASE_ID, RELATED, MANAGER)).thenReturn(true);
        when(conversations.appendCaseSystemEvent(eq(transaction), eq(conversation), any(UUID.class),
                eq("case_system_notice"), eq("事项已处置"))).thenReturn(message);

        adapter.append(transaction, CASE_ID, RELATED, CaseVocabulary.KIND_SYSTEM_NOTICE,
                CaseVocabulary.ACTOR_SYSTEM, 0L, "事项已处置");

        verify(transaction).addEventIntent(Set.of(RELATED, MANAGER), "message_created", 1,
                new ResourceRef("case_conversation", THREAD_ID), "message_created:case:" + MESSAGE_ID,
                new ResourceRef("case_message", MESSAGE_ID), null);
    }

    @Test
    void unclaimedThreadOnlyNotifiesItsRelatedAccount() {
        threadAndMessage();
        when(store.find(CASE_ID)).thenReturn(Optional.of(unclaimed()));
        when(conversations.appendCaseMessage(transaction, conversation, CaseMessageKind.STATEMENT,
                MessageSenderKind.ACCOUNT, RELATED, "说明")).thenReturn(message);

        adapter.append(transaction, CASE_ID, RELATED, CaseVocabulary.KIND_STATEMENT,
                CaseVocabulary.ACTOR_ACCOUNT, RELATED, "说明");

        verify(transaction).addEventIntent(Set.of(RELATED), "message_created", 1,
                new ResourceRef("case_conversation", THREAD_ID), "message_created:case:" + MESSAGE_ID,
                new ResourceRef("case_message", MESSAGE_ID), null);
        verify(participation, never()).canAccess(anyLong(), anyLong(), anyLong());
    }

    @Test
    void missingThreadRejectsBeforeWritingOrRegisteringAnEvent() {
        when(conversations.findCase(CASE_ID, RELATED)).thenReturn(Optional.empty());

        assertThatThrownBy(() -> adapter.append(transaction, CASE_ID, RELATED, CaseVocabulary.KIND_STATEMENT,
                CaseVocabulary.ACTOR_ACCOUNT, RELATED, "说明"))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> org.assertj.core.api.Assertions.assertThat(error.code())
                                .isEqualTo("PARTICIPANT_REQUIRED"));
        verify(transaction, never()).addEventIntent(any(), any(), anyInt(), any(), any(), any(), any());
    }

    private void threadAndMessage() {
        when(conversations.findCase(CASE_ID, RELATED)).thenReturn(Optional.of(conversation));
        when(conversation.id()).thenReturn(THREAD_ID);
        when(message.id()).thenReturn(MESSAGE_ID);
    }

    private static CaseRecords.Facts claimedBy(long manager) {
        return new CaseRecords.Facts(CASE_ID, CaseVocabulary.REPORT, "account", RELATED, null, null,
                11L, "虚假信息", manager, NOW, CaseVocabulary.CLAIMED, null, null, null, null, null,
                null, null, null, NOW, NOW);
    }

    private static CaseRecords.Facts unclaimed() {
        return new CaseRecords.Facts(CASE_ID, CaseVocabulary.REPORT, "account", RELATED, null, null,
                11L, "虚假信息", null, null, CaseVocabulary.PENDING, null, null, null, null, null,
                null, null, null, NOW, NOW);
    }
}
