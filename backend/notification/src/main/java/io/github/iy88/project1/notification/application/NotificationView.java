package io.github.iy88.project1.notification.application;

import io.github.iy88.project1.core.ResourceRef;
import java.time.Instant;

/**
 * One notification as the recipient may currently see it.
 *
 * {@code summary} is produced by the owning module's source projection for the
 * reader's current visibility; {@code source} is null when the recipient can no
 * longer open the linked object, in which case the entry keeps only the approved
 * event hint and no jump target.
 */
public record NotificationView(long notificationId, String eventType, Instant occurredAt, Instant readAt,
                               String summary, ResourceRef source, String subject, String body, Long commentId,
                               Long caseMessageId, String anchor) {
    public NotificationView(long notificationId, String eventType, Instant occurredAt, Instant readAt,
                            String summary, ResourceRef source, String subject, String body, Long commentId,
                            Long caseMessageId) {
        this(notificationId, eventType, occurredAt, readAt, summary, source, subject, body, commentId,
                caseMessageId, null);
    }
    public NotificationView(long notificationId, String eventType, Instant occurredAt, Instant readAt,
                            String summary, ResourceRef source, String subject, String body) {
        this(notificationId, eventType, occurredAt, readAt, summary, source, subject, body, null, null);
    }
}
