package io.github.iy88.project1.api.trade;

import io.github.iy88.project1.conversation.persistence.ConversationStore;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteTransaction;
import io.github.iy88.project1.trade.application.TradePorts;
import java.util.OptionalLong;
import java.util.UUID;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;

@Configuration(proxyBeanMethods = false)
@Profile("infrastructure & !dependency-probe & !file-probe")
class TradeConversationConfiguration {
    @Bean
    TradePorts.Conversation tradeConversation(ConversationStore conversations) {
        return new StoreConversation(conversations);
    }

    /** Adapts the shared conversation store to the trade transaction and lock plan. */
    private record StoreConversation(ConversationStore conversations) implements TradePorts.Conversation {
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
            var conversation = conversations.tradeConversation(conversationId);
            String sourceType = sourceRef == null ? null : sourceRef.type();
            Long sourceId = sourceRef == null ? null : sourceRef.id();
            conversations.appendTradeSystemEvent(transaction, conversation, businessEventId, eventType, body,
                    sourceType, sourceId);
        }

        @Override
        public void archive(WriteTransaction transaction, long conversationId, long tradeId, String reason) {
            conversations.archiveTrade(transaction, conversations.tradeConversation(conversationId));
        }
    }
}
