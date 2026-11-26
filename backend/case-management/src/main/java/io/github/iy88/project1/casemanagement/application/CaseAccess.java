package io.github.iy88.project1.casemanagement.application;

import io.github.iy88.project1.core.ResourceRef;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;

/**
 * Current case facts re-read around the case lock. The case module remains the authority for
 * claim, decision, basis, evidence and prior execution links.
 */
public record CaseAccess(long caseId, long claimedManagerId, long reporterAccountId, ResourceRef target,
                         List<ResourceRef> basis, List<CaseEvidence> evidence,
                         Map<String, EnforcementOutcome> priorExecutions, Set<Long> partyAccountIds) {
    public CaseAccess {
        if (caseId <= 0 || claimedManagerId <= 0) {
            throw new IllegalArgumentException("Invalid case access");
        }
        Objects.requireNonNull(target);
        basis = List.copyOf(basis);
        evidence = List.copyOf(evidence);
        priorExecutions = Map.copyOf(priorExecutions);
        partyAccountIds = Set.copyOf(partyAccountIds);
    }

    public ResourceRef caseRef() {
        return new ResourceRef("case", caseId);
    }
}
