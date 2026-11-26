package io.github.iy88.project1.product.application;

import io.github.iy88.project1.core.ExecutionContext;
import java.time.Instant;

/**
 * Same-transaction hook for notifying buyers after a product edit.
 *
 * <p>The product module owns the edit fact and invokes the hook before its transaction commits.
 * The implementation must write notification facts and delivery intents in that transaction; it
 * must not start a nested transaction or wait for the commit.
 */
@FunctionalInterface
public interface ProductEditNotices {
    void productEdited(ExecutionContext context, long sellerId, long productId, long editId, String productTitle,
                       boolean publiclyVisible, Instant occurredAt);
}
