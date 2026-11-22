package io.github.iy88.project1.api.notification;

import jakarta.servlet.http.HttpServletRequest;
import java.util.UUID;

/**
 * Trusted session adapter for the notification endpoints.
 *
 * The account is resolved from the session cookie by the identity work package
 * (#74); a client supplied account id is never accepted. The shape mirrors the
 * trade work package's {@code TradeActorResolver} so one identity adapter can
 * serve both ports once #74 lands.
 */
public interface NotificationActorResolver {
    Actor resolve(HttpServletRequest request);

    record Actor(long accountId, UUID sessionId, Long credentialVersion) {
        public Actor {
            if (accountId <= 0 || sessionId == null || credentialVersion == null || credentialVersion < 0) {
                throw new IllegalArgumentException("Invalid notification actor");
            }
        }
    }
}
