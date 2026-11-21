package io.github.iy88.project1.casemanagement.application;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteTransaction;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;

class SubjectPlanTests {
    private static final LockPlan.Key PRODUCT = new LockPlan.Key(LockPlan.Domain.PRODUCT, List.of(5L));
    private static final LockPlan.Key TRADE = new LockPlan.Key(LockPlan.Domain.TRADE, List.of(7L));

    @Test
    void mergesAccountsWithTheStrongestModeAndDeduplicatesResourceKeys() {
        var plan = SubjectPlan.account(2, LockPlan.AccountMode.SHARED)
                .merge(SubjectPlan.account(2, LockPlan.AccountMode.EXCLUSIVE))
                .merge(SubjectPlan.account(3, LockPlan.AccountMode.SHARED))
                .merge(SubjectPlan.resource(PRODUCT, transaction -> {}))
                .merge(SubjectPlan.resource(PRODUCT, transaction -> {}));

        assertThat(plan.lockPlan().accounts())
                .containsEntry(2L, LockPlan.AccountMode.EXCLUSIVE)
                .containsEntry(3L, LockPlan.AccountMode.SHARED);
        assertThat(plan.lockPlan().resources()).containsExactly(PRODUCT);
    }


    @Test
    void acquiresResourceLocksInGlobalOrderAndOncePerKey() {
        var transaction = mock(WriteTransaction.class);
        var plan = SubjectPlan.resource(TRADE, ignored -> {})
                .merge(SubjectPlan.resource(PRODUCT, ignored -> {}))
                .merge(SubjectPlan.resource(TRADE, ignored -> {}));

        plan.acquire(transaction);

        var calls = inOrder(transaction);
        calls.verify(transaction).lock(eq(PRODUCT), any());
        calls.verify(transaction).lock(eq(TRADE), any());
        verify(transaction, times(2)).lock(any(), any());
    }

    @Test
    void reportsOnlyNewOrStrongerLocksAgainstThePreparedPlan() {
        var plan = SubjectPlan.account(2, LockPlan.AccountMode.EXCLUSIVE)
                .merge(SubjectPlan.resource(PRODUCT, transaction -> {}))
                .merge(SubjectPlan.resource(TRADE, transaction -> {}));
        var prepared = new LockPlan(Map.of(2L, LockPlan.AccountMode.SHARED), Set.of(PRODUCT));

        var missing = plan.missingFrom(prepared);

        assertThat(missing.accounts()).containsEntry(2L, LockPlan.AccountMode.EXCLUSIVE);
        assertThat(missing.resources()).containsExactly(TRADE);
    }

    @Test
    void reportsNoMissingLocksWhenThePreparedPlanCoversEverything() {
        var plan = SubjectPlan.account(2, LockPlan.AccountMode.SHARED)
                .merge(SubjectPlan.resource(PRODUCT, transaction -> {}));
        var prepared = new LockPlan(Map.of(2L, LockPlan.AccountMode.EXCLUSIVE), Set.of(PRODUCT));

        var missing = plan.missingFrom(prepared);

        assertThat(missing.accounts()).isEmpty();
        assertThat(missing.resources()).isEmpty();
    }

    @Test
    void combinesScopeAndRetainsThePrimaryNotificationRecipients() {
        var first = new SubjectResult(new ResourceRef("product", 5), "PUBLIC", "WITHDRAWN",
                List.of(new ResourceRef("trade_request", 9)), Set.of(10L), false);
        var second = new SubjectResult(new ResourceRef("trade", 7), "ACTIVE", "FROZEN",
                List.of(new ResourceRef("trade", 7)), Set.of(11L), true);

        var combined = SubjectResult.combine(first, second);

        assertThat(combined.affectedScope()).containsExactly(new ResourceRef("trade_request", 9),
                new ResourceRef("trade", 7));
        assertThat(combined.recipientAccountIds()).containsExactly(10L);
        assertThat(combined.alreadyEffective()).isFalse();
    }

    @Test
    void rejectsDuplicateEnforcementIdsBeforeOpeningATransaction() {
        assertThatThrownBy(() -> new EnforcementCommand(3, List.of(
                EnforcementInstruction.of("e1", EnforcementAction.FREEZE_TRADE, new ResourceRef("trade", 7)),
                EnforcementInstruction.of("e1", EnforcementAction.WITHDRAW_PUBLIC_ACCESS,
                        new ResourceRef("product", 5))), List.of(1L), List.of(), "reason", Instant.parse("2026-01-01T00:00:00Z")))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("INPUT_INVALID"));
    }

    @Test
    void rejectsAnActionWhoseTargetTypeDoesNotMatch() {
        assertThatThrownBy(() -> EnforcementInstruction.of("e1", EnforcementAction.FREEZE_TRADE,
                new ResourceRef("product", 5)))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("TARGET_INVALID"));
    }
}
