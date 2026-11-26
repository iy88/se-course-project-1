package io.github.iy88.project1.api.product;

import io.github.iy88.project1.product.application.CaseCommentAccess;
import org.springframework.context.annotation.Profile;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Component;

/**
 * Resolves the claimed manager's necessary scope for a product by reading the case row and the
 * review audit that links it to the product. The case module owns claims; the product module only
 * asks whether the product is covered.
 *
 * <p>On the S2 baseline a case reaches a product through its review audit. Cases that target a
 * comment directly arrive with the case lifecycle work package (S4-04); until then this adapter
 * covers review cases only.
 */
@Component
@Profile("infrastructure")
class ProductCommentCaseAccess implements CaseCommentAccess {
    private final JdbcClient jdbc;

    ProductCommentCaseAccess(JdbcClient jdbc) {
        this.jdbc = jdbc;
    }

    @Override
    public boolean claimedForProduct(long managerId, long caseId, long productId) {
        return jdbc.sql("""
                        select exists (
                            select 1
                              from moderation_case c
                              join product_audit a on a.case_id = c.id
                             where c.id = ? and c.claimed_manager_id = ? and a.product_id = ?)
                        """)
                .param(caseId)
                .param(managerId)
                .param(productId)
                .query(Boolean.class)
                .single();
    }
}
