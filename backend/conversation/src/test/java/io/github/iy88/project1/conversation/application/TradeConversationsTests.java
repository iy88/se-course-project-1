package io.github.iy88.project1.conversation.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import io.github.iy88.project1.conversation.persistence.ConversationStore;
import io.github.iy88.project1.conversation.persistence.TradeConversation;
import io.github.iy88.project1.conversation.persistence.TradeMessage;
import io.github.iy88.project1.core.WriteTransaction;
import java.time.Instant;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class TradeConversationsTests {
    private static final Instant NOW = Instant.parse("2026-11-22T10:00:00Z");

    private final ConversationStore store = mock(ConversationStore.class);
    private final TradeConversations tradeConversations = new TradeConversations(store);
    private final WriteTransaction transaction = mock(WriteTransaction.class);

    @Test
    void ensureCreatesTheTradeConversation() {
        when(store.findTrade(9L)).thenReturn(Optional.empty());
        var conversation = mock(TradeConversation.class);
        when(conversation.id()).thenReturn(1L);
        when(conversation.tradeId()).thenReturn(9L);
        when(store.ensureTrade(transaction, 9L, 7L, 42L)).thenReturn(conversation);

        var ensured = tradeConversations.ensure(transaction, 9L, 7L, 42L);

        assertThat(ensured.conversationId()).isEqualTo(1L);
        assertThat(ensured.created()).isTrue();
    }

    @Test
    void ensureReportsExistingConversation() {
        var existing = mock(TradeConversation.class);
        when(store.findTrade(9L)).thenReturn(Optional.of(existing));
        var conversation = mock(TradeConversation.class);
        when(conversation.id()).thenReturn(1L);
        when(store.ensureTrade(transaction, 9L, 7L, 42L)).thenReturn(conversation);

        var ensured = tradeConversations.ensure(transaction, 9L, 7L, 42L);

        assertThat(ensured.created()).isFalse();
    }

    @Test
    void appendTextLocksByTradeAndReturnsMessageIdentity() {
        var conversation = tradeConversation();
        when(store.lockTradeByTradeId(transaction, 9L)).thenReturn(conversation);
        var message = mock(TradeMessage.class);
        when(message.id()).thenReturn(5L);
        when(message.seq()).thenReturn(1L);
        when(message.createdAt()).thenReturn(NOW);
        when(store.appendTradeText(transaction, conversation, 7L, "hello")).thenReturn(message);

        var appended = tradeConversations.appendText(transaction, 9L, 7L, "hello");

        assertThat(appended.messageId()).isEqualTo(5L);
        assertThat(appended.seq()).isEqualTo(1L);
    }

    @Test
    void appendSystemEventLocksByTrade() {
        var conversation = tradeConversation();
        when(store.lockTradeByTradeId(transaction, 9L)).thenReturn(conversation);
        var eventId = UUID.randomUUID();
        var message = mock(TradeMessage.class);
        when(message.id()).thenReturn(6L);
        when(message.seq()).thenReturn(2L);
        when(message.createdAt()).thenReturn(NOW);
        when(store.appendTradeSystemEvent(transaction, conversation, eventId, "trade_completed", "完成",
                null, null)).thenReturn(message);

        var appended = tradeConversations.appendSystemEvent(transaction, 9L, eventId, "trade_completed",
                "完成", null, null);

        assertThat(appended.messageId()).isEqualTo(6L);
    }

    @Test
    void archiveLocksByTrade() {
        var conversation = tradeConversation();
        when(store.lockTradeByTradeId(transaction, 9L)).thenReturn(conversation);
        when(store.archiveTrade(transaction, conversation)).thenReturn(true);

        assertThat(tradeConversations.archive(transaction, 9L)).isTrue();
        verify(store).archiveTrade(transaction, conversation);
    }

    private static TradeConversation tradeConversation() {
        var conversation = mock(TradeConversation.class);
        when(conversation.id()).thenReturn(1L);
        when(conversation.tradeId()).thenReturn(9L);
        when(conversation.archivedAt()).thenReturn(null);
        return conversation;
    }
}
