package io.github.iy88.project1.api.cases;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import io.github.iy88.project1.casemanagement.application.CaseRecords;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.WriteTransaction;
import io.github.iy88.project1.trade.application.TradePorts;
import io.github.iy88.project1.trade.domain.TradeModels;
import io.github.iy88.project1.trade.domain.TradeStatus;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

class TradeCaseEnforcementTests {
    private static final long MANAGER = 9;
    private static final long BUYER = 11;
    private static final long SELLER = 12;
    private static final long TRADE_ID = 10;
    private static final long PRODUCT_ID = 20;
    private static final long CONVERSATION_ID = 30;
    private static final long CASE_ID = 40;
    private static final Instant NOW = Instant.parse("2026-11-24T00:00:00Z");

    private static final LockPlan.Key PRODUCT_KEY =
            new LockPlan.Key(LockPlan.Domain.PRODUCT, List.of(PRODUCT_ID));
    private static final LockPlan.Key TRADE_KEY = new LockPlan.Key(LockPlan.Domain.TRADE, List.of(TRADE_ID));
    private static final LockPlan.Key CASE_KEY = new LockPlan.Key(LockPlan.Domain.CASE, List.of(CASE_ID));
    private static final LockPlan.Key CONVERSATION_KEY =
            new LockPlan.Key(LockPlan.Domain.TRADE_CONVERSATION, List.of(CONVERSATION_ID));

    private TradePorts.CaseEnforcement trades;
    private TradePorts.Participation participation;
    private WriteTransaction transaction;
    private TradeCaseEnforcement enforcement;

    @BeforeEach
    void setUp() {
        trades = mock(TradePorts.CaseEnforcement.class);
        participation = mock(TradePorts.Participation.class);
        transaction = mock(WriteTransaction.class);
        enforcement = new TradeCaseEnforcement(trades, participation);
        doAnswer(invocation -> {
            ((Runnable) invocation.getArgument(1)).run();
            return null;
        }).when(transaction).lock(any(), any());
        when(participation.findConversationAccess(TRADE_ID)).thenReturn(Optional.of(
                new TradeModels.ConversationAccess(BUYER, SELLER, TradeStatus.IN_PROGRESS)));
    }

    @Test
    void terminalAdjustmentLocksProductTradeAndConversationOnceInPublicOrder() {
        when(trades.prepare(MANAGER, TRADE_ID, CASE_ID, true)).thenReturn(new TradePorts.CaseEnforcementPlan(
                new LockPlan(Map.of(MANAGER, LockPlan.AccountMode.SHARED),
                        Set.of(PRODUCT_KEY, TRADE_KEY, CASE_KEY, CONVERSATION_KEY)), CONVERSATION_ID, PRODUCT_ID));

        var callbacks = enforcement.lockCallbacks(context(), CASE_ID,
                List.of(item("enf-1", "adjust_trade_status", "terminated")));
        callbacks.acquire(transaction);

        var keys = ArgumentCaptor.forClass(LockPlan.Key.class);
        verify(transaction, times(3)).lock(keys.capture(), any());
        assertThat(keys.getAllValues()).containsExactly(PRODUCT_KEY, TRADE_KEY, CONVERSATION_KEY);
        verify(trades).lockCaseProductRow(transaction, PRODUCT_ID);
        verify(trades).lockTradeRow(transaction, TRADE_ID);
        verify(trades).lockConversationRow(transaction, CONVERSATION_ID);
    }

    @Test
    void freezeLocksOnlyTheTradeAndItsConversation() {
        when(trades.prepare(MANAGER, TRADE_ID, CASE_ID, false)).thenReturn(new TradePorts.CaseEnforcementPlan(
                new LockPlan(Map.of(MANAGER, LockPlan.AccountMode.SHARED),
                        Set.of(TRADE_KEY, CASE_KEY, CONVERSATION_KEY)), CONVERSATION_ID, null));

        var callbacks = enforcement.lockCallbacks(context(), CASE_ID,
                List.of(item("enf-1", "freeze_trade", null)));
        callbacks.acquire(transaction);

        var keys = ArgumentCaptor.forClass(LockPlan.Key.class);
        verify(transaction, times(2)).lock(keys.capture(), any());
        assertThat(keys.getAllValues()).containsExactly(TRADE_KEY, CONVERSATION_KEY);
        verify(trades, never()).lockCaseProductRow(any(), anyLong());
        verify(trades).lockTradeRow(transaction, TRADE_ID);
    }

    @Test
    void restoreAdjustmentKeepsTheFreezeAndPublishesTheTradeRestore() {
        when(trades.prepare(MANAGER, TRADE_ID, CASE_ID, false)).thenReturn(new TradePorts.CaseEnforcementPlan(
                new LockPlan(Map.of(MANAGER, LockPlan.AccountMode.SHARED),
                        Set.of(TRADE_KEY, CASE_KEY, CONVERSATION_KEY)), CONVERSATION_ID, null));

        var callbacks = enforcement.lockCallbacks(context(), CASE_ID,
                List.of(item("enf-1", "adjust_trade_status", "in_progress")));
        callbacks.acquire(transaction);

        var keys = ArgumentCaptor.forClass(LockPlan.Key.class);
        verify(transaction, times(2)).lock(keys.capture(), any());
        assertThat(keys.getAllValues()).containsExactly(TRADE_KEY, CONVERSATION_KEY);
        verify(trades, never()).lockCaseProductRow(any(), anyLong());

        var subject = new TradePorts.CaseEnforcementOutcome(TRADE_ID, 57L, UUID.randomUUID(),
                "abnormal", "in_progress", "awaiting_completion", "awaiting_completion",
                true, true, false);
        when(trades.restoreLocked(transaction, CASE_ID, TRADE_ID, "case:40", "reason")).thenReturn(subject);

        var outcomes = enforcement.execute(transaction, context(), CASE_ID, "reason", "case:40",
                List.of(item("enf-1", "adjust_trade_status", "in_progress")), NOW);

        assertThat(outcomes).singleElement().satisfies(outcome -> {
            assertThat(outcome.resultType()).isEqualTo("trade_transition");
            assertThat(outcome.resultId()).isEqualTo(57L);
            assertThat(outcome.previousState()).isEqualTo("status=abnormal,phase=awaiting_completion,frozen=true");
            assertThat(outcome.currentState()).isEqualTo("status=in_progress,phase=awaiting_completion,frozen=true");
            assertThat(outcome.affectedAccountIds()).containsExactly(BUYER, SELLER);
        });
        verify(trades).publishLocked(transaction, CASE_ID, TRADE_ID, "restore_trade", subject, "reason");
        verify(trades, never()).adjustStatusLocked(any(), anyLong(), anyLong(), anyString(), anyString(),
                anyString());
    }

    @Test
    void terminalAdjustmentStillUsesTheTerminalSubjectPath() {
        var subject = new TradePorts.CaseEnforcementOutcome(TRADE_ID, 58L, UUID.randomUUID(),
                "in_progress", "terminated", "awaiting_completion", null, false, false, false);
        when(trades.adjustStatusLocked(transaction, CASE_ID, TRADE_ID, "terminated", "case:40", "reason"))
                .thenReturn(subject);

        var outcomes = enforcement.execute(transaction, context(), CASE_ID, "reason", "case:40",
                List.of(item("enf-1", "adjust_trade_status", "terminated")), NOW);

        assertThat(outcomes).singleElement()
                .satisfies(outcome -> assertThat(outcome.currentState()).isEqualTo("status=terminated,phase=,frozen=false"));
        verify(trades).publishLocked(transaction, CASE_ID, TRADE_ID, "adjust_trade_status", subject, "reason");
        verify(trades, never()).restoreLocked(any(), anyLong(), anyLong(), anyString(), anyString());
    }

    @Test
    void executionUsesTheTradeTransitionReferenceAndPublishesTradeEffects() {
        var subject = new TradePorts.CaseEnforcementOutcome(TRADE_ID, 55L, UUID.randomUUID(),
                "in_progress", "in_progress", "first_agreement_pending", "first_agreement_pending",
                false, true, false);
        when(trades.freezeLocked(transaction, CASE_ID, TRADE_ID, "case:40", "reason")).thenReturn(subject);

        var outcomes = enforcement.execute(transaction, context(), CASE_ID, "reason", "case:40",
                List.of(item("enf-1", "freeze_trade", null)), NOW);

        assertThat(outcomes).singleElement().satisfies(outcome -> {
            assertThat(outcome.resultType()).isEqualTo("trade_transition");
            assertThat(outcome.resultId()).isEqualTo(55L);
            assertThat(outcome.previousState()).isEqualTo("status=in_progress,phase=first_agreement_pending,frozen=false");
            assertThat(outcome.currentState()).isEqualTo("status=in_progress,phase=first_agreement_pending,frozen=true");
            assertThat(outcome.affectedAccountIds()).containsExactly(BUYER, SELLER);
        });
        verify(trades).publishLocked(transaction, CASE_ID, TRADE_ID, "freeze_trade", subject, "reason");
    }

    @Test
    void legacyTradeReferenceResolvesTheUniqueTransitionAndReportsRemainingFreezes() {
        var recorded = new CaseRecords.Enforcement("enf-1", CASE_ID, "freeze_trade", "trade", TRADE_ID,
                "case:40", MANAGER, NOW, "trade", TRADE_ID, "applied", "frozen", "frozen",
                List.of(BUYER, SELLER), null, null, NOW, null);
        var lifted = new TradePorts.CaseEnforcementOutcome(TRADE_ID, 56L, UUID.randomUUID(),
                "in_progress", "in_progress", "first_agreement_pending", "first_agreement_pending",
                true, true, false);
        when(trades.legacyFreezeTransition(CASE_ID, TRADE_ID)).thenReturn(55L);
        when(trades.liftFreezeLocked(transaction, CASE_ID, TRADE_ID, 55L, "case:40", "reason"))
                .thenReturn(lifted);

        var outcomes = enforcement.reverse(transaction, context(), CASE_ID, recorded, "revoke", "case:40",
                "reason", NOW);

        assertThat(outcomes).singleElement().satisfies(outcome -> {
            assertThat(outcome.action()).isEqualTo("lift_trade_freeze");
            assertThat(outcome.resultType()).isEqualTo("trade_transition");
            assertThat(outcome.resultId()).isEqualTo(56L);
            assertThat(outcome.remainingRestrictions()).containsExactly("trade_freeze");
        });
        verify(trades).publishLocked(transaction, CASE_ID, TRADE_ID, "lift_trade_freeze", lifted, "reason");
    }

    @Test
    void terminalAdjustmentCannotBeReversed() {
        var recorded = new CaseRecords.Enforcement("enf-1", CASE_ID, "adjust_trade_status", "trade", TRADE_ID,
                "case:40", MANAGER, NOW, "trade_transition", 55L, "applied", "completed", "completed",
                List.of(BUYER, SELLER), null, null, NOW, null);

        assertThatThrownBy(() -> enforcement.reverse(transaction, context(), CASE_ID, recorded, "revoke",
                "case:40", "reason", NOW))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("TRADE_TERMINAL"));
    }

    private static CaseRecords.EnforcementInstruction item(String id, String action, String expected) {
        return new CaseRecords.EnforcementInstruction(id, action, "trade", TRADE_ID, expected);
    }

    private static ExecutionContext context() {
        return new ExecutionContext(UUID.randomUUID(), ExecutionContext.ActorKind.ACCOUNT,
                Long.toString(MANAGER), UUID.randomUUID(), null, 1L, "trade-case-enforcement-test");
    }
}
