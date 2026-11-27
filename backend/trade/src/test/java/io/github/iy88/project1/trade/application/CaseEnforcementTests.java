package io.github.iy88.project1.trade.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.WriteExecutor;
import io.github.iy88.project1.core.WriteTransaction;
import io.github.iy88.project1.messaging.TaskSchedules;
import io.github.iy88.project1.trade.domain.Trade;
import io.github.iy88.project1.trade.domain.TradeModels;
import io.github.iy88.project1.trade.domain.TradeStatus;
import io.github.iy88.project1.trade.domain.TradeVocabulary.ActorKind;
import io.github.iy88.project1.trade.domain.TradeVocabulary.FreezeSource;
import io.github.iy88.project1.trade.persistence.TradeRepository;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Optional;
import java.util.OptionalLong;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import tools.jackson.databind.json.JsonMapper;

class CaseEnforcementTests {
    private static final long MANAGER = 7001;
    private static final long BUYER = 7002;
    private static final long SELLER = 7003;
    private static final long TRADE_ID = 1001;
    private static final long PRODUCT_ID = 2001;
    private static final long CONVERSATION_ID = 3001;
    private static final long CASE_ID = 4001;
    private static final long OTHER_CASE_ID = 4002;
    private static final Instant NOW = Instant.parse("2026-11-24T00:00:00Z");
    private static final Clock CLOCK = Clock.fixed(NOW, ZoneOffset.UTC);

    private TradeRepository repository;
    private TradePorts.Product product;
    private TradePorts.Accounts accounts;
    private TradePorts.Conversation conversations;
    private TradePorts.Cases cases;
    private TradePorts.Notifications notifications;
    private TaskSchedules schedules;
    private TradeApplication application;
    private WriteTransaction transaction;

    @BeforeEach
    void setUp() {
        repository = mock(TradeRepository.class);
        product = mock(TradePorts.Product.class);
        accounts = mock(TradePorts.Accounts.class);
        conversations = mock(TradePorts.Conversation.class);
        cases = mock(TradePorts.Cases.class);
        notifications = mock(TradePorts.Notifications.class);
        schedules = mock(TaskSchedules.class);
        application = new TradeApplication(repository, mock(WriteExecutor.class), schedules, CLOCK,
                new TradeSettings(604800, "s2-v1", 20, 100, 200), product, accounts, conversations, cases,
                notifications, JsonMapper.builder().build());
        when(accounts.qualification(MANAGER))
                .thenReturn(new TradePorts.AccountQualification(MANAGER, true, false));
        when(product.read(PRODUCT_ID)).thenReturn(Optional.of(productState()));
        when(repository.find(TRADE_ID)).thenReturn(Optional.of(trade(TradeStatus.IN_PROGRESS)));
        when(conversations.find(TRADE_ID)).thenReturn(OptionalLong.of(CONVERSATION_ID));
        when(repository.activeFreezes(TRADE_ID)).thenReturn(List.of());
        when(repository.insertFreeze(eq(TRADE_ID), eq(FreezeSource.ADMIN_CASE), eq(CASE_ID), anyString(), any()))
                .thenReturn(71L);
        when(repository.insertHistory(any())).thenReturn(501L);
        transaction = mock(WriteTransaction.class);
        when(transaction.context()).thenReturn(context());
    }

    @Test
    void freezeReturnsTheInsertedHistoryAndSnapshotsBeforeAndAfter() {
        var outcome = application.freezeLocked(transaction, CASE_ID, TRADE_ID, "basis-1", "under review");

        assertThat(outcome.transitionId()).isEqualTo(501);
        assertThat(outcome.previousStatus()).isEqualTo("in_progress");
        assertThat(outcome.currentStatus()).isEqualTo("in_progress");
        assertThat(outcome.previousPhase()).isEqualTo("first_agreement_pending");
        assertThat(outcome.currentPhase()).isEqualTo("first_agreement_pending");
        assertThat(outcome.frozenBefore()).isFalse();
        assertThat(outcome.frozenAfter()).isTrue();
        assertThat(outcome.alreadyEffective()).isFalse();

        var captured = ArgumentCaptor.forClass(TradeModels.History.class);
        verify(repository).insertHistory(captured.capture());
        assertThat(captured.getValue().action()).isEqualTo("trade.freeze");
        assertThat(captured.getValue().freezeId()).isEqualTo(71);
        assertThat(captured.getValue().fromStatus()).isEqualTo("in_progress");
        assertThat(captured.getValue().toStatus()).isEqualTo("in_progress");
        assertThat(captured.getValue().fromFrozen()).isFalse();
        assertThat(captured.getValue().toFrozen()).isTrue();
        verify(conversations, never()).append(any(), anyLong(), any(), anyString(), anyString(), any());
        verify(notifications, never()).register(any(), any(), anyString(), anyLong(), any());
        verify(transaction).requireExclusiveAccount(BUYER);
        verify(transaction).requireExclusiveAccount(SELLER);
    }

    @Test
    void freezeByTheSameCaseReplaysItsExactTransitionWithoutNewRows() {
        var freeze = freeze(71, FreezeSource.ADMIN_CASE, CASE_ID, true);
        when(repository.activeFreezes(TRADE_ID)).thenReturn(List.of(freeze));
        when(repository.freezeTransition(71)).thenReturn(Optional.of(freezeHistory(501, 71, CASE_ID)));

        var outcome = application.freezeLocked(transaction, CASE_ID, TRADE_ID, "basis-2", "same decision");

        assertThat(outcome.transitionId()).isEqualTo(501);
        assertThat(outcome.alreadyEffective()).isTrue();
        assertThat(outcome.frozenBefore()).isFalse();
        assertThat(outcome.frozenAfter()).isTrue();
        verify(repository, never()).insertFreeze(anyLong(), any(), any(), anyString(), any());
        verify(repository, never()).insertHistory(any());
        verify(conversations, never()).append(any(), anyLong(), any(), anyString(), anyString(), any());
        verify(notifications, never()).register(any(), any(), anyString(), anyLong(), any());
    }

    @Test
    void freezeDoesNotGuessAReplayWhenTheActiveFreezeHasNoExactTransition() {
        var freeze = freeze(71, FreezeSource.ADMIN_CASE, CASE_ID, true);
        when(repository.activeFreezes(TRADE_ID)).thenReturn(List.of(freeze));
        when(repository.freezeTransition(71)).thenReturn(Optional.empty());

        assertThatThrownBy(() -> application.freezeLocked(transaction, CASE_ID, TRADE_ID, "basis-3", "same decision"))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("TARGET_STATE_CONFLICT"));
        verify(repository, never()).insertFreeze(anyLong(), any(), any(), anyString(), any());
    }

    @Test
    void freezeLeavesOtherFreezeSourcesCoexisting() {
        var accountBan = freeze(72, FreezeSource.ACCOUNT_BAN, 9001, true);
        when(repository.activeFreezes(TRADE_ID)).thenReturn(List.of(accountBan));

        var outcome = application.freezeLocked(transaction, CASE_ID, TRADE_ID, "basis-4", "case freeze");

        assertThat(outcome.frozenBefore()).isTrue();
        assertThat(outcome.frozenAfter()).isTrue();
        verify(repository).insertFreeze(eq(TRADE_ID), eq(FreezeSource.ADMIN_CASE), eq(CASE_ID),
                eq("case freeze"), eq(NOW));
        verify(repository, never()).endFreeze(anyLong(), any(), any());
    }

    @Test
    void liftUsesTheOriginallyAssociatedFreezeAndDoesNotReleaseALaterFreeze() {
        var original = freeze(71, FreezeSource.ADMIN_CASE, CASE_ID, false);
        var later = freeze(72, FreezeSource.ADMIN_CASE, CASE_ID, true);
        when(repository.history(501)).thenReturn(Optional.of(freezeHistory(501, 71, CASE_ID)));
        when(repository.freeze(71)).thenReturn(Optional.of(original));
        when(repository.activeFreezes(TRADE_ID)).thenReturn(List.of(later));

        assertThatThrownBy(() -> application.liftFreezeLocked(transaction, CASE_ID, TRADE_ID, 501,
                "basis-5", "release"))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("TRADE_FREEZE_NOT_ACTIVE"));
        verify(repository, never()).endFreeze(anyLong(), any(), any());
        verify(repository, never()).insertHistory(any());
    }

    @Test
    void liftRejectsATransitionForAnotherFreezeSource() {
        var timeout = freeze(73, FreezeSource.TIMEOUT, CASE_ID, true);
        when(repository.history(502)).thenReturn(Optional.of(freezeHistory(502, 73, CASE_ID)));
        when(repository.freeze(73)).thenReturn(Optional.of(timeout));

        assertThatThrownBy(() -> application.liftFreezeLocked(transaction, CASE_ID, TRADE_ID, 502,
                "basis-6", "release"))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("TRADE_FREEZE_NOT_ACTIVE"));
        verify(repository, never()).endFreeze(anyLong(), any(), any());
    }

    @Test
    void liftRejectsAnUnfreezeTransition() {
        var freeze = freeze(71, FreezeSource.ADMIN_CASE, CASE_ID, true);
        var unfreeze = new TradeModels.History(504, TRADE_ID, "trade.unfreeze", "in_progress", "in_progress",
                "first_agreement_pending", "first_agreement_pending", ActorKind.ADMIN, MANAGER, "reason", "basis",
                CASE_ID, 71L, true, true, null, null, null, null, null, null, null, UUID.randomUUID(), NOW);
        when(repository.history(504)).thenReturn(Optional.of(unfreeze));
        when(repository.freeze(71)).thenReturn(Optional.of(freeze));

        assertThatThrownBy(() -> application.liftFreezeLocked(transaction, CASE_ID, TRADE_ID, 504,
                "basis-7", "release"))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("TRADE_FREEZE_NOT_ACTIVE"));
        verify(repository, never()).endFreeze(anyLong(), any(), any());
    }

    @Test
    void liftRejectsATransitionFromAnotherCase() {
        var freeze = freeze(71, FreezeSource.ADMIN_CASE, CASE_ID, true);
        when(repository.history(503)).thenReturn(Optional.of(freezeHistory(503, 71, OTHER_CASE_ID)));
        when(repository.freeze(71)).thenReturn(Optional.of(freeze));

        assertThatThrownBy(() -> application.liftFreezeLocked(transaction, CASE_ID, TRADE_ID, 503,
                "basis-7", "release"))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("TRADE_FREEZE_NOT_ACTIVE"));
        verify(repository, never()).endFreeze(anyLong(), any(), any());
    }

    @Test
    void liftEndsOnlyTheExactFreezeAndLeavesOtherSourcesActive() {
        var original = freeze(71, FreezeSource.ADMIN_CASE, CASE_ID, true);
        var accountBan = freeze(72, FreezeSource.ACCOUNT_BAN, 9001, true);
        when(repository.history(501)).thenReturn(Optional.of(freezeHistory(501, 71, CASE_ID)));
        when(repository.freeze(71)).thenReturn(Optional.of(original));
        when(repository.activeFreezes(TRADE_ID)).thenReturn(List.of(accountBan));
        when(repository.insertHistory(any())).thenReturn(502L);

        var outcome = application.liftFreezeLocked(transaction, CASE_ID, TRADE_ID, 501, "basis-8", "release");

        assertThat(outcome.transitionId()).isEqualTo(502);
        assertThat(outcome.frozenBefore()).isTrue();
        assertThat(outcome.frozenAfter()).isTrue();
        verify(repository).endFreeze(eq(71L), eq(MANAGER), eq(NOW));
        verify(repository, never()).endFreeze(eq(72L), any(), any());
        verify(repository, never()).saveWait(anyLong(), any());
        verify(schedules, never()).schedule(any());

        var captured = ArgumentCaptor.forClass(TradeModels.History.class);
        verify(repository).insertHistory(captured.capture());
        assertThat(captured.getValue().action()).isEqualTo("trade.unfreeze");
        assertThat(captured.getValue().freezeId()).isEqualTo(71);
        assertThat(captured.getValue().fromFrozen()).isTrue();
        assertThat(captured.getValue().toFrozen()).isTrue();
    }

    @Test
    void liftResumesThePausedWaitOnlyWhenNoFreezeRemains() {
        var original = freeze(71, FreezeSource.ADMIN_CASE, CASE_ID, true);
        when(repository.history(501)).thenReturn(Optional.of(freezeHistory(501, 71, CASE_ID)));
        when(repository.freeze(71)).thenReturn(Optional.of(original));
        when(repository.activeFreezes(TRADE_ID)).thenReturn(List.of());
        when(repository.waitFor(TRADE_ID)).thenReturn(Optional.of(new TradeModels.Wait(TRADE_ID,
                NOW.minusSeconds(100), null, 10, 100, "s2-v1", null, null)));
        when(repository.currentConfirmations(TRADE_ID)).thenReturn(List.of(new TradeModels.Confirmation(1,
                TRADE_ID, 1, BUYER, null, NOW.minusSeconds(50), null, null, UUID.randomUUID())));

        var outcome = application.liftFreezeLocked(transaction, CASE_ID, TRADE_ID, 501, "basis-9", "release");

        assertThat(outcome.frozenAfter()).isFalse();
        verify(repository).saveWait(eq(TRADE_ID), any());
        verify(schedules).schedule(any());
    }

    @Test
    void ordinaryLiftReleasesOnlyTheCaseOwnedFreezeAndKeepsOtherSources() {
        var own = freeze(71, FreezeSource.ADMIN_CASE, CASE_ID, true);
        var accountBan = freeze(72, FreezeSource.ACCOUNT_BAN, 9001, true);
        when(repository.activeFreezes(TRADE_ID)).thenReturn(List.of(own, accountBan));
        when(repository.insertHistory(any())).thenReturn(710L);

        var outcome = application.liftCaseFreezeLocked(transaction, CASE_ID, TRADE_ID, "basis-20", "release");

        assertThat(outcome.transitionId()).isEqualTo(710);
        assertThat(outcome.frozenBefore()).isTrue();
        assertThat(outcome.frozenAfter()).isTrue();
        verify(repository).endFreeze(eq(71L), eq(MANAGER), eq(NOW));
        verify(repository, never()).endFreeze(eq(72L), any(), any());
        verify(repository, never()).endAllFreezes(anyLong(), any());

        var captured = ArgumentCaptor.forClass(TradeModels.History.class);
        verify(repository).insertHistory(captured.capture());
        assertThat(captured.getValue().action()).isEqualTo("trade.unfreeze");
        assertThat(captured.getValue().freezeId()).isEqualTo(71);
        assertThat(captured.getValue().fromFrozen()).isTrue();
        assertThat(captured.getValue().toFrozen()).isTrue();
    }

    @Test
    void ordinaryLiftAcceptsTheSystemTimeoutSourceWithoutRestoringTheTrade() {
        when(repository.find(TRADE_ID)).thenReturn(Optional.of(trade(TradeStatus.ABNORMAL)));
        var timeout = freeze(73, FreezeSource.TIMEOUT, CASE_ID, true);
        when(repository.activeFreezes(TRADE_ID)).thenReturn(List.of(timeout), List.of());
        when(repository.insertHistory(any())).thenReturn(711L);

        var outcome = application.liftCaseFreezeLocked(transaction, CASE_ID, TRADE_ID, "basis-21", "release");

        assertThat(outcome.transitionId()).isEqualTo(711);
        assertThat(outcome.previousStatus()).isEqualTo("abnormal");
        assertThat(outcome.currentStatus()).isEqualTo("abnormal");
        assertThat(outcome.frozenBefore()).isTrue();
        assertThat(outcome.frozenAfter()).isFalse();
        verify(repository).endFreeze(eq(73L), eq(MANAGER), eq(NOW));
        verify(repository, never()).save(any(Trade.class));
        verify(repository, never()).invalidateConfirmations(anyLong(), any(), any());
        verify(repository, never()).saveWait(anyLong(), any());
        verify(schedules, never()).schedule(any());
    }

    @Test
    void ordinaryLiftResumesThePausedWaitOnlyAfterTheLastSource() {
        var own = freeze(71, FreezeSource.ADMIN_CASE, CASE_ID, true);
        when(repository.activeFreezes(TRADE_ID)).thenReturn(List.of(own), List.of(), List.of());
        when(repository.waitFor(TRADE_ID)).thenReturn(Optional.of(new TradeModels.Wait(TRADE_ID,
                NOW.minusSeconds(100), null, 10, 100, "s2-v1", null, null)));
        when(repository.currentConfirmations(TRADE_ID)).thenReturn(List.of(new TradeModels.Confirmation(1,
                TRADE_ID, 1, BUYER, null, NOW.minusSeconds(50), null, null, UUID.randomUUID())));
        when(repository.insertHistory(any())).thenReturn(712L);

        var outcome = application.liftCaseFreezeLocked(transaction, CASE_ID, TRADE_ID, "basis-22", "release");

        assertThat(outcome.transitionId()).isEqualTo(712);
        assertThat(outcome.frozenAfter()).isFalse();
        verify(repository).saveWait(eq(TRADE_ID), any());
        verify(schedules).schedule(any());
    }

    @Test
    void ordinaryLiftRejectsAnAccountBanOnlySource() {
        when(repository.activeFreezes(TRADE_ID)).thenReturn(List.of(
                freeze(72, FreezeSource.ACCOUNT_BAN, 9001, true)));

        assertThatThrownBy(() -> application.liftCaseFreezeLocked(transaction, CASE_ID, TRADE_ID,
                "basis-23", "release"))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("TRADE_FREEZE_NOT_ACTIVE"));
        verify(repository, never()).endFreeze(anyLong(), any(), any());
        verify(repository, never()).insertHistory(any());
    }

    @Test
    void ordinaryLiftRejectsAmbiguousCaseSources() {
        var adminCase = freeze(71, FreezeSource.ADMIN_CASE, CASE_ID, true);
        var timeout = freeze(73, FreezeSource.TIMEOUT, CASE_ID, true);
        when(repository.activeFreezes(TRADE_ID)).thenReturn(List.of(adminCase, timeout));

        assertThatThrownBy(() -> application.liftCaseFreezeLocked(transaction, CASE_ID, TRADE_ID,
                "basis-24", "release"))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("TRADE_FREEZE_NOT_ACTIVE"));
        verify(repository, never()).endFreeze(anyLong(), any(), any());
        verify(repository, never()).insertHistory(any());
    }

    @Test
    void ordinaryLiftRejectsASourceFromAnotherCaseOrTrade() {
        var otherCase = freeze(74, FreezeSource.ADMIN_CASE, OTHER_CASE_ID, true);
        var otherTrade = new TradeModels.Freeze(75, TRADE_ID + 1, FreezeSource.TIMEOUT, CASE_ID, "reason",
                NOW.minusSeconds(50), null, null);
        when(repository.activeFreezes(TRADE_ID)).thenReturn(List.of(otherCase, otherTrade));

        assertThatThrownBy(() -> application.liftCaseFreezeLocked(transaction, CASE_ID, TRADE_ID,
                "basis-25", "release"))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("TRADE_FREEZE_NOT_ACTIVE"));
        verify(repository, never()).endFreeze(anyLong(), any(), any());
        verify(repository, never()).insertHistory(any());
    }

    @Test
    void terminalAdjustmentReturnsTheHistoryIdAndClosesTradeOwnedFacts() {
        when(repository.activeFreezes(TRADE_ID)).thenReturn(List.of(
                freeze(71, FreezeSource.ADMIN_CASE, CASE_ID, true)));
        when(repository.insertHistory(any())).thenReturn(700L);

        var outcome = application.adjustStatusLocked(transaction, CASE_ID, TRADE_ID, "completed", "basis-10",
                "completed by admin");

        assertThat(outcome.transitionId()).isEqualTo(700);
        assertThat(outcome.previousStatus()).isEqualTo("in_progress");
        assertThat(outcome.currentStatus()).isEqualTo("completed");
        assertThat(outcome.frozenBefore()).isTrue();
        assertThat(outcome.frozenAfter()).isFalse();
        verify(repository).save(any(Trade.class));
        verify(repository).endAllFreezes(eq(TRADE_ID), eq(NOW));
        verify(repository).terminateOpenDisputes(eq(TRADE_ID), eq(NOW));
        verify(product).release(transaction, productState(), TRADE_ID, "admin_terminated");
        verify(conversations, never()).append(any(), anyLong(), any(), anyString(), anyString(), any());
        verify(notifications, never()).register(any(), any(), anyString(), anyLong(), any());
        verify(repository, never()).lockTrade(any(), anyLong());
    }

    @Test
    void restoreKeepsOccupancyAndEveryFreeze() {
        when(repository.find(TRADE_ID)).thenReturn(Optional.of(trade(TradeStatus.ABNORMAL)));
        when(repository.activeFreezes(TRADE_ID)).thenReturn(List.of(
                freeze(71, FreezeSource.ADMIN_CASE, CASE_ID, true)));
        when(repository.insertHistory(any())).thenReturn(701L);

        var outcome = application.restoreLocked(transaction, CASE_ID, TRADE_ID, "basis-11", "restore");

        assertThat(outcome.transitionId()).isEqualTo(701);
        assertThat(outcome.previousStatus()).isEqualTo("abnormal");
        assertThat(outcome.currentStatus()).isEqualTo("in_progress");
        assertThat(outcome.frozenBefore()).isTrue();
        assertThat(outcome.frozenAfter()).isTrue();
        verify(repository).invalidateConfirmations(eq(TRADE_ID), any(), eq(NOW));
        verify(repository, never()).endAllFreezes(anyLong(), any());
        verify(repository, never()).endFreeze(anyLong(), any(), any());
        verify(product, never()).release(any(), any(), anyLong(), anyString());
        verify(repository, never()).lockTrade(any(), anyLong());
    }

    @Test
    void restoreRejectsADisputedTradeWithoutResolvingTheDispute() {
        when(repository.find(TRADE_ID)).thenReturn(Optional.of(trade(TradeStatus.DISPUTED)));

        assertThatThrownBy(() -> application.restoreLocked(transaction, CASE_ID, TRADE_ID, "basis-12", "restore"))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("TRANSITION_NOT_ALLOWED"));

        verify(repository, never()).invalidateConfirmations(anyLong(), any(), any());
        verify(repository, never()).resolveDispute(anyLong(), any(), anyLong(), any(), any());
        verify(repository, never()).save(any(Trade.class));
    }

    @Test
    void restoreAndAdjustRejectTerminalTrades() {
        when(repository.find(TRADE_ID)).thenReturn(Optional.of(trade(TradeStatus.COMPLETED)));
        assertThatThrownBy(() -> application.restoreLocked(transaction, CASE_ID, TRADE_ID, "basis-12", "restore"))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("TRADE_TERMINAL"));
        assertThatThrownBy(() -> application.adjustStatusLocked(transaction, CASE_ID, TRADE_ID, "terminated",
                "basis-13", "terminate"))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("TRADE_TERMINAL"));
        verify(repository, never()).save(any(Trade.class));
    }

    @Test
    void prepareIncludesTheProductLockOnlyForTerminalAdjustment() {
        when(repository.find(TRADE_ID)).thenReturn(Optional.of(trade(TradeStatus.IN_PROGRESS)));

        var terminal = application.prepare(MANAGER, TRADE_ID, CASE_ID, true);
        var freeze = application.prepare(MANAGER, TRADE_ID, CASE_ID, false);

        assertThat(terminal.productId()).isEqualTo(PRODUCT_ID);
        assertThat(terminal.lockPlan().resources())
                .contains(new LockPlan.Key(LockPlan.Domain.PRODUCT, List.of(PRODUCT_ID)));
        assertThat(freeze.productId()).isNull();
        assertThat(freeze.lockPlan().resources())
                .doesNotContain(new LockPlan.Key(LockPlan.Domain.PRODUCT, List.of(PRODUCT_ID)));
        assertThat(freeze.lockPlan().resources())
                .contains(new LockPlan.Key(LockPlan.Domain.TRADE_CONVERSATION, List.of(CONVERSATION_ID)));
    }

    private static ExecutionContext context() {
        return new ExecutionContext(UUID.randomUUID(), ExecutionContext.ActorKind.ACCOUNT,
                Long.toString(MANAGER), UUID.randomUUID(), null, 1L, "case-enforcement-test");
    }

    private static Trade trade(TradeStatus status) {
        String terminalReason = status == TradeStatus.COMPLETED ? "completed"
                : status == TradeStatus.TERMINATED ? "admin_terminated" : null;
        Instant endedAt = status.isTerminal() ? NOW : null;
        return new Trade(TRADE_ID, PRODUCT_ID, BUYER, SELLER, status, null, null,
                3, null, terminalReason, NOW.minusSeconds(200), null, endedAt, NOW.minusSeconds(300), NOW);
    }

    private static TradePorts.ProductState productState() {
        return new TradePorts.ProductState(PRODUCT_ID, SELLER, 1, "in_progress", TRADE_ID, "title", "description",
                1000, List.of(), List.of());
    }

    private static TradeModels.Freeze freeze(long id, FreezeSource source, long sourceRef, boolean active) {
        return new TradeModels.Freeze(id, TRADE_ID, source, sourceRef, "reason", NOW.minusSeconds(50),
                active ? null : NOW.minusSeconds(20), active ? null : MANAGER);
    }

    private static TradeModels.History freezeHistory(long transitionId, long freezeId, long caseId) {
        return new TradeModels.History(transitionId, TRADE_ID, "trade.freeze", "in_progress", "in_progress",
                "first_agreement_pending", "first_agreement_pending", ActorKind.ADMIN, MANAGER, "reason", "basis",
                caseId, freezeId, false, true, null, null, null, null, null, null, null, UUID.randomUUID(), NOW);
    }
}
