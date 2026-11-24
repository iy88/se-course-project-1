package io.github.iy88.project1.casemanagement.application;

import java.time.Instant;

/** Claim facts read from the case row. */
public record CaseClaim(long caseId, String caseType, Instant createdAt, Long claimedManagerId, Instant claimedAt) {
    public boolean claimed() {
        return claimedManagerId != null;
    }

    public boolean claimedBy(long accountId) {
        return claimedManagerId != null && claimedManagerId == accountId;
    }
}
