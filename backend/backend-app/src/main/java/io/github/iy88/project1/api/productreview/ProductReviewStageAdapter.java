package io.github.iy88.project1.api.productreview;

import io.github.iy88.project1.casemanagement.application.CategoryApplicationView;
import io.github.iy88.project1.casemanagement.application.DecisionResult;
import io.github.iy88.project1.casemanagement.application.ProductReviewDetail;
import io.github.iy88.project1.casemanagement.application.ProductReviewPort;
import io.github.iy88.project1.casemanagement.application.ReviewAction;
import io.github.iy88.project1.casemanagement.application.ReviewDecision;
import io.github.iy88.project1.casemanagement.application.ReviewPlan;
import io.github.iy88.project1.casemanagement.application.SubjectPlan;
import io.github.iy88.project1.casemanagement.application.TodoPage;
import io.github.iy88.project1.casemanagement.application.TodoQuery;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.WriteTransaction;
import io.github.iy88.project1.product.application.ProductReviewSubjects;
import io.github.iy88.project1.product.persistence.ProductAudit;
import java.net.URI;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

@Component
@Profile("infrastructure")
class ProductReviewStageAdapter implements ProductReviewPort {
    private final ProductReviewSubjects subjects;
    private final ManagementTodoReadModel workbench;

    ProductReviewStageAdapter(ProductReviewSubjects subjects, ManagementTodoReadModel workbench) {
        this.subjects = subjects;
        this.workbench = workbench;
    }

    @Override
    public SubjectPlan prepareClaim(long caseId) {
        return plan(subjects.auditByCase(caseId));
    }

    @Override
    public ReviewPlan prepareDecision(long auditId) {
        var audit = subjects.audit(auditId);
        return new ReviewPlan(plan(audit), audit.caseId());
    }

    @Override
    public long requirePendingForClaim(long caseId) {
        var audit = subjects.auditByCase(caseId);
        subjects.requirePending(audit);
        return audit.id();
    }

    @Override
    public long caseIdForAudit(long auditId) {
        return subjects.audit(auditId).caseId();
    }

    @Override
    public DecisionResult decide(WriteTransaction transaction, ReviewDecision request) {
        var input = request.input();
        Boolean approveCategory = input.categoryAction() == null
                ? null : input.categoryAction() == ReviewAction.APPROVE;
        var result = subjects.decide(input.auditId(), Long.parseLong(transaction.context().actorId()),
                input.action() == ReviewAction.APPROVE, input.reason(), input.bannedItemIds(),
                approveCategory, input.categoryReason(), request.occurredAt());
        var audit = result.audit();
        var product = result.product();
        return new DecisionResult(audit.id(), audit.caseId(), product.id(), product.sellerAccountId(),
                audit.status(), product.lifecycleState(), product.contentVersion(), result.reviewedContentVersion(),
                categoryApplication(result.application()), audit.decidedAt(),
                "rejected".equals(audit.status()) ? audit.decisionReason() : null);
    }

    @Override
    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public ProductReviewDetail detail(ExecutionContext context, long auditId) {
        var detail = subjects.detail(auditId);
        var product = detail.product();
        var audit = detail.audit();
        var seller = new ProductReviewDetail.Seller(Long.parseLong(product.seller().id()),
                product.seller().displayName());
        var images = product.images().stream()
                .map(image -> new ProductReviewDetail.Image(Long.parseLong(image.fileId()), URI.create(image.url()),
                        image.expiresAt()))
                .toList();
        var categories = product.categories().stream()
                .map(category -> new ProductReviewDetail.Category(Long.parseLong(category.id()), category.name()))
                .toList();
        var content = new ProductReviewDetail.CurrentContent(product.title(), product.description(), images,
                product.priceCents(), categories, product.contentVersion());
        var banned = detail.bannedScope().groups().stream().flatMap(group -> group.items().stream()
                .map(item -> new ProductReviewDetail.BannedItem(Long.parseLong(item.id()), group.group(),
                        item.content()))).toList();
        var result = audit.reviewedContentVersion() == null || audit.decidedByAdminId() == null
                ? null : new ProductReviewDetail.ReviewResult("passed".equals(audit.status()) ? "approved" : "rejected",
                        audit.decisionReason(), audit.reviewedContentVersion(), audit.decidedAt(), audit.decidedByAdminId());
        return new ProductReviewDetail(auditId, audit.productId(), audit.caseId(), audit.status(), audit.submittedAt(),
                seller, content, categoryApplication(detail.application()), banned, result);
    }

    @Override
    public TodoPage todos(TodoQuery query) {
        return workbench.page(query);
    }

    private SubjectPlan plan(ProductAudit audit) {
        var plan = SubjectPlan.empty();
        for (var key : subjects.lockKeys(audit)) {
            var sharedKey = key.domain() == LockPlan.Domain.PRODUCT_DETAIL
                    ? new LockPlan.Key(LockPlan.Domain.PRODUCT_AUDIT, key.parts()) : key;
            plan = plan.merge(SubjectPlan.resource(sharedKey, transaction -> subjects.lock(key)));
        }
        return plan;
    }

    private static CategoryApplicationView categoryApplication(ProductReviewSubjects.Application application) {
        return application == null ? null
                : new CategoryApplicationView(Long.parseLong(application.id()), application.proposedName(), application.status());
    }
}
