package io.github.iy88.project1.messaging;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteExecutor;
import io.github.iy88.project1.core.WriteTransaction;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import tools.jackson.databind.json.JsonMapper;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

class TaskWorkerTests {
    private static final String KIND = "expire-trade";
    private static final LockPlan EMPTY = new LockPlan(Map.of(), Set.of());
    private final TaskSchedules schedules = mock(TaskSchedules.class);
    private final WriteExecutor writes = mock(WriteExecutor.class);
    private final TaskHandler handler = mock(TaskHandler.class);
    private final WriteTransaction transaction = mock(WriteTransaction.class);
    private final Instant due = Instant.parse("2026-11-19T00:00:00Z");
    private final TaskSchedules.Task task = new TaskSchedules.Task(UUID.randomUUID(),
            new TaskSchedules.Spec(KIND, new ResourceRef("trade", 8), "trigger", "v1", due, "rule-v1"));
    private final TaskSchedules.Lease lease = new TaskSchedules.Lease(task, UUID.randomUUID(), due.plusSeconds(30), 1);
    private final TaskSchedules.Ready ready = new TaskSchedules.Ready(task.id(), KIND);
    private TaskWorker worker;

    @BeforeEach
    void prepareWorker() {
        when(handler.kind()).thenReturn(KIND);
        worker = new TaskWorker(schedules, writes, JsonMapper.builder().build(),
                new DeliverySettings(3600, 10, 30, 5, 3, 1, 10, 100), "test", List.of(handler));
    }

    @ParameterizedTest
    @ValueSource(booleans = {true, false})
    void validatesLeaseBeforeActingAndCompletesOrCancelsTheTask(boolean applicable) {
        when(schedules.claim(ready)).thenReturn(Optional.of(lease));
        when(handler.prepare(any(ExecutionContext.class), eq(task))).thenReturn(EMPTY);
        when(handler.isApplicable(task)).thenReturn(applicable);
        when(writes.run(any(ExecutionContext.class), eq("task." + KIND), eq(task.id().toString()),
                eq(task), any())).thenAnswer(call -> {
                    ExecutionContext context = call.getArgument(0);
                    WriteExecutor.UseCase<TaskSchedules.Task, Boolean> useCase = call.getArgument(4);
                    assertThat(context.actorKind()).isEqualTo(ExecutionContext.ActorKind.SYSTEM);
                    assertThat(context.actorId()).isEqualTo(KIND);
                    assertThat(useCase.digestInput(task).path("task_id").asString()).isEqualTo(task.id().toString());
                    var plan = useCase.prepare(context, task);
                    assertThat(plan.resources()).containsExactly(TaskSchedules.key(task.id()));
                    var response = useCase.write(transaction, task, useCase.qualify(context, task, plan), plan);
                    assertThat(response.status()).isEqualTo(204);
                    assertThat(response.resource()).isEqualTo(task.spec().source());
                    return null;
                });

        assertThat(worker.run(ready)).isTrue();

        var order = inOrder(handler, schedules);
        order.verify(handler).lockAndQualify(transaction, task);
        order.verify(schedules).requireLease(transaction, lease);
        order.verify(handler).isApplicable(task);
        if (applicable) {
            order.verify(handler).execute(transaction, task);
        } else {
            verify(handler, never()).execute(transaction, task);
        }
        order.verify(schedules).finish(transaction, lease, !applicable);
    }

    @Test
    void acknowledgesWhenRetryIsPersisted() {
        when(schedules.claim(ready)).thenReturn(Optional.of(lease));
        when(writes.run(any(ExecutionContext.class), eq("task." + KIND), eq(task.id().toString()), eq(task), any()))
                .thenThrow(new IllegalStateException("worker failure"));
        when(schedules.retry(lease, "TASK_EXECUTION_FAILED")).thenReturn(true);

        assertThat(worker.run(ready)).isTrue();

        verify(schedules).retry(lease, "TASK_EXECUTION_FAILED");
        verify(schedules, never()).canAcknowledge(ready);
    }

    @Test
    void leavesEntryPendingWhenRetryLosesTheLeaseAndTaskRemainsEligible() {
        when(schedules.claim(ready)).thenReturn(Optional.of(lease));
        when(writes.run(any(ExecutionContext.class), eq("task." + KIND), eq(task.id().toString()), eq(task), any()))
                .thenThrow(new BusinessError("TASK_LEASE_LOST", 409, "lease lost"));

        assertThat(worker.run(ready)).isFalse();

        verify(schedules).retry(lease, "TASK_LEASE_LOST");
        verify(schedules).canAcknowledge(ready);
    }

    @Test
    void asksTheSchedulerWhetherAnUnclaimedEntryCanBeAcknowledged() {
        when(schedules.claim(ready)).thenReturn(Optional.empty());
        when(schedules.canAcknowledge(ready)).thenReturn(false, true);

        assertThat(worker.run(ready)).isFalse();
        assertThat(worker.run(ready)).isTrue();
        verifyNoInteractions(writes);
    }

    @Test
    void leavesUnknownTaskKindsForOtherWorkers() {
        assertThat(worker.run(new TaskSchedules.Ready(task.id(), "other"))).isFalse();
        verifyNoInteractions(schedules, writes);
    }
}
