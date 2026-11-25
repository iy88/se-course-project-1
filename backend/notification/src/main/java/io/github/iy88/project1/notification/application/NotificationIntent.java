package io.github.iy88.project1.notification.application;

import io.github.iy88.project1.core.ResourceRef;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.TreeMap;
import java.util.TreeSet;
import java.util.UUID;

/**
 * One approved business intent that must become an in-site notification for each
 * recipient account (API-COM-NOTIFY-001).
 *
 * The intent key is the idempotency scope together with the recipient, so a
 * retried business action reuses the stored notification instead of creating a
 * second one.
 */
public record NotificationIntent(Set<Long> recipientAccountIds, UUID businessEventId, String eventType,
                                 ResourceRef source, String intentKey, String templateKey,
                                 String templateVersion, Map<String, String> displayParams,
                                 Instant occurredAt) {
    private static final int MAX_KEY_LENGTH = 200;

    public NotificationIntent {
        Objects.requireNonNull(occurredAt, "occurredAt");
        Objects.requireNonNull(source, "source");
        if (recipientAccountIds == null || recipientAccountIds.isEmpty()) {
            throw new IllegalArgumentException("At least one recipient is required");
        }
        recipientAccountIds.forEach(id -> {
            if (id == null || id <= 0) {
                throw new IllegalArgumentException("Recipient account ids must be positive");
            }
        });
        requireText(eventType, "eventType", 120);
        requireText(intentKey, "intentKey", MAX_KEY_LENGTH);
        requireText(templateKey, "templateKey", 120);
        requireText(templateVersion, "templateVersion", 60);
        recipientAccountIds = Set.copyOf(new TreeSet<>(recipientAccountIds));
        displayParams = displayParams == null ? Map.of() : Map.copyOf(displayParams);
    }

    /** Recipients in ascending order, which is the batch result order. */
    public List<Long> sortedRecipients() {
        return List.copyOf(new TreeSet<>(recipientAccountIds));
    }

    /**
     * Stable display parameters in key order.
     *
     * Two intents that differ only in a template parameter are different actions,
     * so the parameters take part in the same-intent comparison.
     */
    public Map<String, String> orderedDisplayParams() {
        return new LinkedHashMap<>(new TreeMap<>(displayParams));
    }

    private static void requireText(String value, String field, int maxLength) {
        if (value == null || value.isBlank() || value.length() > maxLength) {
            throw new IllegalArgumentException(field + " must be non-blank and at most " + maxLength
                    + " characters");
        }
    }
}
