package io.github.iy88.project1.casemanagement.application;

import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteTransaction;
import java.time.Instant;
import java.util.Set;

/**
 * Persists case notifications and their delivery intents under the caller's transaction.
 * {@code eventType} is the C3 registry label (for example {@code case.trade_frozen}); the
 * adapter maps it onto the S1 event-intent naming rule.
 */
@FunctionalInterface
public interface EnforcementNotifications {
    void create(WriteTransaction transaction, String eventType, String intentKey, ResourceRef source,
                Set<Long> recipients, String reason, Instant occurredAt);
}
