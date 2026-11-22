package io.github.iy88.project1.casemanagement.application;

import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Objects;

/** One page of the management queue with ownership-scoped kind counts. */
public record TodoPage(List<TodoItem> items, long total, Map<String, Long> countsByKind, Instant asOf) {
    public TodoPage {
        items = List.copyOf(items);
        countsByKind = Map.copyOf(countsByKind);
        Objects.requireNonNull(asOf);
        if (total < 0) {
            throw new IllegalArgumentException("Invalid todo total");
        }
    }
}
