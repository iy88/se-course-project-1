package io.github.iy88.project1.notification.application;

import io.github.iy88.project1.core.WriteTransaction;
import io.github.iy88.project1.notification.persistence.NotificationStore;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicLong;

/**
 * In-memory store used by the module's behaviour tests.
 *
 * It mirrors the rules the JPA implementation relies on: the unique scope is
 * (recipient, intent key), reads are recipient scoped, and the read instant is
 * written once.
 */
public final class InMemoryNotificationStore implements NotificationStore {
    private final Map<Long, Stored> rows = new LinkedHashMap<>();
    private final AtomicLong ids = new AtomicLong();

    @Override
    public Optional<Stored> find(long recipientAccountId, String intentKey) {
        return rows.values().stream()
                .filter(row -> row.recipientAccountId() == recipientAccountId
                        && row.intentKey().equals(intentKey))
                .findFirst();
    }

    @Override
    public Stored insert(long recipientAccountId, NotificationIntent intent, Instant now) {
        long id = ids.incrementAndGet();
        var row = new Stored(id, recipientAccountId, intent.intentKey(), intent.eventType(), intent.source(),
                intent.templateKey(), intent.templateVersion(), intent.orderedDisplayParams(), intent.occurredAt(),
                now, null);
        rows.put(id, row);
        return row;
    }

    @Override
    public Optional<Stored> lock(WriteTransaction transaction, long notificationId, long recipientAccountId) {
        return findForRecipient(notificationId, recipientAccountId);
    }

    @Override
    public Optional<Stored> findForRecipient(long notificationId, long recipientAccountId) {
        return Optional.ofNullable(rows.get(notificationId))
                .filter(row -> row.recipientAccountId() == recipientAccountId);
    }

    @Override
    public Stored markRead(Stored current, Instant readAt) {
        var stored = rows.get(current.notificationId());
        var updated = new Stored(stored.notificationId(), stored.recipientAccountId(), stored.intentKey(),
                stored.eventType(), stored.source(), stored.templateKey(), stored.templateVersion(),
                stored.displayParams(), stored.occurredAt(), stored.createdAt(),
                stored.readAt() == null ? readAt : stored.readAt());
        rows.put(updated.notificationId(), updated);
        return updated;
    }

    @Override
    public List<Stored> page(long recipientAccountId, NotificationQuery.ReadFilter filter, String eventType,
                             int page, int pageSize, boolean management) {
        List<Stored> matching = rows.values().stream()
                .filter(row -> row.recipientAccountId() == recipientAccountId)
                .filter(row -> NotificationStore.inAudience(row.eventType(), management))
                .filter(row -> matchesRead(row, filter))
                .filter(row -> eventType == null || row.eventType().equals(eventType))
                .sorted(Comparator.comparingLong((Stored entry) -> entry.notificationId()).reversed())
                .toList();
        int from = Math.min((page - 1) * pageSize, matching.size());
        int to = Math.min(from + pageSize, matching.size());
        return new ArrayList<>(matching.subList(from, to));
    }

    @Override
    public long count(long recipientAccountId, NotificationQuery.ReadFilter filter, String eventType, boolean management) {
        return rows.values().stream()
                .filter(row -> row.recipientAccountId() == recipientAccountId)
                .filter(row -> NotificationStore.inAudience(row.eventType(), management))
                .filter(row -> matchesRead(row, filter))
                .filter(row -> eventType == null || row.eventType().equals(eventType))
                .count();
    }

    @Override
    public long unreadCount(long recipientAccountId, boolean management) {
        return rows.values().stream()
                .filter(row -> row.recipientAccountId() == recipientAccountId && row.readAt() == null)
                .filter(row -> NotificationStore.inAudience(row.eventType(), management))
                .count();
    }

    /** Number of stored rows; used to assert that a replay inserted nothing. */
    public int size() {
        return rows.size();
    }

    private static boolean matchesRead(Stored row, NotificationQuery.ReadFilter filter) {
        return switch (filter) {
            case ALL -> true;
            case UNREAD -> row.readAt() == null;
            case READ -> row.readAt() != null;
        };
    }
}
