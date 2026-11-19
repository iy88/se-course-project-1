package io.github.iy88.project1.core;

import java.util.Objects;
import java.util.UUID;

public record ExecutionContext(UUID requestId, ActorKind actorKind, String actorId, UUID sessionId,
                               UUID originConnectionId, Long credentialVersion, String configVersion) {
    public ExecutionContext {
        Objects.requireNonNull(requestId);
        Objects.requireNonNull(actorKind);
        Objects.requireNonNull(actorId);
        Objects.requireNonNull(configVersion);
        if (actorId.isBlank() || configVersion.isBlank()) {
            throw new IllegalArgumentException("Actor and configuration version are required");
        }
        if (actorKind == ActorKind.ACCOUNT) {
            long accountId = Long.parseLong(actorId);
            if (accountId <= 0 || !Long.toString(accountId).equals(actorId) || sessionId == null
                    || credentialVersion == null || credentialVersion < 0) {
                throw new IllegalArgumentException("Invalid account execution context");
            }
        } else if (sessionId != null || credentialVersion != null || originConnectionId != null) {
            throw new IllegalArgumentException("Session metadata requires an account actor");
        }
    }

    public enum ActorKind {
        ACCOUNT, ENTRY, SYSTEM
    }
}
