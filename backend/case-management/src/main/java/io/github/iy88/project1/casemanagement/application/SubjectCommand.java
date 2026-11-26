package io.github.iy88.project1.casemanagement.application;

import io.github.iy88.project1.core.ResourceRef;
import java.time.Instant;
import java.util.List;
import java.util.Objects;

/** Immutable subject-facing view of one enforcement entry. */
public record SubjectCommand(long caseId, String enforcementId, EnforcementAction action, ResourceRef target,
                             ResourceRef detail, String expectedResult, String reason,
                             List<ResourceRef> basis, Instant occurredAt) {
    public SubjectCommand {
        if (caseId <= 0) {
            throw new IllegalArgumentException("Invalid case ID");
        }
        Objects.requireNonNull(action);
        Objects.requireNonNull(target);
        Objects.requireNonNull(occurredAt);
        basis = List.copyOf(basis);
    }

    public static SubjectCommand of(EnforcementCommand command, EnforcementInstruction instruction,
                                    CaseAccess access) {
        return new SubjectCommand(command.caseId(), instruction.enforcementId(), instruction.action(),
                instruction.target(), instruction.detail(), instruction.expectedResult(), command.reason(),
                access.basis(), command.occurredAt());
    }

    public ResourceRef caseRef() {
        return new ResourceRef("case", caseId);
    }
}
