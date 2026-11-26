package io.github.iy88.project1.api.cases;

import io.github.iy88.project1.account.application.AccountRestrictions;
import io.github.iy88.project1.casemanagement.application.CasePorts;
import io.github.iy88.project1.casemanagement.application.CaseRecords;
import io.github.iy88.project1.casemanagement.application.SubjectPlan;
import io.github.iy88.project1.casemanagement.persistence.CaseLifecycleStore;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.WriteTransaction;
import io.github.iy88.project1.product.application.ProductDisplayRestrictions;
import io.github.iy88.project1.product.application.ProductInteractions;
import io.github.iy88.project1.product.persistence.ProductRepository;
import io.github.iy88.project1.trade.application.TradePorts;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/** Lock-plan and reversal-contract rules of the production account/product subject handler. */
class SubjectCaseEnforcementTests {
    private static final long CASE = 3L;
    private static final long ACCOUNT = 7L;
    private static final long PRODUCT_A = 10L;
    private static final long PRODUCT_B = 11L;
    private static final long TRADE = 20L;
    private static final long CONVERSATION = 21L;

    private final CaseLifecycleStore cases = mock(CaseLifecycleStore.class);
    private final CasePorts.Targets targets = mock(CasePorts.Targets.class);
    private final AccountRestrictions accounts = mock(AccountRestrictions.class);
    private final ProductDisplayRestrictions displays = mock(ProductDisplayRestrictions.class);
    private final ProductRepository products = mock(ProductRepository.class);
    private final ProductInteractions interactions = mock(ProductInteractions.class);
    private final TradePorts.Closure closures = mock(TradePorts.Closure.class);
    private final TradePorts.CaseEnforcement trades = mock(TradePorts.CaseEnforcement.class);
    private final TradePorts.Participation participation = mock(TradePorts.Participation.class);
    private final SubjectCaseEnforcement handler = new SubjectCaseEnforcement(cases, targets, accounts, displays,
            products, interactions, closures, trades, participation,
            Clock.fixed(Instant.parse("2026-01-01T00:00:00Z"), ZoneOffset.UTC));

    @Test
    void accountBanLocksTheExclusiveAccountEveryProductAndClosureRows() {
        when(displays.sellerProductIds(ACCOUNT)).thenReturn(List.of(PRODUCT_A, PRODUCT_B));
        when(closures.accountBanPlan(ACCOUNT)).thenReturn(closurePlan());
        var instruction = instruction("restrict_account", "account", ACCOUNT);

        var plan = handler.plan(CASE, List.of(instruction));

        assertThat(plan.accounts()).containsEntry(ACCOUNT, LockPlan.AccountMode.EXCLUSIVE);
        assertThat(plan.resources()).containsExactlyInAnyOrder(
                new LockPlan.Key(LockPlan.Domain.PRODUCT, List.of(PRODUCT_A)),
                new LockPlan.Key(LockPlan.Domain.PRODUCT, List.of(PRODUCT_B)),
                new LockPlan.Key(LockPlan.Domain.TRADE, List.of(TRADE)),
                new LockPlan.Key(LockPlan.Domain.TRADE_CONVERSATION, List.of(CONVERSATION)));

        var callbacks = handler.lockCallbacks(CASE, List.of(instruction));
        assertThat(callbacks.missingFrom(plan).accounts()).isEmpty();
        assertThat(callbacks.missingFrom(plan).resources()).isEmpty();

        var transaction = mock(WriteTransaction.class);
        doAnswer(invocation -> {
            ((Runnable) invocation.getArgument(1)).run();
            return null;
        }).when(transaction).lock(any(), any());
        callbacks.acquire(transaction);

        verify(trades).lockCaseProductRow(transaction, PRODUCT_A);
        verify(trades).lockCaseProductRow(transaction, PRODUCT_B);
        verify(trades).lockTradeRow(transaction, TRADE);
        verify(trades).lockConversationRow(transaction, CONVERSATION);
    }

    @Test
    void withdrawalLocksOnlyItsProductAndPendingRequestRows() {
        when(closures.productClosurePlan(PRODUCT_A)).thenReturn(closurePlan());
        var instruction = instruction("withdraw_public_access", "product", PRODUCT_A);

        var plan = handler.plan(CASE, List.of(instruction));

        assertThat(plan.accounts()).containsEntry(101L, LockPlan.AccountMode.SHARED);
        assertThat(plan.resources()).containsExactlyInAnyOrder(
                new LockPlan.Key(LockPlan.Domain.PRODUCT, List.of(PRODUCT_A)),
                new LockPlan.Key(LockPlan.Domain.TRADE, List.of(TRADE)),
                new LockPlan.Key(LockPlan.Domain.TRADE_CONVERSATION, List.of(CONVERSATION)));
        var callbacks = handler.lockCallbacks(CASE, List.of(instruction));
        assertThat(callbacks.missingFrom(plan).resources()).isEmpty();
    }

    @Test
    void reversalWithoutItsRecordedResultFailsClosedBeforeWriting() {
        var legacy = new CaseRecords.Enforcement("e1", CASE, "restrict_account", "account", ACCOUNT, "case:3",
                1L, Instant.parse("2026-01-01T00:00:00Z"), "account_restriction", null, "applied",
                "active", "restricted", List.of(ACCOUNT), null, null,
                Instant.parse("2026-01-01T00:00:00Z"), null);

        assertThatThrownBy(() -> handler.reversePlan(CASE, legacy))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("RESTRICTION_NOT_ACTIVE"));
        assertThatThrownBy(() -> handler.reverseLockCallbacks(CASE, legacy))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("RESTRICTION_NOT_ACTIVE"));
    }

    @Test
    void onlyAccountAndProductSubjectActionsAreClaimed() {
        assertThat(handler.supports("restrict_account")).isTrue();
        assertThat(handler.supports("lift_account_restriction")).isTrue();
        assertThat(handler.supports("withdraw_public_access")).isTrue();
        assertThat(handler.supports("restore_display")).isTrue();
        assertThat(handler.supports("freeze_trade")).isFalse();
        assertThat(handler.supports("remove_content")).isFalse();
    }

    private static LockPlan closurePlan() {
        return new LockPlan(Map.of(101L, LockPlan.AccountMode.SHARED),
                Set.of(new LockPlan.Key(LockPlan.Domain.TRADE, List.of(TRADE)),
                        new LockPlan.Key(LockPlan.Domain.TRADE_CONVERSATION, List.of(CONVERSATION))));
    }

    private static CaseRecords.EnforcementInstruction instruction(String action, String targetType, long targetId) {
        return new CaseRecords.EnforcementInstruction("e-" + action, action, targetType, targetId, null);
    }
}
