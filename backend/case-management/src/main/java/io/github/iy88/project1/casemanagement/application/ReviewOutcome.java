package io.github.iy88.project1.casemanagement.application;

import io.github.iy88.project1.core.ResourceRef;
import java.util.Objects;

/** Result of one review claim or decision. */
public record ReviewOutcome(long caseId, long auditId, ReviewAction action, ResourceRef auditRef,
                            String previousState, String currentState, boolean replayed) {
    public ReviewOutcome {
        Objects.requireNonNull(action);
        Objects.requireNonNull(auditRef);
    }
}
