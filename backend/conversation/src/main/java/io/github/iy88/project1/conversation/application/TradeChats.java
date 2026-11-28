package io.github.iy88.project1.conversation.application;

import io.github.iy88.project1.conversation.ConversationRules;
import io.github.iy88.project1.conversation.persistence.ConversationStore;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.WriteTransaction;
import org.springframework.context.annotation.Lazy;
import org.springframework.context.annotation.Profile;
import org.jspecify.annotations.Nullable;
import org.springframework.stereotype.Service;

/**
 * Buy/sell messages inside the conversation attached to one trade. The trade module owns the
 * trade record and the two-party freeze; this use case applies the shared conversation rules and
 * never writes trade data.
 */
@Lazy
@Service
@Profile("infrastructure")
public class TradeChats {
    private final ConversationStore store;
    private final AccountDirectory accounts;
    private final TradeParticipation trades;

    public TradeChats(ConversationStore store, AccountDirectory accounts, @Nullable TradeParticipation trades) {
        this.store = store;
        this.accounts = accounts;
        this.trades = trades;
    }

    public ConversationViews.ChatMessage send(WriteTransaction transaction, ExecutionContext context,
                                              long conversationId, String body) {
        long actor = accountId(context);
        var conversation = store.lockTrade(transaction, conversationId);
        var participants = tradesOf().participants(conversation.tradeId()).orElse(null);
        if (participants == null || !participants.involves(actor)) {
            throw participantRequired();
        }
        long peer = participants.peerOf(actor);
        // A single denial for either participant avoids disclosing which account is restricted.
        if (accounts.writeRestricted(actor) || accounts.writeRestricted(peer)) {
            throw new BusinessError("MESSAGE_SEND_FORBIDDEN", 403, "账户当前不能发送消息");
        }
        if (tradesOf().pairFrozen(actor, peer)) {
            throw new BusinessError("MESSAGE_SEND_FORBIDDEN", 403, "账户之间存在交易冻结");
        }
        var message = store.appendTradeText(transaction, conversation, actor, body);
        store.advanceTradeRead(transaction, conversation, actor, message.seq());
        long peerUnread = store.tradeUnread(conversation, peer);
        var sender = accounts.profile(actor)
                .orElseThrow(() -> new BusinessError("RESOURCE_NOT_VISIBLE", 404, "账户不可见"));
        return new ConversationViews.ChatMessage(message.id(), message.seq(), actor, sender.displayName(),
                message.body(), message.createdAt(), peerUnread);
    }

    public ConversationViews.ReadProgress advanceRead(WriteTransaction transaction, ExecutionContext context,
                                                      long conversationId, long displayedSeq) {
        long actor = accountId(context);
        var conversation = store.lockTrade(transaction, conversationId);
        var participants = tradesOf().participants(conversation.tradeId()).orElse(null);
        if (participants == null || !participants.involves(actor)) {
            throw participantRequired();
        }
        var progress = store.advanceTradeRead(transaction, conversation, actor, displayedSeq);
        long unread = ConversationRules.unreadCount(conversation.seqHead(), progress.lastReadSeq());
        return new ConversationViews.ReadProgress(progress.lastReadSeq(), unread, progress.lastReadAt());
    }

    private TradeParticipation tradesOf() {
        if (trades == null) {
            // Trade conversations are owned by the trade module; until its port is assembled the
            // call answers 503 rather than a fabricated participant decision.
            throw new BusinessError("DEPENDENCY_UNAVAILABLE", 503, "交易会话由交易模块提供");
        }
        return trades;
    }

    private static BusinessError participantRequired() {
        return new BusinessError("PARTICIPANT_REQUIRED", 404, "会话不存在或无权访问");
    }

    private static long accountId(ExecutionContext context) {
        if (context.actorKind() != ExecutionContext.ActorKind.ACCOUNT) {
            throw new BusinessError("AUTHENTICATION_REQUIRED", 401, "需要登录账户");
        }
        return Long.parseLong(context.actorId());
    }
}
