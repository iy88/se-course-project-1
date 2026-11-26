package io.github.iy88.project1.notification.application;

import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.ResourceRef;
import java.time.Instant;
import java.util.Map;
import java.util.Optional;

/**
 * Source projection port.
 *
 * The notification module owns the notification facts (event type, template,
 * source, first read). The owning module owns the wording and the current
 * visibility of the linked object, so it decides what the recipient may read.
 * A missing projection means "the source is not visible to this reader": the
 * entry keeps the approved event hint and hides the jump target.
 */
@FunctionalInterface
public interface NotificationSourcePort {
    Optional<NotificationSourceView> project(ExecutionContext context, NotificationFacts facts);

    /** Everything the source module needs to render one entry for one reader. */
    record NotificationFacts(long notificationId, long recipientAccountId, String eventType,
                             ResourceRef source, String templateKey, String templateVersion,
                             Map<String, String> displayParams, Instant occurredAt, Instant readAt,
                             String intentKey, boolean includeBody) {}

    /**
     * @param summary approved text for the current reader; must not contain
     *                fields the reader is no longer allowed to see
     * @param source  the object the reader may open, or null to hide the jump
     */
    record NotificationSourceView(String summary, ResourceRef source, String subject, String body, Long commentId,
                                  Long caseMessageId, String anchor) {
        public NotificationSourceView(String summary, ResourceRef source, String subject, String body, Long commentId,
                                      Long caseMessageId) {
            this(summary, source, subject, body, commentId, caseMessageId, null);
        }

        public NotificationSourceView(String summary, ResourceRef source, String subject, String body, Long commentId) {
            this(summary, source, subject, body, commentId, null);
        }

        public NotificationSourceView(String summary, ResourceRef source, String subject, String body) {
            this(summary, source, subject, body, null);
        }

        public NotificationSourceView(String summary, ResourceRef source) {
            this(summary, source, null, null);
        }
    }
}
