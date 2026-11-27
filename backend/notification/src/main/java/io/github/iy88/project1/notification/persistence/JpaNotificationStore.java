package io.github.iy88.project1.notification.persistence;

import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.WriteTransaction;
import io.github.iy88.project1.notification.application.NotificationIntent;
import io.github.iy88.project1.notification.application.NotificationQuery;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicReference;
import org.springframework.context.annotation.Lazy;
import org.springframework.data.domain.PageRequest;
import org.springframework.stereotype.Repository;

/**
 * JPA implementation of the notification store.
 *
 * Lazy so a context that has no data source (the probe-only application context)
 * can start without trying to build this repository.
 */
@Lazy
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
    public Optional<Stored> lock(WriteTransaction transaction, long notificationId, long recipientAccountId) {
        var locked = new AtomicReference<Optional<NotificationRecord>>(Optional.empty());
        transaction.lock(new LockPlan.Key(LockPlan.Domain.NOTIFICATION, List.of(notificationId)),
                () -> locked.set(repository.lockByIdAndRecipient(notificationId, recipientAccountId)));
        return locked.get().map(NotificationRecord::snapshot);
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
                             int page, int pageSize, boolean management) {
        var pageable = PageRequest.of(page - 1, pageSize);
        return repository.pageFor(recipientAccountId, readState(filter), eventType, management, pageable).stream()
                .map(NotificationRecord::snapshot)
                .toList();
    }

    @Override
    public long count(long recipientAccountId, NotificationQuery.ReadFilter filter, String eventType, boolean management) {
        return repository.countFor(recipientAccountId, readState(filter), eventType, management);
    }

    @Override
    public long unreadCount(long recipientAccountId, boolean management) {
        return repository.countUnread(recipientAccountId, management);
    }

    private static int readState(NotificationQuery.ReadFilter filter) {
        return switch (filter) {
            case ALL -> 0;
            case UNREAD -> 1;
            case READ -> 2;
        };
    }
}
