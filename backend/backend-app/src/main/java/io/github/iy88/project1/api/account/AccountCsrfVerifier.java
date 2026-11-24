package io.github.iy88.project1.api.account;

import io.github.iy88.project1.account.application.EntryTokenService;
import io.github.iy88.project1.account.application.SessionService;
import io.github.iy88.project1.account.persistence.SessionGuardRepository;
import io.github.iy88.project1.api.CsrfGuard;
import io.github.iy88.project1.core.BusinessError;
import jakarta.servlet.http.HttpServletRequest;
import java.security.MessageDigest;
import java.util.Base64;
import java.util.UUID;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Profile;
import org.springframework.dao.DataAccessException;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

@Component
@Profile("infrastructure")
public class AccountCsrfVerifier implements CsrfGuard.Verifier {
    private final SessionGuardRepository guards;
    private final EntryTokenService entries;
    private final StringRedisTemplate redis;
    private final String namespace;

    public AccountCsrfVerifier(SessionGuardRepository guards, EntryTokenService entries,
                               StringRedisTemplate redis, @Value("${project1.redis.namespace}") String namespace) {
        this.guards = guards;
        this.entries = entries;
        this.redis = redis;
        this.namespace = namespace;
    }

    @Override
    public boolean matches(HttpServletRequest request, String suppliedToken) {
        byte[] supplied = suppliedToken.getBytes(java.nio.charset.StandardCharsets.UTF_8);
        String sessionCookie = AccountCookies.read(request, AccountCookies.SESSION);
        if (sessionCookie != null && sessionMatches(sessionCookie, supplied)) {
            return true;
        }
        String entryCookie = AccountCookies.read(request, AccountCookies.ENTRY);
        if (entryCookie != null) {
            try {
                return entries.csrfMatches(entries.parse(entryCookie), suppliedToken);
            } catch (BusinessError invalidEntry) {
                return false;
            }
        }
        return false;
    }

    private boolean sessionMatches(String cookie, byte[] supplied) {
        byte[] digest;
        try {
            digest = SessionService.sha256(Base64.getUrlDecoder().decode(cookie));
        } catch (IllegalArgumentException invalid) {
            return false;
        }
        String value;
        try {
            value = redis.opsForValue().get(namespace + ":session:" + hex(digest));
        } catch (DataAccessException unavailable) {
            throw new BusinessError("AUTHENTICATION_UNAVAILABLE", 503, "身份服务暂不可用");
        }
        if (value == null) {
            return false;
        }
        UUID sessionId;
        try {
            sessionId = UUID.fromString(value.split("\\|", -1)[0]);
        } catch (RuntimeException malformed) {
            return false;
        }
        return guards.findById(sessionId)
                .map(guard -> MessageDigest.isEqual(guard.csrfDigest(), SessionService.sha256(supplied)))
                .orElse(false);
    }

    private static String hex(byte[] value) {
        StringBuilder text = new StringBuilder(value.length * 2);
        for (byte part : value) {
            text.append(Character.forDigit((part >> 4) & 0xF, 16)).append(Character.forDigit(part & 0xF, 16));
        }
        return text.toString();
    }
}
