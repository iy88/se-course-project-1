package io.github.iy88.project1.product.application;

import io.github.iy88.project1.core.ExecutionContext;
import java.time.Instant;

/**
 * Same-transaction hook for telling the seller about an administrator category correction.
 *
 * <p>The product module owns the correction fact and invokes the hook before its transaction
 * commits. The implementation must write notification facts and delivery intents in that
 * transaction; it must not start a nested transaction or wait for the commit.
 */
@FunctionalInterface
public interface ProductCorrectionNotices {
    void categoryCorrected(ExecutionContext context, long sellerId, long productId, long editId, long caseId,
                           String productTitle, Instant occurredAt);
}
