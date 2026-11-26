package io.github.iy88.project1.api.conversation;

import jakarta.servlet.http.HttpServletRequest;
import java.util.UUID;

/**
 * Trusted session adapter for the conversation endpoints. The account always comes from the
 * session cookie; a client supplied account id is never accepted.
 */
public interface ConversationActorResolver {
    Actor resolve(HttpServletRequest request);

    record Actor(long accountId, UUID sessionId, Long credentialVersion) {
        public Actor {
            if (accountId <= 0 || sessionId == null || credentialVersion == null || credentialVersion < 0) {
                throw new IllegalArgumentException("Invalid conversation actor");
            }
        }
    }
}
