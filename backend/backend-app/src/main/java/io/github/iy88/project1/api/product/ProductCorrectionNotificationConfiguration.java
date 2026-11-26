package io.github.iy88.project1.api.product;

import io.github.iy88.project1.core.EventIntent;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.messaging.UserEvents;
import io.github.iy88.project1.notification.application.NotificationApplication;
import io.github.iy88.project1.notification.application.NotificationEventSink;
import io.github.iy88.project1.notification.application.NotificationIntent;
import io.github.iy88.project1.notification.application.NotificationSourcePort;
import io.github.iy88.project1.product.application.ProductCorrectionNotices;
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
import org.springframework.jdbc.core.simple.JdbcClient;

/**
 * Seller notice for an administrator category correction (API-PRD-032).
 *
 * <p>The correction runs in {@code ProductService}'s own transaction, so this configuration uses
 * {@link NotificationApplication}'s transaction-neutral entry point and writes the delivery intent
 * through the shared {@link UserEvents} writer in that same transaction. The edit id is part of the
 * intent key, so a replayed correction cannot create a second notice.
 */
@Configuration(proxyBeanMethods = false)
@Profile("infrastructure & !dependency-probe & !file-probe")
class ProductCorrectionNotificationConfiguration {
    static final String SOURCE_TYPE = "product_category_correction";
    static final String EVENT_TYPE = "product.category_corrected";
    static final String TEMPLATE_KEY = "product.category_corrected";
    static final String TEMPLATE_VERSION = "1";
    static final String SUMMARY = "商品分类已纠正";
    static final String BODY = "管理员根据事项纠正了该商品的分类。你可以前往商品详情查看当前分类。";

    @Bean
    ProductCorrectionNotices productCorrectionNotices(NotificationApplication notifications, UserEvents events) {
        return (context, sellerId, productId, editId, caseId, productTitle, occurredAt) -> {
            String intentKey = EVENT_TYPE + ":" + editId;
            Map<String, String> params = new LinkedHashMap<>();
            params.put("product_id", Long.toString(productId));
            params.put("case_id", Long.toString(caseId));
            var pending = new ArrayList<EventIntent>();
            NotificationEventSink sink = (recipients, eventType, schemaVersion, source, key, payload, sourceSequence) ->
                    recipients.stream().sorted()
                            .map(recipient -> new EventIntent(UUID.randomUUID(), recipient, eventType, schemaVersion,
                                    source, key, payload, sourceSequence))
                            .forEach(pending::add);
            var intent = new NotificationIntent(Set.of(sellerId),
                    UUID.nameUUIDFromBytes(intentKey.getBytes(StandardCharsets.UTF_8)), EVENT_TYPE,
                    new ResourceRef(SOURCE_TYPE, editId), intentKey, TEMPLATE_KEY, TEMPLATE_VERSION, params,
                    occurredAt);
            notifications.createNotifications(sink, intent);
            events.persist(context, pending);
        };
    }

    /** Projects the notice onto the product, and hides it from any reader but the seller. */
    @Bean
    NotificationSourcePort productCorrectionNotificationSource(JdbcClient jdbc) {
        return (context, facts) -> {
            if (!SOURCE_TYPE.equals(facts.source().type()) || !EVENT_TYPE.equals(facts.eventType())
                    || context.actorKind() != ExecutionContext.ActorKind.ACCOUNT) {
                return Optional.empty();
            }
            long accountId = Long.parseLong(context.actorId());
            return jdbc.sql("""
                            SELECT p.product_id, p.title
                            FROM product_edit_history e JOIN product p ON p.product_id = e.product_id
                            WHERE e.edit_id = ? AND p.seller_account_id = ? AND p.deleted_at IS NULL
                            """)
                    .param(facts.source().id()).param(accountId)
                    .query((row, index) -> new NotificationSourcePort.NotificationSourceView(SUMMARY,
                            new ResourceRef("product", row.getLong("product_id")), row.getString("title"), BODY))
                    .optional();
        };
    }
}
