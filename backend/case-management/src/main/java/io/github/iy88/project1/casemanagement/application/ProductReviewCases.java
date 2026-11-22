package io.github.iy88.project1.casemanagement.application;

import io.github.iy88.project1.core.WriteTransaction;
import java.time.Instant;

/** Case-owned operations used by product submission and withdrawal. */
public interface ProductReviewCases {
    long open(WriteTransaction transaction, Instant submittedAt);

    void requireUnclaimed(WriteTransaction transaction, long caseId);
}
