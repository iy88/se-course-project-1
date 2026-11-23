package io.github.iy88.project1.conversation.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import io.github.iy88.project1.conversation.ConversationSettings;
import io.github.iy88.project1.conversation.persistence.CaseConversation;
import io.github.iy88.project1.conversation.persistence.CaseMessage;
import io.github.iy88.project1.conversation.persistence.ConversationReader;
import io.github.iy88.project1.conversation.persistence.ConversationStore;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class ConversationCasePageTests {
    private static final Instant NOW = Instant.parse("2026-11-22T10:00:00Z");

    private final ConversationStore store = mock(ConversationStore.class);
    private final ConversationReader reader = mock(ConversationReader.class);
    private final AccountDirectory accounts = mock(AccountDirectory.class);
    private final CaseParticipation cases = mock(CaseParticipation.class);
    private final CaseConversationQueries queries = new CaseConversationQueries(store, reader, accounts, cases,
            new ConversationSettings());

    @Test
    void pagesCaseThreadWithRoleProjection() {
        var conversation = caseConversation(3L, 9L, 7L);
        when(store.caseConversation(3L)).thenReturn(conversation);
        when(cases.canAccess(9L, 7L, 7L)).thenReturn(true);

        var inquiry = caseMessage(30L, 1L, "manager", 99L, "inquiry", "请说明情况", null);
        var statement = caseMessage(31L, 2L, "account", 7L, "statement", "这是我的说明", null);
        var notice = caseMessage(32L, 3L, "system", null, "system_notice", "事项已结案", "case_closed");
        when(reader.caseMessages(3L, null, null, 20)).thenReturn(List.of(inquiry, statement, notice));
        when(accounts.profiles(java.util.Set.of(7L, 99L))).thenReturn(Map.of(
                7L, new AccountDirectory.Profile(7L, "张新悦"),
                99L, new AccountDirectory.Profile(99L, "管理员甲")));

        var page = queries.pageCase(actor(7L), 3L, null, null, 20);

        assertThat(page.items()).hasSize(3);
        assertThat(page.items().getFirst().sender().senderKind()).isEqualTo("manager");
        assertThat(page.items().getFirst().sender().displayName()).isEqualTo("管理员");
        assertThat(page.items().getFirst().messageType()).isEqualTo("inquiry");
        assertThat(page.items().get(1).sender().displayName()).isEqualTo("张新悦");
        assertThat(page.items().getLast().sender().displayName()).isEqualTo("系统");
        assertThat(page.items().getLast().eventType()).isEqualTo("case_closed");
        assertThat(page.branchStatus()).isEqualTo("active");
        assertThat(page.nextBeforeSeq()).isEqualTo(1L);
        assertThat(page.nextAfterSeq()).isEqualTo(3L);
    }

    @Test
    void rejectsAccountsWithoutCaseAccess() {
        var conversation = caseConversation(3L, 9L, 7L);
        when(store.caseConversation(3L)).thenReturn(conversation);
        when(cases.canAccess(9L, 7L, 8L)).thenReturn(false);

        assertThatThrownBy(() -> queries.pageCase(actor(8L), 3L, null, null, 20))
                .isInstanceOfSatisfying(BusinessError.class,
                        failure -> assertThat(failure.code()).isEqualTo("PARTICIPANT_REQUIRED"));
        verify(cases).canAccess(9L, 7L, 8L);
        verifyNoInteractions(reader, accounts);
    }

    @Test
    void deniesPeerThreadsOfTheSameCaseSeparately() {
        var own = caseConversation(3L, 9L, 7L);
        var peer = caseConversation(4L, 9L, 8L);
        when(store.caseConversation(3L)).thenReturn(own);
        when(store.caseConversation(4L)).thenReturn(peer);
        when(cases.canAccess(9L, 7L, 7L)).thenReturn(true);
        when(cases.canAccess(9L, 8L, 7L)).thenReturn(false);
        when(reader.caseMessages(3L, null, null, 20)).thenReturn(List.of());
        when(accounts.profiles(java.util.Set.of())).thenReturn(Map.of());

        assertThat(queries.pageCase(actor(7L), 3L, null, null, 20).items()).isEmpty();
        assertThatThrownBy(() -> queries.pageCase(actor(7L), 4L, null, null, 20))
                .isInstanceOfSatisfying(BusinessError.class,
                        failure -> assertThat(failure.code()).isEqualTo("PARTICIPANT_REQUIRED"));
        verify(reader, never()).caseMessages(4L, null, null, 20);
    }

    @Test
    void allowsEligibleAssignedManager() {
        var conversation = caseConversation(3L, 9L, 7L);
        when(store.caseConversation(3L)).thenReturn(conversation);
        when(cases.canAccess(9L, 7L, 99L)).thenReturn(true);
        when(reader.caseMessages(3L, null, null, 20)).thenReturn(List.of());
        when(accounts.profiles(java.util.Set.of())).thenReturn(Map.of());

        var page = queries.pageCase(actor(99L), 3L, null, null, 20);

        assertThat(page.items()).isEmpty();
    }

    private static CaseConversation caseConversation(long id, long caseId, long relatedAccountId) {
        var conversation = mock(CaseConversation.class);
        when(conversation.id()).thenReturn(id);
        when(conversation.caseId()).thenReturn(caseId);
        when(conversation.relatedAccountId()).thenReturn(relatedAccountId);
        when(conversation.archived()).thenReturn(false);
        return conversation;
    }

    @Test
    void bindsAccessToTheSpecificCaseThread() {
        var threadForSeven = caseConversation(3L, 9L, 7L);
        var threadForEight = caseConversation(4L, 9L, 8L);
        when(store.caseConversation(3L)).thenReturn(threadForSeven);
        when(store.caseConversation(4L)).thenReturn(threadForEight);
        when(cases.canAccess(9L, 7L, 7L)).thenReturn(true);
        when(cases.canAccess(9L, 8L, 8L)).thenReturn(true);
        var sevenMessage = caseMessage(30L, 1L, "account", 7L, "statement", "七号的线程", null);
        var eightMessage = caseMessage(40L, 1L, "account", 8L, "statement", "八号的线程", null);
        when(reader.caseMessages(3L, null, null, 20)).thenReturn(List.of(sevenMessage));
        when(reader.caseMessages(4L, null, null, 20)).thenReturn(List.of(eightMessage));
        when(accounts.profiles(java.util.Set.of(7L))).thenReturn(Map.of(
                7L, new AccountDirectory.Profile(7L, "张新悦")));
        when(accounts.profiles(java.util.Set.of(8L))).thenReturn(Map.of(
                8L, new AccountDirectory.Profile(8L, "李四")));

        var sevenPage = queries.pageCase(actor(7L), 3L, null, null, 20);
        var eightPage = queries.pageCase(actor(8L), 4L, null, null, 20);

        assertThat(sevenPage.items()).extracting(ConversationViews.Message::body)
                .containsExactly("七号的线程");
        assertThat(eightPage.items()).extracting(ConversationViews.Message::body)
                .containsExactly("八号的线程");
        assertThatThrownBy(() -> queries.pageCase(actor(7L), 4L, null, null, 20))
                .isInstanceOfSatisfying(BusinessError.class,
                        failure -> assertThat(failure.code()).isEqualTo("PARTICIPANT_REQUIRED"));
    }

    private static CaseMessage caseMessage(long id, long seq, String senderKind, Long senderAccountId,
                                           String messageKind, String body, String eventType) {
        var message = mock(CaseMessage.class);
        when(message.id()).thenReturn(id);
        when(message.seq()).thenReturn(seq);
        when(message.senderKind()).thenReturn(senderKind);
        when(message.senderAccountId()).thenReturn(senderAccountId);
        when(message.messageKind()).thenReturn(messageKind);
        when(message.body()).thenReturn(body);
        when(message.eventType()).thenReturn(eventType);
        when(message.createdAt()).thenReturn(NOW);
        return message;
    }

    private static ExecutionContext actor(long accountId) {
        return new ExecutionContext(UUID.randomUUID(), ExecutionContext.ActorKind.ACCOUNT, Long.toString(accountId),
                UUID.randomUUID(), null, 1L, "s1-v1");
    }
}
