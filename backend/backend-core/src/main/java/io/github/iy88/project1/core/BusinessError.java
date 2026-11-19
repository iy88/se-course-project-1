package io.github.iy88.project1.core;

import java.io.Serial;
import java.util.Map;
import java.util.UUID;

public final class BusinessError extends RuntimeException {
    @Serial
    private static final long serialVersionUID = 1L;

    private final String code;
    private final int status;
    private final transient Map<String, ?> details;
    private UUID operationId;

    public BusinessError(String code, int status, String message) {
        this(code, status, message, Map.of());
    }

    public BusinessError(String code, int status, String message, Map<String, ?> details) {
        super(message);
        this.code = code;
        this.status = status;
        this.details = Map.copyOf(details);
    }

    public String code() { return code; }
    public int status() { return status; }
    public Map<String, ?> details() { return details; }
    public UUID operationId() { return operationId; }

    BusinessError forOperation(UUID id) {
        operationId = id;
        return this;
    }
}
