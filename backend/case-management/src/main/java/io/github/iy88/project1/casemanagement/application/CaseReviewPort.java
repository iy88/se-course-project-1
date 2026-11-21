package io.github.iy88.project1.casemanagement.application;

import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.WriteTransaction;

/**
 * Case-owned review claim and projection contract supplied by the case domain. The application
 * calls the product review capability first, then this port, so the product audit keeps review
 * authority and the case keeps fixed ownership.
 */
public interface CaseReviewPort {
    SubjectPlan prepare(ReviewCommand command);

    void requireManager(ExecutionContext context, ReviewCommand command);

    void claim(WriteTransaction transaction, ReviewCommand command);

    void recordDecision(WriteTransaction transaction, ReviewCommand command, ReviewSubject subject);

    void requireReplayAccess(ExecutionContext context, long caseId);
}
