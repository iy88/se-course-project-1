package io.github.iy88.project1.conversation.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import io.github.iy88.project1.conversation.persistence.ChatConversation;
import io.github.iy88.project1.conversation.persistence.ChatMessage;
import io.github.iy88.project1.conversation.persistence.ChatReadProgress;
import io.github.iy88.project1.conversation.persistence.ConversationStore;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.WriteTransaction;
import java.time.Instant;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class ConversationsTests {
    private static final Instant NOW = Instant.parse("2026-11-22T10:00:00Z");

    private final ConversationStore store = mock(ConversationStore.class);
    private final AccountDirectory accounts = mock(AccountDirectory.class);
    private final TradeParticipation trades = mock(TradeParticipation.class);
    private final WriteTransaction transaction = mock(WriteTransaction.class);
    private final Conversations conversations = new Conversations(store, accounts, trades);

    @Test
    void rejectsSelfConversation() {
        assertThatThrownBy(() -> conversations.startPrivateChat(transaction, actor(7L), 7L))
                .isInstanceOfSatisfying(BusinessError.class,
                        failure -> assertThat(failure.code()).isEqualTo("SELF_CONVERSATION_FORBIDDEN"));
    }

    @Test
    void rejectsInvisibleTarget() {
        when(accounts.profile(8L)).thenReturn(Optional.empty());

        assertThatThrownBy(() -> conversations.startPrivateChat(transaction, actor(7L), 8L))
                .isInstanceOfSatisfying(BusinessError.class,
                        failure -> assertThat(failure.code()).isEqualTo("RESOURCE_NOT_VISIBLE"));
    }

    @Test
    void rejectsWriteRestrictedInitiator() {
        when(accounts.profile(8L)).thenReturn(Optional.of(new AccountDirectory.Profile(8L, "peer")));
        when(accounts.writeRestricted(7L)).thenReturn(true);

        assertThatThrownBy(() -> conversations.startPrivateChat(transaction, actor(7L), 8L))
                .isInstanceOfSatisfying(BusinessError.class,
                        failure -> assertThat(failure.code()).isEqualTo("ACCOUNT_WRITE_RESTRICTED"));
    }

    @Test
    void reportsReusedChat() {
        when(accounts.profile(8L)).thenReturn(Optional.of(new AccountDirectory.Profile(8L, "peer")));
        when(accounts.writeRestricted(7L)).thenReturn(false);
        when(store.findChat(7L, 8L)).thenReturn(Optional.of(mock(ChatConversation.class)));
        var conversation = mock(ChatConversation.class);
        when(conversation.id()).thenReturn(5L);
        when(store.ensureChat(transaction, 7L, 8L)).thenReturn(conversation);

        var started = conversations.startPrivateChat(transaction, actor(7L), 8L);

        assertThat(started.conversationId()).isEqualTo(5L);
        assertThat(started.reused()).isTrue();
        assertThat(started.peerAccountId()).isEqualTo(8L);
    }

    @Test
    void sendRejectsFrozenPair() {
        var conversation = chat(7L, 42L);
        when(store.lockChat(transaction, 1L)).thenReturn(conversation);
        when(accounts.writeRestricted(7L)).thenReturn(false);
        when(trades.pairFrozen(7L, 42L)).thenReturn(true);

        assertThatThrownBy(() -> conversations.sendChat(transaction, actor(7L), 1L, "hello"))
                .isInstanceOfSatisfying(BusinessError.class,
                        failure -> assertThat(failure.code()).isEqualTo("MESSAGE_SEND_FORBIDDEN"));
    }

    @Test
    void sendRejectsWriteRestrictedPeerWithoutAFreeze() {
        var conversation = chat(7L, 42L);
        when(store.lockChat(transaction, 1L)).thenReturn(conversation);
        when(accounts.writeRestricted(7L)).thenReturn(false);
        when(accounts.writeRestricted(42L)).thenReturn(true);
        when(trades.pairFrozen(7L, 42L)).thenReturn(false);

        assertThatThrownBy(() -> conversations.sendChat(transaction, actor(7L), 1L, "hello"))
                .isInstanceOfSatisfying(BusinessError.class,
                        failure -> assertThat(failure.code()).isEqualTo("MESSAGE_SEND_FORBIDDEN"));
        verify(store, never()).appendChatText(transaction, conversation, 7L, "hello");
        verify(store, never()).advanceChatRead(any(), any(), anyLong(), anyLong());
    }

    @Test
    void sendRejectsWriteRestrictedSender() {
        var conversation = chat(7L, 42L);
        when(store.lockChat(transaction, 1L)).thenReturn(conversation);
        when(accounts.writeRestricted(7L)).thenReturn(true);

        assertThatThrownBy(() -> conversations.sendChat(transaction, actor(7L), 1L, "hello"))
                .isInstanceOfSatisfying(BusinessError.class,
                        failure -> assertThat(failure.code()).isEqualTo("MESSAGE_SEND_FORBIDDEN"));
    }

    @Test
    void sendAdvancesSenderReadAndReturnsPeerUnread() {
        var conversation = chat(7L, 42L);
        when(store.lockChat(transaction, 1L)).thenReturn(conversation);
        when(accounts.writeRestricted(7L)).thenReturn(false);
        when(trades.pairFrozen(7L, 42L)).thenReturn(false);
        var message = mock(ChatMessage.class);
        when(message.id()).thenReturn(11L);
        when(message.seq()).thenReturn(6L);
        when(message.body()).thenReturn("hello");
        when(message.createdAt()).thenReturn(NOW);
        when(store.appendChatText(transaction, conversation, 7L, "hello")).thenReturn(message);
        when(store.chatUnread(conversation, 42L)).thenReturn(3L);
        when(accounts.profile(7L)).thenReturn(Optional.of(new AccountDirectory.Profile(7L, "张新悦")));

        var view = conversations.sendChat(transaction, actor(7L), 1L, "hello");

        assertThat(view.seq()).isEqualTo(6L);
        assertThat(view.peerUnread()).isEqualTo(3L);
        assertThat(view.senderDisplayName()).isEqualTo("张新悦");
        verify(store).advanceChatRead(transaction, conversation, 7L, 6L);
    }

    @Test
    void advanceReadReturnsDerivedUnread() {
        var conversation = chat(7L, 42L);
        when(conversation.seqHead()).thenReturn(9L);
        when(store.lockChat(transaction, 1L)).thenReturn(conversation);
        var progress = mock(ChatReadProgress.class);
        when(progress.lastReadSeq()).thenReturn(4L);
        when(progress.lastReadAt()).thenReturn(NOW);
        when(store.advanceChatRead(transaction, conversation, 7L, 4L)).thenReturn(progress);

        var view = conversations.advanceChatRead(transaction, actor(7L), 1L, 4L);

        assertThat(view.unreadCount()).isEqualTo(5L);
        assertThat(view.lastReadSeq()).isEqualTo(4L);
    }

    @Test
    void sendsChatWithoutTradePort() {
        var withoutTrades = new Conversations(store, accounts, null);
        var conversation = chat(7L, 42L);
        when(store.lockChat(transaction, 1L)).thenReturn(conversation);
        when(accounts.writeRestricted(7L)).thenReturn(false);
        when(accounts.writeRestricted(42L)).thenReturn(false);
        var message = mock(ChatMessage.class);
        when(message.id()).thenReturn(11L);
        when(message.seq()).thenReturn(6L);
        when(message.body()).thenReturn("hello");
        when(message.createdAt()).thenReturn(NOW);
        when(store.appendChatText(transaction, conversation, 7L, "hello")).thenReturn(message);
        when(store.chatUnread(conversation, 42L)).thenReturn(0L);
        when(accounts.profile(7L)).thenReturn(Optional.of(new AccountDirectory.Profile(7L, "sender")));

        var view = withoutTrades.sendChat(transaction, actor(7L), 1L, "hello");

        assertThat(view.seq()).isEqualTo(6L);
    }

    private static ChatConversation chat(long actorId, long peerId) {
        var conversation = mock(ChatConversation.class);
        when(conversation.id()).thenReturn(1L);
        when(conversation.involves(actorId)).thenReturn(true);
        when(conversation.otherAccount(actorId)).thenReturn(peerId);
        return conversation;
    }

    private static ExecutionContext actor(long accountId) {
        return new ExecutionContext(UUID.randomUUID(), ExecutionContext.ActorKind.ACCOUNT, Long.toString(accountId),
                UUID.randomUUID(), null, 1L, "s1-v1");
    }
}
