package io.github.iy88.project1.api.realtime;

import io.github.iy88.project1.conversation.application.TradeParticipation;
import io.github.iy88.project1.conversation.persistence.ConversationReader;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.messaging.RealtimeEventSources.ConversationRef;
import io.github.iy88.project1.messaging.RealtimeEventSources.Conversations;
import io.github.iy88.project1.messaging.RealtimeEventSources.MessageHint;
import java.util.Optional;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Component;

@Component
@Profile("infrastructure & !dependency-probe & !file-probe")
record ConversationRealtimeProjection(ConversationReader reader, TradeParticipation trades) implements Conversations {
    @Override
    public boolean canRead(ExecutionContext context, ConversationRef conversation) {
        if (context.actorKind() != ExecutionContext.ActorKind.ACCOUNT) {
            return false;
        }
        long actor = Long.parseLong(context.actorId());
        return switch (conversation.kind()) {
            case CHAT -> reader.findChat(conversation.id()).filter(chat -> chat.involves(actor)).isPresent();
            case TRADE -> reader.findTrade(conversation.id()).flatMap(branch -> trades.participants(branch.tradeId()))
                    .filter(participants -> participants.involves(actor)).isPresent();
            case CASE -> false;
        };
    }

    @Override
    public Optional<MessageHint> readMessage(ExecutionContext context, ConversationRef conversation, long messageId) {
        if (!canRead(context, conversation)) {
            return Optional.empty();
        }
        return switch (conversation.kind()) {
            case CHAT -> reader.findChatMessage(conversation.id(), messageId)
                    .map(message -> new MessageHint(message.seq(), null));
            case TRADE -> reader.findTradeMessage(conversation.id(), messageId)
                    .map(message -> new MessageHint(message.seq(), message.businessEventId()));
            case CASE -> Optional.empty();
        };
    }
}
