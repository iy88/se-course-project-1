package io.github.iy88.project1.notification.persistence;

import jakarta.persistence.LockModeType;
import java.util.List;
import java.util.Optional;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.Repository;
import org.springframework.data.repository.query.Param;

interface NotificationRepository extends Repository<NotificationRecord, Long> {
    NotificationRecord save(NotificationRecord record);

    Optional<NotificationRecord> findById(long id);

    Optional<NotificationRecord> findByRecipientAccountIdAndIntentKey(long recipientAccountId, String intentKey);

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select n from NotificationRecord n where n.id = :id and n.recipientAccountId = :recipient")
    Optional<NotificationRecord> lockByIdAndRecipient(@Param("id") long id,
                                                      @Param("recipient") long recipientAccountId);

    Optional<NotificationRecord> findByIdAndRecipientAccountId(long id, long recipientAccountId);

    /**
     * One page for the recipient. {@code readState} is 0 for all, 1 for unread and
     * 2 for read; the event filter is part of the predicate so {@code total} uses
     * the same rule before paging.
     */
    @Query("""
            select n from NotificationRecord n
            where n.recipientAccountId = :recipient
              and (:readState = 0
                   or (:readState = 1 and n.readAt is null)
                   or (:readState = 2 and n.readAt is not null))
              and (:eventType is null or n.eventType = :eventType)
              and ((:management = true and n.eventType like 'management.%')
                   or (:management = false and n.eventType not like 'management.%'))
            order by n.id desc
            """)
    List<NotificationRecord> pageFor(@Param("recipient") long recipientAccountId,
                                     @Param("readState") int readState,
                                     @Param("eventType") String eventType, @Param("management") boolean management, Pageable page);

    @Query("""
            select count(n) from NotificationRecord n
            where n.recipientAccountId = :recipient
              and (:readState = 0
                   or (:readState = 1 and n.readAt is null)
                   or (:readState = 2 and n.readAt is not null))
              and (:eventType is null or n.eventType = :eventType)
              and ((:management = true and n.eventType like 'management.%')
                   or (:management = false and n.eventType not like 'management.%'))
            """)
    long countFor(@Param("recipient") long recipientAccountId, @Param("readState") int readState,
                  @Param("eventType") String eventType, @Param("management") boolean management);

    @Query("""
            select count(n) from NotificationRecord n
            where n.recipientAccountId = :recipient and n.readAt is null
              and ((:management = true and n.eventType like 'management.%')
                   or (:management = false and n.eventType not like 'management.%'))
            """)
    long countUnread(@Param("recipient") long recipientAccountId, @Param("management") boolean management);
}
