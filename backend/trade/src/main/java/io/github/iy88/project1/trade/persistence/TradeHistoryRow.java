package io.github.iy88.project1.trade.persistence;

import io.github.iy88.project1.trade.domain.TradeModels;
import io.github.iy88.project1.trade.domain.TradeVocabulary.ActorKind;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;
import java.util.UUID;

@Entity
@Table(name = "trade_state_history")
class TradeHistoryRow {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    private long tradeId;
    private String action;
    private String fromStatus;
    private String toStatus;
    private String fromPhase;
    private String toPhase;
    private String actorKind;
    private Long actorId;
    private String reason;
    private String basisRef;
    private Long caseId;
    private Long agreementId;
    private Long agreementDecisionId;
    private Long confirmationId;
    private Long cancellationId;
    private Long cancellationDecisionId;
    private Long disputeId;
    private Long disputeResolutionConfirmationId;
    private UUID businessEventId;
    private Instant createdAt;

    protected TradeHistoryRow() {}

    TradeHistoryRow(TradeModels.History history) {
        tradeId = history.tradeId();
        action = history.action();
        fromStatus = history.fromStatus();
        toStatus = history.toStatus();
        fromPhase = history.fromPhase();
        toPhase = history.toPhase();
        actorKind = history.actorKind().value();
        actorId = history.actorId();
        reason = history.reason();
        basisRef = history.basisRef();
        caseId = history.caseId();
        agreementId = history.agreementId();
        agreementDecisionId = history.agreementDecisionId();
        confirmationId = history.confirmationId();
        cancellationId = history.cancellationId();
        cancellationDecisionId = history.cancellationDecisionId();
        disputeId = history.disputeId();
        disputeResolutionConfirmationId = history.disputeResolutionConfirmationId();
        businessEventId = history.businessEventId();
        createdAt = history.createdAt();
    }

    long id() {
        return id;
    }

    TradeModels.History toHistory() {
        return new TradeModels.History(id, tradeId, action, fromStatus, toStatus, fromPhase, toPhase,
                ActorKind.from(actorKind), actorId, reason, basisRef, caseId, agreementId, agreementDecisionId,
                confirmationId, cancellationId, cancellationDecisionId, disputeId, disputeResolutionConfirmationId,
                businessEventId, createdAt);
    }
}
