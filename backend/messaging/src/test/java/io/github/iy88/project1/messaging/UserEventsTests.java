package io.github.iy88.project1.messaging;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ResourceRef;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.core.simple.JdbcClient;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.startsWith;
import static org.mockito.Mockito.RETURNS_SELF;
import static org.mockito.Mockito.doReturn;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.spy;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

class UserEventsTests {
    private static final long ACCOUNT = 14L;
    private final UUID epoch = UUID.randomUUID();
    private final UserEvents.Head head = new UserEvents.Head(epoch, 5L, 2L);
    private final JdbcClient jdbc = mock(JdbcClient.class);
    private final UserEvents events = spy(new UserEvents(jdbc,
            new DeliverySettings(3600, 10, 30, 5, 3, 1, 3, 100)));

    @BeforeEach
    void configureHead() {
        doReturn(head).when(events).head(ACCOUNT);
    }

    @Test
    void rejectsWrongEpochAndCursorsOutsideTheRetainedSequenceRange() {
        requiresResync(UUID.randomUUID(), 2);
        requiresResync(epoch, 1);
        requiresResync(epoch, 6);
        verifyNoInteractions(jdbc);
    }

    @Test
    void startsAtTheReplayFloorAndUsesTheLastReturnedSequenceAsTheNextCursor() {
        var event = new UserEvents.Event(UUID.randomUUID(), 3, "trade_changed", 1,
                new ResourceRef("trade", 8), null, null, null, Instant.EPOCH);
        var statement = mock(JdbcClient.StatementSpec.class, RETURNS_SELF);
        JdbcClient.MappedQuerySpec<UserEvents.Event> rows = mock();
        when(statement.query(org.mockito.ArgumentMatchers.<RowMapper<UserEvents.Event>>any())).thenReturn(rows);
        when(rows.list()).thenReturn(List.of(event)).thenReturn(List.of());
        when(jdbc.sql(startsWith("SELECT event_id, account_seq"))).thenReturn(statement);

        assertThat(events.scan(ACCOUNT, epoch, 2, 1)).isEqualTo(new UserEvents.Page(head, List.of(event), 3, true));
        assertThat(events.scan(ACCOUNT, epoch, 5, 1)).isEqualTo(new UserEvents.Page(head, List.of(), 5, false));

        verify(statement).param("after", 2L);
        verify(statement).param("after", 5L);
    }

    @Test
    void advancesTheReplayFloorOnlyToTheLastDeletedSequenceAndHonorsTheBatchSize() {
        var accounts = mock(JdbcClient.StatementSpec.class, RETURNS_SELF);
        var remove = mock(JdbcClient.StatementSpec.class, RETURNS_SELF);
        var update = mock(JdbcClient.StatementSpec.class, RETURNS_SELF);
        JdbcClient.MappedQuerySpec<Long> accountRows = mock();
        JdbcClient.MappedQuerySpec<Long> removedRows = mock();
        when(jdbc.sql(startsWith("SELECT h.account_id"))).thenReturn(accounts);
        when(jdbc.sql(startsWith("WITH prefix AS"))).thenReturn(remove);
        when(jdbc.sql(startsWith("UPDATE account_event_head SET replay_floor"))).thenReturn(update);
        when(accounts.query(Long.class)).thenReturn(accountRows);
        when(remove.query(Long.class)).thenReturn(removedRows);
        when(accountRows.list()).thenReturn(List.of(ACCOUNT, 15L, 16L));
        when(removedRows.list()).thenReturn(List.of(4L, 3L)).thenReturn(List.of(7L));

        assertThat(events.pruneExpired()).isEqualTo(3);

        var order = inOrder(remove, update);
        order.verify(remove).param("account", ACCOUNT);
        order.verify(remove).param("limit", 3);
        order.verify(update).param(4L);
        order.verify(update).param(ACCOUNT);
        order.verify(update).update();
        order.verify(remove).param("account", 15L);
        order.verify(remove).param("limit", 1);
        order.verify(update).param(7L);
        order.verify(update).param(15L);
        order.verify(update).update();
        order.verifyNoMoreInteractions();
    }

    private void requiresResync(UUID requestedEpoch, long requestedSequence) {
        assertThatThrownBy(() -> events.scan(ACCOUNT, requestedEpoch, requestedSequence, 1))
                .isInstanceOfSatisfying(BusinessError.class, error -> {
                    assertThat(error.code()).isEqualTo("EVENT_RESYNC_REQUIRED");
                    assertThat(error.details()).isEqualTo(Map.of("epoch", epoch, "head_seq", 5L, "replay_floor", 2L));
                });
    }
}
