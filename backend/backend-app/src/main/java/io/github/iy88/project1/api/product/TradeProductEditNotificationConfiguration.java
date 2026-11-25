package io.github.iy88.project1.api.product;

import io.github.iy88.project1.core.EventIntent;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.messaging.UserEvents;
import io.github.iy88.project1.notification.application.NotificationApplication;
import io.github.iy88.project1.notification.application.NotificationEventSink;
import io.github.iy88.project1.notification.application.NotificationIntent;
import io.github.iy88.project1.notification.application.NotificationSourcePort;
import io.github.iy88.project1.product.application.ProductEditNotices;
import io.github.iy88.project1.trade.application.TradeOwnedReadModel;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;

/**
 * Product-edit notice source for buyers of an active request or trade.
 *
 * <p>The product edit runs in {@code ProductService}'s transaction rather than the shared
 * {@code WriteExecutor}. This configuration therefore uses {@link NotificationApplication}'s
 * transaction-neutral entry point and persists the same delivery intents through the real
 * {@link UserEvents} writer in that transaction. No nested transaction and no post-commit write is
 * introduced.
 */
@Configuration(proxyBeanMethods = false)
@Profile("infrastructure & !dependency-probe & !file-probe")
class TradeProductEditNotificationConfiguration {
    static final String SOURCE_TYPE = "trade_product_edit";
    static final String EVENT_TYPE = "trade.product_updated";
    static final String TEMPLATE_KEY = "trade.product_updated";
    static final String TEMPLATE_VERSION = "1";
    static final String SUMMARY = "商品信息已更新";
    static final String BODY = "卖家更新了你正在请求或交易中的商品信息。你可以前往交易详情查看当前内容。";

    @Bean
    ProductEditNotices productEditNotices(NotificationApplication notifications, UserEvents events,
                                           TradeOwnedReadModel trades) {
        return (context, sellerId, productId, editId, productTitle, publiclyVisible, occurredAt) -> {
            if (!publiclyVisible) {
                return;
            }
            var targets = trades.productNoticeTargets(productId);
            if (targets.isEmpty()) {
                return;
            }
            var pending = new ArrayList<EventIntent>();
            NotificationEventSink sink = (recipients, eventType, schemaVersion, source, intentKey, payload,
                                          sourceSequence) -> recipients.stream().sorted()
                    .map(recipient -> new EventIntent(UUID.randomUUID(), recipient, eventType, schemaVersion,
                            source, intentKey, payload, sourceSequence))
                    .forEach(pending::add);
            for (TradeOwnedReadModel.ProductNoticeTarget target : targets) {
                String intentKey = EVENT_TYPE + ":" + editId + ":" + target.tradeId();
                Map<String, String> params = new LinkedHashMap<>();
                params.put("trade_id", Long.toString(target.tradeId()));
                params.put("product_id", Long.toString(productId));
                params.put("edit_id", Long.toString(editId));
                var intent = new NotificationIntent(Set.of(target.buyerId()),
                        UUID.nameUUIDFromBytes(intentKey.getBytes(StandardCharsets.UTF_8)), EVENT_TYPE,
                        new ResourceRef(SOURCE_TYPE, target.tradeId()), intentKey, TEMPLATE_KEY,
                        TEMPLATE_VERSION, params, occurredAt);
                notifications.createNotifications(sink, intent);
            }
            events.persist(context, pending);
        };
    }

    /**
     * Projects the edit notice back onto the trade, so the client opens the exact trade and the
     * existing trade detail decides what the reader may currently see.
     */
    @Bean
    NotificationSourcePort tradeProductEditNotificationSource(TradeOwnedReadModel trades) {
        return (context, facts) -> {
            if (!SOURCE_TYPE.equals(facts.source().type()) || !EVENT_TYPE.equals(facts.eventType())
                    || context.actorKind() != ExecutionContext.ActorKind.ACCOUNT) {
                return Optional.empty();
            }
            long accountId = Long.parseLong(context.actorId());
            long tradeId = facts.source().id();
            return trades.productNoticeContext(tradeId, accountId)
                    .map(trade -> new NotificationSourcePort.NotificationSourceView(SUMMARY,
                            new ResourceRef("trade", tradeId), trade.productTitle(), BODY));
        };
    }
}
