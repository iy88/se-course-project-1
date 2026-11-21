package io.github.iy88.project1.casemanagement.application;

import io.github.iy88.project1.core.BusinessError;
import java.time.Instant;
import java.util.List;
import java.util.Objects;

/**
 * Caller content for a product-review claim or decision. The product audit is the authoritative
 * review record; the case side keeps the claim and execution/projection link.
 */
public record ReviewCommand(long caseId, long auditId, ReviewAction action, String reason,
                            List<Long> basisRefs, ReviewAction categoryDecision,
                            String categoryReason, Instant occurredAt) {
    public ReviewCommand {
        if (caseId <= 0 || auditId <= 0) {
            throw new BusinessError("INPUT_INVALID", 422, "审核标识无效");
        }
        Objects.requireNonNull(action);
        Objects.requireNonNull(basisRefs);
        basisRefs = basisRefs.stream().distinct().sorted().toList();
        if (basisRefs.stream().anyMatch(id -> id == null || id <= 0)) {
            throw new BusinessError("INPUT_INVALID", 422, "审核依据无效");
        }
        if (action == ReviewAction.REJECT && (reason == null || reason.isBlank())) {
            throw new BusinessError("INPUT_INVALID", 422, "审核结论理由不能为空");
        }
        Objects.requireNonNull(occurredAt);
    }
}
