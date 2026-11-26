package io.github.iy88.project1.notification.application;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteTransaction;
import io.github.iy88.project1.notification.persistence.NotificationStore;
import java.time.Clock;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;

/**
 * Writes notification facts for an approved business intent (API-COM-NOTIFY-001)
 * and records the first read of one notification (API-COM-NOTIFY-004).
 *
 * The caller already holds the business transaction, so the notification rows and
 * the delivery intents commit or roll back with the business change: a failure
 * here aborts the whole action instead of announcing something that did not
 * happen.
 */
public class NotificationApplication {
    /** Delivery schema version of the notification event payloads. */
    public static final int SCHEMA_VERSION = 1;

    /**
     * Delivery event type of a newly created notification.
     *
     * The business type (for example {@code product_audit.rejected}) stays in the
     * notification row; the delivery event is always this one and carries the
     * created notification id, so the realtime projection can decide by recipient
     * qualification instead of by business label.
     */
    public static final String CREATED_EVENT_TYPE = "notification_created";

    /** Event type of the first-read notification. */
    public static final String READ_EVENT_TYPE = "notification_read";

    private static final String NOTIFICATION_RESOURCE = "notification";

    private final NotificationStore store;
    private final Clock clock;

    public NotificationApplication(NotificationStore store, Clock clock) {
        this.store = store;
        this.clock = clock;
    }

    /**
     * Persist one notification per recipient and register one delivery intent per
     * created notification in the caller's transaction.
     *
     * A retried intent returns the stored notifications and registers no second
     * event. The same key with different event type, source, template or template
     * parameters is a conflict, because the stored row would otherwise describe
     * another action.
     */
    public NotificationBatch createNotifications(WriteTransaction transaction, NotificationIntent intent) {
        return createNotifications(transaction::addEventIntent, intent);
    }

    /**
     * Same notification rules for a caller that owns an active transaction but not a
     * {@link WriteTransaction}. The sink registers the delivery event in that same transaction.
     */
    public NotificationBatch createNotifications(NotificationEventSink events, NotificationIntent intent) {
        Instant now = clock.instant();
        List<NotificationItem> items = new ArrayList<>();
        for (long recipient : intent.sortedRecipients()) {
            var existing = store.find(recipient, intent.intentKey());
            if (existing.isPresent()) {
                if (!existing.get().describes(intent)) {
                    throw new BusinessError("NOTIFICATION_INTENT_CONFLICT", 409,
                            "同一个意图键对应了不同的通知内容");
                }
                items.add(existing.get().item());
                continue;
            }
            var created = store.insert(recipient, intent, now);
            items.add(created.item());
            // One delivery event per created notification, addressed to its
            // recipient and pointing at the notification the client must load.
            events.register(Set.of(recipient), CREATED_EVENT_TYPE, SCHEMA_VERSION,
                    intent.source(), intent.intentKey(),
                    new ResourceRef(NOTIFICATION_RESOURCE, created.notificationId()), null);
        }
        return new NotificationBatch(items);
    }

    /**
     * Record the first read of one of the current account's notifications.
     *
     * The instant never moves once set: a second read, from this or another
     * device, returns the stored value and registers no second event.
     */
    public NotificationItem markRead(WriteTransaction transaction, long accountId, long notificationId) {
        var locked = store.lock(transaction, notificationId, accountId)
                .orElseThrow(() -> new BusinessError("RESOURCE_NOT_VISIBLE", 404, "通知不存在"));
        if (locked.readAt() != null) {
            return locked.item();
        }
        var read = store.markRead(locked, clock.instant());
        transaction.addEventIntent(Set.of(accountId), READ_EVENT_TYPE, SCHEMA_VERSION, locked.source(),
                READ_EVENT_TYPE + ":" + notificationId, new ResourceRef(NOTIFICATION_RESOURCE, notificationId), null);
        return read.item();
    }
}
