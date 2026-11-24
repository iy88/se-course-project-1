package io.github.iy88.project1.api.productreview;

import io.github.iy88.project1.casemanagement.application.CategoryApplicationView;
import io.github.iy88.project1.casemanagement.application.DecisionResult;
import io.github.iy88.project1.casemanagement.application.ProductReviewDetail;
import io.github.iy88.project1.casemanagement.application.ProductReviewPort;
import io.github.iy88.project1.casemanagement.application.ReviewAction;
import io.github.iy88.project1.casemanagement.application.ReviewDecision;
import io.github.iy88.project1.casemanagement.application.ReviewPlan;
import io.github.iy88.project1.casemanagement.application.SubjectPlan;
import io.github.iy88.project1.casemanagement.application.TodoItem;
import io.github.iy88.project1.casemanagement.application.TodoKinds;
import io.github.iy88.project1.casemanagement.application.TodoOwnership;
import io.github.iy88.project1.casemanagement.application.TodoPage;
import io.github.iy88.project1.casemanagement.application.TodoQuery;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.WriteTransaction;
import io.github.iy88.project1.product.application.ProductReviewSubjects;
import io.github.iy88.project1.product.persistence.ProductAudit;
import java.net.URI;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;
import org.springframework.context.annotation.Profile;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

@Component
@Profile("infrastructure")
class ProductReviewStageAdapter implements ProductReviewPort {
    private final ProductReviewSubjects subjects;
    private final JdbcClient jdbc;

    ProductReviewStageAdapter(ProductReviewSubjects subjects, JdbcClient jdbc) {
        this.subjects = subjects;
        this.jdbc = jdbc;
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
    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public TodoPage todos(TodoQuery query) {
        String source = """
                 FROM moderation_case c
                 JOIN product_audit a ON a.case_id = c.id
                 JOIN product p ON p.product_id = a.product_id
                 WHERE c.case_type = 'product_review' AND a.status = 'pending'
                   AND p.lifecycle_state = 'pending_review' AND p.deleted_at IS NULL
                """ + (query.ownership() == TodoOwnership.MINE
                ? " AND c.claimed_manager_id = :manager" : " AND c.claimed_manager_id IS NULL");
        var asOf = jdbc.sql("select transaction_timestamp()").query(OffsetDateTime.class).single().toInstant();
        long count = queueQuery("SELECT COUNT(*)" + source, query).query(Long.class).single();
        var counts = Map.of(TodoKinds.PRODUCT_REVIEW, count);
        if (!TodoKinds.PRODUCT_REVIEW.equals(query.kind()) || count == 0) {
            return new TodoPage(List.of(), 0, counts, asOf);
        }
        var rows = queueQuery("""
                SELECT c.id, c.created_at, coalesce(c.claimed_at, c.created_at) AS updated_at,
                       a.audit_id, a.product_id
                """ + source + " ORDER BY updated_at DESC, c.id DESC LIMIT :limit OFFSET :offset", query)
                .param("limit", query.pageSize())
                .param("offset", (long) (query.page() - 1) * query.pageSize())
                .query((row, index) -> new TodoItem(row.getLong("id"), TodoKinds.PRODUCT_REVIEW,
                        row.getObject("created_at", OffsetDateTime.class).toInstant(),
                        row.getObject("updated_at", OffsetDateTime.class).toInstant(),
                        row.getLong("audit_id"), row.getLong("product_id")))
                .list();
        return new TodoPage(rows, count, counts, asOf);
    }

    private JdbcClient.StatementSpec queueQuery(String sql, TodoQuery query) {
        var statement = jdbc.sql(sql);
        return query.ownership() == TodoOwnership.MINE ? statement.param("manager", query.managerId()) : statement;
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
