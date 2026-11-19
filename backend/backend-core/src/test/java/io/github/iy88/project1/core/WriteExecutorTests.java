package io.github.iy88.project1.core;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.SimpleTransactionStatus;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.startsWith;
import static org.mockito.Mockito.RETURNS_SELF;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

class WriteExecutorTests {
    private static final String OPERATION = "trade.update";
    private static final String KEY = "request-1";
    private static final String REQUEST = "change";
    private static final LockPlan EMPTY = new LockPlan(Map.of(), Set.of());

    private final PlatformTransactionManager transactions = mock(PlatformTransactionManager.class);
    private final JdbcClient jdbc = mock(JdbcClient.class);
    private final ObjectProvider<EventIntent.Writer> eventWriter = new ObjectProvider<>() {};
    private final JsonMapper json = JsonMapper.builder().build();
    private final JsonNode input = json.createObjectNode().put("value", REQUEST);
    private final ExecutionContext context = new ExecutionContext(UUID.randomUUID(),
            ExecutionContext.ActorKind.SYSTEM, "test-worker", null, null, null, "test");
    private final ResourceRef resource = new ResourceRef("trade", 1);
    private final WriteExecutor.UseCase<String, Boolean> useCase = mock();
    private final WriteExecutor executor = new WriteExecutor(transactions, jdbc, json,
            new WriteSettings(1, 5, 1, 10, 32, 600), eventWriter);

    @BeforeEach
    void configureTransactionsAndInput() {
        when(transactions.getTransaction(any())).thenAnswer(invocation -> new SimpleTransactionStatus());
        when(useCase.digestInput(REQUEST)).thenReturn(input);
    }

    @ParameterizedTest
    @ValueSource(strings = {"40001", "40P01"})
    void retriesSerializationFailuresAndDeadlocksThenReturnsTheSuccessfulWrite(String sqlState) {
        successfulWrite();
        when(useCase.prepare(context, REQUEST))
                .thenThrow(new IllegalStateException(new SQLException("retryable", sqlState)))
                .thenReturn(EMPTY);

        var result = executor.run(context, OPERATION, KEY, REQUEST, useCase);

        assertThat(result.status()).isEqualTo(200);
        assertThat(result.data().path("value").asString()).isEqualTo("updated");
        verify(useCase, times(2)).prepare(context, REQUEST);
        verify(useCase).write(any(WriteTransaction.class), eq(REQUEST),
                eq(true), eq(EMPTY));
        verify(transactions).rollback(any());
        verify(transactions, times(2)).commit(any());
    }

    @Test
    void rollsBackIfTheWriteLosesItsLockPlanAndRetriesWithTheAdditionalResource() {
        successfulWrite();
        var additional = new LockPlan(Map.of(), Set.of(new LockPlan.Key(LockPlan.Domain.TRADE, List.of(3L))));
        when(useCase.prepare(context, REQUEST)).thenReturn(EMPTY);
        when(useCase.qualify(context, REQUEST, EMPTY)).thenThrow(new LockPlan.Changed(additional));
        when(useCase.qualify(context, REQUEST, additional)).thenReturn(true);
        when(useCase.write(any(), eq(REQUEST), eq(true),
                eq(additional))).thenAnswer(ignored -> new WriteResult.Response<>(200, Map.of(), resource));

        assertThat(executor.run(context, OPERATION, KEY, REQUEST, useCase).status()).isEqualTo(200);

        verify(useCase, times(2)).prepare(context, REQUEST);
        verify(useCase).qualify(context, REQUEST, additional);
        verify(transactions).rollback(any());
    }

    @Test
    void stopsWhenTheRetryBudgetIsExhausted() {
        when(useCase.prepare(context, REQUEST))
                .thenThrow(new IllegalStateException(new SQLException("deadlock", "40P01")));

        assertThatThrownBy(() -> executor.run(context, OPERATION, KEY, REQUEST, useCase))
                .isInstanceOfSatisfying(BusinessError.class, error -> {
                    assertThat(error.code()).isEqualTo("TRANSACTION_RETRY_EXHAUSTED");
                    assertThat(error.status()).isEqualTo(503);
                    assertThat(error.operationId()).isNotNull();
                });
        verify(useCase, times(2)).prepare(context, REQUEST);
        verify(transactions, times(2)).rollback(any());
        verifyNoInteractions(jdbc);
    }

    @Test
    void propagatesAnUnrelatedDatabaseErrorWithoutRetrying() {
        var failure = new IllegalStateException(new SQLException("unique violation", "23505"));
        when(useCase.prepare(context, REQUEST)).thenThrow(failure);

        assertThatThrownBy(() -> executor.run(context, OPERATION, KEY, REQUEST, useCase)).isSameAs(failure);
        verify(useCase).prepare(context, REQUEST);
        verify(transactions).rollback(any());
        verifyNoInteractions(jdbc);
    }

    @Test
    void rejectsMalformedIdempotencyKeyBeforeOpeningATransaction() {
        assertThatThrownBy(() -> executor.run(context, OPERATION, "with spaces", REQUEST, useCase))
                .isInstanceOfSatisfying(BusinessError.class, error -> assertThat(error.code()).isEqualTo("INPUT_INVALID"));
        verifyNoInteractions(transactions, jdbc);
    }

    @Test
    void rechecksAccessOnReplayAndDoesNotRepeatTheWrite() throws Exception {
        UUID previousId = existingOperation(input);

        var result = executor.run(context, OPERATION, KEY, REQUEST, useCase);

        assertThat(result.operationId()).isEqualTo(previousId);
        assertThat(result.status()).isEqualTo(201);
        assertThat(result.replayed()).isTrue();
        assertThat(result.data().path("value").asString()).isEqualTo("saved");
        verify(useCase).requireReplayAccess(context, true, resource);
        verify(useCase, never()).write(any(), any(), any(), any());
        verify(jdbc, never()).sql(startsWith("UPDATE operation_record"));
    }

    @Test
    void rejectsReplayWhenAccessHasBeenRevoked() throws Exception {
        UUID previousId = existingOperation(input);
        doThrow(new BusinessError("RESOURCE_NOT_VISIBLE", 404, "not visible"))
                .when(useCase).requireReplayAccess(context, true, resource);

        assertThatThrownBy(() -> executor.run(context, OPERATION, KEY, REQUEST, useCase))
                .isInstanceOfSatisfying(BusinessError.class, error -> {
                    assertThat(error.code()).isEqualTo("RESOURCE_NOT_VISIBLE");
                    assertThat(error.operationId()).isEqualTo(previousId);
                });
        verify(useCase, never()).write(any(), any(), any(), any());
        verify(transactions).rollback(any());
    }

    @Test
    void rejectsReusingTheSameKeyWithChangedInput() throws Exception {
        UUID previousId = existingOperation(json.createObjectNode().put("value", "different"));

        assertThatThrownBy(() -> executor.run(context, OPERATION, KEY, REQUEST, useCase))
                .isInstanceOfSatisfying(BusinessError.class, error -> {
                    assertThat(error.code()).isEqualTo("IDEMPOTENCY_PAYLOAD_CONFLICT");
                    assertThat(error.operationId()).isEqualTo(previousId);
                });
        verify(useCase, never()).requireReplayAccess(any(), any(), any());
        verify(useCase, never()).write(any(), any(), any(), any());
    }

    private void successfulWrite() {
        var statement = allowWrite();
        when(statement.update()).thenReturn(1);
        when(useCase.write(any(), eq(REQUEST), eq(true),
                eq(EMPTY)))
                .thenAnswer(ignored -> new WriteResult.Response<>(200, Map.of("value", "updated"), resource));
    }

    private JdbcClient.StatementSpec allowWrite() {
        var statement = mock(JdbcClient.StatementSpec.class, RETURNS_SELF);
        JdbcClient.MappedQuerySpec<String> lockTimeout = mock();
        when(statement.query(String.class)).thenReturn(lockTimeout);
        when(lockTimeout.single()).thenReturn("1s");
        when(jdbc.sql(anyString())).thenReturn(statement);
        when(useCase.prepare(context, REQUEST)).thenReturn(EMPTY);
        when(useCase.qualify(context, REQUEST, EMPTY)).thenReturn(true);
        return statement;
    }

    private UUID existingOperation(JsonNode recordedInput) throws SQLException {
        var statement = allowWrite();
        UUID previousId = UUID.randomUUID();
        var row = mock(ResultSet.class);
        when(row.getObject("operation_id", UUID.class)).thenReturn(previousId);
        when(row.getString("digest_version")).thenReturn(WriteRecords.DIGEST_VERSION);
        when(row.getBytes("request_digest")).thenReturn(WriteExecutor.digest(recordedInput));
        when(row.getInt("response_status")).thenReturn(201);
        when(row.getString("response_data")).thenReturn("{\"value\":\"saved\"}");
        when(row.getString("resource_type")).thenReturn(resource.type());
        when(row.getLong("resource_id")).thenReturn(resource.id());
        when(statement.query(org.mockito.ArgumentMatchers.<RowMapper<WriteRecords.Decision>>any()))
                .thenAnswer(invocation -> {
                    RowMapper<WriteRecords.Decision> mapper = invocation.getArgument(0);
                    JdbcClient.MappedQuerySpec<WriteRecords.Decision> query = mock();
                    when(query.single()).thenAnswer(ignored -> mapper.mapRow(row, 0));
                    return query;
                });
        return previousId;
    }
}
