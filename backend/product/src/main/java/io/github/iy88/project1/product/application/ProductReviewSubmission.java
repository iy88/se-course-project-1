package io.github.iy88.project1.product.application;

import io.github.iy88.project1.category.application.CategoryDirectory;
import io.github.iy88.project1.core.AuditActions;
import io.github.iy88.project1.core.AuditContext;
import io.github.iy88.project1.core.AuditStore;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.product.persistence.CategoryApplication;
import io.github.iy88.project1.product.persistence.CategoryApplicationRepository;
import io.github.iy88.project1.product.persistence.Product;
import io.github.iy88.project1.product.persistence.ProductAudit;
import io.github.iy88.project1.product.persistence.ProductAuditRepository;
import io.github.iy88.project1.product.persistence.ProductCategoryRepository;
import io.github.iy88.project1.product.persistence.ProductRepository;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * Seller review submission flows: resubmitting a rejected or withdrawn product opens a new review
 * case, while withdrawing a pending review closes the audit and any pending category application.
 *
 * <p>The public entry points and their DTOs stay on {@link ProductService}. This collaborator runs
 * inside the same {@link TransactionTemplate} instance, so the seller lock, version check,
 * qualification, review and category locks, write clock, snapshot and audit order stay unchanged.
 */
final class ProductReviewSubmission {
    private final ProductRepository products;
    private final ProductCategoryRepository links;
    private final ProductAuditRepository audits;
    private final CategoryApplicationRepository applications;
    private final ObjectProvider<ProductReviewCaseLifecycle> reviewCases;
    private final AccountWriteGuard writeGuard;
    private final CategoryDirectory directory;
    private final ObjectProvider<ProductTradeFreeze> tradeFreezes;
    private final JdbcClient jdbc;
    private final TransactionTemplate transaction;
    private final AuditStore auditRecords;

    ProductReviewSubmission(ProductRepository products, ProductCategoryRepository links,
                            ProductAuditRepository audits, CategoryApplicationRepository applications,
                            ObjectProvider<ProductReviewCaseLifecycle> reviewCases, AccountWriteGuard writeGuard,
                            CategoryDirectory directory, ObjectProvider<ProductTradeFreeze> tradeFreezes,
                            JdbcClient jdbc, TransactionTemplate transaction, AuditStore auditRecords) {
        this.products = products;
        this.links = links;
        this.audits = audits;
        this.applications = applications;
        this.reviewCases = reviewCases;
        this.writeGuard = writeGuard;
        this.directory = directory;
        this.tradeFreezes = tradeFreezes;
        this.jdbc = jdbc;
        this.transaction = transaction;
        this.auditRecords = auditRecords;
    }

    ProductService.Resubmitted resubmit(long sellerId, long productId, Integer expectedVersion,
                                        AuditContext auditContext) {
        return transaction.execute(status -> {
            writeGuard.requireWritable(sellerId);
            Product product = ProductWriteSupport.lockForSeller(products, sellerId, productId);
            ProductWriteSupport.requireVersion(product, expectedVersion);
            ProductWriteSupport.requirePublishOrDelistable(tradeFreezes, sellerId);
            ProductAudit latest = ProductWriteSupport.latestAudit(audits, productId);
            if (!resubmittable(product, latest)) {
                throw new BusinessError("PRODUCT_NOT_RESUBMITTABLE", 409, "当前商品不能重新提交审核");
            }
            boolean hasSelectableCategory = links.activeCategoryIds(productId).stream()
                    .anyMatch(id -> directory.find(id).map(element -> element.selectable()).orElse(false));
            if (!hasSelectableCategory && applications.lockPending(productId).isEmpty()) {
                throw new BusinessError("CATEGORY_REQUIRED", 422, "请至少选择一个分类或提交新分类申请");
            }
            Instant now = Instant.now();
            int sequence = audits.maxSequence(productId) + 1;
            long caseId = openCase(now);
            ProductAudit audit = audits.save(new ProductAudit(productId, sequence, caseId, now));
            if (reviewCases.getIfAvailable() != null) {
                captureCaseSnapshot(caseId, product);
            }
            product.transition(Product.PENDING_REVIEW, now);
            products.save(product);
            Map<String, Object> facts = new LinkedHashMap<>();
            facts.put("audit_id", Long.toString(audit.id()));
            facts.put("case_id", Long.toString(audit.caseId()));
            facts.put("lifecycle_state", product.lifecycleState());
            facts.put("content_version", product.contentVersion());
            auditRecords.record(auditContext, AuditActions.PRODUCT_REVIEW_RESUBMITTED,
                    new ResourceRef("product", productId), null, facts);
            return new ProductService.Resubmitted(Long.toString(audit.id()), Long.toString(audit.caseId()),
                    product.lifecycleState(), product.contentVersion());
        });
    }

    ProductService.Withdrawn withdraw(long sellerId, long productId, Integer expectedVersion,
                                      AuditContext auditContext) {
        return transaction.execute(status -> {
            writeGuard.requireWritable(sellerId);
            Product product = ProductWriteSupport.lockForSeller(products, sellerId, productId);
            ProductWriteSupport.requireVersion(product, expectedVersion);
            if (!Product.PENDING_REVIEW.equals(product.lifecycleState())) {
                throw new BusinessError("STATE_CONFLICT", 409, "商品不在待审核状态");
            }
            ProductAudit audit = audits.lockPending(productId)
                    .orElseThrow(() -> new BusinessError("REVIEW_NOT_PENDING", 409, "没有待处理审核"));
            ProductReviewCaseLifecycle lifecycle = reviewCases.getIfAvailable();
            if (lifecycle != null) {
                lifecycle.requireUnclaimed(audit.caseId());
            }
            Instant now = Instant.now();
            audit.withdraw(now);
            audits.save(audit);
            if (lifecycle != null) {
                lifecycle.withdrawn(audit.caseId(), now);
            }
            CategoryApplication pending = applications.lockPending(productId).orElse(null);
            Long applicationId = null;
            if (pending != null) {
                pending.withdraw(now);
                applications.save(pending);
                applicationId = pending.id();
            }
            product.transition(Product.OFF_SHELF, now);
            products.save(product);
            Map<String, Object> facts = new LinkedHashMap<>();
            facts.put("audit_id", Long.toString(audit.id()));
            facts.put("lifecycle_state", product.lifecycleState());
            facts.put("content_version", product.contentVersion());
            if (applicationId != null) {
                facts.put("category_application_id", Long.toString(applicationId));
            }
            auditRecords.record(auditContext, AuditActions.PRODUCT_REVIEW_WITHDRAWN,
                    new ResourceRef("product", productId), null, facts);
            return new ProductService.Withdrawn(Product.OFF_SHELF, "withdrawn", "withdrawn",
                    product.contentVersion());
        });
    }

    /**
     * Shared eligibility for resubmission and the owner-facing permission. A review rejection keeps
     * its own lifecycle; a withdrawal or rejection after a submission lands on off_shelf with the
     * withdrawn or rejected latest audit. Pending and approved off-shelf relisting are excluded.
     */
    static boolean resubmittable(Product product, ProductAudit latest) {
        if (Product.REVIEW_REJECTED.equals(product.lifecycleState())) {
            return true;
        }
        return Product.OFF_SHELF.equals(product.lifecycleState())
                && latest != null
                && ("rejected".equals(latest.status()) || "withdrawn".equals(latest.status()));
    }

    long openCase(Instant submittedAt) {
        ProductReviewCaseLifecycle lifecycle = reviewCases.getIfAvailable();
        return lifecycle == null ? nextCaseId() : lifecycle.open(submittedAt);
    }

    void captureCaseSnapshot(long caseId, Product product) {
        jdbc.sql("""
                        insert into product_case_snapshot
                            (case_id, product_id, content_version, title, description, price_cents, captured_at)
                        select id, :productId, :version, :title, :description, :price, statement_timestamp()
                          from moderation_case where id = :caseId
                        on conflict (case_id) do nothing
                        """).param("caseId", caseId).param("productId", product.id())
                .param("version", product.contentVersion()).param("title", product.title())
                .param("description", product.description()).param("price", product.priceCents()).update();
    }

    private long nextCaseId() {
        return jdbc.sql("select nextval('product_review_case_seq')").query(Long.class).single();
    }
}
