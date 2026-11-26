package io.github.iy88.project1.core;

import java.util.Objects;
import java.util.UUID;

/**
 * Request execution context plus the operation identifier that owns the business audit.
 *
 * <p>The identifier is the same one stored by the idempotency claim, so a replay keeps the original
 * operation id and never creates a second business audit. The request id is intentionally kept
 * separate.
 */
public record AuditContext(ExecutionContext execution, UUID operationId) {
    public AuditContext {
        Objects.requireNonNull(execution);
        Objects.requireNonNull(operationId);
    }
}
