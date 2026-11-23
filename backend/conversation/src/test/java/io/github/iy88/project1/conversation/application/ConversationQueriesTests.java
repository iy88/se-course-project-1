package io.github.iy88.project1.conversation.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import io.github.iy88.project1.conversation.ConversationSettings;
import io.github.iy88.project1.conversation.persistence.ChatConversation;
import io.github.iy88.project1.conversation.persistence.ChatMessage;
import io.github.iy88.project1.conversation.persistence.ConversationReader;
import io.github.iy88.project1.conversation.persistence.ConversationStore;
import io.github.iy88.project1.conversation.persistence.TradeConversation;
import io.github.iy88.project1.conversation.persistence.TradeMessage;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class ConversationQueriesTests {
    private static final Instant NOW = Instant.parse("2026-11-22T10:00:00Z");

    private final ConversationStore store = mock(ConversationStore.class);
    private final ConversationReader reader = mock(ConversationReader.class);
    private final AccountDirectory accounts = mock(AccountDirectory.class);
    private final TradeParticipation trades = mock(TradeParticipation.class);
    private final ConversationQueries queries = new ConversationQueries(store, reader, accounts, trades,
            new ConversationSettings());

    @Test
    void rejectsBothCursors() {
        var conversation = mock(ChatConversation.class);
        when(conversation.involves(7L)).thenReturn(true);
        when(store.chat(1L)).thenReturn(conversation);

        assertThatThrownBy(() -> queries.pageChat(actor(7L), 1L, 5L, 6L, 20))
                .isInstanceOfSatisfying(BusinessError.class,
                        failure -> assertThat(failure.code()).isEqualTo("INPUT_INVALID"));
    }

    @Test
    void rejectsNonParticipant() {
        var conversation = mock(ChatConversation.class);
        when(conversation.involves(9L)).thenReturn(false);
        when(store.chat(1L)).thenReturn(conversation);

        assertThatThrownBy(() -> queries.pageChat(actor(9L), 1L, null, null, 20))
                .isInstanceOfSatisfying(BusinessError.class,
                        failure -> assertThat(failure.code()).isEqualTo("PARTICIPANT_REQUIRED"));
    }

    @Test
    void pagesChatMessagesWithSenderNamesAndCursors() {
        var conversation = mock(ChatConversation.class);
        when(conversation.involves(7L)).thenReturn(true);
        when(store.chat(1L)).thenReturn(conversation);
        var first = chatMessage(10L, 1L, 7L, "hello", NOW);
        var second = chatMessage(11L, 2L, 42L, "hi", NOW.plusSeconds(1));
        when(reader.chatMessages(1L, null, null, 20)).thenReturn(List.of(first, second));
        when(accounts.profiles(java.util.Set.of(7L, 42L))).thenReturn(Map.of(
                7L, new AccountDirectory.Profile(7L, "张新悦"),
                42L, new AccountDirectory.Profile(42L, "李四")));

        var page = queries.pageChat(actor(7L), 1L, null, null, 20);

        assertThat(page.items()).hasSize(2);
        assertThat(page.items().getFirst().sender().displayName()).isEqualTo("张新悦");
        assertThat(page.items().getLast().sender().displayName()).isEqualTo("李四");
        assertThat(page.nextBeforeSeq()).isEqualTo(1L);
        assertThat(page.nextAfterSeq()).isEqualTo(2L);
        assertThat(page.branchStatus()).isEqualTo("active");
    }

    @Test
    void listsChatAndTradeBranchesGroupedByPeer() {
        var chat = mock(ChatConversation.class);
        when(chat.id()).thenReturn(1L);
        when(chat.otherAccount(7L)).thenReturn(42L);
        when(chat.createdAt()).thenReturn(NOW);
        when(reader.chatConversations(7L)).thenReturn(List.of(chat));
        when(store.chatUnread(chat, 7L)).thenReturn(2L);
        var chatLast = chatMessage(10L, 1L, 42L, "hello", NOW);
        when(reader.chatLastMessage(1L)).thenReturn(Optional.of(chatLast));

        var trade = mock(TradeConversation.class);
        when(trade.id()).thenReturn(2L);
        when(trade.tradeId()).thenReturn(9L);
        when(trade.createdAt()).thenReturn(NOW.plusSeconds(5));
        when(trade.archivedAt()).thenReturn(null);
        when(trades.tradeIdsOf(7L)).thenReturn(List.of(9L));
        when(reader.tradeConversations(List.of(9L))).thenReturn(List.of(trade));
        when(trades.participants(9L)).thenReturn(Optional.of(new TradeParticipation.Participants(7L, 42L)));
        when(store.tradeUnread(trade, 7L)).thenReturn(1L);
        var tradeLast = tradeMessage(20L, 1L, "sold", NOW.plusSeconds(5));
        when(reader.tradeLastMessage(2L)).thenReturn(Optional.of(tradeLast));

        when(accounts.profiles(java.util.Set.of(42L))).thenReturn(Map.of(
                42L, new AccountDirectory.Profile(42L, "李四")));

        var page = queries.list(actor(7L), 1, 20);

        assertThat(page.items()).hasSize(1);
        assertThat(page.total()).isEqualTo(1L);
        var summary = page.items().getFirst();
        assertThat(summary.peer().displayName()).isEqualTo("李四");
        assertThat(summary.branches()).hasSize(2);
        assertThat(summary.branches().getFirst().conversationKind()).isEqualTo("trade");
        assertThat(summary.branches()).extracting(ConversationViews.Branch::unreadCount)
                .containsExactly(1L, 2L);
    }

    @Test
    void listsOversizedPageAsEmpty() {
        when(reader.chatConversations(7L)).thenReturn(List.of());
        when(trades.tradeIdsOf(7L)).thenReturn(List.of());

        var page = queries.list(actor(7L), Integer.MAX_VALUE, 20);

        assertThat(page.items()).isEmpty();
        assertThat(page.page()).isEqualTo(Integer.MAX_VALUE);
        assertThat(page.total()).isZero();
    }

    private static ChatMessage chatMessage(long id, long seq, long sender, String body, Instant at) {
        var message = mock(ChatMessage.class);
        when(message.id()).thenReturn(id);
        when(message.seq()).thenReturn(seq);
        when(message.senderAccountId()).thenReturn(sender);
        when(message.body()).thenReturn(body);
        when(message.createdAt()).thenReturn(at);
        return message;
    }

    private static TradeMessage tradeMessage(long id, long seq, String body, Instant at) {
        var message = mock(TradeMessage.class);
        when(message.id()).thenReturn(id);
        when(message.seq()).thenReturn(seq);
        when(message.body()).thenReturn(body);
        when(message.createdAt()).thenReturn(at);
        return message;
    }

    private static ExecutionContext actor(long accountId) {
        return new ExecutionContext(UUID.randomUUID(), ExecutionContext.ActorKind.ACCOUNT, Long.toString(accountId),
                UUID.randomUUID(), null, 1L, "s1-v1");
    }
}
