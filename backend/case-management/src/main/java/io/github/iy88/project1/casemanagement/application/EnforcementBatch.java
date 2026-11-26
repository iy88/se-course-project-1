package io.github.iy88.project1.casemanagement.application;

import io.github.iy88.project1.core.ResourceRef;
import java.util.List;

/** Result of one decision execution, in the caller's enforcement order. */
public record EnforcementBatch(long caseId, List<EnforcementOutcome> enforcements,
                               List<Long> notifiedAccountIds) {
    public EnforcementBatch {
        enforcements = List.copyOf(enforcements);
        notifiedAccountIds = notifiedAccountIds.stream().distinct().sorted().toList();
    }

    public ResourceRef caseRef() {
        return new ResourceRef("case", caseId);
    }
}
