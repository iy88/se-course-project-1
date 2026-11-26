package io.github.iy88.project1.casemanagement.application;

import java.time.Instant;

/** A case change that is delivered only if the business transaction commits. */
public record ManagementCaseChange(long caseId, String kind, String occurrence, Instant occurredAt,
                                   Long messageId, Long evidenceAnchorId) {
    public ManagementCaseChange(long caseId, String kind, String occurrence, Instant occurredAt) {
        this(caseId, kind, occurrence, occurredAt, null, null);
    }

    public static ManagementCaseChange opened(long caseId, Instant at) {
        return new ManagementCaseChange(caseId, "opened", "opened", at);
    }
}
