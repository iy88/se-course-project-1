package io.github.iy88.project1.casemanagement.application;

import java.time.Instant;

/** The management workbench's allowlisted projection. */
public record TodoItem(long caseId, String kind, Instant createdAt, Instant updatedAt,
                       String decisionKind, Long managerId, Instant completedAt,
                       String title, Long auditId, Long productId) {}
