package io.github.iy88.project1.api.account;

import io.github.iy88.project1.account.application.AccountService;
import io.github.iy88.project1.account.application.AccountQueries;
import io.github.iy88.project1.account.application.SessionService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.context.annotation.Profile;
import org.springframework.http.CacheControl;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/account/session")
@Profile("infrastructure")
class AccountSessionController {
    private final AccountService accounts;
    private final SessionService sessions;
    private final io.github.iy88.project1.account.application.AccountAvatarService avatars;
    private final CurrentAccount current;
    private final AccountQueries queries;

    AccountSessionController(AccountService accounts, SessionService sessions,
                             io.github.iy88.project1.account.application.AccountAvatarService avatars,
                             CurrentAccount current, AccountQueries queries) {
        this.accounts = accounts;
        this.sessions = sessions;
        this.avatars = avatars;
        this.current = current;
        this.queries = queries;
    }

    @PostMapping
    ResponseEntity<AccountViews.IdentityView> login(@RequestBody LoginRequest body, HttpServletResponse response) {
        var issued = accounts.login(body.email(), body.password());
        response.addHeader(HttpHeaders.SET_COOKIE,
                AccountCookies.cookie(AccountCookies.SESSION, issued.token(), issued.absoluteExpiresAt()).toString());
        response.addHeader(HttpHeaders.SET_COOKIE,
                AccountCookies.cookie(AccountCookies.CSRF, issued.csrfToken(), issued.absoluteExpiresAt()).toString());
        return ResponseEntity.ok()
                .cacheControl(CacheControl.noStore())
                .body(AccountViews.identity(issued, avatars.currentUrl(issued.account().id()),
                        queries.writeRestricted(issued.account().id())));
    }

    @GetMapping
    ResponseEntity<AccountViews.IdentityView> current(HttpServletRequest request) {
        var identity = current.require(request);
        return ResponseEntity.ok()
                .cacheControl(CacheControl.noStore())
                .body(AccountViews.identity(identity.account(), identity.guard(),
                        avatars.currentUrl(identity.account().id()),
                        queries.writeRestricted(identity.account().id())));
    }

    @DeleteMapping
    ResponseEntity<Void> logout(HttpServletRequest request, HttpServletResponse response) {
        try {
            var identity = current.require(request);
            sessions.revoke(identity);
        } catch (io.github.iy88.project1.core.BusinessError failure) {
            if (failure.status() != 401) {
                throw failure;
            }
        }
        response.addHeader(HttpHeaders.SET_COOKIE, AccountCookies.clear(AccountCookies.SESSION).toString());
        response.addHeader(HttpHeaders.SET_COOKIE, AccountCookies.clear(AccountCookies.CSRF).toString());
        return ResponseEntity.noContent().cacheControl(CacheControl.noStore()).build();
    }

    record LoginRequest(String email, String password) {
    }
}
