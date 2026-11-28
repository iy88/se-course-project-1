package io.github.iy88.project1.api.productreview;

import jakarta.servlet.http.HttpServletRequest;
import java.util.UUID;

/**
 * Trusted browser identity seam. The account module supplies the production implementation; tests
 * may supply a fixture. The controller never accepts account ids or roles from request headers or
 * bodies.
 */
@FunctionalInterface
public interface ReviewActorAccess {
    Actor current(HttpServletRequest request);

    record Actor(long accountId, UUID sessionId, UUID originConnectionId, long credentialVersion) {
        public Actor {
            if (accountId <= 0 || sessionId == null || credentialVersion < 0) {
                throw new IllegalArgumentException("Invalid review actor");
            }
        }
    }
}
