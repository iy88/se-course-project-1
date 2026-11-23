package io.github.iy88.project1.api.realtime;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import io.github.iy88.project1.conversation.application.CaseParticipation;
import io.github.iy88.project1.conversation.application.TradeParticipation;
import io.github.iy88.project1.conversation.persistence.CaseConversation;
import io.github.iy88.project1.conversation.persistence.ChatConversation;
import io.github.iy88.project1.conversation.persistence.ChatMessage;
import io.github.iy88.project1.conversation.persistence.ConversationReader;
import io.github.iy88.project1.conversation.persistence.ConversationStore;
import io.github.iy88.project1.conversation.persistence.TradeConversation;
import io.github.iy88.project1.conversation.persistence.TradeMessage;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.messaging.RealtimeEventSources;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.ObjectProvider;

class ConversationRealtimeTests {
    private final ConversationStore store = mock(ConversationStore.class);
    private final ConversationReader reader = mock(ConversationReader.class);
    private final TradeParticipation trades = mock(TradeParticipation.class);
    @SuppressWarnings("unchecked")
    private final ObjectProvider<CaseParticipation> cases = mock(ObjectProvider.class);
    private final ConversationRealtime realtime = new ConversationRealtime(store, reader, trades, cases);

    @Test
    void readsChatOnlyForItsParticipants() {
        var conversation = mock(ChatConversation.class);
        when(conversation.involves(7L)).thenReturn(true);
        when(conversation.involves(8L)).thenReturn(false);
        when(store.chat(1L)).thenReturn(conversation);

        assertThat(realtime.canRead(context(7L), ref(RealtimeEventSources.ConversationKind.CHAT, 1L))).isTrue();
        assertThat(realtime.canRead(context(8L), ref(RealtimeEventSources.ConversationKind.CHAT, 1L))).isFalse();
    }

    @Test
    void readsTradeOnlyForItsParticipants() {
        var conversation = mock(TradeConversation.class);
        when(conversation.tradeId()).thenReturn(9L);
        when(store.trade(2L)).thenReturn(conversation);
        when(trades.participants(9L)).thenReturn(Optional.of(new TradeParticipation.Participants(7L, 42L)));

        assertThat(realtime.canRead(context(42L), ref(RealtimeEventSources.ConversationKind.TRADE, 2L))).isTrue();
        assertThat(realtime.canRead(context(8L), ref(RealtimeEventSources.ConversationKind.TRADE, 2L))).isFalse();
    }

    @Test
    void returnsMessageHintsOnlyForTheSameThread() {
        var conversation = mock(ChatConversation.class);
        when(conversation.involves(7L)).thenReturn(true);
        when(store.chat(1L)).thenReturn(conversation);
        var other = mock(ChatConversation.class);
        when(other.involves(7L)).thenReturn(false);
        when(store.chat(2L)).thenReturn(other);
        var message = mock(ChatMessage.class);
        when(message.conversationId()).thenReturn(1L);
        when(message.seq()).thenReturn(4L);
        when(reader.chatMessage(10L)).thenReturn(Optional.of(message));

        assertThat(realtime.readMessage(context(7L), ref(RealtimeEventSources.ConversationKind.CHAT, 1L), 10L))
                .hasValueSatisfying(hint -> assertThat(hint.sequence()).isEqualTo(4L));
        assertThat(realtime.readMessage(context(7L), ref(RealtimeEventSources.ConversationKind.CHAT, 2L), 10L))
                .isEmpty();
    }

    @Test
    void hidesCaseThreadsUntilTheCaseAdapterExists() {
        when(cases.getIfAvailable()).thenReturn(null);

        assertThat(realtime.canRead(context(7L), ref(RealtimeEventSources.ConversationKind.CASE, 3L))).isFalse();
    }

    @Test
    void readsSystemEventBusinessIdForTradeMessages() {
        var trade = mock(TradeConversation.class);
        when(trade.tradeId()).thenReturn(9L);
        when(store.trade(2L)).thenReturn(trade);
        when(trades.participants(9L)).thenReturn(Optional.of(new TradeParticipation.Participants(7L, 42L)));
        var message = mock(TradeMessage.class);
        when(message.conversationId()).thenReturn(2L);
        when(message.seq()).thenReturn(5L);
        when(message.businessEventId()).thenReturn(UUID.fromString("00000000-0000-0000-0000-000000000001"));
        when(reader.tradeMessage(20L)).thenReturn(Optional.of(message));

        assertThat(realtime.readMessage(context(7L), ref(RealtimeEventSources.ConversationKind.TRADE, 2L), 20L))
                .hasValueSatisfying(hint -> assertThat(hint.businessEventId()).isNotNull());
    }

    private static RealtimeEventSources.ConversationRef ref(RealtimeEventSources.ConversationKind kind, long id) {
        return new RealtimeEventSources.ConversationRef(kind, id);
    }

    private static ExecutionContext context(long accountId) {
        return new ExecutionContext(UUID.randomUUID(), ExecutionContext.ActorKind.ACCOUNT, Long.toString(accountId),
                UUID.randomUUID(), null, 1L, "s1-v1");
    }
}
