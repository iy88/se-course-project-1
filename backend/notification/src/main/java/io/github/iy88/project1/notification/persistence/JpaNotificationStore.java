package io.github.iy88.project1.notification.persistence;

import io.github.iy88.project1.notification.application.NotificationIntent;
import io.github.iy88.project1.notification.application.NotificationQuery;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import org.springframework.data.domain.PageRequest;
import org.springframework.stereotype.Repository;

/** JPA implementation of the notification store. */
@Repository
class JpaNotificationStore implements NotificationStore {
    private final NotificationRepository repository;

    JpaNotificationStore(NotificationRepository repository) {
        this.repository = repository;
    }

    @Override
    public Optional<Stored> find(long recipientAccountId, String intentKey) {
        return repository.findByRecipientAccountIdAndIntentKey(recipientAccountId, intentKey)
                .map(NotificationRecord::snapshot);
    }

    @Override
    public Stored insert(long recipientAccountId, NotificationIntent intent, Instant now) {
        var record = new NotificationRecord(recipientAccountId, intent.intentKey(), intent.eventType(),
                intent.businessEventId(), intent.source(), intent.templateKey(), intent.templateVersion(),
                intent.orderedDisplayParams(), intent.occurredAt(), now);
        return repository.save(record).snapshot();
    }

    @Override
    public Optional<Stored> lock(long notificationId, long recipientAccountId) {
        return repository.lockByIdAndRecipient(notificationId, recipientAccountId)
                .map(NotificationRecord::snapshot);
    }

    @Override
    public Optional<Stored> findForRecipient(long notificationId, long recipientAccountId) {
        return repository.findByIdAndRecipientAccountId(notificationId, recipientAccountId)
                .map(NotificationRecord::snapshot);
    }

    @Override
    public Stored markRead(Stored current, Instant readAt) {
        var record = repository.findById(current.notificationId()).orElseThrow();
        record.markRead(readAt);
        return repository.save(record).snapshot();
    }

    @Override
    public List<Stored> page(long recipientAccountId, NotificationQuery.ReadFilter filter, String eventType,
                             int page, int pageSize) {
        var pageable = PageRequest.of(page - 1, pageSize);
        return repository.pageFor(recipientAccountId, readState(filter), eventType, pageable).stream()
                .map(NotificationRecord::snapshot)
                .toList();
    }

    @Override
    public long count(long recipientAccountId, NotificationQuery.ReadFilter filter, String eventType) {
        return repository.countFor(recipientAccountId, readState(filter), eventType);
    }

    @Override
    public long unreadCount(long recipientAccountId) {
        return repository.countUnread(recipientAccountId);
    }

    private static int readState(NotificationQuery.ReadFilter filter) {
        return switch (filter) {
            case ALL -> 0;
            case UNREAD -> 1;
            case READ -> 2;
        };
    }
}
