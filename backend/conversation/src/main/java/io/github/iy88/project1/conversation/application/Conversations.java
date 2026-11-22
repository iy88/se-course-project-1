package io.github.iy88.project1.conversation.application;

import io.github.iy88.project1.conversation.ConversationRules;
import io.github.iy88.project1.conversation.persistence.ChatConversation;
import io.github.iy88.project1.conversation.persistence.ConversationStore;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.WriteTransaction;
import org.springframework.context.annotation.Lazy;
import org.springframework.stereotype.Service;

/**
 * Private-chat use cases. Callers own the write transaction and idempotency; these methods apply
 * participant, qualification and freeze rules before touching the conversation store.
 */
@Lazy
@Service
public class Conversations {
    private final ConversationStore store;
    private final AccountDirectory accounts;
    private final TradeParticipation trades;

    public Conversations(ConversationStore store, AccountDirectory accounts, TradeParticipation trades) {
        this.store = store;
        this.accounts = accounts;
        this.trades = trades;
    }

    public ConversationViews.StartedChat startPrivateChat(WriteTransaction transaction, ExecutionContext context,
                                                          long targetAccountId) {
        long actor = accountId(context);
        if (actor == targetAccountId) {
            throw new BusinessError("SELF_CONVERSATION_FORBIDDEN", 422, "不能与自己建立会话");
        }
        var peer = accounts.profile(targetAccountId)
                .orElseThrow(() -> new BusinessError("RESOURCE_NOT_VISIBLE", 404, "目标账户不可见"));
        if (accounts.writeRestricted(actor)) {
            throw new BusinessError("ACCOUNT_WRITE_RESTRICTED", 403, "账户当前不能发起新会话");
        }
        boolean reused = store.findChat(actor, targetAccountId).isPresent();
        ChatConversation conversation = store.ensureChat(transaction, actor, targetAccountId);
        return new ConversationViews.StartedChat(conversation.id(), peer.accountId(), peer.displayName(), reused);
    }

    public ConversationViews.ChatMessage sendChat(WriteTransaction transaction, ExecutionContext context,
                                                  long conversationId, String body) {
        long actor = accountId(context);
        var conversation = store.lockChat(transaction, conversationId);
        requireParticipant(conversation, actor);
        if (accounts.writeRestricted(actor)) {
            throw new BusinessError("ACCOUNT_WRITE_RESTRICTED", 403, "账户当前不能发送消息");
        }
        long peer = conversation.otherAccount(actor);
        if (trades.pairFrozen(actor, peer)) {
            throw new BusinessError("MESSAGE_SEND_FORBIDDEN", 403, "账户之间存在交易冻结");
        }
        var message = store.appendChatText(transaction, conversation, actor, body);
        store.advanceChatRead(transaction, conversation, actor, message.seq());
        long peerUnread = store.chatUnread(conversation, peer);
        var sender = accounts.profile(actor)
                .orElseThrow(() -> new BusinessError("RESOURCE_NOT_VISIBLE", 404, "账户不可见"));
        return new ConversationViews.ChatMessage(message.id(), message.seq(), actor, sender.displayName(),
                message.body(), message.createdAt(), peerUnread);
    }

    public ConversationViews.ReadProgress advanceChatRead(WriteTransaction transaction, ExecutionContext context,
                                                          long conversationId, long displayedSeq) {
        long actor = accountId(context);
        var conversation = store.lockChat(transaction, conversationId);
        requireParticipant(conversation, actor);
        var progress = store.advanceChatRead(transaction, conversation, actor, displayedSeq);
        long unread = ConversationRules.unreadCount(conversation.seqHead(), progress.lastReadSeq());
        return new ConversationViews.ReadProgress(progress.lastReadSeq(), unread, progress.lastReadAt());
    }

    private static void requireParticipant(ChatConversation conversation, long accountId) {
        if (!conversation.involves(accountId)) {
            throw new BusinessError("PARTICIPANT_REQUIRED", 404, "会话不存在或无权访问");
        }
    }

    private static long accountId(ExecutionContext context) {
        if (context.actorKind() != ExecutionContext.ActorKind.ACCOUNT) {
            throw new BusinessError("AUTHENTICATION_REQUIRED", 401, "需要登录账户");
        }
        return Long.parseLong(context.actorId());
    }
}
