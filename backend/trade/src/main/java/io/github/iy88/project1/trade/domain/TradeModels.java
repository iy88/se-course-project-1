package io.github.iy88.project1.trade.domain;

import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

/** Immutable trade facts shared by the domain, application and persistence layers. */
public final class TradeModels {
    private TradeModels() {
    }

    public record Snapshot(long tradeId, long productId, String title, String description, long priceCents,
                           List<String> categoryNames, List<Long> imageFileIds, Instant capturedAt) {
        public Snapshot {
            categoryNames = List.copyOf(categoryNames);
            imageFileIds = List.copyOf(imageFileIds);
        }
    }

    public record Agreement(long id, long tradeId, Long baseAgreementId, int versionNo,
                            TradeVocabulary.AgreementStatus status, long proposedBy, Instant deliveryAt,
                            String deliveryPlaceText, String deliveryMethod, long amountCents,
                            String paymentMethod, String paymentTiming, Instant proposedAt, UUID businessEventId) {
    }

    public record Decision(long id, long agreementId, TradeVocabulary.Decision decision, long actorId,
                           Instant decidedAt, UUID businessEventId) {
    }

    public record Cancellation(long id, long tradeId, long proposedBy, TradeVocabulary.CancellationMode mode,
                               String reason, TradeVocabulary.CancellationStatus status, Instant proposedAt,
                               UUID businessEventId) {
    }

    public record CancellationDecision(long id, long cancellationId, TradeVocabulary.Decision decision,
                                       long actorId, Instant decidedAt, UUID businessEventId) {
    }

    public record Dispute(long id, long tradeId, long initiatorId, String statement,
                          TradeVocabulary.DisputeStatus status, TradeVocabulary.ResolutionMode resolutionMode,
                          Long resolvedBy, Long caseId, Instant openedAt, Instant resolvedAt) {
        public boolean open() { return status == TradeVocabulary.DisputeStatus.OPEN; }
    }

    public record ResolutionConfirmation(long id, long disputeId, long confirmerId, Instant confirmedAt,
                                         UUID businessEventId) {
    }

    public record Confirmation(long id, long tradeId, long agreementId, long confirmerId, String note,
                               Instant submittedAt, Instant invalidatedAt,
                               TradeVocabulary.InvalidationReason invalidationReason, UUID businessEventId) {
        public boolean current() { return invalidatedAt == null; }
    }

    public record Wait(long tradeId, Instant startedAt, Instant activeSince, int accumulatedSeconds,
                       int waitSeconds, String policyVersion, Instant endedAt,
                       TradeVocabulary.WaitEndReason endReason) {
        public static Wait start(Instant now, int waitSeconds, String policyVersion) {
            return new Wait(0, now, now, 0, waitSeconds, policyVersion, null, null);
        }

        public boolean active() { return endedAt == null && activeSince != null; }

        public boolean paused() { return endedAt == null && activeSince == null; }

        public boolean ended() { return endedAt != null; }

        public long elapsedSeconds(Instant now) {
            long running = activeSince == null ? 0 : Math.max(0, Duration.between(activeSince, now).getSeconds());
            return accumulatedSeconds + running;
        }

        public long remainingSeconds(Instant now) {
            return Math.max(0, waitSeconds - elapsedSeconds(now));
        }

        public Instant deadline(Instant now) { return now.plusSeconds(remainingSeconds(now)); }

        public Wait pause(Instant now) {
            if (!active()) {
                return this;
            }
            int accumulated = accumulatedSeconds
                    + (int) Math.max(0, Duration.between(activeSince, now).getSeconds());
            return new Wait(tradeId, startedAt, null, accumulated, waitSeconds, policyVersion, endedAt, endReason);
        }

        public Wait resume(Instant now) {
            if (endedAt != null || activeSince != null) {
                return this;
            }
            return new Wait(tradeId, startedAt, now, accumulatedSeconds, waitSeconds, policyVersion, null, null);
        }

        public Wait end(Instant now, TradeVocabulary.WaitEndReason reason) {
            if (endedAt != null) {
                return this;
            }
            var paused = activeSince == null ? this : pause(now);
            return new Wait(tradeId, startedAt, null, paused.accumulatedSeconds, waitSeconds, policyVersion, now, reason);
        }

        /** Identifies the running interval so obsolete timeout tasks can be recognised. */
        public String fingerprint() {
            return startedAt.toEpochMilli() + ":" + waitSeconds + ":"
                    + (activeSince == null ? "paused" : activeSince.toEpochMilli());
        }
    }

    public record Freeze(long id, long tradeId, TradeVocabulary.FreezeSource source, Long sourceRef, String reason,
                         Instant startedAt, Instant endedAt, Long endedBy) {
        public boolean active() { return endedAt == null; }
    }

    public record History(long id, long tradeId, String action, String fromStatus, String toStatus,
                          String fromPhase, String toPhase, TradeVocabulary.ActorKind actorKind, Long actorId,
                          String reason, String basisRef, Long caseId, Long agreementId, Long agreementDecisionId,
                          Long confirmationId, Long cancellationId, Long cancellationDecisionId, Long disputeId,
                          Long disputeResolutionConfirmationId, UUID businessEventId, Instant createdAt) {
    }

    public record ConversationAccess(long buyerId, long sellerId, TradeStatus status) {
        public boolean contains(long accountId) { return buyerId == accountId || sellerId == accountId; }
    }

    public record ReviewEligibility(long tradeId, long reviewerId, long revieweeId, boolean eligible, String reason) {
    }
}
