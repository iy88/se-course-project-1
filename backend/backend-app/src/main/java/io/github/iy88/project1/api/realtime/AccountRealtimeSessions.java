package io.github.iy88.project1.api.realtime;

import io.github.iy88.project1.account.AccountSettings;
import io.github.iy88.project1.account.application.SessionService;
import io.github.iy88.project1.account.persistence.AccountRepository;
import io.github.iy88.project1.account.persistence.SessionGuard;
import io.github.iy88.project1.account.persistence.SessionGuardRepository;
import io.github.iy88.project1.api.account.AccountCookies;
import io.github.iy88.project1.core.BusinessError;
import jakarta.servlet.http.HttpServletRequest;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.Optional;

/**
 * Account-session adapter for the realtime channel. Cookie sessions are authenticated by the
 * account module; a resolved session is re-checked for revocation, absolute expiry and credential
 * version. Idle timeout is maintained by the session service in Redis and is not duplicated here.
 */
final class AccountRealtimeSessions implements RealtimeSessions {
    private final SessionService sessions;
    private final SessionGuardRepository guards;
    private final AccountRepository accounts;
    private final AccountSettings settings;
    private final String configVersion;

    AccountRealtimeSessions(SessionService sessions, SessionGuardRepository guards, AccountRepository accounts,
                            AccountSettings settings, String configVersion) {
        this.sessions = sessions;
        this.guards = guards;
        this.accounts = accounts;
        this.settings = settings;
        this.configVersion = configVersion;
    }

    @Override
    public Optional<RealtimeAccess.Session> resolve(HttpServletRequest request) {
        String token = AccountCookies.read(request, AccountCookies.SESSION);
        if (token == null || token.isBlank()) {
            return Optional.empty();
        }
        try {
            var identity = sessions.authenticate(token);
            return Optional.of(new RealtimeAccess.Session(identity.account().id(), identity.guard().id(),
                    identity.guard().credentialVersion(), configVersion));
        } catch (BusinessError unavailableOrExpired) {
            return Optional.empty();
        }
    }

    @Override
    public void requireCurrent(RealtimeAccess.Session session) {
        SessionGuard guard = guards.findById(session.id()).orElseThrow(AccountRealtimeSessions::required);
        var account = accounts.findById(session.accountId()).orElseThrow(AccountRealtimeSessions::required);
        if (guard.revoked() || !Instant.now().isBefore(guard.absoluteExpiresAt())
                || account.credentialVersion() != guard.credentialVersion()
                || account.id() != guard.accountId()) {
            throw required();
        }
    }

    @Override
    public void requireCsrf(RealtimeAccess.Session session, String token) {
        SessionGuard guard = guards.findById(session.id()).orElseThrow(AccountRealtimeSessions::required);
        if (token == null || !MessageDigest.isEqual(guard.csrfDigest(),
                SessionService.sha256(token.getBytes(StandardCharsets.UTF_8)))) {
            throw new BusinessError("CSRF_INVALID", 403, "CSRF 校验失败");
        }
    }

    @Override
    public PublicAccountLimits publicLimits() {
        return new PublicAccountLimits(settings.passwordMinLength(), settings.passwordMaxLength(),
                settings.displayNameMaxLength());
    }

    private static BusinessError required() {
        return new BusinessError("AUTHENTICATION_REQUIRED", 401, "登录状态已失效");
    }
}
