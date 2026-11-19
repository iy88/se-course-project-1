package io.github.iy88.project1.messaging;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteTransaction;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Objects;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import org.springframework.context.annotation.Profile;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

@Service
@Profile("infrastructure")
public class TaskSchedules {
    private static final String FIELDS = """
            task_id, task_kind, source_type, source_id, trigger_key, source_version, due_at, rule_version
            """;
    private final JdbcClient jdbc;
    private final DeliverySettings settings;

    public TaskSchedules(JdbcClient jdbc, DeliverySettings settings) {
        this.jdbc = jdbc;
        this.settings = settings;
    }

    @Transactional(propagation = Propagation.MANDATORY)
    public Task schedule(Spec spec) {
        var due = spec.dueAt().atOffset(ZoneOffset.UTC);
        jdbc.sql("""
                INSERT INTO task_schedule(task_id, task_kind, source_type, source_id, trigger_key,
                    source_version, due_at, rule_version, next_attempt_at)
                VALUES (:id, :kind, :type, :source, :trigger, :version, :due, :rule, :due)
                ON CONFLICT (task_kind, trigger_key) DO NOTHING
                """).param("id", UUID.randomUUID()).param("kind", spec.kind()).param("type", spec.source().type())
                .param("source", spec.source().id()).param("trigger", spec.triggerKey())
                .param("version", spec.sourceVersion()).param("due", due).param("rule", spec.ruleVersion()).update();
        var task = jdbc.sql("SELECT " + FIELDS + " FROM task_schedule WHERE task_kind = :kind AND trigger_key = :trigger")
                .param("kind", spec.kind()).param("trigger", spec.triggerKey()).query((row, index) -> task(row)).single();
        if (!task.spec().equals(spec)) {
            throw new BusinessError("TASK_TRIGGER_CONFLICT", 409, "任务触发条件冲突");
        }
        return task;
    }

    public List<Ready> due(Set<String> kinds) {
        if (kinds.isEmpty()) return List.of();
        jdbc.sql("""
                WITH expired AS (
                    SELECT task_id FROM task_schedule
                    WHERE task_kind IN (:kinds) AND completed_at IS NULL AND cancelled_at IS NULL
                        AND attempts >= :retries AND lease_until <= statement_timestamp()
                    ORDER BY lease_until, task_id LIMIT :limit FOR UPDATE SKIP LOCKED
                )
                UPDATE task_schedule t SET lease_token = NULL, lease_until = NULL, last_error = 'TASK_LEASE_EXPIRED'
                FROM expired e WHERE t.task_id = e.task_id
                """).param("kinds", kinds).param("retries", settings.retryLimit())
                .param("limit", settings.batchSize()).update();
        return jdbc.sql("""
                SELECT task_id, task_kind FROM task_schedule WHERE task_kind IN (:kinds)
                  AND completed_at IS NULL AND cancelled_at IS NULL
                  AND due_at <= statement_timestamp() AND next_attempt_at <= statement_timestamp()
                  AND (lease_until IS NULL OR lease_until <= statement_timestamp())
                  AND attempts < :retries
                ORDER BY next_attempt_at, task_id LIMIT :limit
                """).param("kinds", kinds).param("retries", settings.retryLimit()).param("limit", settings.batchSize())
                .query((row, index) -> new Ready(row.getObject(1, UUID.class), row.getString(2))).list();
    }

    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public Optional<Lease> claim(Ready ready) {
        var token = UUID.randomUUID();
        return jdbc.sql("""
                WITH candidate AS (
                    SELECT task_id FROM task_schedule WHERE task_id = :id AND task_kind = :kind
                        AND completed_at IS NULL AND cancelled_at IS NULL AND due_at <= statement_timestamp()
                        AND next_attempt_at <= statement_timestamp()
                        AND (lease_until IS NULL OR lease_until <= statement_timestamp())
                        AND attempts < :retries FOR UPDATE SKIP LOCKED
                )
                UPDATE task_schedule SET lease_token = :token,
                    lease_until = statement_timestamp() + :lease * interval '1 second', attempts = attempts + 1
                WHERE task_id = (SELECT task_id FROM candidate)
                RETURNING
                """ + FIELDS + ", attempts, lease_until")
                .param("token", token).param("lease", settings.leaseSeconds()).param("id", ready.id())
                .param("kind", ready.kind()).param("retries", settings.retryLimit()).query((row, index) ->
                        new Lease(task(row), token, instant(row, "lease_until"), row.getInt("attempts"))).optional();
    }

    public boolean canAcknowledge(Ready ready) {
        return jdbc.sql("""
                SELECT NOT EXISTS (
                    SELECT 1 FROM task_schedule WHERE task_id = :id AND task_kind = :kind
                        AND completed_at IS NULL AND cancelled_at IS NULL
                        AND due_at <= statement_timestamp() AND next_attempt_at <= statement_timestamp()
                        AND (lease_until IS NULL OR lease_until <= statement_timestamp()) AND attempts < :retries
                )
                """).param("id", ready.id()).param("kind", ready.kind()).param("retries", settings.retryLimit())
                .query(Boolean.class).single();
    }

    public void requireLease(WriteTransaction transaction, Lease lease) {
        transaction.lock(key(lease.task().id()), () -> {
            var locked = jdbc.sql("""
                    SELECT lease_token, lease_until FROM task_schedule WHERE task_id = :id
                        AND completed_at IS NULL AND cancelled_at IS NULL FOR UPDATE
                    """).param("id", lease.task().id())
                    .query((row, index) -> new LeaseStamp(row.getObject("lease_token", UUID.class),
                            instant(row, "lease_until"))).optional();
            var now = jdbc.sql("SELECT clock_timestamp()").query(OffsetDateTime.class).single().toInstant();
            if (locked.isEmpty() || !lease.token().equals(locked.get().token()) || locked.get().until() == null
                    || !now.isBefore(locked.get().until())) {
                throw lostLease();
            }
        });
    }

    @Transactional(propagation = Propagation.MANDATORY)
    public void finish(WriteTransaction transaction, Lease lease, boolean obsolete) {
        requireLease(transaction, lease);
        String terminal = obsolete ? "cancelled_at" : "completed_at";
        jdbc.sql("UPDATE task_schedule SET " + terminal + """
                = statement_timestamp(), lease_token = NULL, lease_until = NULL, last_error = NULL
                WHERE task_id = :id AND lease_token = :token
                """).param("id", lease.task().id()).param("token", lease.token()).update();
    }

    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public boolean retry(Lease lease, String errorCode) {
        if (errorCode == null || !errorCode.matches("[A-Z][A-Z0-9_]{0,63}")) {
            throw new IllegalArgumentException("Expected a task error code");
        }
        return jdbc.sql("""
                UPDATE task_schedule SET lease_token = NULL, lease_until = NULL, last_error = :error,
                    next_attempt_at = statement_timestamp() + :delay * interval '1 second'
                WHERE task_id = :id AND lease_token = :token AND lease_until > statement_timestamp()
                """).param("error", errorCode).param("delay", settings.retryDelay(lease.attempt()))
                .param("id", lease.task().id()).param("token", lease.token()).update() == 1;
    }

    public static LockPlan.Key key(UUID id) {
        long high = id.getMostSignificantBits();
        long low = id.getLeastSignificantBits();
        return new LockPlan.Key(LockPlan.Domain.TASK, List.of(high >>> 1, high & 1, low >>> 1, low & 1));
    }

    private static BusinessError lostLease() {
        return new BusinessError("TASK_LEASE_LOST", 409, "任务租约已失效");
    }

    private static Task task(ResultSet row) throws SQLException {
        return new Task(row.getObject("task_id", UUID.class), new Spec(row.getString("task_kind"),
                new ResourceRef(row.getString("source_type"), row.getLong("source_id")), row.getString("trigger_key"),
                row.getString("source_version"), instant(row, "due_at"), row.getString("rule_version")));
    }

    private static Instant instant(ResultSet row, String column) throws SQLException {
        var value = row.getObject(column, OffsetDateTime.class);
        return value == null ? null : value.toInstant();
    }

    public record Spec(String kind, ResourceRef source, String triggerKey, String sourceVersion, Instant dueAt,
                       String ruleVersion) {
        public Spec {
            Objects.requireNonNull(source);
            dueAt = dueAt.truncatedTo(java.time.temporal.ChronoUnit.MICROS);
            if (kind == null || !kind.matches("[a-z][a-z0-9_.-]*") || triggerKey == null || triggerKey.isBlank()
                    || sourceVersion == null || sourceVersion.isBlank() || ruleVersion == null || ruleVersion.isBlank()) {
                throw new IllegalArgumentException("Invalid task schedule");
            }
        }
    }

    public record Ready(UUID id, String kind) {}
    public record Task(UUID id, Spec spec) {}
    public record Lease(Task task, UUID token, Instant until, int attempt) {}
    private record LeaseStamp(UUID token, Instant until) {}
}
