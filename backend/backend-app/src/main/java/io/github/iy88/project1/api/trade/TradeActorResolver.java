package io.github.iy88.project1.api.trade;

import jakarta.servlet.http.HttpServletRequest;
import java.util.UUID;

/**
 * Trusted session adapter supplied by the identity task (#78). Implementations must resolve the
 * account from the session cookie and must not accept a client supplied account id.
 */
public interface TradeActorResolver {
    Actor resolve(HttpServletRequest request);

    record Actor(long accountId, UUID sessionId, Long credentialVersion) {
        public Actor {
            if (accountId <= 0 || sessionId == null || credentialVersion == null || credentialVersion < 0) {
                throw new IllegalArgumentException("Invalid trade actor");
            }
        }
    }
}
