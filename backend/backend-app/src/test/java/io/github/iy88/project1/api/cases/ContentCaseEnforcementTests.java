package io.github.iy88.project1.api.cases;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import io.github.iy88.project1.casemanagement.application.CasePorts;
import io.github.iy88.project1.casemanagement.application.CaseRecords;
import io.github.iy88.project1.casemanagement.persistence.CaseLifecycleStore;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.WriteTransaction;
import io.github.iy88.project1.product.application.ProductInteractions;
import io.github.iy88.project1.product.domain.ProductComment;
import io.github.iy88.project1.product.persistence.Product;
import io.github.iy88.project1.product.persistence.ProductRepository;
import io.github.iy88.project1.trade.application.TradePorts;
import io.github.iy88.project1.trade.application.TradeReviewModeration;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.Set;
import org.junit.jupiter.api.Test;

/** Exact-target, lock, write and reversal rules of the production content enforcement handler. */
class ContentCaseEnforcementTests {
    private static final long CASE = 41L;
    private static final long COMMENT = 501L;
    private static final long OTHER_COMMENT = 502L;
    private static final long REVIEW = 601L;
    private static final long PRODUCT = 701L;
    private static final long TRADE = 801L;
    private static final long AUTHOR = 901L;
    private static final long REPORTER = 902L;
    private static final long MANAGER = 903L;
    private static final Instant NOW = Instant.parse("2026-12-01T00:00:00Z");

    private final CaseLifecycleStore cases = mock(CaseLifecycleStore.class);
    private final CasePorts.Targets targets = mock(CasePorts.Targets.class);
    private final ProductRepository products = mock(ProductRepository.class);
    private final ProductInteractions comments = mock(ProductInteractions.class);
    private final TradeReviewModeration reviews = mock(TradeReviewModeration.class);
    private final TradePorts.CaseEnforcement trades = mock(TradePorts.CaseEnforcement.class);
    private final ContentCaseEnforcement handler = new ContentCaseEnforcement(cases, targets, products, comments,
            reviews, trades);

    @Test
    void commentRemovalLocksTheProductRootThenTheExactCommentRow() {
        var facts = facts("comment", COMMENT);
        when(cases.find(CASE)).thenReturn(Optional.of(facts));
        when(comments.commentTarget(COMMENT)).thenReturn(Optional.of(
                new ProductInteractions.CommentTarget(COMMENT, PRODUCT, AUTHOR)));
        when(products.lockById(PRODUCT)).thenReturn(Optional.of(mock(Product.class)));
        when(comments.lockCommentRow(COMMENT)).thenReturn(comment(COMMENT));

        var plan = handler.plan(CASE, List.of(instruction("remove_content", "comment", COMMENT)));

        assertThat(plan.accounts()).containsEntry(AUTHOR, LockPlan.AccountMode.SHARED);
        assertThat(plan.resources()).containsExactlyInAnyOrder(
                ProductInteractions.productLockKey(PRODUCT),
                ProductInteractions.commentLockKey(COMMENT));
        var transaction = mock(WriteTransaction.class);
        doAnswer(invocation -> {
            ((Runnable) invocation.getArgument(1)).run();
            return null;
        }).when(transaction).lock(any(), any());
        handler.lockCallbacks(CASE, List.of(instruction("remove_content", "comment", COMMENT))).acquire(transaction);
        var locks = inOrder(products, comments);
        locks.verify(products).lockById(PRODUCT);
        locks.verify(comments).lockCommentRow(COMMENT);
        verifyNoInteractions(trades);
    }

    @Test
    void evaluationRemovalUsesTheRealTradeRowCallback() {
        var facts = facts("evaluation", REVIEW);
        when(cases.find(CASE)).thenReturn(Optional.of(facts));
        when(reviews.target(REVIEW)).thenReturn(Optional.of(
                new TradeReviewModeration.ReviewTarget(REVIEW, TRADE, AUTHOR)));

        var plan = handler.plan(CASE, List.of(instruction("remove_evaluation_content", "evaluation", REVIEW)));

        assertThat(plan.accounts()).containsEntry(AUTHOR, LockPlan.AccountMode.SHARED);
        assertThat(plan.resources()).containsExactly(TradeReviewModeration.tradeLockKey(TRADE));
        var transaction = mock(WriteTransaction.class);
        doAnswer(invocation -> {
            ((Runnable) invocation.getArgument(1)).run();
            return null;
        }).when(transaction).lock(any(), any());
        handler.lockCallbacks(CASE, List.of(instruction("remove_evaluation_content", "evaluation", REVIEW)))
                .acquire(transaction);
        verify(trades).lockTrade(transaction, TRADE);
        verifyNoInteractions(products, comments);
    }

    @Test
    void removeContentAlsoAcceptsTheEvaluationTargetKind() {
        var facts = facts("evaluation", REVIEW);
        when(cases.find(CASE)).thenReturn(Optional.of(facts));
        when(reviews.target(REVIEW)).thenReturn(Optional.of(
                new TradeReviewModeration.ReviewTarget(REVIEW, TRADE, AUTHOR)));

        var plan = handler.plan(CASE, List.of(instruction("remove_content", "evaluation", REVIEW)));

        assertThat(plan.resources()).containsExactly(TradeReviewModeration.tradeLockKey(TRADE));
    }

    @Test
    void commentExecutionWritesOnlyTheModerationFactsAndTargetsTheAuthor() {
        var facts = facts("comment", COMMENT);
        var transaction = mock(WriteTransaction.class);
        when(cases.requireLocked(transaction, CASE)).thenReturn(facts);
        when(targets.relatedAccountIds(facts)).thenReturn(Set.of(AUTHOR));
        when(comments.commentTarget(COMMENT)).thenReturn(Optional.of(
                new ProductInteractions.CommentTarget(COMMENT, PRODUCT, AUTHOR)));
        when(comments.removeCommentLocked(transaction, CASE, COMMENT, PRODUCT, "enf-1", "spam", NOW))
                .thenReturn(new ProductInteractions.RemovedComment("501", AUTHOR, "published", "removed_by_admin"));

        var outcomes = handler.execute(transaction, CASE, "spam", "case:41",
                List.of(instruction("remove_content", "comment", COMMENT)), NOW);

        assertThat(outcomes).singleElement().satisfies(outcome -> {
            assertThat(outcome.action()).isEqualTo("remove_content");
            assertThat(outcome.targetType()).isEqualTo("comment");
            assertThat(outcome.targetId()).isEqualTo(COMMENT);
            assertThat(outcome.resultType()).isEqualTo("product_comment");
            assertThat(outcome.affectedAccountIds()).containsExactly(AUTHOR);
            assertThat(outcome.currentState()).isEqualTo("removed_by_admin");
        });
        verify(comments).removeCommentLocked(transaction, CASE, COMMENT, PRODUCT, "enf-1", "spam", NOW);
        verifyNoInteractions(reviews);
    }

    @Test
    void evaluationExecutionWritesOnlyTheModerationFactsAndTargetsTheAuthor() {
        var facts = facts("evaluation", REVIEW);
        var transaction = mock(WriteTransaction.class);
        when(cases.requireLocked(transaction, CASE)).thenReturn(facts);
        when(targets.relatedAccountIds(facts)).thenReturn(Set.of(AUTHOR));
        when(reviews.target(REVIEW)).thenReturn(Optional.of(
                new TradeReviewModeration.ReviewTarget(REVIEW, TRADE, AUTHOR)));
        when(reviews.removeLocked(transaction, REVIEW, TRADE, "spam", "case:41", NOW))
                .thenReturn(new TradeReviewModeration.RemovedReview("601", AUTHOR, "published",
                        "removed_by_admin"));

        var outcomes = handler.execute(transaction, CASE, "spam", "case:41",
                List.of(instruction("remove_evaluation_content", "evaluation", REVIEW)), NOW);

        assertThat(outcomes).singleElement().satisfies(outcome -> {
            assertThat(outcome.action()).isEqualTo("remove_evaluation_content");
            assertThat(outcome.targetType()).isEqualTo("evaluation");
            assertThat(outcome.targetId()).isEqualTo(REVIEW);
            assertThat(outcome.resultType()).isEqualTo("trade_review");
            assertThat(outcome.affectedAccountIds()).containsExactly(AUTHOR);
        });
        verify(reviews).removeLocked(transaction, REVIEW, TRADE, "spam", "case:41", NOW);
        verifyNoInteractions(comments);
    }

    @Test
    void anInstructionCannotRetargetAnotherCommentOnTheSameProduct() {
        when(cases.find(CASE)).thenReturn(Optional.of(facts("comment", COMMENT)));

        assertFailure(() -> handler.plan(CASE, List.of(instruction("remove_content", "comment", OTHER_COMMENT))),
                "OWNERSHIP_MISMATCH");
        verifyNoInteractions(comments, products, reviews, trades);
    }

    @Test
    void executionRechecksTheCaseTargetAfterTheCaseLock() {
        var transaction = mock(WriteTransaction.class);
        when(cases.requireLocked(transaction, CASE)).thenReturn(facts("comment", OTHER_COMMENT));

        assertFailure(() -> handler.execute(transaction, CASE, "spam", "case:41",
                List.of(instruction("remove_content", "comment", COMMENT)), NOW), "OWNERSHIP_MISMATCH");
        verify(comments, never()).removeCommentLocked(any(), anyLong(), anyLong(), anyLong(), any(), any(),
                any());
    }

    @Test
    void missingContentFailsClosedBeforeAnyRemoval() {
        when(cases.find(CASE)).thenReturn(Optional.of(facts("comment", COMMENT)));
        when(comments.commentTarget(COMMENT)).thenReturn(Optional.empty());

        assertFailure(() -> handler.plan(CASE, List.of(instruction("remove_content", "comment", COMMENT))),
                "CONTENT_NOT_FOUND");
        verify(comments, never()).removeCommentLocked(any(), anyLong(), anyLong(), anyLong(), any(), any(),
                any());
    }

    @Test
    void anAuthorOutsideTheCaseRelatedAccountsIsRejected() {
        var facts = facts("evaluation", REVIEW);
        var transaction = mock(WriteTransaction.class);
        when(cases.requireLocked(transaction, CASE)).thenReturn(facts);
        when(reviews.target(REVIEW)).thenReturn(Optional.of(
                new TradeReviewModeration.ReviewTarget(REVIEW, TRADE, AUTHOR)));
        when(targets.relatedAccountIds(facts)).thenReturn(Set.of(REPORTER));

        assertFailure(() -> handler.execute(transaction, CASE, "spam", "case:41",
                List.of(instruction("remove_evaluation_content", "evaluation", REVIEW)), NOW), "OWNERSHIP_MISMATCH");
        verify(reviews, never()).removeLocked(any(), anyLong(), anyLong(), any(), any(), any());
    }

    @Test
    void removeContentOnlyAcceptsCommentOrEvaluationTargets() {
        when(cases.find(CASE)).thenReturn(Optional.of(facts("product", PRODUCT)));

        assertFailure(() -> handler.plan(CASE, List.of(instruction("remove_content", "product", PRODUCT))),
                "TARGET_INVALID");
        assertFailure(() -> handler.plan(CASE, List.of(instruction("remove_evaluation_content", "comment", COMMENT))),
                "TARGET_INVALID");
    }

    @Test
    void contentReversalFailsClosedWithoutAnyContentWrite() {
        var recorded = new CaseRecords.Enforcement("enf-1", CASE, "remove_content", "comment", COMMENT, "case:41",
                MANAGER, NOW, "product_comment", COMMENT, "applied", "published", "removed_by_admin",
                List.of(AUTHOR), null, null, NOW, null);

        assertFailure(() -> handler.reversePlan(CASE, recorded), "DEPENDENCY_UNAVAILABLE");
        assertFailure(() -> handler.reverseLockCallbacks(CASE, recorded), "DEPENDENCY_UNAVAILABLE");
        assertFailure(() -> handler.reverse(mock(WriteTransaction.class), CASE, recorded, "case:41", "restore",
                NOW), "DEPENDENCY_UNAVAILABLE");
        verifyNoInteractions(comments, products, reviews, trades);
    }

    @Test
    void onlyTheTwoContentRemovalActionsAreClaimed() {
        assertThat(handler.supports("remove_content")).isTrue();
        assertThat(handler.supports("remove_evaluation_content")).isTrue();
        assertThat(handler.supports("withdraw_public_access")).isFalse();
        assertThat(handler.supports("freeze_trade")).isFalse();
    }

    private void assertFailure(org.assertj.core.api.ThrowableAssert.ThrowingCallable call, String code) {
        assertThatThrownBy(call).isInstanceOfSatisfying(BusinessError.class,
                error -> assertThat(error.code()).isEqualTo(code));
    }

    private static ProductComment comment(long id) {
        return new ProductComment(id, PRODUCT, AUTHOR, null, "body", NOW, null, null, null, null);
    }

    private static CaseRecords.Facts facts(String targetType, long targetId) {
        return new CaseRecords.Facts(CASE, "report", targetType, targetId, null, null, REPORTER, "请核实",
                MANAGER, NOW, "claimed", null, null, null, null, null, null, null, null, NOW, NOW);
    }

    private static CaseRecords.EnforcementInstruction instruction(String action, String targetType, long targetId) {
        return new CaseRecords.EnforcementInstruction("enf-1", action, targetType, targetId, null);
    }
}
