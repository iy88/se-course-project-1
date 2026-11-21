package io.github.iy88.project1.trade.application;

import java.time.Instant;

/** Named application commands. HTTP DTOs are converted to these at the API boundary. */
public final class TradeCommands {
    private TradeCommands() {
    }

    public record CreatePurchaseRequest(long productId, String note, int expectedProductVersion) {
    }

    public record Versioned(long tradeId, int expectedVersion) {
    }

    public record Reject(long tradeId, String reason, int expectedVersion) {
    }

    public record ProposeAgreement(long tradeId, Instant deliveryAt, String deliveryPlaceText, String deliveryMethod,
                                   long amountCents, String paymentMethod, String paymentTiming, Long baseAgreementId,
                                   int expectedVersion) {
    }

    public record DecideAgreement(long tradeId, long agreementId, String decision, int expectedVersion) {
    }

    public record ConfirmCompletion(long tradeId, String note, int expectedVersion) {
    }

    public record ProposeCancellation(long tradeId, String reason, int expectedVersion) {
    }

    public record DecideCancellation(long tradeId, long cancellationId, String decision, int expectedVersion) {
    }

    public record OpenDispute(long tradeId, String statement, int expectedVersion) {
    }

    public record ConfirmResolution(long tradeId, long disputeId, int expectedVersion) {
    }

    public record Freeze(long caseId, long tradeId, String basisRef, String reason) {
    }

    public record LiftFreeze(long caseId, long tradeId, long freezeId, String basisRef, String reason) {
    }

    public record AdjustStatus(long caseId, long tradeId, String targetStatus, String basisRef, String reason) {
    }

    public record Restore(long caseId, long tradeId, String basisRef, String reason) {
    }

    public record ResolveDispute(long caseId, long disputeId, String basisRef, String reason) {
    }
}
