package io.github.iy88.project1.api.conversation;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import io.github.iy88.project1.conversation.application.CaseConversations;
import io.github.iy88.project1.conversation.application.CaseParticipation;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteTransaction;
import java.time.Instant;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class CaseReadUseCaseTests {
    private static final long THREAD_ID = 5L;
    private static final long MANAGER = 31L;
    private static final long RELATED = 21L;
    private static final Instant NOW = Instant.parse("2026-11-26T00:00:00Z");

    private final CaseConversations cases = mock(CaseConversations.class);
    private final CaseParticipation participation = mock(CaseParticipation.class);
    private final WriteTransaction transaction = mock(WriteTransaction.class);
    private final WriteBackedConversationCommands.CaseReadUseCase useCase =
            new WriteBackedConversationCommands.CaseReadUseCase(cases, participation);

    @Test
    void prepareOrderDeclaresTheCaseThreadThenTheActorsOwnProgressRow() {
        var plan = useCase.prepare(context(MANAGER), request(2L));

        assertThat(plan.resources()).containsExactlyInAnyOrder(
                new LockPlan.Key(LockPlan.Domain.CASE_CONVERSATION, List.of(THREAD_ID)),
                new LockPlan.Key(LockPlan.Domain.READ_PROGRESS, List.of(THREAD_ID, MANAGER)));
    }

    @Test
    void actualProgressRegistersMessageReadForTheReaderOnly() {
        var operationId = UUID.randomUUID();
        when(transaction.context()).thenReturn(context(MANAGER));
        when(transaction.operationId()).thenReturn(operationId);
        when(cases.advanceRead(transaction, THREAD_ID, MANAGER, 2L, participation))
                .thenReturn(new CaseConversations.ReadProgress(2L, 1L, NOW, true));

        var response = useCase.write(transaction, request(2L), request(2L), plan());

        assertThat(response.status()).isEqualTo(200);
        verify(transaction).addEventIntent(Set.of(MANAGER), "message_read", 1,
                new ResourceRef("case_conversation", THREAD_ID), "message_read:" + operationId, null, 2L);
    }

    @Test
    void repeatedOrOlderReadDoesNotRegisterAnotherMessageRead() {
        when(transaction.context()).thenReturn(context(RELATED));
        when(cases.advanceRead(transaction, THREAD_ID, RELATED, 1L, participation))
                .thenReturn(new CaseConversations.ReadProgress(2L, 0L, NOW, false));

        var response = useCase.write(transaction, request(1L), request(1L), plan());

        assertThat(response.status()).isEqualTo(200);
        verify(transaction, never()).addEventIntent(any(), any(), anyInt(), any(), any(), any(), any());
    }

    @Test
    void failedCaseQualificationRegistersNothing() {
        when(transaction.context()).thenReturn(context(RELATED));
        when(cases.advanceRead(transaction, THREAD_ID, RELATED, 2L, participation))
                .thenThrow(new BusinessError("PARTICIPANT_REQUIRED", 404, "会话不存在或无权访问"));

        assertThatThrownBy(() -> useCase.write(transaction, request(2L), request(2L), plan()))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("PARTICIPANT_REQUIRED"));
        verify(transaction, never()).addEventIntent(any(), any(), anyInt(), any(), any(), any(), any());
    }

    @Test
    void managerReadUsesTheManagerAccountAndNeverTheRelatedAccount() {
        when(transaction.context()).thenReturn(context(MANAGER));
        when(transaction.operationId()).thenReturn(UUID.randomUUID());
        when(cases.advanceRead(transaction, THREAD_ID, MANAGER, 3L, participation))
                .thenReturn(new CaseConversations.ReadProgress(3L, 2L, NOW, true));

        useCase.write(transaction, request(3L), request(3L), plan());

        verify(transaction).addEventIntent(Set.of(MANAGER), "message_read", 1,
                new ResourceRef("case_conversation", THREAD_ID),
                "message_read:" + transaction.operationId(), null, 3L);
        verify(cases).advanceRead(transaction, THREAD_ID, MANAGER, 3L, participation);
        verify(cases, never()).advanceRead(any(), anyLong(), eq(RELATED), anyLong(), any());
    }

    private static WriteBackedConversationCommands.CaseReadRequest request(long displayedSeq) {
        return new WriteBackedConversationCommands.CaseReadRequest(THREAD_ID, displayedSeq);
    }

    private static LockPlan plan() {
        return new LockPlan(java.util.Map.of(), Set.of());
    }

    private static ExecutionContext context(long actor) {
        return new ExecutionContext(UUID.randomUUID(), ExecutionContext.ActorKind.ACCOUNT,
                Long.toString(actor), UUID.randomUUID(), null, 1L, "test");
    }
}
