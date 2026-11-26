package io.github.iy88.project1.casemanagement.application;

/**
 * Evidence authorized by the case module for this execution. {@code ownerAccountId} is the
 * submitter recorded by the case domain, never a caller-supplied claim.
 */
public record CaseEvidence(long fileId, long ownerAccountId, String slot) {
    public CaseEvidence {
        if (fileId <= 0 || ownerAccountId <= 0 || slot == null || slot.isBlank()) {
            throw new IllegalArgumentException("Invalid case evidence");
        }
    }
}
