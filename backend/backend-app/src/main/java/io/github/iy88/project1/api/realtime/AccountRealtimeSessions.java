package io.github.iy88.project1.api.realtime;

import io.github.iy88.project1.account.AccountSettings;
import io.github.iy88.project1.account.application.SessionService;
import io.github.iy88.project1.account.persistence.SessionGuard;
import io.github.iy88.project1.account.persistence.SessionGuardRepository;
import io.github.iy88.project1.api.account.AccountCookies;
import io.github.iy88.project1.core.BusinessError;
import jakarta.servlet.http.HttpServletRequest;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Optional;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnWebApplication;
import org.springframework.context.annotation.Profile;
import org.springframework.dao.DataAccessException;
import org.springframework.stereotype.Component;

/** Account Session, CSRF and public limit adapter for the realtime entry. */
@Component
@Profile("infrastructure & !dependency-probe & !file-probe")
@ConditionalOnWebApplication(type = ConditionalOnWebApplication.Type.SERVLET)
public class AccountRealtimeSessions implements RealtimeSessions {
    private final SessionService sessions;
    private final SessionGuardRepository guards;
    private final AccountSettings settings;
    private final String configVersion;

    public AccountRealtimeSessions(SessionService sessions, SessionGuardRepository guards,
                                   AccountSettings settings,
                                   @Value("${project1.config-version}") String configVersion) {
        this.sessions = sessions;
        this.guards = guards;
        this.settings = settings;
        this.configVersion = configVersion;
    }

    @Override
    public Optional<RealtimeAccess.Session> resolve(HttpServletRequest request) {
        String cookie = AccountCookies.read(request, AccountCookies.SESSION);
        if (cookie == null) {
            return Optional.empty();
        }
        var identity = sessions.authenticate(cookie);
        return Optional.of(new RealtimeAccess.Session(identity.account().id(), identity.guard().id(),
                identity.account().credentialVersion(), configVersion));
    }

    @Override
    public void requireCurrent(RealtimeAccess.Session session) {
        sessions.requireCurrent(session.accountId(), session.id(), session.credentialVersion(), false);
    }

    @Override
    public void requireCsrf(RealtimeAccess.Session session, String token) {
        if (token == null || token.isBlank()) {
            throw csrfRejected();
        }
        SessionGuard guard;
        try {
            guard = guards.findById(session.id()).orElseThrow(AccountRealtimeSessions::authenticationRequired);
        } catch (DataAccessException unavailable) {
            throw new BusinessError("AUTHENTICATION_UNAVAILABLE", 503, "身份服务暂不可用");
        }
        if (guard.accountId() != session.accountId()
                || guard.credentialVersion() != session.credentialVersion() || guard.revoked()) {
            throw authenticationRequired();
        }
        byte[] supplied = SessionService.sha256(token.getBytes(StandardCharsets.UTF_8));
        if (!MessageDigest.isEqual(guard.csrfDigest(), supplied)) {
            throw csrfRejected();
        }
    }

    @Override
    public PublicAccountLimits publicLimits() {
        return new PublicAccountLimits(settings.passwordMinLength(), settings.passwordMaxLength(),
                settings.displayNameMaxLength());
    }

    private static BusinessError authenticationRequired() {
        return new BusinessError("AUTHENTICATION_REQUIRED", 401, "登录状态已失效");
    }

    private static BusinessError csrfRejected() {
        return new BusinessError("CSRF_INVALID", 403, "请求校验失败");
    }
}
