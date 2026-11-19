package io.github.iy88.project1.messaging;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteTransaction;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.OffsetDateTime;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.core.simple.JdbcClient;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.startsWith;
import static org.mockito.Mockito.RETURNS_SELF;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

class TaskSchedulesTests {
    private final OffsetDateTime now = OffsetDateTime.parse("2026-11-19T00:00:00Z");
    private final TaskSchedules.Task task = new TaskSchedules.Task(UUID.randomUUID(),
            new TaskSchedules.Spec("expire-trade", new ResourceRef("trade", 8), "trigger", "v1",
                    now.minusMinutes(1).toInstant(), "rule-v1"));
    private final TaskSchedules.Lease lease = new TaskSchedules.Lease(task, UUID.randomUUID(), now.plusSeconds(1).toInstant(), 1);
    private final JdbcClient jdbc = mock(JdbcClient.class);
    private final JdbcClient.StatementSpec locked = mock(JdbcClient.StatementSpec.class, RETURNS_SELF);
    private final JdbcClient.StatementSpec update = mock(JdbcClient.StatementSpec.class, RETURNS_SELF);
    private final WriteTransaction transaction = mock(WriteTransaction.class);
    private final TaskSchedules schedules = new TaskSchedules(jdbc, new DeliverySettings(3600, 10, 30, 5, 3, 1, 3, 100));

    @BeforeEach
    void configureLeaseQueries() {
        doAnswer(call -> {
            call.<Runnable>getArgument(1).run();
            return null;
        }).when(transaction).lock(eq(TaskSchedules.key(task.id())), any(Runnable.class));
        when(jdbc.sql(startsWith("SELECT lease_token, lease_until"))).thenReturn(locked);
        when(jdbc.sql(startsWith("UPDATE task_schedule SET completed_at"))).thenReturn(update);
        var clock = mock(JdbcClient.StatementSpec.class);
        JdbcClient.MappedQuerySpec<OffsetDateTime> clockRows = mock();
        when(jdbc.sql("SELECT clock_timestamp()")).thenReturn(clock);
        when(clock.query(OffsetDateTime.class)).thenReturn(clockRows);
        when(clockRows.single()).thenReturn(now);
    }

    @Test
    void completesOnlyTheTaskWithTheCurrentUnexpiredLease() throws SQLException {
        leaseRow(lease.token(), now.plusSeconds(1));

        schedules.finish(transaction, lease, false);

        verify(transaction).lock(eq(TaskSchedules.key(task.id())), any(Runnable.class));
        verify(update).param("id", task.id());
        verify(update).param("token", lease.token());
        verify(update).update();
    }

    @Test
    void rejectsLeaseAtTheExactExpiryBoundary() throws SQLException {
        leaseRow(lease.token(), now);

        rejectsCompletion();
    }

    @Test
    void rejectsLeaseAfterAnotherWorkerTakesOver() throws SQLException {
        leaseRow(UUID.randomUUID(), now.plusSeconds(15));

        rejectsCompletion();
    }

    private void rejectsCompletion() {
        assertThatThrownBy(() -> schedules.finish(transaction, lease, false))
                .isInstanceOfSatisfying(BusinessError.class, error -> {
                    assertThat(error.code()).isEqualTo("TASK_LEASE_LOST");
                    assertThat(error.status()).isEqualTo(409);
                });
        verifyNoInteractions(update);
    }

    private void leaseRow(UUID token, OffsetDateTime until) throws SQLException {
        var row = mock(ResultSet.class);
        when(row.getObject("lease_token", UUID.class)).thenReturn(token);
        when(row.getObject("lease_until", OffsetDateTime.class)).thenReturn(until);
        when(locked.query(org.mockito.ArgumentMatchers.<RowMapper<Object>>any())).thenAnswer(call -> {
            RowMapper<Object> mapper = call.getArgument(0);
            JdbcClient.MappedQuerySpec<Object> result = mock();
            when(result.optional()).thenAnswer(ignored -> Optional.of(mapper.mapRow(row, 0)));
            return result;
        });
    }
}
