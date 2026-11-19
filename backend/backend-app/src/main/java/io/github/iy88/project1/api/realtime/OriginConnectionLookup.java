package io.github.iy88.project1.api.realtime;

import java.util.Optional;
import java.util.UUID;

@FunctionalInterface
public interface OriginConnectionLookup {
    Optional<UUID> resolve(RealtimeAccess.Session session, String suppliedConnectionId);
}
