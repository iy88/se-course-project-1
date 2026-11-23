package io.github.iy88.project1.api.account;

import io.github.iy88.project1.api.notification.NotificationActorResolver;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Component;

/**
 * Binds the notification endpoints to the account session.
 *
 * The actor is derived from the session cookie only; client supplied account identifiers
 * are never trusted. Missing or expired sessions surface as 401 and an unavailable
 * identity dependency as 503, both raised by the session service.
 */
@Component
@Profile("infrastructure")
public class AccountNotificationActorResolver implements NotificationActorResolver {
    private final CurrentAccount current;

    public AccountNotificationActorResolver(CurrentAccount current) {
        this.current = current;
    }

    @Override
    public Actor resolve(HttpServletRequest request) {
        var identity = current.require(request);
        return new Actor(identity.account().id(), identity.guard().id(),
                (long) identity.guard().credentialVersion());
    }
}
