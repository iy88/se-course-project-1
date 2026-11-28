package io.github.iy88.project1.product.application;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.product.persistence.ProductAuditRepository;
import java.util.Map;
import java.util.Optional;
import org.springframework.jdbc.core.simple.JdbcClient;

/**
 * Read side of the case-time product snapshot. The manager authorization runs before either read,
 * the captured snapshot row wins and a reviewed audit is only the fallback for older cases.
 *
 * <p>Case snapshot capture remains on the write path. The public entry points and their Spring
 * transaction annotations stay on {@link ProductService}; this query owns no transaction
 * annotations and no data of its own, so the captured row and the audit fallback are read in the
 * caller's repeatable-read transaction. No case-snapshot entity or repository projection exists,
 * so the original parameterized queries are kept unchanged.
 */
final class ProductCaseSnapshotQueries {
    private final JdbcClient jdbc;
    private final ProductAuditRepository audits;
    private final CaseCommentAccess cases;

    ProductCaseSnapshotQueries(JdbcClient jdbc, ProductAuditRepository audits, CaseCommentAccess cases) {
        this.jdbc = jdbc;
        this.audits = audits;
        this.cases = cases;
    }

    ProductTradeHistory.PurchaseSnapshot managerSnapshot(long managerId, long productId, long caseId) {
        if (!cases.claimedForProduct(managerId, caseId, productId)) {
            throw notVisible();
        }
        return jdbc.sql("""
                        select content_version, title, description, price_cents, captured_at
                          from product_case_snapshot
                         where case_id = :caseId and product_id = :productId
                        """).param("caseId", caseId).param("productId", productId)
                .query((row, index) -> new ProductTradeHistory.PurchaseSnapshot(row.getInt("content_version"),
                        row.getString("title"), row.getString("description"), row.getLong("price_cents"),
                        row.getTimestamp("captured_at").toInstant())).optional()
                .or(() -> reviewedSnapshot(productId, caseId))
                .orElseThrow(ProductCaseSnapshotQueries::notVisible);
    }

    private Optional<ProductTradeHistory.PurchaseSnapshot> reviewedSnapshot(long productId, long caseId) {
        return audits.findByCaseId(caseId)
                .filter(audit -> audit.productId() == productId && audit.decidedAt() != null
                        && audit.reviewedContentVersion() != null)
                .flatMap(audit -> {
                    Map<String, Object> content = audit.reviewedContent();
                    if (content.get("title") instanceof String title
                            && content.get("description") instanceof String description
                            && content.get("price_cents") instanceof Number price) {
                        return Optional.of(new ProductTradeHistory.PurchaseSnapshot(audit.reviewedContentVersion(),
                                title, description, price.longValue(), audit.decidedAt()));
                    }
                    return Optional.empty();
                });
    }

    Optional<ProductService.ReportSnapshot> reportSnapshot(long caseId) {
        return jdbc.sql("""
                        select product_id, title, description from product_case_snapshot where case_id = ?
                        """).param(caseId)
                .query((row, index) -> new ProductService.ReportSnapshot(row.getLong("product_id"),
                        row.getString("title"), row.getString("description"))).optional();
    }

    private static BusinessError notVisible() {
        return new BusinessError("RESOURCE_NOT_VISIBLE", 404, "商品不存在");
    }
}
