package io.github.iy88.project1.api.trade;

import io.github.iy88.project1.conversation.application.TradeParticipation;
import io.github.iy88.project1.conversation.persistence.ConversationStore;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteTransaction;
import io.github.iy88.project1.messaging.BusinessEventIntents;
import io.github.iy88.project1.messaging.RealtimeEventSources;
import io.github.iy88.project1.trade.application.TradePorts;
import io.github.iy88.project1.trade.persistence.TradeRepository;
import java.util.List;
import java.util.Optional;
import java.util.OptionalLong;
import java.util.Set;
import java.util.UUID;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;

@Configuration(proxyBeanMethods = false)
@Profile("infrastructure & !dependency-probe & !file-probe")
class TradeConversationConfiguration {
    @Bean
    TradePorts.Conversation tradeConversation(ConversationStore conversations, TradeRepository trades) {
        return new StoreConversation(conversations, trades);
    }

    @Bean
    TradeParticipation tradeParticipation(TradePorts.Participation trades) {
        return new TradeParticipationAdapter(trades);
    }

    /** Projects trade reads required by the conversation module. */
    private record TradeParticipationAdapter(TradePorts.Participation trades) implements TradeParticipation {
        @Override
        public Optional<TradeParticipation.Participants> participants(long tradeId) {
            return trades.findConversationAccess(tradeId)
                    .map(access -> new TradeParticipation.Participants(access.buyerId(), access.sellerId()));
        }

        @Override
        public boolean pairFrozen(long firstAccountId, long secondAccountId) {
            return trades.pairFrozen(firstAccountId, secondAccountId);
        }

        @Override
        public List<Long> tradeIdsOf(long accountId) {
            return trades.tradeIdsOf(accountId);
        }
    }

    /** Adapts the shared conversation store to the trade transaction and lock plan. */
    private record StoreConversation(ConversationStore conversations, TradeRepository trades) implements TradePorts.Conversation {
        @Override
        public long ensure(WriteTransaction transaction, long tradeId, long productId, long buyerId, long sellerId) {
            return conversations.ensureTrade(transaction, tradeId, buyerId, sellerId).id();
        }

        @Override
        public OptionalLong find(long tradeId) {
            return conversations.findTrade(tradeId)
                    .map(conversation -> OptionalLong.of(conversation.id()))
                    .orElseGet(OptionalLong::empty);
        }

        @Override
        public void lockConversation(WriteTransaction transaction, long conversationId) {
            conversations.lockTrade(transaction, conversationId);
        }

        @Override
        public void append(WriteTransaction transaction, long conversationId, UUID businessEventId, String eventType,
                           String body, ResourceRef sourceRef) {
            var conversation = conversations.trade(conversationId);
            String sourceType = sourceRef == null ? null : sourceRef.type();
            Long sourceId = sourceRef == null ? null : sourceRef.id();
            var message = conversations.appendTradeSystemEvent(transaction, conversation, businessEventId, eventType,
                    body, sourceType, sourceId);
            BusinessEventIntents.messageCreated(transaction, recipients(conversation.tradeId()),
                    reference(conversationId), message.id(), "message_created:trade:" + message.id());
        }

        @Override
        public void archive(WriteTransaction transaction, long conversationId, long tradeId, String reason) {
            if (conversations.archiveTrade(transaction, conversations.trade(conversationId))) {
                BusinessEventIntents.conversationArchived(transaction, recipients(tradeId), reference(conversationId),
                        "conversation_archived:" + conversationId);
            }
        }

        private Set<Long> recipients(long tradeId) {
            var trade = trades.find(tradeId).orElseThrow();
            return Set.of(trade.buyerId(), trade.sellerId());
        }

        private static RealtimeEventSources.ConversationRef reference(long conversationId) {
            return new RealtimeEventSources.ConversationRef(RealtimeEventSources.ConversationKind.TRADE, conversationId);
        }
    }
}
