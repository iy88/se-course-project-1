package io.github.iy88.project1.api.realtime;

import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.messaging.EventReplay;
import jakarta.servlet.http.HttpServletRequest;
import java.util.UUID;

public interface RealtimeAccess extends EventReplay.Projector {
    Session authenticate(HttpServletRequest request);

    void requireCurrent(Session session);

    void requireHello(Session session, String csrfToken);

    record Session(long accountId, UUID id, long credentialVersion, String configVersion) {
        public ExecutionContext context(UUID requestId, UUID connectionId) {
            return new ExecutionContext(requestId, ExecutionContext.ActorKind.ACCOUNT, Long.toString(accountId),
                    id, connectionId, credentialVersion, configVersion);
        }
    }
}
