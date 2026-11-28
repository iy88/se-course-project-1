package io.github.iy88.project1.api.product;

import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.notification.application.NotificationSourcePort;
import java.util.Optional;
import org.springframework.jdbc.core.simple.JdbcClient;

/**
 * Projects the category-correction notice onto the product for its seller (API-PRD-032).
 *
 * <p>The edit history supplies the corrected product, and the joined product supplies the current
 * title and ownership. Only the seller of an undeleted product may read the notice.</p>
 */
final class ProductCorrectionNotificationSource implements NotificationSourcePort {
    static final String SOURCE_TYPE = "product_category_correction";
    static final String EVENT_TYPE = "product.category_corrected";
    private static final String SUMMARY = "商品分类已纠正";
    private static final String BODY = "管理员根据事项纠正了该商品的分类。你可以前往商品详情查看当前分类。";

    private final JdbcClient jdbc;

    ProductCorrectionNotificationSource(JdbcClient jdbc) {
        this.jdbc = jdbc;
    }

    @Override
    public Optional<NotificationSourceView> project(ExecutionContext context, NotificationFacts facts) {
        if (!SOURCE_TYPE.equals(facts.source().type()) || !EVENT_TYPE.equals(facts.eventType())
                || context.actorKind() != ExecutionContext.ActorKind.ACCOUNT) {
            return Optional.empty();
        }
        long accountId = Long.parseLong(context.actorId());
        return jdbc.sql("""
                        SELECT p.product_id, p.title
                        FROM product_edit_history e JOIN product p ON p.product_id = e.product_id
                        WHERE e.edit_id = ? AND p.seller_account_id = ? AND p.deleted_at IS NULL
                        """)
                .param(facts.source().id()).param(accountId)
                .query((row, index) -> new NotificationSourceView(SUMMARY,
                        new ResourceRef("product", row.getLong("product_id")), row.getString("title"), BODY))
                .optional();
    }
}
