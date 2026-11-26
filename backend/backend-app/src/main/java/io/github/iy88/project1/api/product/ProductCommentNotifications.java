package io.github.iy88.project1.api.product;

import io.github.iy88.project1.core.EventIntent;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.messaging.UserEvents;
import io.github.iy88.project1.notification.application.NotificationApplication;
import io.github.iy88.project1.notification.application.NotificationIntent;
import io.github.iy88.project1.notification.application.NotificationSourcePort;
import io.github.iy88.project1.product.application.ProductCommentNotice;
import io.github.iy88.project1.product.application.ProductInteractions;
import io.github.iy88.project1.product.application.ProductService;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import org.springframework.context.annotation.Profile;
import org.springframework.context.event.EventListener;
import org.springframework.stereotype.Component;

@Component
@Profile("infrastructure & !dependency-probe & !file-probe")
class ProductCommentNotifications implements NotificationSourcePort {
    private static final String COMMENT_CREATED = "product_comment.created";
    private static final String COMMENT_REPLIED = "product_comment.replied";

    private final NotificationApplication notifications;
    private final UserEvents events;
    private final ProductService products;
    private final ProductInteractions interactions;

    ProductCommentNotifications(NotificationApplication notifications, UserEvents events, ProductService products,
                                ProductInteractions interactions) {
        this.notifications = notifications;
        this.events = events;
        this.products = products;
        this.interactions = interactions;
    }

    @EventListener
    void create(ProductCommentNotice notice) {
        String eventType = notice.reply() ? COMMENT_REPLIED : COMMENT_CREATED;
        String intentKey = eventType + ":" + notice.commentId();
        UUID eventId = UUID.randomUUID();
        var context = new ExecutionContext(eventId, ExecutionContext.ActorKind.SYSTEM, "product-comment",
                null, null, null, "product-comment");
        var intent = new NotificationIntent(Set.of(notice.recipientId()), eventId, eventType,
                new ResourceRef("product", notice.productId()), intentKey, eventType, "1", Map.of(),
                notice.occurredAt());
        // The synchronous listener stores both the notification and delivery intent in the comment transaction.
        notifications.createNotifications((recipients, type, version, source, key, payload, sequence) ->
                events.persist(context, List.of(new EventIntent(UUID.randomUUID(), notice.recipientId(), type,
                        version, source, key, payload, sequence))), intent);
    }

    @Override
    public Optional<NotificationSourceView> project(ExecutionContext context, NotificationFacts facts) {
        if (!"product".equals(facts.source().type()) || context.actorKind() != ExecutionContext.ActorKind.ACCOUNT
                || !context.actorId().equals(Long.toString(facts.recipientAccountId()))) {
            return Optional.empty();
        }
        String summary = switch (facts.eventType()) {
            case COMMENT_CREATED -> "你的商品收到新评论";
            case COMMENT_REPLIED -> "卖家回复了你的评论";
            default -> null;
        };
        if (summary == null) {
            return Optional.empty();
        }
        return Optional.of(products.notificationTitle(facts.recipientAccountId(), facts.source().id())
                .map(title -> commentView(facts, summary, title))
                .orElseGet(() -> new NotificationSourceView(summary, null, null, "关联商品当前不可查看。")));
    }

    private NotificationSourceView commentView(NotificationFacts facts, String summary, String title) {
        if (!facts.includeBody()) {
            return new NotificationSourceView(summary, facts.source(), title, null);
        }
        var unavailable = new NotificationSourceView(summary, facts.source(), title, "该评论当前不可查看。");
        // The intent key has included the exact comment ID since the first comment notification.
        String prefix = facts.eventType() + ":";
        if (!facts.intentKey().startsWith(prefix)) {
            return unavailable;
        }
        try {
            long id = Long.parseLong(facts.intentKey().substring(prefix.length()));
            return interactions.notificationCommentBody(facts.recipientAccountId(), facts.source().id(), id,
                            COMMENT_REPLIED.equals(facts.eventType()))
                    .map(body -> new NotificationSourceView(summary, facts.source(), title, body, id))
                    .orElse(unavailable);
        } catch (NumberFormatException invalid) {
            return unavailable;
        }
    }
}
