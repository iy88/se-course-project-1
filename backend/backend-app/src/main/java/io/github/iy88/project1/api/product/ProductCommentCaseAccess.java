package io.github.iy88.project1.api.product;

import io.github.iy88.project1.product.application.CaseCommentAccess;
import org.springframework.context.annotation.Profile;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Component;

/** Resolves product scope using the claimed review or a report targeting that product. */
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
                              join account manager on manager.account_id = c.claimed_manager_id
                                  and manager.role = 'manager'
                              left join product_audit a on a.case_id = c.id
                             where c.id = ? and c.claimed_manager_id = ?
                               and ((c.case_type = 'product_review' and a.product_id = ?)
                                    or (c.case_type = 'report' and c.target_type = 'product' and c.target_id = ?)))
                        """)
                .param(caseId)
                .param(managerId)
                .param(productId)
                .param(productId)
                .query(Boolean.class)
                .single();
    }
}
