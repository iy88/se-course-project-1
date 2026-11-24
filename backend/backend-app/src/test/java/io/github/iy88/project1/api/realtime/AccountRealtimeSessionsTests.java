package io.github.iy88.project1.api.realtime;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import io.github.iy88.project1.account.AccountSettings;
import io.github.iy88.project1.account.application.SessionService;
import io.github.iy88.project1.account.persistence.Account;
import io.github.iy88.project1.account.persistence.SessionGuard;
import io.github.iy88.project1.account.persistence.SessionGuardRepository;
import io.github.iy88.project1.core.BusinessError;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import java.nio.charset.StandardCharsets;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class AccountRealtimeSessionsTests {
    private final SessionService sessions = mock(SessionService.class);
    private final SessionGuardRepository guards = mock(SessionGuardRepository.class);
    private final AccountSettings settings = mock(AccountSettings.class);
    private final AccountRealtimeSessions adapter = new AccountRealtimeSessions(sessions, guards, settings, "cfg");

    @Test
    void missingSessionCookieMeansNoIdentity() {
        HttpServletRequest request = mock(HttpServletRequest.class);
        when(request.getCookies()).thenReturn(null);

        assertThat(adapter.resolve(request)).isEmpty();
    }

    @Test
    void sessionCookieResolvesToTheAccountIdentity() {
        UUID accountSession = UUID.randomUUID();
        Account account = mock(Account.class);
        when(account.id()).thenReturn(7L);
        when(account.credentialVersion()).thenReturn(4);
        SessionGuard guard = mock(SessionGuard.class);
        when(guard.id()).thenReturn(accountSession);
        when(sessions.authenticate("cookie-value"))
                .thenReturn(new SessionService.Identity(account, guard));
        HttpServletRequest request = requestWithSessionCookie();

        assertThat(adapter.resolve(request))
                .contains(new RealtimeAccess.Session(7, accountSession, 4L, "cfg"));
    }

    @Test
    void currentCheckUsesTheSessionCredentialVersion() {
        UUID accountSession = UUID.randomUUID();
        adapter.requireCurrent(new RealtimeAccess.Session(7, accountSession, 4L, "cfg"));

        org.mockito.Mockito.verify(sessions).requireCurrent(7, accountSession, 4L, false);
    }

    @Test
    void csrfMustMatchTheSessionDigest() {
        UUID accountSession = UUID.randomUUID();
        SessionGuard guard = guard(accountSession, "7", 4, false,
                SessionService.sha256("token".getBytes(StandardCharsets.UTF_8)));
        when(guards.findById(accountSession)).thenReturn(Optional.of(guard));
        var session = new RealtimeAccess.Session(7, accountSession, 4L, "cfg");

        adapter.requireCsrf(session, "token");

        assertThatThrownBy(() -> adapter.requireCsrf(session, "other"))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("CSRF_INVALID"));
    }

    @Test
    void revokedOrReplacedSessionsCannotFinishTheHandshake() {
        UUID accountSession = UUID.randomUUID();
        var session = new RealtimeAccess.Session(7, accountSession, 4L, "cfg");
        SessionGuard revoked = guard(accountSession, "7", 4, true, new byte[32]);
        when(guards.findById(accountSession)).thenReturn(Optional.of(revoked));

        assertThatThrownBy(() -> adapter.requireCsrf(session, "token"))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("AUTHENTICATION_REQUIRED"));
    }

    @Test
    void publicLimitsComeFromAccountSettings() {
        when(settings.passwordMinLength()).thenReturn(10);
        when(settings.passwordMaxLength()).thenReturn(128);
        when(settings.displayNameMaxLength()).thenReturn(32);

        assertThat(adapter.publicLimits())
                .isEqualTo(new RealtimeSessions.PublicAccountLimits(10, 128, 32));
    }

    private static HttpServletRequest requestWithSessionCookie() {
        HttpServletRequest request = mock(HttpServletRequest.class);
        when(request.getCookies()).thenReturn(new Cookie[]{new Cookie("__Host-se_session", "cookie-value")});
        return request;
    }

    private static SessionGuard guard(UUID sessionId, String accountId, int credentialVersion, boolean revoked,
                                      byte[] csrfDigest) {
        SessionGuard guard = mock(SessionGuard.class);
        when(guard.id()).thenReturn(sessionId);
        when(guard.accountId()).thenReturn(Long.parseLong(accountId));
        when(guard.credentialVersion()).thenReturn(credentialVersion);
        when(guard.revoked()).thenReturn(revoked);
        when(guard.csrfDigest()).thenReturn(csrfDigest);
        return guard;
    }
}
