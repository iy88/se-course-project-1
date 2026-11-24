package io.github.iy88.project1.notification.application;

import java.time.Instant;

/** One persisted notification fact, as returned to the calling business action. */
public record NotificationItem(long notificationId, long recipientAccountId, String intentKey,
                               Instant createdAt, Instant readAt) {}
