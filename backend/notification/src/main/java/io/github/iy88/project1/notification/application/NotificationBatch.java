package io.github.iy88.project1.notification.application;

import java.util.List;

/** Result of {@code create_notifications}: items sorted by recipient account id. */
public record NotificationBatch(List<NotificationItem> items) {
    public NotificationBatch {
        items = List.copyOf(items);
    }
}
