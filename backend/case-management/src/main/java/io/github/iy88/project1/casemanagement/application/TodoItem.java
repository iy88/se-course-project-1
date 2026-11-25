package io.github.iy88.project1.casemanagement.application;

import java.time.Instant;

/** Minimal queue row; the summary exposes only the audit/product identifiers needed for detail. */
public record TodoItem(long caseId, String kind, Instant createdAt, Instant updatedAt,
                       long auditId, long productId) {}
