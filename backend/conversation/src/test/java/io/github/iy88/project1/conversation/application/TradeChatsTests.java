package io.github.iy88.project1.conversation.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import io.github.iy88.project1.conversation.persistence.ConversationStore;
import io.github.iy88.project1.conversation.persistence.TradeConversation;
import io.github.iy88.project1.conversation.persistence.TradeMessage;
import io.github.iy88.project1.conversation.persistence.TradeReadProgress;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.WriteTransaction;
import java.time.Instant;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class TradeChatsTests {
    private static final Instant NOW = Instant.parse("2026-11-22T10:00:00Z");

    private final ConversationStore store = mock(ConversationStore.class);
    private final AccountDirectory accounts = mock(AccountDirectory.class);
    private final TradeParticipation trades = mock(TradeParticipation.class);
    private final WriteTransaction transaction = mock(WriteTransaction.class);
    private final TradeChats chats = new TradeChats(store, accounts, trades);

    @Test
    void rejectsNonParticipant() {
        var conversation = tradeConversation();
        when(store.lockTrade(transaction, 2L)).thenReturn(conversation);
        when(trades.participants(9L)).thenReturn(Optional.of(new TradeParticipation.Participants(7L, 42L)));

        assertThatThrownBy(() -> chats.send(transaction, actor(8L), 2L, "hello"))
                .isInstanceOfSatisfying(BusinessError.class,
                        failure -> assertThat(failure.code()).isEqualTo("PARTICIPANT_REQUIRED"));
        verify(store, never()).appendTradeText(any(), any(), anyLong(), any());
    }

    @Test
    void rejectsWriteRestrictedPeerWithoutAFreeze() {
        var conversation = tradeConversation();
        when(store.lockTrade(transaction, 2L)).thenReturn(conversation);
        when(trades.participants(9L)).thenReturn(Optional.of(new TradeParticipation.Participants(7L, 42L)));
        when(accounts.writeRestricted(42L)).thenReturn(true);
        when(trades.pairFrozen(7L, 42L)).thenReturn(false);

        assertThatThrownBy(() -> chats.send(transaction, actor(7L), 2L, "hello"))
                .isInstanceOfSatisfying(BusinessError.class,
                        failure -> assertThat(failure.code()).isEqualTo("MESSAGE_SEND_FORBIDDEN"));
    }

    @Test
    void rejectsFrozenPair() {
        var conversation = tradeConversation();
        when(store.lockTrade(transaction, 2L)).thenReturn(conversation);
        when(trades.participants(9L)).thenReturn(Optional.of(new TradeParticipation.Participants(7L, 42L)));
        when(trades.pairFrozen(7L, 42L)).thenReturn(true);

        assertThatThrownBy(() -> chats.send(transaction, actor(7L), 2L, "hello"))
                .isInstanceOfSatisfying(BusinessError.class,
                        failure -> assertThat(failure.code()).isEqualTo("MESSAGE_SEND_FORBIDDEN"));
    }

    @Test
    void sendAdvancesSenderReadAndReturnsPeerUnread() {
        var conversation = tradeConversation();
        when(store.lockTrade(transaction, 2L)).thenReturn(conversation);
        when(trades.participants(9L)).thenReturn(Optional.of(new TradeParticipation.Participants(7L, 42L)));
        when(trades.pairFrozen(7L, 42L)).thenReturn(false);
        var message = mock(TradeMessage.class);
        when(message.id()).thenReturn(21L);
        when(message.seq()).thenReturn(4L);
        when(message.body()).thenReturn("hello");
        when(message.createdAt()).thenReturn(NOW);
        when(store.appendTradeText(transaction, conversation, 7L, "hello")).thenReturn(message);
        when(store.tradeUnread(conversation, 42L)).thenReturn(2L);
        when(accounts.profile(7L)).thenReturn(Optional.of(new AccountDirectory.Profile(7L, "张新悦")));

        var view = chats.send(transaction, actor(7L), 2L, "hello");

        assertThat(view.seq()).isEqualTo(4L);
        assertThat(view.peerUnread()).isEqualTo(2L);
        assertThat(view.senderDisplayName()).isEqualTo("张新悦");
        verify(store).advanceTradeRead(transaction, conversation, 7L, 4L);
    }

    @Test
    void advanceReadReturnsDerivedUnread() {
        var conversation = tradeConversation();
        when(conversation.seqHead()).thenReturn(9L);
        when(store.lockTrade(transaction, 2L)).thenReturn(conversation);
        when(trades.participants(9L)).thenReturn(Optional.of(new TradeParticipation.Participants(7L, 42L)));
        var progress = mock(TradeReadProgress.class);
        when(progress.lastReadSeq()).thenReturn(4L);
        when(progress.lastReadAt()).thenReturn(NOW);
        when(store.advanceTradeRead(transaction, conversation, 7L, 4L)).thenReturn(progress);

        var view = chats.advanceRead(transaction, actor(7L), 2L, 4L);

        assertThat(view.unreadCount()).isEqualTo(5L);
        assertThat(view.lastReadSeq()).isEqualTo(4L);
    }

    private static TradeConversation tradeConversation() {
        var conversation = mock(TradeConversation.class);
        when(conversation.id()).thenReturn(2L);
        when(conversation.tradeId()).thenReturn(9L);
        return conversation;
    }

    private static ExecutionContext actor(long accountId) {
        return new ExecutionContext(UUID.randomUUID(), ExecutionContext.ActorKind.ACCOUNT, Long.toString(accountId),
                UUID.randomUUID(), null, 1L, "s1-v1");
    }
}
