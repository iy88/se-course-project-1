package io.github.iy88.project1.api.productreview;

import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.notification.application.NotificationSourcePort;
import io.github.iy88.project1.notification.application.ReviewNotificationAdapter;
import java.util.Optional;
import org.springframework.jdbc.core.simple.JdbcClient;

/**
 * Projects a product-review decision onto the seller's product.
 *
 * <p>The audit row supplies the decision, the joined product supplies ownership and the current
 * title, and the JSONB snapshot title wins when present. Only the seller may read the notice.</p>
 */
final class ReviewNotificationSource implements NotificationSourcePort {
    private final JdbcClient jdbc;

    ReviewNotificationSource(JdbcClient jdbc) {
        this.jdbc = jdbc;
    }

    @Override
    public Optional<NotificationSourceView> project(ExecutionContext context, NotificationFacts facts) {
        if (!ReviewNotificationAdapter.SOURCE_TYPE.equals(facts.source().type())) {
            return Optional.empty();
        }
        return jdbc.sql("""
                        SELECT p.product_id, a.status, a.decision_reason,
                               COALESCE(a.reviewed_content ->> 'title', p.title) AS title
                        FROM product_audit a JOIN product p ON p.product_id = a.product_id
                        WHERE a.audit_id = ? AND p.seller_account_id = ?
                          AND p.deleted_at IS NULL AND a.status IN ('passed', 'rejected')
                        """)
                .param(facts.source().id()).param(Long.parseLong(context.actorId()))
                .query((row, index) -> {
                    var reason = row.getString("decision_reason");
                    boolean passed = "passed".equals(row.getString("status"));
                    var summary = passed ? "商品审核通过" : "商品审核未通过";
                    var body = passed ? "该商品已通过审核。你可以前往商品详情查看当前展示状态。"
                            : "你可以根据审核意见修改商品内容，再提交审核。";
                    if (!passed && reason != null && !reason.isBlank()) {
                        body = "审核意见\n" + reason + "\n\n" + body;
                    }
                    return new NotificationSourceView(summary,
                            new ResourceRef("product", row.getLong("product_id")), row.getString("title"), body);
                }).optional();
    }
}
