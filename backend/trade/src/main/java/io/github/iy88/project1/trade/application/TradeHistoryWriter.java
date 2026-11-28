package io.github.iy88.project1.trade.application;

import io.github.iy88.project1.core.WriteTransaction;
import io.github.iy88.project1.trade.domain.Trade;
import io.github.iy88.project1.trade.domain.TradeModels;
import io.github.iy88.project1.trade.domain.TradePhase;
import io.github.iy88.project1.trade.domain.TradeVocabulary.ActorKind;
import io.github.iy88.project1.trade.persistence.TradeRepository;
import java.time.Instant;
import java.util.UUID;

/**
 * Writes trade history rows. Callers invoke it synchronously inside the owning WriteTransaction so
 * history stays part of the same commit as the state change it records.
 */
final class TradeHistoryWriter {
    private final TradeRepository repository;

    TradeHistoryWriter(TradeRepository repository) {
        this.repository = repository;
    }

    long history(WriteTransaction transaction, Trade before, Trade after, String action, ActorKind actorKind,
                 Long actorId, String reason, String basisRef, Long caseId, UUID eventId, Instant now) {
        return history(transaction, before, after, action, actorKind, actorId, reason, basisRef, caseId,
                null, null, null, null, null, null, null, eventId, now);
    }

    long historyAgreement(WriteTransaction transaction, Trade before, Trade after, String action,
                          ActorKind actorKind, Long actorId, String reason, String basisRef, Long caseId,
                          Long agreementId, Long agreementDecisionId, UUID eventId, Instant now) {
        return history(transaction, before, after, action, actorKind, actorId, reason, basisRef, caseId,
                agreementId, agreementDecisionId, null, null, null, null, null, eventId, now);
    }

    long historyConfirmation(WriteTransaction transaction, Trade before, Trade after, String action,
                             ActorKind actorKind, Long actorId, String reason, String basisRef, Long caseId,
                             Long agreementId, Long confirmationId, UUID eventId, Instant now) {
        return history(transaction, before, after, action, actorKind, actorId, reason, basisRef, caseId,
                agreementId, null, confirmationId, null, null, null, null, eventId, now);
    }

    long historyCancellation(WriteTransaction transaction, Trade before, Trade after, String action,
                             ActorKind actorKind, Long actorId, String reason, String basisRef, Long caseId,
                             Long cancellationId, Long cancellationDecisionId, UUID eventId, Instant now) {
        return history(transaction, before, after, action, actorKind, actorId, reason, basisRef, caseId,
                null, null, null, cancellationId, cancellationDecisionId, null, null, eventId, now);
    }

    long historyDispute(WriteTransaction transaction, Trade before, Trade after, String action,
                        ActorKind actorKind, Long actorId, String reason, String basisRef, Long caseId,
                        Long disputeId, Long resolutionConfirmationId, UUID eventId, Instant now) {
        return history(transaction, before, after, action, actorKind, actorId, reason, basisRef, caseId,
                null, null, null, null, null, disputeId, resolutionConfirmationId, eventId, now);
    }

    long historyDisputeAgreement(WriteTransaction transaction, Trade before, Trade after, String action,
                                 ActorKind actorKind, Long actorId, String reason, String basisRef,
                                 Long caseId, Long agreementId, Long disputeId, UUID eventId, Instant now) {
        return history(transaction, before, after, action, actorKind, actorId, reason, basisRef, caseId,
                agreementId, null, null, null, null, disputeId, null, eventId, now);
    }

    long history(WriteTransaction transaction, Trade before, Trade after, String action, ActorKind actorKind,
                 Long actorId, String reason, String basisRef, Long caseId, Long agreementId,
                 Long agreementDecisionId, Long confirmationId, Long cancellationId,
                 Long cancellationDecisionId, Long disputeId, Long resolutionConfirmationId, UUID eventId,
                 Instant now) {
        String fromStatus = before.status() == after.status() ? null : before.status().value();
        String toStatus = before.status() == after.status() ? null : after.status().value();
        var beforePhase = before.phase();
        var afterPhase = after.phase();
        String fromPhase = beforePhase == afterPhase ? null : phase(beforePhase);
        String toPhase = beforePhase == afterPhase ? null : phase(afterPhase);
        return repository.insertHistory(new TradeModels.History(0, before.id(), action, fromStatus, toStatus,
                fromPhase, toPhase, actorKind, actorId, reason, basisRef, caseId, null, null, null, agreementId,
                agreementDecisionId, confirmationId, cancellationId, cancellationDecisionId, disputeId,
                resolutionConfirmationId, eventId, now));
    }

    /**
     * Records a freeze transition with its exact freeze association and a status snapshot. The
     * snapshot is only exposed through the case-subject result; the public history projection keeps
     * suppressing unchanged from/to values.
     */
    long historyFreeze(WriteTransaction transaction, Trade trade, String action, ActorKind actorKind,
                       Long actorId, String reason, String basisRef, Long caseId, long freezeId,
                       boolean frozenBefore, boolean frozenAfter, UUID eventId, Instant now) {
        String status = trade.status().value();
        String tradePhase = phase(trade.phase());
        return repository.insertHistory(new TradeModels.History(0, trade.id(), action, status, status,
                tradePhase, tradePhase, actorKind, actorId, reason, basisRef, caseId, freezeId, frozenBefore,
                frozenAfter, null, null, null, null, null, null, null, eventId, now));
    }

    static String phase(TradePhase phase) {
        return phase == null ? null : phase.value();
    }
}
