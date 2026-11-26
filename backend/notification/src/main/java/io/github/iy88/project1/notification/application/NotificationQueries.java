package io.github.iy88.project1.notification.application;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.notification.persistence.NotificationStore;
import java.util.List;
import java.util.Optional;

/**
 * Read side of the notification module (API-COM-NOTIFY-002／003).
 *
 * Only the recipient's own rows are visible; an entry whose source is no longer
 * readable keeps the approved event hint and shows no jump target. The summary is
 * produced by the source module for the current reader, so a notification can
 * never keep displaying content the reader lost access to.
 */
public class NotificationQueries {
    /** Copy used when the source module reports the linked object as not visible. */
    static final String HIDDEN_SOURCE_SUMMARY = "关联内容当前不可查看";

    private final NotificationStore store;
    private final Optional<NotificationSourcePort> sources;

    public NotificationQueries(NotificationStore store, Optional<NotificationSourcePort> sources) {
        this.store = store;
        this.sources = sources;
    }

    public NotificationPage list(ExecutionContext context, NotificationQuery query) {
        long accountId = recipientOf(context);
        List<NotificationStore.Stored> rows = store.page(accountId, query.read(), query.eventType(), query.page(),
                query.pageSize());
        long total = store.count(accountId, query.read(), query.eventType());
        long unread = store.unreadCount(accountId);
        return new NotificationPage(rows.stream().map(row -> project(context, row, false)).toList(), query.page(),
                query.pageSize(), total, unread);
    }

    public NotificationView get(ExecutionContext context, long notificationId) {
        long accountId = recipientOf(context);
        var row = store.findForRecipient(notificationId, accountId)
                .orElseThrow(() -> new BusinessError("RESOURCE_NOT_VISIBLE", 404, "通知不存在"));
        return project(context, row, true);
    }

    /** Recipient-scoped transport metadata; the source module is not consulted. */
    public Optional<NotificationItem> findRecipientItem(ExecutionContext context, long notificationId) {
        long accountId = recipientOf(context);
        return store.findForRecipient(notificationId, accountId).map(NotificationStore.Stored::item);
    }

    private NotificationView project(ExecutionContext context, NotificationStore.Stored row, boolean includeBody) {
        var projected = sources.flatMap(port -> port.project(context, facts(row, includeBody)));
        return projected
                .map(view -> new NotificationView(row.notificationId(), row.eventType(), row.occurredAt(),
                        row.readAt(), view.summary(), view.source(), view.subject(), view.body(), view.commentId(),
                        view.caseMessageId()))
                .orElseGet(() -> new NotificationView(row.notificationId(), row.eventType(), row.occurredAt(),
                        row.readAt(), HIDDEN_SOURCE_SUMMARY, null, null, null));
    }

    private static NotificationSourcePort.NotificationFacts facts(NotificationStore.Stored row, boolean includeBody) {
        return new NotificationSourcePort.NotificationFacts(row.notificationId(), row.recipientAccountId(),
                row.eventType(), row.source(), row.templateKey(), row.templateVersion(), row.displayParams(),
                row.occurredAt(), row.readAt(), row.intentKey(), includeBody);
    }

    /** The actor of a read is always an account; a guest cannot read notifications. */
    private static long recipientOf(ExecutionContext context) {
        if (context.actorKind() != ExecutionContext.ActorKind.ACCOUNT) {
            throw new BusinessError("AUTHENTICATION_REQUIRED", 401, "请先登录");
        }
        return Long.parseLong(context.actorId());
    }
}
