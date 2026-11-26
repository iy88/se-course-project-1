package io.github.iy88.project1.api.realtime;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import io.github.iy88.project1.conversation.application.CaseParticipation;
import io.github.iy88.project1.conversation.application.TradeParticipation;
import io.github.iy88.project1.conversation.persistence.CaseConversation;
import io.github.iy88.project1.conversation.persistence.CaseMessage;
import io.github.iy88.project1.conversation.persistence.ConversationReader;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.messaging.RealtimeEventSources.ConversationKind;
import io.github.iy88.project1.messaging.RealtimeEventSources.ConversationRef;
import java.time.Instant;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class ConversationRealtimeProjectionTests {
    private static final long THREAD_ID = 7L;
    private static final long CASE_ID = 9L;
    private static final long RELATED = 21L;
    private static final long MANAGER = 31L;

    private final ConversationReader reader = mock(ConversationReader.class);
    private final TradeParticipation trades = mock(TradeParticipation.class);
    private final CaseParticipation cases = mock(CaseParticipation.class);
    private final ConversationRealtimeProjection projection =
            new ConversationRealtimeProjection(reader, trades, cases);

    @Test
    void relatedAccountCanReadTheCaseThreadAndItsMessage() {
        caseThread();
        var businessEventId = UUID.randomUUID();
        var message = mock(CaseMessage.class);
        when(message.seq()).thenReturn(3L);
        when(message.businessEventId()).thenReturn(businessEventId);
        when(cases.canAccess(CASE_ID, RELATED, RELATED)).thenReturn(true);
        when(reader.findCaseMessage(THREAD_ID, 8L)).thenReturn(Optional.of(message));

        var conversation = new ConversationRef(ConversationKind.CASE, THREAD_ID);
        assertThat(projection.canRead(context(RELATED), conversation)).isTrue();
        assertThat(projection.readMessage(context(RELATED), conversation, 8L))
                .contains(new io.github.iy88.project1.messaging.RealtimeEventSources.MessageHint(3L, businessEventId));
    }

    @Test
    void currentClaimantManagerCanReadTheCaseThread() {
        caseThread();
        when(cases.canAccess(CASE_ID, RELATED, MANAGER)).thenReturn(true);

        assertThat(projection.canRead(context(MANAGER), new ConversationRef(ConversationKind.CASE, THREAD_ID)))
                .isTrue();
        verify(cases).canAccess(CASE_ID, RELATED, MANAGER);
    }

    @Test
    void claimantWhoseRoleOrClaimChangedIsSuppressedOnReplay() {
        caseThread();
        when(cases.canAccess(CASE_ID, RELATED, MANAGER)).thenReturn(false);

        assertThat(projection.canRead(context(MANAGER), new ConversationRef(ConversationKind.CASE, THREAD_ID)))
                .isFalse();
    }

    @Test
    void otherThreadsAndForeignMessagesStayHidden() {
        caseThread();
        when(cases.canAccess(CASE_ID, RELATED, 99L)).thenReturn(false);

        var conversation = new ConversationRef(ConversationKind.CASE, THREAD_ID);
        assertThat(projection.canRead(context(99L), conversation)).isFalse();
        assertThat(projection.readMessage(context(99L), conversation, 8L)).isEmpty();
        verify(reader, never()).findCaseMessage(THREAD_ID, 8L);
    }

    private void caseThread() {
        var thread = mock(CaseConversation.class);
        when(thread.caseId()).thenReturn(CASE_ID);
        when(thread.relatedAccountId()).thenReturn(RELATED);
        when(thread.archivedAt()).thenReturn(Instant.parse("2026-11-26T00:00:00Z"));
        when(reader.findCase(THREAD_ID)).thenReturn(Optional.of(thread));
    }

    private static ExecutionContext context(long actor) {
        return new ExecutionContext(UUID.randomUUID(), ExecutionContext.ActorKind.ACCOUNT,
                Long.toString(actor), UUID.randomUUID(), null, 1L, "test");
    }
}
