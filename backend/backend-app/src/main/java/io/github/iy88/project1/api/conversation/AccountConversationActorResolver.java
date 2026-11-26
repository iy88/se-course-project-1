package io.github.iy88.project1.api.conversation;

import io.github.iy88.project1.api.account.CurrentAccount;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Component;

/** Binds the conversation endpoints to the account session created by the identity module. */
@Component
@Profile("infrastructure")
public class AccountConversationActorResolver implements ConversationActorResolver {
    private final CurrentAccount current;

    public AccountConversationActorResolver(CurrentAccount current) {
        this.current = current;
    }

    @Override
    public Actor resolve(HttpServletRequest request) {
        var identity = current.require(request);
        return new Actor(identity.account().id(), identity.guard().id(),
                (long) identity.guard().credentialVersion());
    }
}
