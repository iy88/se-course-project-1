package io.github.iy88.project1.trade.application;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.WriteTransaction;
import io.github.iy88.project1.trade.persistence.TradeRepository;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Service;

/**
 * Trade-owned moderation of completed-trade reviews used by the case enforcement path.
 *
 * <p>The caller authorizes the claimed case, plans the trade key and acquires the trade row. This
 * capability re-reads the review under that lock, hides it and records the moderation facts; it
 * leaves the body, rating, author and case notifications to their owners. A removed review is not
 * made visible again here.</p>
 */
@Service
@Profile("infrastructure & !dependency-probe & !file-probe")
public class TradeReviewModeration {
    public static final String PUBLISHED = "published";
    public static final String HIDDEN = "hidden";
    public static final String REMOVED_BY_ADMIN = "removed_by_admin";

    /** Trade and author of a review, resolved before the caller plans its locks. */
    public record ReviewTarget(long reviewId, long tradeId, long authorAccountId) {
    }

    /** Exact review content for the claimed manager's case target. */
    public record ReviewSnapshot(long reviewId, long tradeId, long authorAccountId, String body, int rating,
                                 String state, Instant createdAt, Instant removedAt) {
    }

    /** A removed review with the retained author and named before/after states. */
    public record RemovedReview(String reviewId, long authorAccountId, String previousState,
                                String currentState) {
        public RemovedReview(String reviewId, long authorAccountId, String status) {
            this(reviewId, authorAccountId, null, status);
        }

        public String resultId() {
            return reviewId;
        }

        public String status() {
            return currentState;
        }
    }

    private final TradeRepository reviews;

    public TradeReviewModeration(TradeRepository reviews) {
        this.reviews = reviews;
    }

    /** Read-only target lookup for the enforcement prepare phase. */
    public Optional<ReviewTarget> target(long reviewId) {
        return reviews.reviewModerationFact(reviewId)
                .map(fact -> new ReviewTarget(fact.reviewId(), fact.tradeId(), fact.authorAccountId()));
    }

    /** Descriptive alias for {@link #target(long)}. */
    public Optional<ReviewTarget> reviewTarget(long reviewId) {
        return target(reviewId);
    }

    /**
     * Read-only snapshot for a caller that has already authorized the exact case target. The body
     * is retained after moderation so the claimed manager can review it without widening trade
     * conversation access.
     */
    public Optional<ReviewSnapshot> snapshot(long reviewId) {
        return reviews.reviewSnapshot(reviewId)
                .map(fact -> new ReviewSnapshot(fact.reviewId(), fact.tradeId(), fact.authorAccountId(),
                        fact.body(), fact.rating(), fact.state(), fact.createdAt(), fact.removedAt()));
    }

    /**
     * Removes one review under the already locked trade row. The caller owns case authorization and
     * notifications; this method writes only the visibility and moderation history fields.
     */
    public RemovedReview removeLocked(WriteTransaction transaction, long reviewId, long tradeId,
                                      String reason, String basisRef, Instant at) {
        transaction.requireLocked(tradeLockKey(tradeId));
        if (at == null) {
            throw new BusinessError("INPUT_INVALID", 422, "移除时间无效");
        }
        String text = requiredReason(reason);
        String basis = requiredBasis(basisRef);
        var fact = reviews.reviewModerationFact(reviewId)
                .orElseThrow(() -> new BusinessError("CONTENT_NOT_FOUND", 404, "评价不存在"));
        if (fact.tradeId() != tradeId) {
            throw new BusinessError("TARGET_STATE_CONFLICT", 409, "评价不属于该交易");
        }
        if (fact.removedAt() != null) {
            throw new BusinessError("TARGET_STATE_CONFLICT", 409, "评价已被移除");
        }
        if (transaction.context().actorKind() != ExecutionContext.ActorKind.ACCOUNT) {
            throw new BusinessError("ACTION_NOT_ALLOWED", 403, "当前执行者不能移除评价");
        }
        long managerId = Long.parseLong(transaction.context().actorId());
        if (!reviews.markReviewRemoved(reviewId, tradeId, managerId, text, basis, at)) {
            throw new BusinessError("TARGET_STATE_CONFLICT", 409, "评价已被移除");
        }
        return new RemovedReview(Long.toString(reviewId), fact.authorAccountId(),
                fact.visible() ? PUBLISHED : HIDDEN, REMOVED_BY_ADMIN);
    }

    /** Shared key for the trade row that serializes review moderation and submission. */
    public static LockPlan.Key tradeLockKey(long tradeId) {
        return new LockPlan.Key(LockPlan.Domain.TRADE, List.of(tradeId));
    }

    private static String requiredReason(String value) {
        String reason = value == null ? "" : value.trim();
        if (reason.isEmpty() || reason.codePointCount(0, reason.length()) > 1000) {
            throw new BusinessError("INPUT_INVALID", 422, "移除原因无效");
        }
        return reason;
    }

    private static String requiredBasis(String value) {
        String basis = value == null ? "" : value.trim();
        if (basis.isEmpty() || basis.codePointCount(0, basis.length()) > 500) {
            throw new BusinessError("INPUT_INVALID", 422, "移除依据无效");
        }
        return basis;
    }
}
