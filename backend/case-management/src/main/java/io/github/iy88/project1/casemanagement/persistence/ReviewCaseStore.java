package io.github.iy88.project1.casemanagement.persistence;

import io.github.iy88.project1.casemanagement.application.ManagementCaseChange;
import org.springframework.context.ApplicationEventPublisher;
import io.github.iy88.project1.casemanagement.application.CaseClaim;
import io.github.iy88.project1.casemanagement.application.ProductReviewCases;
import io.github.iy88.project1.casemanagement.application.SubjectPlan;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.WriteTransaction;
import java.time.Instant;
import org.springframework.context.annotation.Profile;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionSynchronizationManager;

/**
 * Case-owned persistence for product review. Ordinary facts are JPA entities; the case row lock
 * uses the caller's transaction so it composes with the shared lock plan.
 */
@Service
@Profile("infrastructure")
public class ReviewCaseStore implements ProductReviewCases {
    private static final String PRODUCT_REVIEW = "product_review";

    private final ModerationCaseRepository cases;
    private final ModerationCaseActionRepository actions;
    private final JdbcClient jdbc;
    private final ApplicationEventPublisher events;

    public ReviewCaseStore(ModerationCaseRepository cases, ModerationCaseActionRepository actions, JdbcClient jdbc, ApplicationEventPublisher events) {
        this.cases = cases;
        this.actions = actions;
        this.jdbc = jdbc;
        this.events = events;
    }

    @Override
    public long open(WriteTransaction transaction, Instant submittedAt) {
        return open(submittedAt);
    }

    public long open(Instant submittedAt) {
        requireWriteTransaction();
        long id = cases.save(new ModerationCase(PRODUCT_REVIEW, submittedAt)).id();
        events.publishEvent(ManagementCaseChange.opened(id, submittedAt));
        return id;
    }

    @Override
    public void requireUnclaimed(WriteTransaction transaction, long caseId) {
        transaction.lock(ProductReviewCases.lockKey(caseId), () -> lockRow(caseId));
        checkUnclaimed(caseId);
    }

    /** Used by product withdrawal after it locks the product and the pending audit. */
    public void requireUnclaimed(long caseId) {
        requireWriteTransaction();
        lockRow(caseId);
        checkUnclaimed(caseId);
    }

    private void checkUnclaimed(long caseId) {
        var current = require(caseId);
        if (current.claimed()) {
            throw new BusinessError("REVIEW_ALREADY_CLAIMED", 409, "审核已被认领");
        }
    }

    /** Case lock candidate; the callback runs inside the ordered shared lock plan. */
    public SubjectPlan plan(long caseId) {
        return SubjectPlan.resource(ProductReviewCases.lockKey(caseId), transaction -> lockRow(caseId));
    }

    /** Read-only claim projection for detail and replay authorization. */
    public CaseClaim read(long caseId) {
        return require(caseId);
    }

    public void claim(long caseId, long managerId, Instant claimedAt) {
        var current = requireEntity(caseId);
        current.claim(managerId, claimedAt);
        actions.save(ModerationCaseAction.claim(caseId, managerId, claimedAt));
        events.publishEvent(new ManagementCaseChange(caseId, "claim", "review:claim", claimedAt));
    }

    public void recordDecision(long caseId, long managerId, Instant decidedAt) {
        actions.save(ModerationCaseAction.decision(caseId, managerId, decidedAt));
        events.publishEvent(new ManagementCaseChange(caseId, "decide", "review:decide", decidedAt));
    }

    /**
     * Replay authorization: the case must still exist and be fixed to the current manager. The
     * review's decided state is deliberately not checked so a same-key replay stays readable.
     */
    public void requireClaimedBy(ExecutionContext context, long caseId) {
        var current = require(caseId);
        if (!current.claimedBy(Long.parseLong(context.actorId()))) {
            throw new BusinessError("RESOURCE_NOT_VISIBLE", 404, "审核不可见");
        }
    }

    private CaseClaim require(long caseId) {
        return requireEntity(caseId).snapshot();
    }

    private ModerationCase requireEntity(long caseId) {
        return cases.findById(caseId)
                .filter(item -> PRODUCT_REVIEW.equals(item.snapshot().caseType()))
                .orElseThrow(() -> new BusinessError("RESOURCE_NOT_VISIBLE", 404, "事项不可见"));
    }

    private static void requireWriteTransaction() {
        if (!TransactionSynchronizationManager.isActualTransactionActive()
                || TransactionSynchronizationManager.isCurrentTransactionReadOnly()) {
            throw new IllegalStateException("Product review case changes require a write transaction");
        }
    }

    private void lockRow(long caseId) {
        var found = jdbc.sql("SELECT 1 FROM moderation_case WHERE id = ? FOR UPDATE")
                .param(caseId).query(Integer.class).optional();
        if (found.isEmpty()) {
            throw new BusinessError("RESOURCE_NOT_VISIBLE", 404, "事项不可见");
        }
    }
}
