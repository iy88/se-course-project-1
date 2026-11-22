package io.github.iy88.project1.casemanagement.application;

import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.WriteTransaction;
import java.time.Instant;
import java.util.List;

/**
 * Case-owned operations used by product submission and withdrawal. Both methods run inside the
 * caller's {@link WriteTransaction}; this module never opens an independent transaction or sends
 * a notification.
 */
public interface ProductReviewCases {
    /**
     * Creates the case row for one product review. The caller creates the matching audit row in
     * the same transaction; the unique review link stays on the product audit.
     */
    long open(WriteTransaction transaction, Instant submittedAt);

    /**
     * Locks the case row and accepts the withdrawal only while no manager has claimed it.
     *
     * <p>Callers must declare {@link #lockKey(long)} in their lock plan and acquire the product
     * and audit locks before calling this method. The method locks the case in the caller's
     * transaction and throws {@code REVIEW_ALREADY_CLAIMED} when a manager already owns it.</p>
     */
    void requireUnclaimed(WriteTransaction transaction, long caseId);

    /** Stable case lock key shared by product submission, withdrawal and review use cases. */
    static LockPlan.Key lockKey(long caseId) {
        if (caseId <= 0) {
            throw new IllegalArgumentException("Invalid case id");
        }
        return new LockPlan.Key(LockPlan.Domain.CASE, List.of(caseId));
    }
}
