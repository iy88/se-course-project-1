package io.github.iy88.project1.api.trade;

import io.github.iy88.project1.api.account.CurrentAccount;
import jakarta.servlet.http.HttpServletRequest;

/** Resolves the trade actor from the account Session cookie; client supplied ids are never used. */
final class AccountTradeActorResolver implements TradeActorResolver {
    private final CurrentAccount accounts;

    AccountTradeActorResolver(CurrentAccount accounts) {
        this.accounts = accounts;
    }

    @Override
    public Actor resolve(HttpServletRequest request) {
        var identity = accounts.require(request);
        return new Actor(identity.account().id(), identity.guard().id(),
                (long) identity.account().credentialVersion());
    }
}
