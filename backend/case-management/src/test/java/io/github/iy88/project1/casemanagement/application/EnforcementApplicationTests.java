package io.github.iy88.project1.casemanagement.application;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteExecutor;
import io.github.iy88.project1.core.WriteTransaction;
import io.github.iy88.project1.storage.persistence.FileReferences;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class EnforcementApplicationTests {
    private static final ExecutionContext CONTEXT = new ExecutionContext(UUID.randomUUID(),
            ExecutionContext.ActorKind.ACCOUNT, "7", UUID.randomUUID(), null, 1L, "test");
    private static final EnforcementCommand COMMAND = new EnforcementCommand(3, List.of(
            EnforcementInstruction.of("e1", EnforcementAction.WITHDRAW_PUBLIC_ACCESS,
                    new ResourceRef("product", 5))), List.of(1L), List.of(), "reason", Instant.parse("2026-01-01T00:00:00Z"));
    private static final CaseAccess ACCESS = new CaseAccess(3, 7, 8, new ResourceRef("product", 5),
            List.of(new ResourceRef("evidence", 1)), List.of(), Map.of(), Set.of());
    private static final LockPlan.Key PRODUCT_KEY = new LockPlan.Key(LockPlan.Domain.PRODUCT, List.of(5L));
    private static final LockPlan.Key CASE_KEY = new LockPlan.Key(LockPlan.Domain.CASE, List.of(3L));

    private final CaseEnforcementPort cases = mock(CaseEnforcementPort.class);
    private final AccountEnforcementPort accounts = mock(AccountEnforcementPort.class);
    private final ProductEnforcementPort products = mock(ProductEnforcementPort.class);
    private final TradeEnforcementPort trades = mock(TradeEnforcementPort.class);
    private final ConversationEnforcementPort conversations = mock(ConversationEnforcementPort.class);
    private final EnforcementNotifications notifications = mock(EnforcementNotifications.class);
    private final FileReferences files = mock(FileReferences.class);
    private final EnforcementApplication application = new EnforcementApplication(
            mock(WriteExecutor.class), cases, accounts, products, trades, conversations, notifications,
            files, JsonMapper.builder().build());

    @Test
    void recordsOnlyGenuineFailedBusinessExecutionInTheCaseFailureTrail() {
        application.recordFailure(CONTEXT, COMMAND, new BusinessError("TARGET_STATE_CONFLICT", 409, "conflict"));

        verify(cases).recordFailure(CONTEXT, COMMAND, "TARGET_STATE_CONFLICT", "conflict");
    }

    @Test
    void neverRecordsReplayAuthorizationOrConflictFailuresAsExecutionFailures() {
        application.recordFailure(CONTEXT, COMMAND,
                new BusinessError("IDEMPOTENCY_PAYLOAD_CONFLICT", 409, "payload"));
        application.recordFailure(CONTEXT, COMMAND, new BusinessError("NOT_CASE_MANAGER", 404, "auth"));
        application.recordFailure(CONTEXT, COMMAND, new BusinessError("STATE_CONFLICT", 409, "state"));

        verify(cases, never()).recordFailure(any(), any(), anyString(), anyString());
    }

    @Test
    void ambientBatchLocksBeforeCallerStepAndReReadsTheCaseBeforeTheDecidedCheck() {
        var events = new ArrayList<String>();
        var transaction = transaction(events);
        var prepared = preparePlan();
        when(cases.requireManager(CONTEXT, COMMAND)).thenReturn(ACCESS);
        when(cases.revalidate(transaction, CONTEXT, COMMAND, ACCESS)).thenAnswer(ignored -> {
            events.add("revalidate");
            return ACCESS;
        });
        doAnswer(ignored -> {
            events.add("require-executable");
            return null;
        }).when(cases).requireExecutable(transaction, CONTEXT, COMMAND, ACCESS);
        when(products.withdraw(transaction, command("e1"))).thenReturn(withdrawal());
        when(trades.closeRequests(eq(transaction), any(), any()))
                .thenReturn(SubjectResult.of(new ResourceRef("trade_request", 9), "PENDING", "CLOSED"));
        when(conversations.archiveRequestBranches(eq(transaction), any(), any()))
                .thenReturn(SubjectResult.of(new ResourceRef("trade_conversation", 9), "ACTIVE", "ARCHIVED"));
        when(transaction.audit(any(), any(), any(), any())).thenReturn(1L);

        var batch = application.executeInTransaction(transaction, COMMAND, prepared, SubjectPlan.empty(),
                (locked, access) -> {
                    assertThat(access).isEqualTo(ACCESS);
                    events.add("caller");
                });

        assertThat(events).containsExactly("lock:PRODUCT", "lock:CASE", "revalidate", "caller",
                "revalidate", "require-executable");
        assertThat(batch.caseRef()).isEqualTo(new ResourceRef("case", 3));
        assertThat(batch.enforcements()).singleElement()
                .satisfies(outcome -> assertThat(outcome.status()).isEqualTo(EnforcementOutcome.Status.APPLIED));
        assertThat(batch.notifiedAccountIds()).containsExactly(11L);
        verify(cases).recordExecution(eq(transaction), eq(CONTEXT), eq(COMMAND), any(), any());
        verify(notifications).create(transaction, "case.display_withdrawn", "case:3:e1:withdrawn",
                new ResourceRef("case", 3), Set.of(11L), "reason", COMMAND.occurredAt());
    }

    @Test
    void preparePlanDeduplicatesCallerCallbacksBehindTheEnforcementCallbacks() {
        when(cases.prepare(CONTEXT, COMMAND)).thenReturn(ACCESS);
        configureSubjectPlans();
        var callerProductCalls = new AtomicInteger();
        var callerCaseCalls = new AtomicInteger();
        var additional = SubjectPlan.account(12, LockPlan.AccountMode.SHARED)
                .merge(SubjectPlan.resource(PRODUCT_KEY, ignored -> callerProductCalls.incrementAndGet()))
                .merge(SubjectPlan.resource(CASE_KEY, ignored -> callerCaseCalls.incrementAndGet()));

        var plan = application.preparePlan(CONTEXT, COMMAND).merge(additional);
        assertThat(plan.lockPlan().accounts()).containsEntry(12L, LockPlan.AccountMode.SHARED);
        assertThat(plan.lockPlan().resources()).containsExactlyInAnyOrder(PRODUCT_KEY, CASE_KEY);

        var transaction = transaction(new ArrayList<>());
        plan.acquire(transaction);

        assertThat(callerProductCalls).hasValue(0);
        assertThat(callerCaseCalls).hasValue(0);
        verify(cases).lockCase(transaction, 3L);
    }

    @Test
    void ambientBatchPropagatesPlanDriftFromThePostLockCaseRead() {
        var events = new ArrayList<String>();
        var transaction = transaction(events);
        var prepared = preparePlan();
        when(cases.requireManager(CONTEXT, COMMAND)).thenReturn(ACCESS);
        var expanded = new CaseAccess(3, 7, 8, new ResourceRef("product", 5),
                List.of(new ResourceRef("evidence", 1)), List.of(), Map.of(), Set.of(12L, 13L));
        when(cases.revalidate(transaction, CONTEXT, COMMAND, ACCESS)).thenReturn(expanded);

        assertThatThrownBy(() -> application.executeInTransaction(transaction, COMMAND, prepared,
                SubjectPlan.empty(), null))
                .isInstanceOfSatisfying(LockPlan.Changed.class,
                        changed -> assertThat(changed.additional().accounts()).containsKeys(12L, 13L));
        verify(cases, never()).requireExecutable(any(), any(), any(), any());
    }

    private WriteTransaction transaction(List<String> events) {
        var transaction = mock(WriteTransaction.class);
        when(transaction.context()).thenReturn(CONTEXT);
        doAnswer(invocation -> {
            var key = (LockPlan.Key) invocation.getArgument(0);
            events.add("lock:" + key.domain().name());
            ((Runnable) invocation.getArgument(1)).run();
            return null;
        }).when(transaction).lock(any(), any());
        return transaction;
    }

    private LockPlan preparePlan() {
        when(cases.prepare(CONTEXT, COMMAND)).thenReturn(ACCESS);
        configureSubjectPlans();
        var prepared = application.preparePlan(CONTEXT, COMMAND).lockPlan();
        assertThat(prepared.resources()).containsExactlyInAnyOrder(PRODUCT_KEY, CASE_KEY);
        return prepared;
    }

    private void configureSubjectPlans() {
        when(accounts.prepare(any())).thenReturn(SubjectPlan.empty());
        when(products.prepare(any())).thenReturn(SubjectPlan.resource(PRODUCT_KEY, ignored -> {}));
        when(trades.prepare(any())).thenReturn(SubjectPlan.empty());
        when(conversations.prepare(any())).thenReturn(SubjectPlan.empty());
    }

    private static SubjectCommand command(String enforcementId) {
        var instruction = COMMAND.enforcements().stream()
                .filter(item -> item.enforcementId().equals(enforcementId)).findFirst().orElseThrow();
        return SubjectCommand.of(COMMAND, instruction, ACCESS);
    }

    private static ProductEnforcementPort.Withdrawal withdrawal() {
        return new ProductEnforcementPort.Withdrawal(new SubjectResult(
                new ResourceRef("product_display_restriction", 6), "PUBLIC", "DISPLAY_WITHDRAWN",
                List.of(new ResourceRef("trade_request", 9)), Set.of(11L), false),
                List.of(new ResourceRef("trade_request", 9)));
    }
}
