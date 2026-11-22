package io.github.iy88.project1.conversation.persistence;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import io.github.iy88.project1.conversation.ConversationSettings;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.WriteTransaction;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.test.util.ReflectionTestUtils;

class ConversationStoreTests {
    private static final Instant NOW = Instant.parse("2026-11-22T10:00:00Z");

    private final ChatConversationRepository chats = mock(ChatConversationRepository.class);
    private final TradeConversationRepository trades = mock(TradeConversationRepository.class);
    private final CaseConversationRepository cases = mock(CaseConversationRepository.class);
    private final ChatMessageRepository chatMessages = mock(ChatMessageRepository.class);
    private final TradeMessageRepository tradeMessages = mock(TradeMessageRepository.class);
    private final CaseMessageRepository caseMessages = mock(CaseMessageRepository.class);
    private final ChatReadProgressRepository chatProgress = mock(ChatReadProgressRepository.class);
    private final TradeReadProgressRepository tradeProgress = mock(TradeReadProgressRepository.class);
    private final CaseReadProgressRepository caseProgress = mock(CaseReadProgressRepository.class);
    private final WriteTransaction transaction = mock(WriteTransaction.class);
    private final ConversationStore store = new ConversationStore(chats, trades, cases, chatMessages, tradeMessages,
            caseMessages, chatProgress, tradeProgress, caseProgress, mock(JdbcClient.class),
            new ConversationSettings(), Clock.fixed(NOW, ZoneOffset.UTC));

    @BeforeEach
    void echoSavedMessages() {
        when(chatMessages.save(any())).thenAnswer(call -> call.getArgument(0));
        when(tradeMessages.save(any())).thenAnswer(call -> call.getArgument(0));
        when(caseMessages.save(any())).thenAnswer(call -> call.getArgument(0));
    }

    @Test
    void rejectsBlankChatBodyWithoutAllocatingASequence() {
        var conversation = persisted(new ChatConversation(7L, 42L, NOW), 1L);

        assertThatThrownBy(() -> store.appendChatText(transaction, conversation, 7L, "  "))
                .isInstanceOfSatisfying(BusinessError.class,
                        failure -> assertThat(failure.code()).isEqualTo("INPUT_INVALID"));

        assertThat(conversation.seqHead()).isZero();
        verify(chatMessages, never()).save(any());
    }

    @Test
    void allocatesContiguousChatSequencesForParticipants() {
        var conversation = persisted(new ChatConversation(7L, 42L, NOW), 1L);

        var first = store.appendChatText(transaction, conversation, 7L, "hello");
        var second = store.appendChatText(transaction, conversation, 42L, "hi");

        assertThat(first.seq()).isEqualTo(1L);
        assertThat(second.seq()).isEqualTo(2L);
        assertThat(conversation.seqHead()).isEqualTo(2L);
    }

    @Test
    void rejectsMessagesFromAccountsOutsideTheChat() {
        var conversation = persisted(new ChatConversation(7L, 42L, NOW), 1L);

        assertThatThrownBy(() -> store.appendChatText(transaction, conversation, 9L, "hello"))
                .isInstanceOfSatisfying(BusinessError.class,
                        failure -> assertThat(failure.code()).isEqualTo("PARTICIPANT_REQUIRED"));
    }

    @Test
    void archivedTradeConversationRejectsNewMessages() {
        var conversation = persisted(new TradeConversation(11L, NOW), 1L);
        conversation.archive(NOW);

        assertThatThrownBy(() -> store.appendTradeText(transaction, conversation, 7L, "hello"))
                .isInstanceOfSatisfying(BusinessError.class,
                        failure -> assertThat(failure.code()).isEqualTo("BRANCH_ARCHIVED"));
    }

    @Test
    void repeatedSystemEventReturnsThePersistedMessage() {
        var conversation = persisted(new TradeConversation(11L, NOW), 1L);
        var eventId = UUID.randomUUID();
        var existing = TradeMessage.systemEvent(1L, 1L, eventId, "trade_completed", "交易已完成",
                null, null, NOW);
        when(tradeMessages.findByBusinessEventId(eventId)).thenReturn(Optional.of(existing));

        var message = store.appendTradeSystemEvent(transaction, conversation, eventId, "trade_completed",
                "交易已完成", null, null);

        assertThat(message).isSameAs(existing);
        assertThat(conversation.seqHead()).isZero();
        verify(tradeMessages, never()).save(any());
    }

    @Test
    void readProgressKeepsTheLargestDisplayedSequence() {
        var conversation = persisted(new ChatConversation(7L, 42L, NOW), 1L);
        for (int index = 0; index < 3; index++) {
            conversation.allocateSeq();
        }
        var progress = new ChatReadProgress(1L, 7L);
        progress.advanceTo(2L, NOW);
        when(chatProgress.lockByConversationAndAccount(1L, 7L)).thenReturn(Optional.of(progress));
        when(chatProgress.save(any())).thenAnswer(call -> call.getArgument(0));

        store.advanceChatRead(transaction, conversation, 7L, 1L);

        assertThat(progress.lastReadSeq()).isEqualTo(2L);
    }

    @Test
    void readProgressRejectsSequencesBeyondTheHead() {
        var conversation = persisted(new ChatConversation(7L, 42L, NOW), 1L);

        assertThatThrownBy(() -> store.advanceChatRead(transaction, conversation, 7L, 1L))
                .isInstanceOfSatisfying(BusinessError.class,
                        failure -> assertThat(failure.code()).isEqualTo("INPUT_INVALID"));
    }

    private static <T> T persisted(T entity, long id) {
        ReflectionTestUtils.setField(entity, "id", id);
        return entity;
    }
}
