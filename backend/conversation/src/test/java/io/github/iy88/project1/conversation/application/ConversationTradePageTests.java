package io.github.iy88.project1.conversation.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import io.github.iy88.project1.conversation.ConversationSettings;
import io.github.iy88.project1.conversation.persistence.ConversationReader;
import io.github.iy88.project1.conversation.persistence.ConversationStore;
import io.github.iy88.project1.conversation.persistence.TradeConversation;
import io.github.iy88.project1.conversation.persistence.TradeMessage;
import io.github.iy88.project1.core.ExecutionContext;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class ConversationTradePageTests {
    private static final Instant NOW = Instant.parse("2026-11-22T10:00:00Z");

    private final ConversationStore store = mock(ConversationStore.class);
    private final ConversationReader reader = mock(ConversationReader.class);
    private final AccountDirectory accounts = mock(AccountDirectory.class);
    private final TradeParticipation trades = mock(TradeParticipation.class);
    private final ConversationQueries queries = new ConversationQueries(store, reader, accounts, trades,
            new ConversationSettings());

    @Test
    void pagesTradeMessagesWithSystemProjection() {
        var conversation = mock(TradeConversation.class);
        when(conversation.id()).thenReturn(2L);
        when(conversation.tradeId()).thenReturn(9L);
        when(conversation.archived()).thenReturn(false);
        when(store.trade(2L)).thenReturn(conversation);
        when(trades.participants(9L)).thenReturn(Optional.of(new TradeParticipation.Participants(7L, 42L)));

        var system = tradeMessage(20L, 1L, "system", null, "system_event", "交易已完成",
                "trade_completed", "trade_transition", 55L);
        var text = tradeMessage(21L, 2L, "account", 7L, "text", "你好", null, null, null);
        when(reader.tradeMessages(2L, null, null, 20)).thenReturn(List.of(system, text));
        when(accounts.profiles(java.util.Set.of(7L))).thenReturn(Map.of(
                7L, new AccountDirectory.Profile(7L, "张新悦")));

        var page = queries.pageTrade(actor(7L), 2L, null, null, 20);

        assertThat(page.items()).hasSize(2);
        assertThat(page.items().getFirst().sender().senderKind()).isEqualTo("system");
        assertThat(page.items().getFirst().sender().displayName()).isEqualTo("系统");
        assertThat(page.items().getFirst().eventType()).isEqualTo("trade_completed");
        assertThat(page.items().getFirst().sourceRef()).isNull();
        assertThat(page.items().getLast().sender().displayName()).isEqualTo("张新悦");
        assertThat(page.branchStatus()).isEqualTo("active");
        assertThat(page.nextBeforeSeq()).isEqualTo(1L);
        assertThat(page.nextAfterSeq()).isEqualTo(2L);
    }

    @Test
    void archivedTradeReportsArchivedStatus() {
        var conversation = mock(TradeConversation.class);
        when(conversation.id()).thenReturn(2L);
        when(conversation.tradeId()).thenReturn(9L);
        when(conversation.archived()).thenReturn(true);
        when(store.trade(2L)).thenReturn(conversation);
        when(trades.participants(9L)).thenReturn(Optional.of(new TradeParticipation.Participants(7L, 42L)));
        when(reader.tradeMessages(2L, null, null, 20)).thenReturn(List.of());

        var page = queries.pageTrade(actor(7L), 2L, null, null, 20);

        assertThat(page.branchStatus()).isEqualTo("archived");
        assertThat(page.items()).isEmpty();
        assertThat(page.nextAfterSeq()).isNull();
        assertThat(page.nextBeforeSeq()).isNull();
    }

    private static TradeMessage tradeMessage(long id, long seq, String senderKind, Long senderAccountId,
                                             String messageType, String body, String eventType, String sourceType,
                                             Long sourceId) {
        var message = mock(TradeMessage.class);
        when(message.id()).thenReturn(id);
        when(message.seq()).thenReturn(seq);
        when(message.senderKind()).thenReturn(senderKind);
        when(message.senderAccountId()).thenReturn(senderAccountId);
        when(message.messageType()).thenReturn(messageType);
        when(message.body()).thenReturn(body);
        when(message.eventType()).thenReturn(eventType);
        when(message.sourceType()).thenReturn(sourceType);
        when(message.sourceId()).thenReturn(sourceId);
        when(message.createdAt()).thenReturn(NOW);
        return message;
    }

    private static ExecutionContext actor(long accountId) {
        return new ExecutionContext(UUID.randomUUID(), ExecutionContext.ActorKind.ACCOUNT, Long.toString(accountId),
                UUID.randomUUID(), null, 1L, "s1-v1");
    }
}
