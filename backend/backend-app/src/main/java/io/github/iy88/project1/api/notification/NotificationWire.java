package io.github.iy88.project1.api.notification;

import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.notification.application.NotificationItem;
import io.github.iy88.project1.notification.application.NotificationPage;
import io.github.iy88.project1.notification.application.NotificationView;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * JSON shape of the notification endpoints (API-COM-NOTIFY-002—004).
 *
 * Ids are decimal strings and times are UTC ISO 8601, matching the shared
 * conventions. A null `read_at` stays in the payload as an explicit null so the
 * client can tell "unread" from "field missing", and a null `source` means the
 * linked object is no longer visible to this reader.
 */
final class NotificationWire {
    private NotificationWire() {}

    private static Map<String, Object> summary(NotificationView view) {
        var body = new LinkedHashMap<String, Object>();
        body.put("notification_id", Long.toString(view.notificationId()));
        body.put("event_type", view.eventType());
        body.put("occurred_at", view.occurredAt());
        body.put("read_at", view.readAt());
        body.put("summary", view.summary());
        body.put("source", source(view.source()));
        if (view.subject() != null) body.put("subject", view.subject());
        return body;
    }

    static Map<String, Object> detail(NotificationView view) {
        var body = summary(view);
        if (view.body() != null) body.put("body", view.body());
        if (view.commentId() != null) body.put("comment_id", Long.toString(view.commentId()));
        if (view.caseMessageId() != null) body.put("case_message_id", Long.toString(view.caseMessageId()));
        if (view.anchor() != null) body.put("anchor", view.anchor());
        return body;
    }

    static Map<String, Object> page(NotificationPage page) {
        var body = new LinkedHashMap<String, Object>();
        body.put("items", page.items().stream().map(NotificationWire::summary).toList());
        body.put("page", page.page());
        body.put("page_size", page.pageSize());
        body.put("total", page.total());
        body.put("unread_count", page.unreadCount());
        return body;
    }

    static Map<String, Object> item(NotificationItem item) {
        var body = new LinkedHashMap<String, Object>();
        body.put("notification_id", Long.toString(item.notificationId()));
        body.put("read_at", item.readAt());
        return body;
    }

    private static Map<String, Object> source(ResourceRef source) {
        if (source == null) return null;
        return Map.of("resource_type", source.type(), "resource_id", Long.toString(source.id()));
    }
}
