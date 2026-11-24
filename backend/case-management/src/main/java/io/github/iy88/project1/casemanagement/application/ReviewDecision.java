package io.github.iy88.project1.casemanagement.application;

import java.time.Instant;

/** Decision command with the single time value used by the whole operation. */
public record ReviewDecision(ReviewDecisionInput input, Instant occurredAt) {}
