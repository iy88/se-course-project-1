package io.github.iy88.project1.casemanagement.application;

import io.github.iy88.project1.core.WriteTransaction;
import java.time.Instant;

/**
 * Persists the in-site seller notification for a decided review. The adapter maps this call onto
 * the notification module's {@code create_notifications}; a failure must abort the shared
 * transaction.
 */
@FunctionalInterface
public interface ReviewNotifications {
    void reviewDecided(WriteTransaction transaction, long sellerAccountId, long auditId, long productId,
                       String status, String rejectionReason, Instant occurredAt);
}
