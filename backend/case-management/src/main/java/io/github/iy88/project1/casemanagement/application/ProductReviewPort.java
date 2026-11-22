package io.github.iy88.project1.casemanagement.application;

import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.WriteTransaction;

/**
 * Product-owned review capability. The adapter owns the audit, latest content, category and
 * public-visibility rules; the case module only orchestrates claim ownership and the shared
 * transaction.
 */
public interface ProductReviewPort {
    /** Read-only lock candidates for claiming the review linked to a case. */
    SubjectPlan prepareClaim(long caseId);

    /** Read-only lock candidates for a decision identified by audit id. */
    ReviewPlan prepareDecision(long auditId);

    /** Returns the audit id after checking the audit is pending under the caller's row locks. */
    long requirePendingForClaim(long caseId);

    /** Applies the product, audit and category decision after the case ownership check. */
    DecisionResult decide(WriteTransaction transaction, ReviewDecision decision);

    /** Returns the case id from the immutable, unique product audit link. */
    long caseIdForAudit(long auditId);

    /** Reads current content, signing referenced images after the caller has checked the claim. */
    ProductReviewDetail detail(ExecutionContext context, long auditId);

    /** Database-side queue projection joined with the case claim columns. */
    TodoPage todos(TodoQuery query);
}
