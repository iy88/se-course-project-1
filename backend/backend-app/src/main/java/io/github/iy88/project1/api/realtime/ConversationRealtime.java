package io.github.iy88.project1.api.realtime;

import io.github.iy88.project1.conversation.application.CaseParticipation;
import io.github.iy88.project1.conversation.application.TradeParticipation;
import io.github.iy88.project1.conversation.persistence.ChatMessage;
import io.github.iy88.project1.conversation.persistence.ConversationReader;
import io.github.iy88.project1.conversation.persistence.ConversationStore;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.messaging.RealtimeEventSources;
import java.util.Optional;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.context.annotation.Lazy;
import org.springframework.context.annotation.Profile;

/**
 * Projects conversation readability and message hints for the realtime channel.
 *
 * <p>Chat and trade threads use the same participant rules as the HTTP reads. Case threads remain
 * unreadable here until the case module supplies {@link CaseParticipation} (#84, S4); a missing
 * adapter is reported as unreadable, never as granted.
 */
@Lazy
@Profile("infrastructure & !dependency-probe & !file-probe")
class ConversationRealtime implements RealtimeEventSources.Conversations {
    private final ConversationStore store;
    private final ConversationReader reader;
    private final TradeParticipation trades;
    private final ObjectProvider<CaseParticipation> cases;

    ConversationRealtime(ConversationStore store, ConversationReader reader, TradeParticipation trades,
                         ObjectProvider<CaseParticipation> cases) {
        this.store = store;
        this.reader = reader;
        this.trades = trades;
        this.cases = cases;
    }

    @Override
    public boolean canRead(ExecutionContext context, RealtimeEventSources.ConversationRef conversation) {
        long actor = actor(context);
        return switch (conversation.kind()) {
            case CHAT -> store.chat(conversation.id()).involves(actor);
            case TRADE -> tradeParticipants(conversation.id()).map(participants -> participants.involves(actor))
                    .orElse(false);
            case CASE -> caseAccess(conversation, actor);
        };
    }

    @Override
    public Optional<RealtimeEventSources.MessageHint> readMessage(
            ExecutionContext context, RealtimeEventSources.ConversationRef conversation, long messageId) {
        if (!canRead(context, conversation)) {
            return Optional.empty();
        }
        return switch (conversation.kind()) {
            case CHAT -> reader.chatMessage(messageId)
                    .filter(message -> message.conversationId() == conversation.id())
                    .map(ConversationRealtime::hint);
            case TRADE -> reader.tradeMessage(messageId)
                    .filter(message -> message.conversationId() == conversation.id())
                    .map(message -> new RealtimeEventSources.MessageHint(message.seq(), message.businessEventId()));
            case CASE -> reader.caseMessage(messageId)
                    .filter(message -> message.conversationId() == conversation.id())
                    .map(message -> new RealtimeEventSources.MessageHint(message.seq(), message.businessEventId()));
        };
    }

    private Optional<TradeParticipation.Participants> tradeParticipants(long conversationId) {
        return trades.participants(store.trade(conversationId).tradeId());
    }

    private boolean caseAccess(RealtimeEventSources.ConversationRef conversation, long actor) {
        var access = cases.getIfAvailable();
        if (access == null) {
            return false;
        }
        var thread = store.caseConversation(conversation.id());
        return access.canAccess(thread.caseId(), thread.relatedAccountId(), actor);
    }

    private static RealtimeEventSources.MessageHint hint(ChatMessage message) {
        return new RealtimeEventSources.MessageHint(message.seq(), null);
    }

    private static long actor(ExecutionContext context) {
        if (context.actorKind() != ExecutionContext.ActorKind.ACCOUNT) {
            throw new BusinessError("AUTHENTICATION_REQUIRED", 401, "需要登录账户");
        }
        return Long.parseLong(context.actorId());
    }
}
