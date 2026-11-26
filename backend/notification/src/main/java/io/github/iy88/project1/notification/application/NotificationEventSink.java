package io.github.iy88.project1.notification.application;

import io.github.iy88.project1.core.ResourceRef;
import java.util.Set;

/**
 * Transport-event sink used by a caller that already owns a business transaction but cannot obtain
 * the shared {@link io.github.iy88.project1.core.WriteTransaction} (for example the product edit
 * path, which uses its own transaction template).
 *
 * <p>The sink must persist the event in the caller's active transaction. A production
 * implementation should delegate to the same event writer as the regular write path.
 */
@FunctionalInterface
public interface NotificationEventSink {
    void register(Set<Long> recipients, String eventType, int schemaVersion, ResourceRef source,
                  String intentKey, ResourceRef payload, Long sourceSequence);
}
