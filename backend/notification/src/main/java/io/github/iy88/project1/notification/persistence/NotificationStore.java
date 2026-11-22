package io.github.iy88.project1.notification.persistence;

import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteTransaction;
import io.github.iy88.project1.notification.application.NotificationIntent;
import io.github.iy88.project1.notification.application.NotificationItem;
import io.github.iy88.project1.notification.application.NotificationQuery;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * Persistence port of the notification module.
 *
 * Split from the application service so the rules (intent replay, first read,
 * recipient-only access) can be unit tested without a database and the JPA
 * mapping stays replaceable.
 */
public interface NotificationStore {
    Optional<Stored> find(long recipientAccountId, String intentKey);

    Stored insert(long recipientAccountId, NotificationIntent intent, Instant now);

    /**
     * Acquire the notification row under the caller's transaction and lock plan.
     *
     * The row is locked through {@link WriteTransaction#lock} so it follows the
     * shared lock order: the notification row comes after the account and
     * source-object locks the caller already declared.
     */
    Optional<Stored> lock(WriteTransaction transaction, long notificationId, long recipientAccountId);

    Optional<Stored> findForRecipient(long notificationId, long recipientAccountId);

    Stored markRead(Stored current, Instant readAt);

    List<Stored> page(long recipientAccountId, NotificationQuery.ReadFilter filter, String eventType, int page,
                      int pageSize);

    long count(long recipientAccountId, NotificationQuery.ReadFilter filter, String eventType);

    long unreadCount(long recipientAccountId);

    /** One stored notification with the fields the read rules need. */
    record Stored(long notificationId, long recipientAccountId, String intentKey, String eventType,
                  ResourceRef source, String templateKey, String templateVersion,
                  Map<String, String> displayParams, Instant occurredAt, Instant createdAt, Instant readAt) {
        public Stored {
            displayParams = displayParams == null ? Map.of() : Map.copyOf(displayParams);
        }

        public NotificationItem item() {
            return new NotificationItem(notificationId, recipientAccountId, intentKey, createdAt, readAt);
        }

        /**
         * True when this row was produced by the same business intent.
         *
         * Template parameters are part of the comparison: the same intent key with
         * only a different reason would otherwise silently return the old entry
         * instead of reporting the conflict the contract requires.
         */
        public boolean describes(NotificationIntent intent) {
            return eventType.equals(intent.eventType()) && source.equals(intent.source())
                    && templateKey.equals(intent.templateKey())
                    && templateVersion.equals(intent.templateVersion())
                    && displayParams.equals(intent.orderedDisplayParams());
        }
    }
}
