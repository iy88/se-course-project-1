package io.github.iy88.project1.api.trade;

import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.notification.application.NotificationApplication;
import io.github.iy88.project1.notification.application.NotificationIntent;
import io.github.iy88.project1.notification.application.NotificationSourcePort;
import io.github.iy88.project1.trade.application.TradePorts;
import java.time.Clock;
import java.util.Map;
import java.util.Optional;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;

@Configuration(proxyBeanMethods = false)
@Profile("infrastructure & !dependency-probe & !file-probe")
class TradeNotificationConfiguration {
    @Bean
    TradePorts.Notifications tradeNotifications(NotificationApplication notifications, Clock clock) {
        return (transaction, eventId, eventType, tradeId, recipients) -> notifications.createNotifications(transaction,
                new NotificationIntent(recipients, eventId, eventType, new ResourceRef("trade", tradeId),
                        eventType + ":" + eventId, eventType, "1", Map.of("trade_id", Long.toString(tradeId)),
                        clock.instant()));
    }

    @Bean
    NotificationSourcePort tradeNotificationSource(TradePorts.Participation trades) {
        return (context, facts) -> {
            if (!"trade".equals(facts.source().type()) || context.actorKind() != ExecutionContext.ActorKind.ACCOUNT) {
                return Optional.empty();
            }
            long accountId = Long.parseLong(context.actorId());
            return trades.findConversationAccess(facts.source().id())
                    .filter(access -> accountId == access.buyerId() || accountId == access.sellerId())
                    .map(access -> new NotificationSourcePort.NotificationSourceView("交易状态有更新", facts.source()));
        };
    }
}
