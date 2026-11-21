package io.github.iy88.project1.casemanagement.application;

import io.github.iy88.project1.core.WriteTransaction;

/**
 * Product-owned review capability ({@code REVIEW_CLAIMED}, {@code REVIEW_PASSED},
 * {@code REVIEW_REJECTED}). It owns audit row locks, content snapshots and seller notification.
 */
public interface ProductReviewPort {
    SubjectPlan prepare(ReviewCommand command);

    ReviewSubject claim(WriteTransaction transaction, ReviewCommand command);

    ReviewSubject decide(WriteTransaction transaction, ReviewCommand command);
}
