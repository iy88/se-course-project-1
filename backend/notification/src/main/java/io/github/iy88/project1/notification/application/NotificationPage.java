package io.github.iy88.project1.notification.application;

import java.util.List;

/**
 * One page of the recipient's notifications plus their whole unread total.
 *
 * {@code unreadCount} is not affected by the read or event filter, per
 * API-COM-NOTIFY-002.
 */
public record NotificationPage(List<NotificationView> items, int page, int pageSize, long total,
                               long unreadCount) {
    public NotificationPage {
        items = List.copyOf(items);
    }
}
