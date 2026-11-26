package io.github.iy88.project1.messaging;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.mockito.ArgumentCaptor;
import org.springframework.data.redis.connection.RedisStreamCommands.XAddOptions;
import org.springframework.data.redis.connection.stream.RecordId;
import org.springframework.data.redis.core.StreamOperations;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.SimpleTransactionStatus;
import org.springframework.transaction.support.TransactionTemplate;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.startsWith;
import static org.mockito.Mockito.RETURNS_SELF;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

class EventDispatchTests {
    private static final String STREAM = "test:events";
    private final UUID eventId = UUID.randomUUID();
    private final Map<String, String> hint = Map.of("event_id", eventId.toString(),
            "recipient_account_id", "14", "account_seq", "3");
    private final JdbcClient jdbc = mock(JdbcClient.class);
    private final JdbcClient.StatementSpec claim = mock(JdbcClient.StatementSpec.class, RETURNS_SELF);
    private final JdbcClient.StatementSpec markPublished = mock(JdbcClient.StatementSpec.class, RETURNS_SELF);
    private final JdbcClient.StatementSpec retry = mock(JdbcClient.StatementSpec.class, RETURNS_SELF);
    private final StringRedisTemplate redis = mock(StringRedisTemplate.class);
    private final StreamOperations<String, Object, Object> stream = mock();
    private final PlatformTransactionManager manager = mock(PlatformTransactionManager.class);
    private final DeliverySettings settings = new DeliverySettings(3600, 10, 30, 5, 3, 2, 1, 100);
    private final EventDispatch events = new EventDispatch(jdbc, new TransactionTemplate(manager), settings, redis, "test");

    @BeforeEach
    void configureDependencies() {
        when(manager.getTransaction(any())).thenAnswer(invocation -> new SimpleTransactionStatus());
        when(redis.opsForStream()).thenReturn(stream);
        when(jdbc.sql(startsWith("WITH candidate AS"))).thenReturn(claim);
        when(jdbc.sql(startsWith("UPDATE user_event SET published_at"))).thenReturn(markPublished);
        when(jdbc.sql(startsWith("UPDATE user_event SET lease_token = NULL"))).thenReturn(retry);
    }

    @ParameterizedTest
    @ValueSource(ints = {0, 1})
    void requestsRedisConfirmationBeforeMarkingTheClaimPublished(int updatedRows) throws SQLException {
        claimEvent(1);
        when(stream.add(eq(STREAM), eq(hint), any(XAddOptions.class))).thenReturn(RecordId.of("1-0"));
        when(markPublished.update()).thenReturn(updatedRows);

        assertThat(events.publishDue()).isEqualTo(updatedRows);

        var calls = inOrder(manager, stream, markPublished, redis);
        calls.verify(manager).commit(any());
        calls.verify(stream).add(eq(STREAM), eq(hint), any(XAddOptions.class));
        calls.verify(markPublished).update();
        if (updatedRows == 1) calls.verify(redis).convertAndSend("test:events:wake", "14");
        else verify(redis, never()).convertAndSend(any(), any());
        verify(markPublished).param("id", eventId);
        UUID token = leaseToken();
        verify(markPublished).param("token", token);
        verifyNoInteractions(retry);
    }

    @ParameterizedTest
    @ValueSource(booleans = {true, false})
    void reschedulesTheClaimWhenRedisFailsOrReturnsNoConfirmation(boolean redisThrows) throws SQLException {
        int attempts = redisThrows ? 1 : settings.retryLimit();
        claimEvent(attempts);
        if (redisThrows) {
            when(stream.add(eq(STREAM), eq(hint), any(XAddOptions.class)))
                    .thenThrow(new IllegalStateException("Redis unavailable"));
        }

        assertThat(events.publishDue()).isZero();

        verify(retry).param("delay", redisThrows ? 2 : 300);
        verify(retry).param("id", eventId);
        UUID token = leaseToken();
        verify(retry).param("token", token);
        verify(retry).update();
        verifyNoInteractions(markPublished);
    }

    private void claimEvent(int attempts) throws SQLException {
        var row = mock(ResultSet.class);
        when(row.getObject(1, UUID.class)).thenReturn(eventId);
        when(row.getLong(2)).thenReturn(14L);
        when(row.getLong(3)).thenReturn(3L);
        when(row.getInt(4)).thenReturn(attempts);
        when(claim.query(org.mockito.ArgumentMatchers.<RowMapper<Object>>any())).thenAnswer(invocation -> {
            RowMapper<Object> mapper = invocation.getArgument(0);
            JdbcClient.MappedQuerySpec<Object> query = mock();
            when(query.optional()).thenAnswer(ignored -> Optional.of(mapper.mapRow(row, 0)));
            return query;
        });
    }

    private UUID leaseToken() {
        var token = ArgumentCaptor.forClass(UUID.class);
        verify(claim).param(eq("token"), token.capture());
        return token.getValue();
    }
}
