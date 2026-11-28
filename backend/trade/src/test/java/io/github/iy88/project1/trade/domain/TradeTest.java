package io.github.iy88.project1.trade.domain;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import io.github.iy88.project1.core.BusinessError;
import java.time.Instant;
import org.junit.jupiter.api.Test;

class TradeTest {
    private static final Instant T0 = Instant.parse("2026-11-20T00:00:00Z");
    private static final Trade PENDING = trade(TradeStatus.PENDING_ACCEPTANCE, null, 1);
    private static final Trade FIRST = trade(TradeStatus.IN_PROGRESS, null, 2);
    private static final Trade AWAITING = trade(TradeStatus.IN_PROGRESS, 90L, 3);
    private static final Trade DISPUTED = trade(TradeStatus.DISPUTED, 90L, 4);
    private static final Trade TERMINATED = trade(TradeStatus.TERMINATED, 90L, 5);

    @Test
    void phaseIsDerivedFromStatusAndEffectiveAgreement() {
        assertThat(PENDING.phase()).isNull();
        assertThat(FIRST.phase()).isEqualTo(TradePhase.FIRST_AGREEMENT_PENDING);
        assertThat(AWAITING.phase()).isEqualTo(TradePhase.AWAITING_COMPLETION);
        assertThat(DISPUTED.phase()).isEqualTo(TradePhase.AWAITING_COMPLETION);
        assertThat(TERMINATED.phase()).isNull();
    }

    @Test
    void terminalAndEndedRequestErrorsAreStable() {
        assertThatThrownBy(() -> TERMINATED.requireNotTerminal())
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("TRADE_TERMINAL"));
        var rejected = trade(TradeStatus.REJECTED, null, 1);
        assertThatThrownBy(() -> rejected.status().requireTransition(TradeStatus.IN_PROGRESS))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("REQUEST_ALREADY_ENDED"));
        assertThatThrownBy(() -> AWAITING.status().requireTransition(TradeStatus.PENDING_ACCEPTANCE))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("STATE_CONFLICT"));
    }

    @Test
    void participantAndRoleChecksDoNotLeakExistence() {
        assertThatThrownBy(() -> AWAITING.requireParticipant(999))
                .isInstanceOfSatisfying(BusinessError.class, error -> {
                    assertThat(error.code()).isEqualTo("RESOURCE_NOT_VISIBLE");
                    assertThat(error.status()).isEqualTo(404);
                });
        assertThatThrownBy(() -> AWAITING.requireSeller(11))
                .isInstanceOfSatisfying(BusinessError.class, error -> {
                    assertThat(error.code()).isEqualTo("ACTION_NOT_ALLOWED");
                    assertThat(error.status()).isEqualTo(403);
                });
        AWAITING.requireBuyer(11);
    }

    @Test
    void allowedActionsFollowRoleStatusAndPendingObjects() {
        assertThat(PENDING.allowedActions(11, false, false, false, false))
                .containsExactly("withdraw");
        assertThat(PENDING.allowedActions(22, false, false, false, false))
                .containsExactly("accept", "reject");
        assertThat(FIRST.allowedActions(11, false, false, false, false))
                .containsExactly("propose_agreement", "open_dispute", "propose_cancellation");
        assertThat(AWAITING.allowedActions(11, true, true, false, false))
                .containsExactly("submit_confirmation", "open_dispute", "decide_agreement", "decide_cancellation");
        assertThat(AWAITING.allowedActions(11, false, false, true, false))
                .doesNotContain("submit_confirmation");
        assertThat(AWAITING.allowedActions(11, false, false, false, true)).isEmpty();
        assertThat(DISPUTED.allowedActions(22, false, false, false, false))
                .containsExactly("propose_cancellation", "confirm_dispute_resolution");
        assertThat(TERMINATED.allowedActions(11, false, false, false, false)).isEmpty();
        assertThat(AWAITING.allowedActions(999, false, false, false, false)).isEmpty();
    }

    @Test
    void cancellationModeUsesStageRoleAndCurrentConfirmation() {
        assertThat(FIRST.cancellationMode(11, false)).isEqualTo(TradeVocabulary.CancellationMode.DIRECT);
        assertThat(FIRST.cancellationMode(11, true)).isEqualTo(TradeVocabulary.CancellationMode.APPROVAL);
        assertThat(FIRST.cancellationMode(22, false)).isEqualTo(TradeVocabulary.CancellationMode.APPROVAL);
        assertThat(AWAITING.cancellationMode(11, false)).isEqualTo(TradeVocabulary.CancellationMode.APPROVAL);
        assertThat(DISPUTED.cancellationMode(11, false)).isEqualTo(TradeVocabulary.CancellationMode.APPROVAL);
    }

    @Test
    void versionConflictDoesNotChangeState() {
        assertThatThrownBy(() -> AWAITING.requireVersion(99))
                .isInstanceOfSatisfying(BusinessError.class, error -> {
                    assertThat(error.code()).isEqualTo("VERSION_CONFLICT");
                    assertThat(error.status()).isEqualTo(409);
                });
    }

    @Test
    void waitPausesAndResumesWithoutLosingAccumulatedTime() {
        var wait = TradeModels.Wait.start(T0, 604800, "s2-v1");
        assertThat(wait.active()).isTrue();
        assertThat(wait.elapsedSeconds(T0)).isZero();
        assertThat(wait.remainingSeconds(T0)).isEqualTo(604800);

        var paused = wait.pause(T0.plusSeconds(2 * 86400));
        assertThat(paused.paused()).isTrue();
        assertThat(paused.elapsedSeconds(T0.plusSeconds(4 * 86400))).isEqualTo(2 * 86400);

        var resumed = paused.resume(T0.plusSeconds(4 * 86400));
        assertThat(resumed.active()).isTrue();
        assertThat(resumed.remainingSeconds(T0.plusSeconds(5 * 86400)))
                .isEqualTo(604800 - 3 * 86400);
        assertThat(resumed.fingerprint()).isNotEqualTo(paused.fingerprint());
    }

    @Test
    void waitEndsAtMostOnceAndKeepsTheReason() {
        var wait = TradeModels.Wait.start(T0, 604800, "s2-v1");
        var ended = wait.end(T0.plusSeconds(10), TradeVocabulary.WaitEndReason.DISPUTED);
        assertThat(ended.ended()).isTrue();
        assertThat(ended.endReason()).isEqualTo(TradeVocabulary.WaitEndReason.DISPUTED);
        assertThat(ended.activeSince()).isNull();
        assertThat(ended.accumulatedSeconds()).isEqualTo(10);
        assertThat(ended.end(T0.plusSeconds(20), TradeVocabulary.WaitEndReason.TIMEOUT)).isEqualTo(ended);
    }

    private static Trade trade(TradeStatus status, Long agreementId, int version) {
        return new Trade(1, 100, 11, 22, status, null, agreementId, version, null, null,
                T0, null, null, T0, T0);
    }
}
