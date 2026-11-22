package io.github.iy88.project1.notification.application;

import java.util.Objects;

/**
 * Read filters of API-COM-NOTIFY-002.
 *
 * {@code eventType} is applied as part of the paging predicate, never after the
 * page has been built, so {@code total} is the recipient's total for the same
 * filter.
 */
public record NotificationQuery(int page, int pageSize, ReadFilter read, String eventType) {
    public static final int DEFAULT_PAGE_SIZE = 20;
    public static final int MAX_PAGE_SIZE = 100;

    public NotificationQuery {
        if (page < 1) {
            throw new IllegalArgumentException("page must be at least 1");
        }
        if (pageSize < 1 || pageSize > MAX_PAGE_SIZE) {
            throw new IllegalArgumentException("page_size must be between 1 and " + MAX_PAGE_SIZE);
        }
        read = read == null ? ReadFilter.ALL : read;
        if (eventType != null) {
            Objects.requireNonNull(eventType);
            if (eventType.isBlank()) {
                throw new IllegalArgumentException("event_type must not be blank");
            }
        }
    }

    public static NotificationQuery firstPage() {
        return new NotificationQuery(1, DEFAULT_PAGE_SIZE, ReadFilter.ALL, null);
    }

    public enum ReadFilter {
        ALL, UNREAD, READ
    }
}
