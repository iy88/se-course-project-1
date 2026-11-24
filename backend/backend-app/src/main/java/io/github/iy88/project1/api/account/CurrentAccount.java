package io.github.iy88.project1.api.account;

import io.github.iy88.project1.account.application.SessionService;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Component;

@Component
@Profile("infrastructure")
public class CurrentAccount {
    private final SessionService sessions;

    public CurrentAccount(SessionService sessions) {
        this.sessions = sessions;
    }

    public SessionService.Identity require(HttpServletRequest request) {
        return sessions.authenticate(AccountCookies.read(request, AccountCookies.SESSION));
    }
}
