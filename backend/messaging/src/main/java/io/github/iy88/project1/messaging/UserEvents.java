package io.github.iy88.project1.messaging;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.EventIntent;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.ResourceRef;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import java.util.UUID;
import java.util.stream.Collectors;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Profile;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

@Service
@Profile("infrastructure")
@EnableConfigurationProperties(DeliverySettings.class)
public class UserEvents implements EventIntent.Writer {
    private final JdbcClient jdbc;
    private final DeliverySettings settings;

    public UserEvents(JdbcClient jdbc, DeliverySettings settings) {
        this.jdbc = jdbc;
        this.settings = settings;
    }

    @Override
    @Transactional(propagation = Propagation.MANDATORY)
    public void persist(ExecutionContext context, List<EventIntent> intents) {
        var groups = intents.stream().collect(Collectors.groupingBy(EventIntent::recipientAccountId,
                TreeMap::new, Collectors.toList()));
        try {
            groups.forEach((account, events) -> append(account, events, context.originConnectionId()));
        } catch (DuplicateKeyException conflict) {
            throw new BusinessError("EVENT_INTENT_CONFLICT", 409, "事件意图重复");
        }
    }

    private void append(long account, List<EventIntent> events, UUID originConnection) {
        jdbc.sql("INSERT INTO account_event_head(account_id) VALUES (?) ON CONFLICT DO NOTHING")
                .param(account).update();
        long tail = jdbc.sql("""
                UPDATE account_event_head SET seq_head = seq_head + :size
                WHERE account_id = :account RETURNING seq_head
                """).param("size", events.size()).param("account", account).query(Long.class).single();
        long sequence = tail - events.size();
        for (var event : events) {
            var payload = event.payload();
            jdbc.sql("""
                    INSERT INTO user_event(event_id, recipient_account_id, account_seq, event_type, schema_version,
                        intent_key, source_type, source_id, payload_type, payload_id, source_sequence,
                        origin_connection_id, occurred_at, created_at, expires_at, next_attempt_at)
                    VALUES (:event, :account, :sequence, :type, :version, :intent, :sourceType, :sourceId, :payloadType,
                        :payloadId, :sourceSequence, :origin, statement_timestamp(), statement_timestamp(),
                        statement_timestamp() + :retention * interval '1 second', statement_timestamp())
                    """).param("event", event.eventId()).param("account", account).param("sequence", ++sequence)
                    .param("type", event.eventType()).param("version", event.schemaVersion())
                    .param("intent", event.intentKey()).param("sourceType", event.source().type())
                    .param("sourceId", event.source().id()).param("payloadType", payload == null ? null : payload.type())
                    .param("payloadId", payload == null ? null : payload.id())
                    .param("sourceSequence", event.sourceSequence()).param("origin", originConnection)
                    .param("retention", settings.retentionSeconds()).update();
        }
    }

    @Transactional(readOnly = true)
    public Head head(long account) {
        if (account <= 0) throw new IllegalArgumentException("Account ID must be positive");
        return jdbc.sql("""
                SELECT epoch, coalesce(seq_head, 0), coalesce(replay_floor, 0)
                FROM event_namespace LEFT JOIN account_event_head ON account_id = :account
                WHERE singleton
                """).param("account", account).query((row, index) ->
                new Head(row.getObject(1, UUID.class), row.getLong(2), row.getLong(3))).single();
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ, propagation = Propagation.REQUIRES_NEW)
    public Page scan(long account, UUID epoch, long after, int limit) {
        if (limit < 1 || limit > settings.replayMax() || after < 0) {
            throw new BusinessError("INPUT_INVALID", 422, "事件读取参数无效");
        }
        var head = head(account);
        if (!head.epoch().equals(epoch) || after < head.replayFloor() || after > head.headSequence()) {
            throw new BusinessError("EVENT_RESYNC_REQUIRED", 409, "需要重新同步事件",
                    Map.of("epoch", head.epoch(), "head_seq", head.headSequence(), "replay_floor", head.replayFloor()));
        }
        var rows = jdbc.sql("""
                SELECT event_id, account_seq, event_type, schema_version, source_type, source_id,
                    payload_type, payload_id, source_sequence, origin_connection_id, occurred_at
                FROM user_event WHERE recipient_account_id = :account AND account_seq > :after
                ORDER BY account_seq LIMIT :limit
                """).param("account", account).param("after", after).param("limit", limit)
                .query((row, index) -> event(row)).list();
        long next = rows.isEmpty() ? after : rows.getLast().sequence();
        return new Page(head, rows, next, next < head.headSequence());
    }

    @Transactional
    public int pruneExpired() {
        // The head row serializes retention updates with sequence allocation.
        var accounts = jdbc.sql("""
                SELECT h.account_id FROM account_event_head h JOIN user_event e
                    ON e.recipient_account_id = h.account_id AND e.account_seq = h.replay_floor + 1
                WHERE e.expires_at <= statement_timestamp() ORDER BY h.account_id
                LIMIT :limit FOR UPDATE OF h SKIP LOCKED
                """).param("limit", settings.batchSize()).query(Long.class).list();
        int deleted = 0;
        for (long account : accounts) {
            int remaining = settings.batchSize() - deleted;
            if (remaining == 0) break;
            var removed = jdbc.sql("""
                    WITH prefix AS (
                        SELECT e.account_seq
                        FROM user_event e JOIN account_event_head h ON h.account_id = e.recipient_account_id
                        WHERE e.recipient_account_id = :account AND e.account_seq > h.replay_floor
                          AND e.account_seq <= h.replay_floor + :limit
                        ORDER BY e.account_seq
                    ), expired AS (
                        SELECT account_seq FROM prefix WHERE account_seq < coalesce((
                            SELECT min(e.account_seq) FROM user_event e JOIN prefix p USING (account_seq)
                            WHERE e.recipient_account_id = :account AND e.expires_at > statement_timestamp()
                        ), 9007199254740992)
                    )
                    DELETE FROM user_event e USING expired x
                    WHERE e.recipient_account_id = :account AND e.account_seq = x.account_seq
                    RETURNING e.account_seq
                    """).param("account", account).param("limit", remaining).query(Long.class).list();
            if (!removed.isEmpty()) {
                long floor = removed.stream().mapToLong(Long::longValue).max().orElseThrow();
                jdbc.sql("UPDATE account_event_head SET replay_floor = ? WHERE account_id = ?")
                        .param(floor).param(account).update();
                deleted += removed.size();
            }
        }
        return deleted;
    }

    private static Event event(ResultSet row) throws SQLException {
        String payloadType = row.getString("payload_type");
        return new Event(row.getObject("event_id", UUID.class), row.getLong("account_seq"),
                row.getString("event_type"), row.getInt("schema_version"),
                new ResourceRef(row.getString("source_type"), row.getLong("source_id")),
                payloadType == null ? null : new ResourceRef(payloadType, row.getLong("payload_id")),
                row.getObject("source_sequence", Long.class), row.getObject("origin_connection_id", UUID.class),
                row.getObject("occurred_at", OffsetDateTime.class).toInstant());
    }

    public record Head(UUID epoch, long headSequence, long replayFloor) {}
    public record Event(UUID eventId, long sequence, String type, int schemaVersion, ResourceRef source,
                        ResourceRef payload, Long sourceSequence, UUID originConnectionId, Instant occurredAt) {}
    public record Page(Head head, List<Event> events, long nextSequence, boolean hasMore) {}
}
