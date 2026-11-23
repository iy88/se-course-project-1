package io.github.iy88.project1.api.realtime;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import io.github.iy88.project1.account.AccountSettings;
import io.github.iy88.project1.account.application.SessionService;
import io.github.iy88.project1.account.persistence.Account;
import io.github.iy88.project1.account.persistence.AccountRepository;
import io.github.iy88.project1.account.persistence.SessionGuard;
import io.github.iy88.project1.account.persistence.SessionGuardRepository;
import io.github.iy88.project1.core.BusinessError;
import jakarta.servlet.http.Cookie;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;

class AccountRealtimeSessionsTests {
    private final SessionService sessions = mock(SessionService.class);
    private final SessionGuardRepository guards = mock(SessionGuardRepository.class);
    private final AccountRepository accounts = mock(AccountRepository.class);
    private final AccountSettings settings = mock(AccountSettings.class);
    private final AccountRealtimeSessions realtime = new AccountRealtimeSessions(sessions, guards, accounts, settings,
            "cfg-1");

    @Test
    void resolvesTheSessionCookieThroughTheAccountService() {
        var account = mock(Account.class);
        when(account.id()).thenReturn(7L);
        var guard = mock(SessionGuard.class);
        when(guard.id()).thenReturn(UUID.randomUUID());
        when(guard.credentialVersion()).thenReturn(2);
        when(sessions.authenticate("cookie-token")).thenReturn(new SessionService.Identity(account, guard));

        var request = new MockHttpServletRequest();
        request.setCookies(new Cookie("__Host-se_session", "cookie-token"));

        assertThat(realtime.resolve(request)).hasValueSatisfying(session -> {
            assertThat(session.accountId()).isEqualTo(7L);
            assertThat(session.credentialVersion()).isEqualTo(2L);
            assertThat(session.configVersion()).isEqualTo("cfg-1");
        });
    }

    @Test
    void resolvesNoSessionWithoutTheCookie() {
        assertThat(realtime.resolve(new MockHttpServletRequest())).isEmpty();
    }

    @Test
    void rechecksARevokedSession() {
        var id = UUID.randomUUID();
        var session = new RealtimeAccess.Session(7L, id, 1L, "cfg-1");
        var guard = mock(SessionGuard.class);
        when(guard.revoked()).thenReturn(true);
        when(guards.findById(id)).thenReturn(Optional.of(guard));

        assertThatThrownBy(() -> realtime.requireCurrent(session))
                .isInstanceOfSatisfying(BusinessError.class,
                        failure -> assertThat(failure.code()).isEqualTo("AUTHENTICATION_REQUIRED"));
    }

    @Test
    void verifiesTheSessionBoundCsrfToken() {
        var id = UUID.randomUUID();
        var session = new RealtimeAccess.Session(7L, id, 1L, "cfg-1");
        var guard = mock(SessionGuard.class);
        when(guard.csrfDigest()).thenReturn(SessionService.sha256("csrf-token".getBytes(StandardCharsets.UTF_8)));
        when(guards.findById(id)).thenReturn(Optional.of(guard));

        realtime.requireCsrf(session, "csrf-token");

        assertThatThrownBy(() -> realtime.requireCsrf(session, "wrong"))
                .isInstanceOfSatisfying(BusinessError.class,
                        failure -> assertThat(failure.code()).isEqualTo("CSRF_INVALID"));
    }

    @Test
    void exposesThePublicAccountLimits() {
        when(settings.passwordMinLength()).thenReturn(8);
        when(settings.passwordMaxLength()).thenReturn(64);
        when(settings.displayNameMaxLength()).thenReturn(20);

        var limits = realtime.publicLimits();

        assertThat(limits.passwordMinLength()).isEqualTo(8);
        assertThat(limits.passwordMaxLength()).isEqualTo(64);
        assertThat(limits.displayNameMaxLength()).isEqualTo(20);
    }

    @Test
    void acceptsACurrentSession() {
        var id = UUID.randomUUID();
        var session = new RealtimeAccess.Session(7L, id, 1L, "cfg-1");
        var guard = mock(SessionGuard.class);
        when(guard.revoked()).thenReturn(false);
        when(guard.absoluteExpiresAt()).thenReturn(Instant.now().plusSeconds(60));
        when(guard.credentialVersion()).thenReturn(1);
        when(guard.accountId()).thenReturn(7L);
        var account = mock(Account.class);
        when(account.credentialVersion()).thenReturn(1);
        when(account.id()).thenReturn(7L);
        when(guards.findById(id)).thenReturn(Optional.of(guard));
        when(accounts.findById(7L)).thenReturn(Optional.of(account));

        realtime.requireCurrent(session);
    }
}
