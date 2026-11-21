package io.github.iy88.project1.casemanagement.application;

import io.github.iy88.project1.core.ResourceRef;
import java.util.Objects;

/** Product-owned review result consumed by the case projection. */
public record ReviewSubject(ResourceRef auditRef, String previousState, String currentState,
                           boolean alreadyEffective) {
    public ReviewSubject {
        Objects.requireNonNull(auditRef);
    }
}
