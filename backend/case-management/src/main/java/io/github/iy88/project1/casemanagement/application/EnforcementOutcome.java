package io.github.iy88.project1.casemanagement.application;

import io.github.iy88.project1.core.ResourceRef;
import java.time.Instant;
import java.util.List;
import java.util.Objects;

/**
 * Public result of one enforcement entry. The result reference is owned by the subject module
 * (restriction, transition or content record); this application only carries it through.
 */
public record EnforcementOutcome(String enforcementId, EnforcementAction action, ResourceRef target,
                                 ResourceRef result, String previousState, String currentState,
                                 List<ResourceRef> affectedScope, Instant occurredAt, Status status) {
    public EnforcementOutcome {
        if (enforcementId == null || enforcementId.isBlank()) {
            throw new IllegalArgumentException("Enforcement ID is required");
        }
        Objects.requireNonNull(action);
        Objects.requireNonNull(target);
        Objects.requireNonNull(result);
        Objects.requireNonNull(occurredAt);
        Objects.requireNonNull(status);
        affectedScope = List.copyOf(affectedScope);
    }

    public EnforcementOutcome replayed() {
        return status == Status.REPLAYED ? this : new EnforcementOutcome(enforcementId, action, target, result,
                previousState, currentState, affectedScope, occurredAt, Status.REPLAYED);
    }

    public enum Status {
        APPLIED, REPLAYED
    }
}
