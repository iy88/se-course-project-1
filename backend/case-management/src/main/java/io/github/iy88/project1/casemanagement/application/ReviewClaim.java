package io.github.iy88.project1.casemanagement.application;

import io.github.iy88.project1.core.BusinessError;
import java.time.Instant;
import java.util.Objects;

/** Server-derived claim command for one product-review case. */
public record ReviewClaim(long caseId, Instant occurredAt) {
    public ReviewClaim {
        if (caseId <= 0) {
            throw new BusinessError("INPUT_INVALID", 422, "事项标识无效");
        }
        Objects.requireNonNull(occurredAt);
    }
}
