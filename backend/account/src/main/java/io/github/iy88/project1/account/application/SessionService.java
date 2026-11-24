package io.github.iy88.project1.account.application;

import io.github.iy88.project1.account.AccountSettings;
import io.github.iy88.project1.account.persistence.Account;
import io.github.iy88.project1.account.persistence.AccountRepository;
import io.github.iy88.project1.account.persistence.SessionGuard;
import io.github.iy88.project1.account.persistence.SessionGuardRepository;
import io.github.iy88.project1.account.persistence.SessionRevocation;
import io.github.iy88.project1.account.persistence.SessionRevocationRepository;
import io.github.iy88.project1.core.BusinessError;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.time.Duration;
import java.time.Instant;
import java.util.Base64;
import java.util.UUID;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Profile;
import org.springframework.dao.DataAccessException;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

@Service
@Profile("infrastructure")
public class SessionService {
    private static final SecureRandom RANDOM = new SecureRandom();
    private static final Base64.Encoder ENCODER = Base64.getUrlEncoder().withoutPadding();
    private static final Base64.Decoder DECODER = Base64.getUrlDecoder();

    private final AccountRepository accounts;
    private final SessionGuardRepository guards;
    private final SessionRevocationRepository revocations;
    private final StringRedisTemplate redis;
    private final AccountSettings settings;
    private final String namespace;
    private final TransactionTemplate transaction;

    public SessionService(AccountRepository accounts, SessionGuardRepository guards,
                          SessionRevocationRepository revocations, StringRedisTemplate redis,
                          AccountSettings settings, @Value("${project1.redis.namespace}") String namespace,
                          PlatformTransactionManager manager) {
        this.accounts = accounts;
        this.guards = guards;
        this.revocations = revocations;
        this.redis = redis;
        this.settings = settings;
        this.namespace = namespace;
        this.transaction = new TransactionTemplate(manager);
    }

    /** Creates the guard inside the caller's account transaction; Redis is written by {@link #complete}. */
    public Prepared prepare(Account account) {
        if (!org.springframework.transaction.support.TransactionSynchronizationManager
                .isActualTransactionActive()) {
            throw new IllegalStateException("Session guards must be created inside the account transaction");
        }
        Instant now = Instant.now();
        byte[] token = randomBytes();
        byte[] csrf = randomBytes();
        byte[] tokenDigest = sha256(token);
        String csrfToken = ENCODER.encodeToString(csrf);
        byte[] csrfDigest = sha256(csrfToken.getBytes(java.nio.charset.StandardCharsets.UTF_8));
        UUID sessionId = UUID.randomUUID();
        Instant absoluteExpiresAt = now.plusSeconds(settings.sessionAbsoluteSeconds());
        SessionGuard guard = new SessionGuard(sessionId, tokenDigest, account.id(), account.credentialVersion(),
                now, absoluteExpiresAt, settings.sessionIdleSeconds(), settings.sessionRenewIntervalSeconds(),
                csrfDigest);
        guards.save(guard);
        return new Prepared(sessionId, ENCODER.encodeToString(token), csrfToken, account, now, absoluteExpiresAt,
                tokenDigest);
    }

    /** Writes the Redis value after the guard transaction commits. */
    public Issued complete(Prepared prepared) {
        try {
            store(prepared.sessionId(), prepared.tokenDigest(), prepared.absoluteExpiresAt(), prepared.issuedAt());
        } catch (DataAccessException unavailable) {
            revokePersisted(prepared.sessionId(), prepared.issuedAt());
            throw unavailable();
        }
        return new Issued(prepared.sessionId(), prepared.token(), prepared.csrfToken(), prepared.account(),
                prepared.issuedAt(), prepared.absoluteExpiresAt());
    }

    /**
     * Revalidates the current session from PostgreSQL and its Redis projection.
     *
     * <p>Writes lock the account row before the guard row so password, email and session changes keep
     * the existing account-first order. Reads do not renew the idle timestamp.
     */
    public Account requireCurrent(long accountId, UUID sessionId, long credentialVersion, boolean lockForWrite) {
        if (accountId <= 0 || sessionId == null) {
            throw required();
        }
        try {
            Account account = (lockForWrite ? accounts.lockById(accountId) : accounts.findById(accountId))
                    .orElseThrow(SessionService::required);
            SessionGuard guard = (lockForWrite ? guards.lockById(sessionId) : guards.findById(sessionId))
                    .orElseThrow(SessionService::required);
            if (guard.accountId() != accountId || guard.credentialVersion() != credentialVersion
                    || account.credentialVersion() != credentialVersion || guard.revoked()) {
                throw required();
            }
            Instant now = Instant.now();
            if (!now.isBefore(guard.absoluteExpiresAt())) {
                throw required();
            }
            String value = redis.opsForValue().get(redisKey(guard.tokenDigest()));
            if (value == null) {
                throw required();
            }
            UUID storedSessionId;
            long lastActivity;
            try {
                String[] parts = value.split("\\|", -1);
                storedSessionId = UUID.fromString(parts[0]);
                lastActivity = Long.parseLong(parts[1]);
            } catch (RuntimeException malformed) {
                throw required();
            }
            if (!sessionId.equals(storedSessionId)
                    || now.getEpochSecond() >= lastActivity + guard.idleTimeoutSeconds()) {
                throw required();
            }
            return account;
        } catch (DataAccessException unavailable) {
            throw unavailable();
        }
    }

    public Identity authenticate(String cookieToken) {
        byte[] digest = digestOfCookie(cookieToken);
        String value;
        try {
            value = redis.opsForValue().get(redisKey(digest));
        } catch (DataAccessException unavailable) {
            throw unavailable();
        }
        if (value == null) {
            throw required();
        }
        UUID sessionId;
        long lastActivity;
        try {
            String[] parts = value.split("\\|", -1);
            sessionId = UUID.fromString(parts[0]);
            lastActivity = Long.parseLong(parts[1]);
        } catch (RuntimeException malformed) {
            throw required();
        }
        SessionGuard guard = guards.findById(sessionId).orElseThrow(SessionService::required);
        Account account = accounts.findById(guard.accountId()).orElseThrow(SessionService::required);
        Instant now = Instant.now();
        if (guard.revoked() || !now.isBefore(guard.absoluteExpiresAt())
                || now.getEpochSecond() >= lastActivity + guard.idleTimeoutSeconds()
                || account.credentialVersion() != guard.credentialVersion()) {
            throw required();
        }
        if (now.getEpochSecond() - lastActivity >= guard.renewIntervalSeconds()) {
            try {
                store(sessionId, guard.tokenDigest(), guard.absoluteExpiresAt(), now);
            } catch (DataAccessException ignored) {
                // Renewal failures keep the persisted validity untouched.
            }
        }
        return new Identity(account, guard);
    }

    public void revoke(Identity identity) {
        Instant now = Instant.now();
        transaction.executeWithoutResult(status -> {
            SessionGuard guard = guards.lockById(identity.guard().id()).orElseThrow(SessionService::required);
            if (guard.revoke(now)) {
                guards.save(guard);
                revocations.save(new SessionRevocation(guard.id(), now));
            }
        });
        try {
            redis.delete(redisKey(identity.guard().tokenDigest()));
        } catch (DataAccessException ignored) {
            // The persisted revocation already makes the session unusable.
        }
    }

    public static byte[] sha256(byte[] value) {
        try {
            return MessageDigest.getInstance("SHA-256").digest(value);
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException(impossible);
        }
    }

    private void revokePersisted(UUID sessionId, Instant now) {
        try {
            transaction.executeWithoutResult(status -> {
                guards.lockById(sessionId).ifPresent(guard -> {
                    if (guard.revoke(now)) {
                        guards.save(guard);
                        revocations.save(new SessionRevocation(guard.id(), now));
                    }
                });
            });
        } catch (RuntimeException ignored) {
            // Best effort: the unreachable Redis value expires on its own.
        }
    }

    private void store(UUID sessionId, byte[] tokenDigest, Instant absoluteExpiresAt, Instant activity) {
        long idleSeconds = Duration.between(activity, absoluteExpiresAt).toSeconds();
        long ttl = Math.max(1, Math.min(idleSeconds, settings.sessionIdleSeconds()));
        redis.opsForValue().set(redisKey(tokenDigest), sessionId + "|" + activity.getEpochSecond(),
                Duration.ofSeconds(ttl));
    }

    private String redisKey(byte[] tokenDigest) {
        return namespace + ":session:" + hex(tokenDigest);
    }

    private static byte[] digestOfCookie(String token) {
        if (token == null || token.isBlank()) {
            throw required();
        }
        try {
            return sha256(DECODER.decode(token));
        } catch (IllegalArgumentException invalid) {
            throw required();
        }
    }

    private static byte[] randomBytes() {
        byte[] value = new byte[32];
        RANDOM.nextBytes(value);
        return value;
    }

    private static String hex(byte[] value) {
        StringBuilder text = new StringBuilder(value.length * 2);
        for (byte part : value) {
            text.append(Character.forDigit((part >> 4) & 0xF, 16)).append(Character.forDigit(part & 0xF, 16));
        }
        return text.toString();
    }

    private static BusinessError required() {
        return new BusinessError("AUTHENTICATION_REQUIRED", 401, "登录状态已失效");
    }

    private static BusinessError unavailable() {
        return new BusinessError("AUTHENTICATION_UNAVAILABLE", 503, "身份服务暂不可用");
    }

    public record Prepared(UUID sessionId, String token, String csrfToken, Account account, Instant issuedAt,
                           Instant absoluteExpiresAt, byte[] tokenDigest) {
    }

    public record Issued(UUID sessionId, String token, String csrfToken, Account account, Instant issuedAt,
                         Instant absoluteExpiresAt) {
    }

    public record Identity(Account account, SessionGuard guard) {
    }
}
