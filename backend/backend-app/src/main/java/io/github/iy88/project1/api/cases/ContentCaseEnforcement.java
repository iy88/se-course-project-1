package io.github.iy88.project1.api.cases;

import io.github.iy88.project1.casemanagement.application.CasePorts;
import io.github.iy88.project1.casemanagement.application.CaseRecords;
import io.github.iy88.project1.casemanagement.application.SubjectPlan;
import io.github.iy88.project1.casemanagement.persistence.CaseLifecycleStore;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.WriteTransaction;
import io.github.iy88.project1.product.application.ProductInteractions;
import io.github.iy88.project1.product.persistence.ProductRepository;
import io.github.iy88.project1.trade.application.TradePorts;
import io.github.iy88.project1.trade.application.TradeReviewModeration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;
import java.util.Set;

/**
 * Comment and evaluation removal for one decided case batch.
 *
 * <p>The case target is the only source of truth. A removal instruction is accepted only when its
 * target type and id exactly match the case's own target; the target is checked again after the
 * case row is locked. The caller plans and acquires the product/comment or trade locks through the
 * shared {@link SubjectPlan}, and this handler re-reads the content under those locks. The write is
 * limited to the owner module's moderation fields, so the body and author stay available only to
 * the author and the claimed manager.</p>
 */
final class ContentCaseEnforcement {
    private static final String REMOVE_CONTENT = "remove_content";
    private static final String REMOVE_EVALUATION_CONTENT = "remove_evaluation_content";
    private static final String COMMENT = "comment";
    private static final String EVALUATION = "evaluation";
    private static final Set<String> SUPPORTED = Set.of(REMOVE_CONTENT, REMOVE_EVALUATION_CONTENT);

    private final CaseLifecycleStore cases;
    private final CasePorts.Targets targets;
    private final ProductRepository products;
    private final ProductInteractions comments;
    private final TradeReviewModeration reviews;
    private final TradePorts.CaseEnforcement trades;

    ContentCaseEnforcement(CaseLifecycleStore cases, CasePorts.Targets targets, ProductRepository products,
                           ProductInteractions comments, TradeReviewModeration reviews,
                           TradePorts.CaseEnforcement trades) {
        this.cases = Objects.requireNonNull(cases);
        this.targets = Objects.requireNonNull(targets);
        this.products = Objects.requireNonNull(products);
        this.comments = Objects.requireNonNull(comments);
        this.reviews = Objects.requireNonNull(reviews);
        this.trades = Objects.requireNonNull(trades);
    }

    boolean supports(String action) {
        return SUPPORTED.contains(action);
    }

    // ------------------------------------------------------------------ read-only plans

    LockPlan plan(long caseId, List<CaseRecords.EnforcementInstruction> items) {
        return lockCallbacks(caseId, items).lockPlan();
    }

    SubjectPlan lockCallbacks(long caseId, List<CaseRecords.EnforcementInstruction> items) {
        var facts = facts(caseId);
        var subjects = SubjectPlan.empty();
        for (var item : items) {
            subjects = subjects.merge(switch (targetKind(facts, item)) {
                case COMMENT -> commentCallbacks(item.targetId());
                case EVALUATION -> evaluationCallbacks(item.targetId());
                default -> throw targetInvalid();
            });
        }
        return subjects;
    }

    private SubjectPlan commentCallbacks(long commentId) {
        var target = comments.commentTarget(commentId).orElseThrow(ContentCaseEnforcement::contentNotFound);
        var productKey = ProductInteractions.productLockKey(target.productId());
        var commentKey = ProductInteractions.commentLockKey(commentId);
        return SubjectPlan.account(target.authorAccountId(), LockPlan.AccountMode.SHARED)
                .merge(SubjectPlan.resource(productKey, transaction -> {
            products.lockById(target.productId())
                    .filter(product -> !product.deleted())
                    .orElseThrow(ContentCaseEnforcement::contentNotFound);
        })).merge(SubjectPlan.resource(commentKey, transaction -> comments.lockCommentRow(commentId)));
    }

    private SubjectPlan evaluationCallbacks(long evaluationId) {
        var target = reviews.target(evaluationId).orElseThrow(ContentCaseEnforcement::contentNotFound);
        return SubjectPlan.account(target.authorAccountId(), LockPlan.AccountMode.SHARED)
                .merge(SubjectPlan.resource(TradeReviewModeration.tradeLockKey(target.tradeId()),
                        transaction -> trades.lockTrade(transaction, target.tradeId())));
    }

    // ------------------------------------------------------------------ apply

    List<CaseRecords.EnforcementOutcome> execute(WriteTransaction transaction, long caseId, String reason,
                                                 String basisRef,
                                                 List<CaseRecords.EnforcementInstruction> items,
                                                 Instant occurredAt) {
        var facts = cases.requireLocked(transaction, caseId);
        var outcomes = new ArrayList<CaseRecords.EnforcementOutcome>();
        for (var item : items) {
            String kind = targetKind(facts, item);
            outcomes.add(switch (kind) {
                case COMMENT -> removeComment(transaction, facts, item, reason, occurredAt);
                case EVALUATION -> removeEvaluation(transaction, facts, item, reason, basisRef, occurredAt);
                default -> throw targetInvalid();
            });
        }
        return outcomes;
    }

    private CaseRecords.EnforcementOutcome removeComment(WriteTransaction transaction, CaseRecords.Facts facts,
                                                         CaseRecords.EnforcementInstruction item, String reason,
                                                         Instant occurredAt) {
        var target = comments.commentTarget(item.targetId()).orElseThrow(ContentCaseEnforcement::contentNotFound);
        requireRelatedAuthor(facts, target.authorAccountId());
        // The comment row and its product root were locked by the planned callbacks. The capability
        // re-reads the row and rejects a stale product/parent or an already removed comment.
        var removed = comments.removeCommentLocked(transaction, facts.caseId(), item.targetId(),
                target.productId(), item.enforcementId(), reason, occurredAt);
        return new CaseRecords.EnforcementOutcome(item.enforcementId(), item.action(), COMMENT, item.targetId(),
                "product_comment", item.targetId(), "applied", removed.previousState(), removed.currentState(),
                List.of(removed.authorAccountId()), occurredAt);
    }

    private CaseRecords.EnforcementOutcome removeEvaluation(WriteTransaction transaction, CaseRecords.Facts facts,
                                                            CaseRecords.EnforcementInstruction item, String reason,
                                                            String basisRef, Instant occurredAt) {
        var target = reviews.target(item.targetId()).orElseThrow(ContentCaseEnforcement::contentNotFound);
        requireRelatedAuthor(facts, target.authorAccountId());
        // The moderation capability re-reads the review under the locked trade row and keeps the body.
        var removed = reviews.removeLocked(transaction, item.targetId(), target.tradeId(), reason, basisRef,
                occurredAt);
        return new CaseRecords.EnforcementOutcome(item.enforcementId(), item.action(), EVALUATION, item.targetId(),
                "trade_review", item.targetId(), "applied", removed.previousState(), removed.currentState(),
                List.of(removed.authorAccountId()), occurredAt);
    }

    // ------------------------------------------------------------------ reverse

    List<CaseRecords.EnforcementOutcome> reverse(WriteTransaction transaction, long caseId,
                                                 CaseRecords.Enforcement recorded, String basisRef,
                                                 String reason, Instant occurredAt) {
        throw notReversible();
    }

    LockPlan reversePlan(long caseId, CaseRecords.Enforcement recorded) {
        throw notReversible();
    }

    SubjectPlan reverseLockCallbacks(long caseId, CaseRecords.Enforcement recorded) {
        throw notReversible();
    }

    // ------------------------------------------------------------------ validation

    /**
     * Resolves the exact content type from the case target and the instruction. The client cannot
     * point the action at another comment or evaluation, even one on the same product or trade.
     */
    private static String targetKind(CaseRecords.Facts facts, CaseRecords.EnforcementInstruction item) {
        requireSupported(item);
        String expected = switch (item.action()) {
            case REMOVE_CONTENT -> item.targetType();
            case REMOVE_EVALUATION_CONTENT -> EVALUATION;
            default -> throw unsupported();
        };
        if (!COMMENT.equals(expected) && !EVALUATION.equals(expected)) {
            throw targetInvalid();
        }
        if (!expected.equals(item.targetType())) {
            throw targetInvalid();
        }
        if (facts.targetId() == null || !expected.equals(facts.targetType())
                || facts.targetId() != item.targetId()) {
            throw ownershipMismatch();
        }
        return expected;
    }

    private void requireRelatedAuthor(CaseRecords.Facts facts, long authorAccountId) {
        if (!targets.relatedAccountIds(facts).contains(authorAccountId)) {
            throw ownershipMismatch();
        }
    }

    private CaseRecords.Facts facts(long caseId) {
        return cases.find(caseId).orElseThrow(() -> new BusinessError("RESOURCE_NOT_VISIBLE", 404, "事项不存在"));
    }

    private static void requireSupported(CaseRecords.EnforcementInstruction item) {
        if (item.targetId() <= 0 || !SUPPORTED.contains(item.action())) {
            throw unsupported();
        }
    }

    private static BusinessError unsupported() {
        return new BusinessError("DEPENDENCY_UNAVAILABLE", 503, "该内容处置动作尚未启用");
    }

    private static BusinessError targetInvalid() {
        return new BusinessError("TARGET_INVALID", 422, "内容处置目标类型无效");
    }

    private static BusinessError ownershipMismatch() {
        return new BusinessError("OWNERSHIP_MISMATCH", 403, "内容不属于本事项的精确目标");
    }

    private static BusinessError contentNotFound() {
        return new BusinessError("CONTENT_NOT_FOUND", 404, "内容不存在");
    }

    private static BusinessError notReversible() {
        // The approved enforcement registry has no content restoration action. Do not fake a
        // reversal or make removed content visible again.
        return new BusinessError("DEPENDENCY_UNAVAILABLE", 503, "内容移除不提供恢复");
    }
}
