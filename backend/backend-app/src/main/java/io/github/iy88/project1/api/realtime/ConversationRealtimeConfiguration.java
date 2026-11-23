package io.github.iy88.project1.api.realtime;

import io.github.iy88.project1.conversation.application.CaseParticipation;
import io.github.iy88.project1.conversation.application.TradeParticipation;
import io.github.iy88.project1.conversation.persistence.ConversationReader;
import io.github.iy88.project1.conversation.persistence.ConversationStore;
import io.github.iy88.project1.messaging.RealtimeEventSources;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;

@Configuration(proxyBeanMethods = false)
@Profile("infrastructure & !dependency-probe & !file-probe")
class ConversationRealtimeConfiguration {

    @Bean
    @ConditionalOnMissingBean(RealtimeEventSources.Conversations.class)
    RealtimeEventSources.Conversations conversationRealtime(ConversationStore store, ConversationReader reader,
                                                            TradeParticipation trades,
                                                            ObjectProvider<CaseParticipation> cases) {
        return new ConversationRealtime(store, reader, trades, cases);
    }
}
