package io.github.iy88.project1.core;

import java.util.List;
import java.util.Objects;
import java.util.UUID;

public record EventIntent(UUID eventId, long recipientAccountId, String eventType, int schemaVersion,
                          ResourceRef source, String intentKey, ResourceRef payload, Long sourceSequence) {
    public EventIntent {
        Objects.requireNonNull(eventId);
        Objects.requireNonNull(source);
        if (recipientAccountId <= 0 || eventType == null || !eventType.matches("[a-z][a-z0-9_]*")
                || schemaVersion <= 0 || intentKey == null || intentKey.isBlank()
                || (sourceSequence != null && (sourceSequence < 0 || sourceSequence > 9_007_199_254_740_991L))) {
            throw new IllegalArgumentException("Invalid event intent");
        }
    }

    public record Item(long recipientAccountId, UUID eventId) {}
    public record Batch(List<Item> items) {
        public Batch {
            items = List.copyOf(items);
        }
    }

    @FunctionalInterface
    public interface Writer {
        void persist(ExecutionContext context, List<EventIntent> intents);
    }
}
