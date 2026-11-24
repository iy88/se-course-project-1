package io.github.iy88.project1.product.application;

import java.time.Instant;

/**
 * Port implemented by the composition layer for the shared product-review case.
 *
 * <p>Product keeps the review audit row and remains the owner of review state. The integration
 * implementation opens the real R2b case inside the same product transaction and reports whether
 * the case is still unclaimed before a seller withdrawal is applied.
 */
public interface ProductReviewCaseLifecycle {
    long open(Instant submittedAt);

    void requireUnclaimed(long caseId);
}
