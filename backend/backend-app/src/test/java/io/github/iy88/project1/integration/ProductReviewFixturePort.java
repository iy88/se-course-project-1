package io.github.iy88.project1.integration;

import io.github.iy88.project1.api.productreview.ReviewActorAccess;
import io.github.iy88.project1.casemanagement.application.CategoryApplicationView;
import io.github.iy88.project1.casemanagement.application.DecisionResult;
import io.github.iy88.project1.casemanagement.application.ProductReviewDetail;
import io.github.iy88.project1.casemanagement.application.ProductReviewPort;
import io.github.iy88.project1.casemanagement.application.ReviewCaseSchema;
import io.github.iy88.project1.casemanagement.application.ReviewDecision;
import io.github.iy88.project1.casemanagement.application.ReviewManagerAccess;
import io.github.iy88.project1.casemanagement.application.ReviewPlan;
import io.github.iy88.project1.casemanagement.application.SubjectPlan;
import io.github.iy88.project1.casemanagement.application.TodoItem;
import io.github.iy88.project1.casemanagement.application.TodoKinds;
import io.github.iy88.project1.casemanagement.application.TodoOwnership;
import io.github.iy88.project1.casemanagement.application.TodoPage;
import io.github.iy88.project1.casemanagement.application.TodoQuery;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.WriteTransaction;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import java.util.concurrent.CopyOnWriteArrayList;
import org.springframework.jdbc.core.simple.JdbcClient;

/**
 * Test-only product, category and account adapter. The case module, its Flyway migration, the
 * shared write executor and the notification adapter are real; these fixture tables stand in for
 * the product and account modules until their production adapters are merged.
 */
class ProductReviewFixturePort implements ProductReviewPort, ReviewManagerAccess, ReviewActorAccess {
    private final JdbcClient db;
    private final LockTrace trace;

    ProductReviewFixturePort(JdbcClient db, LockTrace trace) {
        this.db = db;
        this.trace = trace;
    }

    @Override
    public SubjectPlan prepareClaim(long caseId) {
        return plan(auditByCase(caseId));
    }

    @Override
    public ReviewPlan prepareDecision(long auditId) {
        var audit = auditById(auditId);
        return new ReviewPlan(plan(audit), audit.caseId());
    }

    @Override
    public long requirePendingForClaim(long caseId) {
        var audit = auditByCase(caseId);
        if (!"pending".equals(audit.status())) {
            throw new BusinessError("REVIEW_NOT_PENDING", 409, "审核已结束");
        }
        return audit.auditId();
    }

    @Override
    public long caseIdForAudit(long auditId) {
        return auditById(auditId).caseId();
    }

    @Override
    public DecisionResult decide(WriteTransaction transaction, ReviewDecision decision) {
        var input = decision.input();
        var audit = auditById(input.auditId());
        if (!"pending".equals(audit.status())) {
            throw new BusinessError("REVIEW_NOT_PENDING", 409, "审核已结束");
        }
        var product = product(audit.productId());
        validateBannedItems(input.bannedItemIds());
        var application = applyCategoryApplication(input.categoryAction(), input.categoryReason(), audit);
        if (input.action() == io.github.iy88.project1.casemanagement.application.ReviewAction.APPROVE) {
            requireSelectableCategories(audit.productId());
        }
        boolean approved = input.action() == io.github.iy88.project1.casemanagement.application.ReviewAction.APPROVE;
        String status = approved ? "passed" : "rejected";
        String decisionValue = approved ? "approved" : "rejected";
        String lifecycle = approved ? "public" : "review_rejected";
        db.sql("""
                UPDATE review_audit_fixture
                SET status = ?, reviewed_content_version = ?, decision = ?, reason = ?, decided_at = ?, decided_by = ?
                WHERE audit_id = ?
                """).param(status).param(product.contentVersion()).param(decisionValue)
                .param(input.reason()).param(java.sql.Timestamp.from(decision.occurredAt()))
                .param(Long.parseLong(transaction.context().actorId())).param(audit.auditId()).update();
        db.sql("UPDATE review_product_fixture SET lifecycle_state = ? WHERE product_id = ?")
                .param(lifecycle).param(audit.productId()).update();
        return new DecisionResult(audit.auditId(), audit.caseId(), audit.productId(), product.sellerId(),
                status, lifecycle, product(audit.productId()).contentVersion(), product.contentVersion(),
                application, decision.occurredAt(),
                approved ? null : input.reason());
    }

    @Override
    public ProductReviewDetail detail(ExecutionContext context, long auditId) {
        var audit = auditById(auditId);
        var product = product(audit.productId());
        var seller = db.sql("SELECT display_name FROM review_seller_fixture WHERE account_id = ?")
                .param(product.sellerId()).query(String.class).single();
        var reviewResult = audit.decision() == null || audit.reviewedContentVersion() == null
                ? null
                : new ProductReviewDetail.ReviewResult(audit.decision(), audit.reason(), audit.reviewedContentVersion(),
                        audit.decidedAt(), audit.decidedBy());
        return new ProductReviewDetail(audit.auditId(), audit.productId(), audit.caseId(), audit.status(),
                audit.submittedAt(), new ProductReviewDetail.Seller(product.sellerId(), seller),
                new ProductReviewDetail.CurrentContent(product.title(), product.description(), images(product.productId()),
                        product.priceCents(), detailCategories(product.productId()), product.contentVersion()),
                categoryApplication(audit.auditId()).orElse(null), bannedItems(), reviewResult);
    }

    @Override
    public TodoPage todos(TodoQuery query) {
        var ownershipClause = query.ownership() == TodoOwnership.UNCLAIMED
                ? " AND c." + ReviewCaseSchema.CASE_CLAIMED_MANAGER_ID + " IS NULL"
                : " AND c." + ReviewCaseSchema.CASE_CLAIMED_MANAGER_ID + " = :manager";
        var from = " FROM " + ReviewCaseSchema.CASE_TABLE + " c JOIN review_audit_fixture a ON a.case_id = c."
                + ReviewCaseSchema.CASE_ID
                + " WHERE c." + ReviewCaseSchema.CASE_TYPE + " = 'product_review' AND a.status = 'pending'"
                + ownershipClause;
        var asOf = db.sql("SELECT statement_timestamp()").query(java.sql.Timestamp.class).single().toInstant();
        long productCount = count(from, query);
        if (!TodoKinds.PRODUCT_REVIEW.equals(query.kind())) {
            return new TodoPage(List.of(), 0, Map.of(TodoKinds.PRODUCT_REVIEW, productCount), asOf);
        }
        var sql = "SELECT c." + ReviewCaseSchema.CASE_ID + " AS case_id, c."
                + ReviewCaseSchema.CASE_CREATED_AT + " AS created_at, coalesce(c."
                + ReviewCaseSchema.CASE_CLAIMED_AT + ", c." + ReviewCaseSchema.CASE_CREATED_AT
                + ") AS updated_at, a.audit_id, a.product_id" + from
                + " ORDER BY updated_at DESC, c." + ReviewCaseSchema.CASE_ID + " DESC LIMIT :limit OFFSET :offset";
        var statement = db.sql(sql);
        if (query.ownership() == TodoOwnership.MINE) {
            statement = statement.param("manager", query.managerId());
        }
        var items = statement.param("limit", query.pageSize())
                .param("offset", (long) (query.page() - 1) * query.pageSize())
                .query((row, index) -> new TodoItem(row.getLong("case_id"), TodoKinds.PRODUCT_REVIEW,
                        row.getTimestamp("created_at").toInstant(), row.getTimestamp("updated_at").toInstant(),
                        row.getLong("audit_id"), row.getLong("product_id")))
                .list();
        return new TodoPage(items, productCount, Map.of(TodoKinds.PRODUCT_REVIEW, productCount), asOf);
    }

    @Override
    public void requireManager(ExecutionContext context, String forbiddenCode, int forbiddenStatus) {
        if (!manager(Long.parseLong(context.actorId()))) {
            throw new BusinessError(forbiddenCode, forbiddenStatus, "无管理权限");
        }
    }

    @Override
    public void requireManagerForWrite(ExecutionContext context, String forbiddenCode, int forbiddenStatus) {
        requireManager(context, forbiddenCode, forbiddenStatus);
        var account = db.sql("SELECT account_id FROM review_session_fixture WHERE session_id = ? FOR SHARE")
                .param(context.sessionId()).query(Long.class).optional();
        if (account.isEmpty() || account.get() != Long.parseLong(context.actorId())) {
            throw new BusinessError("AUTHENTICATION_REQUIRED", 401, "身份已失效");
        }
    }

    @Override
    public Actor current(HttpServletRequest request) {
        var cookies = request.getCookies();
        if (cookies == null) {
            throw new BusinessError("AUTHENTICATION_REQUIRED", 401, "身份已失效");
        }
        for (Cookie cookie : cookies) {
            if ("it_session".equals(cookie.getName())) {
                UUID sessionId;
                try {
                    sessionId = UUID.fromString(cookie.getValue());
                } catch (IllegalArgumentException malformed) {
                    break;
                }
                var row = db.sql("SELECT account_id, credential_version FROM review_session_fixture WHERE session_id = ?")
                        .param(sessionId)
                        .query((result, index) -> new Actor(result.getLong("account_id"), sessionId, null,
                                result.getLong("credential_version")))
                        .optional();
                if (row.isPresent()) {
                    return row.get();
                }
            }
        }
        throw new BusinessError("AUTHENTICATION_REQUIRED", 401, "身份已失效");
    }

    LockTrace trace() {
        return trace;
    }

    AuditRow auditByCase(long caseId) {
        return auditByCaseInternal(caseId);
    }

    void lockAudit(long auditId) {
        lock("review_audit_fixture", "audit_id", auditId);
    }

    private SubjectPlan plan(AuditRow audit) {
        var productKey = key(LockPlan.Domain.PRODUCT, audit.productId());
        var plan = SubjectPlan.resource(productKey, transaction -> {
            trace.add(productKey);
            lock("review_product_fixture", "product_id", audit.productId());
        });
        var auditKey = key(LockPlan.Domain.PRODUCT_AUDIT, audit.auditId());
        plan = plan.merge(SubjectPlan.resource(auditKey, transaction -> {
            trace.add(auditKey);
            lock("review_audit_fixture", "audit_id", audit.auditId());
        }));
        for (long categoryId : categories(audit.productId())) {
            long id = categoryId;
            var categoryKey = key(LockPlan.Domain.CATEGORY, id);
            plan = plan.merge(SubjectPlan.resource(categoryKey, transaction -> {
                trace.add(categoryKey);
                lock("review_category_fixture", "category_id", id);
            }));
        }
        return plan;
    }

    private CategoryApplicationView applyCategoryApplication(
            io.github.iy88.project1.casemanagement.application.ReviewAction action, String reason, AuditRow audit) {
        var application = categoryApplication(audit.auditId()).orElse(null);
        if (application == null) {
            if (action != null) {
                throw new BusinessError("INPUT_INVALID", 422, "不存在待处理分类申请");
            }
            return null;
        }
        if (!"pending".equals(application.status())) {
            if (action != null) {
                throw new BusinessError("INPUT_INVALID", 422, "分类申请已处理");
            }
            return application;
        }
        if (action == null) {
            throw new BusinessError("REVIEW_CATEGORY_INSUFFICIENT", 409, "分类申请待处理");
        }
        boolean approved = action == io.github.iy88.project1.casemanagement.application.ReviewAction.APPROVE;
        db.sql("UPDATE review_category_application_fixture SET status = ?, reason = ? WHERE application_id = ?")
                .param(approved ? "approved" : "rejected").param(reason)
                .param(application.applicationId()).update();
        if (approved) {
            long resolved = db.sql("SELECT category_id FROM review_category_fixture WHERE main_name = ? "
                            + "ORDER BY category_id LIMIT 1").param(application.proposedName())
                    .query(Long.class).optional()
                    .orElseGet(() -> {
                        long id = db.sql("SELECT coalesce(max(category_id), 0) + 1 FROM review_category_fixture")
                                .query(Long.class).single();
                        db.sql("INSERT INTO review_category_fixture (category_id, main_name, selectable) "
                                        + "VALUES (?, ?, TRUE)")
                                .param(id).param(application.proposedName()).update();
                        return id;
                    });
            int inserted = db.sql("INSERT INTO review_product_category_fixture (product_id, category_id) "
                            + "VALUES (?, ?) ON CONFLICT DO NOTHING")
                    .param(audit.productId()).param(resolved).update();
            if (inserted > 0) {
                db.sql("UPDATE review_product_fixture SET content_version = content_version + 1 WHERE product_id = ?")
                        .param(audit.productId()).update();
            }
        }
        return new CategoryApplicationView(application.applicationId(), application.proposedName(),
                approved ? "approved" : "rejected");
    }

    private void requireSelectableCategories(long productId) {
        var categories = categories(productId);
        if (categories.isEmpty()) {
            throw new BusinessError("CATEGORY_NOT_SELECTABLE", 409, "分类不可选择");
        }
        long blocked = db.sql("""
                SELECT count(*) FROM review_product_category_fixture pc
                JOIN review_category_fixture c ON c.category_id = pc.category_id
                WHERE pc.product_id = ? AND NOT c.selectable
                """).param(productId).query(Long.class).single();
        if (blocked > 0) {
            throw new BusinessError("CATEGORY_NOT_SELECTABLE", 409, "分类不可选择");
        }
    }

    private void validateBannedItems(List<Long> itemIds) {
        for (long itemId : itemIds) {
            var active = db.sql("SELECT active FROM review_banned_item_fixture WHERE item_id = ?")
                    .param(itemId).query(Boolean.class).optional();
            if (active.isEmpty() || !active.get()) {
                throw new BusinessError("INPUT_INVALID", 422, "审核依据无效");
            }
        }
    }

    private long count(String from, TodoQuery query) {
        var statement = db.sql("SELECT count(*)" + from);
        if (query.ownership() == TodoOwnership.MINE) {
            statement = statement.param("manager", query.managerId());
        }
        return statement.query(Long.class).single();
    }

    private AuditRow auditById(long auditId) {
        return db.sql("""
                SELECT audit_id, case_id, product_id, status, submitted_at, reviewed_content_version,
                       decision, reason, decided_at, decided_by
                FROM review_audit_fixture WHERE audit_id = ?
                """).param(auditId).query((row, index) -> new AuditRow(row.getLong("audit_id"),
                        row.getLong("case_id"), row.getLong("product_id"), row.getString("status"),
                        row.getTimestamp("submitted_at").toInstant(),
                        row.getObject("reviewed_content_version", Integer.class), row.getString("decision"),
                        row.getString("reason"),
                        row.getTimestamp("decided_at") == null ? null : row.getTimestamp("decided_at").toInstant(),
                        row.getObject("decided_by", Long.class))).optional()
                .orElseThrow(() -> new BusinessError("RESOURCE_NOT_VISIBLE", 404, "审核不可见"));
    }

    private AuditRow auditByCaseInternal(long caseId) {
        return db.sql("""
                SELECT audit_id, case_id, product_id, status, submitted_at, reviewed_content_version,
                       decision, reason, decided_at, decided_by
                FROM review_audit_fixture WHERE case_id = ?
                """).param(caseId).query((row, index) -> new AuditRow(row.getLong("audit_id"),
                        row.getLong("case_id"), row.getLong("product_id"), row.getString("status"),
                        row.getTimestamp("submitted_at").toInstant(),
                        row.getObject("reviewed_content_version", Integer.class), row.getString("decision"),
                        row.getString("reason"),
                        row.getTimestamp("decided_at") == null ? null : row.getTimestamp("decided_at").toInstant(),
                        row.getObject("decided_by", Long.class))).optional()
                .orElseThrow(() -> new BusinessError("RESOURCE_NOT_VISIBLE", 404, "审核不可见"));
    }

    private ProductRow product(long productId) {
        return db.sql("""
                SELECT product_id, seller_account_id, title, description, price_cents, content_version, lifecycle_state
                FROM review_product_fixture WHERE product_id = ?
                """).param(productId).query((row, index) -> new ProductRow(row.getLong("product_id"),
                        row.getLong("seller_account_id"), row.getString("title"), row.getString("description"),
                        row.getLong("price_cents"), row.getInt("content_version"),
                        row.getString("lifecycle_state"))).optional()
                .orElseThrow(() -> new BusinessError("RESOURCE_NOT_VISIBLE", 404, "商品不可见"));
    }

    private Optional<CategoryApplicationView> categoryApplication(long auditId) {
        return db.sql("""
                SELECT application_id, proposed_name, status FROM review_category_application_fixture
                WHERE audit_id = ?
                """).param(auditId).query((row, index) -> new CategoryApplicationView(row.getLong("application_id"),
                row.getString("proposed_name"), row.getString("status"))).optional();
    }

    private List<Long> categories(long productId) {
        return db.sql("SELECT category_id FROM review_product_category_fixture WHERE product_id = ? ORDER BY category_id")
                .param(productId).query(Long.class).list();
    }

    private List<ProductReviewDetail.Image> images(long productId) {
        return db.sql("SELECT file_id FROM review_product_image_fixture WHERE product_id = ? ORDER BY file_id")
                .param(productId).query((row, index) -> {
                    long id = row.getLong(1);
                    return new ProductReviewDetail.Image(id, java.net.URI.create("https://files.invalid/" + id),
                            Instant.now().plusSeconds(60));
                }).list();
    }

    private List<ProductReviewDetail.Category> detailCategories(long productId) {
        return db.sql("""
                SELECT c.category_id, c.main_name
                FROM review_product_category_fixture pc
                JOIN review_category_fixture c ON c.category_id = pc.category_id
                WHERE pc.product_id = ?
                ORDER BY c.category_id
                """).param(productId)
                .query((row, index) -> new ProductReviewDetail.Category(row.getLong(1), row.getString(2))).list();
    }

    private List<ProductReviewDetail.BannedItem> bannedItems() {
        return db.sql("SELECT item_id, group_name, content FROM review_banned_item_fixture "
                        + "WHERE active ORDER BY item_id")
                .query((row, index) -> new ProductReviewDetail.BannedItem(row.getLong("item_id"),
                        row.getString("group_name"), row.getString("content"))).list();
    }

    private boolean manager(long accountId) {
        return db.sql("SELECT 1 FROM review_manager_fixture WHERE account_id = ?")
                .param(accountId).query(Integer.class).optional().isPresent();
    }

    private void lock(String table, String column, long id) {
        var found = db.sql("SELECT 1 FROM " + table + " WHERE " + column + " = ? FOR UPDATE")
                .param(id).query(Integer.class).optional();
        if (found.isEmpty()) {
            throw new BusinessError("RESOURCE_NOT_VISIBLE", 404, "审核关联不可见");
        }
    }

    private static LockPlan.Key key(LockPlan.Domain domain, long id) {
        return new LockPlan.Key(domain, List.of(id));
    }

    record AuditRow(long auditId, long caseId, long productId, String status, Instant submittedAt,
                    Integer reviewedContentVersion, String decision, String reason, Instant decidedAt,
                    Long decidedBy) {
    }

    record ProductRow(long productId, long sellerId, String title, String description, long priceCents,
                      int contentVersion, String lifecycleState) {
    }

    static final class LockTrace {
        private final List<LockPlan.Key> keys = new CopyOnWriteArrayList<>();

        void add(LockPlan.Key key) {
            keys.add(key);
        }

        List<LockPlan.Key> keys() {
            return new ArrayList<>(keys);
        }

        void clear() {
            keys.clear();
        }
    }
}
