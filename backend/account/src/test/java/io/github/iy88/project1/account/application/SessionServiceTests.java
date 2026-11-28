package io.github.iy88.project1.account.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.catchThrowableOfType;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoMoreInteractions;
import static org.mockito.Mockito.when;

import io.github.iy88.project1.account.AccountSettings;
import io.github.iy88.project1.account.persistence.Account;
import io.github.iy88.project1.account.persistence.AccountRepository;
import io.github.iy88.project1.account.persistence.SessionGuard;
import io.github.iy88.project1.account.persistence.SessionGuardRepository;
import io.github.iy88.project1.account.persistence.SessionRevocation;
import io.github.iy88.project1.account.persistence.SessionRevocationRepository;
import io.github.iy88.project1.core.BusinessError;
import java.time.Instant;
import java.util.Arrays;
import java.util.Base64;
import java.util.HexFormat;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.SimpleTransactionStatus;

/**
 * Session credential-version and revocation boundaries that gate all business pages.
 *
 * <p>The cases model a revoked cookie and a password-change credential bump against mocked Redis
 * values. Real Redis expiry, multi-instance renewal and cookie attributes stay in the account
 * integration suites.
 */
class SessionServiceTests {
    private static final long ACCOUNT_ID = 7L;
    private static final String NAMESPACE = "test:account";

    private final AccountRepository accounts = mock(AccountRepository.class);
    private final SessionGuardRepository guards = mock(SessionGuardRepository.class);
    private final SessionRevocationRepository revocations = mock(SessionRevocationRepository.class);
    private final StringRedisTemplate redis = mock(StringRedisTemplate.class);
    @SuppressWarnings("unchecked")
    private final ValueOperations<String, String> values = mock(ValueOperations.class);
    private final AccountSettings settings = new AccountSettings(12, 256, 64, 3_600, 1_800, 60,
            6, 600, 5, 60, 1_800, "01234567890123456789012345678901", "v1");
    private SessionService service;

    @BeforeEach
    void setUp() {
        PlatformTransactionManager manager = mock(PlatformTransactionManager.class);
        when(manager.getTransaction(any())).thenReturn(new SimpleTransactionStatus());
        when(redis.opsForValue()).thenReturn(values);
        service = new SessionService(accounts, guards, revocations, redis, settings, NAMESPACE, manager);
    }

    @Test
    void aSessionIssuedBeforeTheCredentialVersionChangeIsRejected() {
        Account account = account(2);
        SessionGuard guard = guard(1);
        when(accounts.findById(ACCOUNT_ID)).thenReturn(Optional.of(account));
        when(guards.findById(guard.id())).thenReturn(Optional.of(guard));

        BusinessError failure = catchThrowableOfType(
                BusinessError.class, () -> service.requireCurrent(ACCOUNT_ID, guard.id(), 2, false));

        assertThat(failure).isNotNull();
        assertThat(failure.code()).isEqualTo("AUTHENTICATION_REQUIRED");
        assertThat(failure.status()).isEqualTo(401);
    }

    @Test
    void revokingOneSessionKeepsItsRevocationFactOnceAndOnlyDeletesItsOwnToken() {
        Account account = account(1);
        SessionGuard guard = guard(1);
        when(guards.lockById(guard.id())).thenReturn(Optional.of(guard));
        when(redis.delete(any(String.class))).thenReturn(true);
        SessionService.Identity identity = new SessionService.Identity(account, guard);

        service.revoke(identity);
        service.revoke(identity);

        assertThat(guard.revoked()).isTrue();
        verify(revocations, times(1)).save(any(SessionRevocation.class));
        verify(redis, times(2)).delete(key(guard.tokenDigest()));
        verifyNoMoreInteractions(redis);
    }

    @Test
    void aRevokedCookieCannotAuthenticateEvenWhenItsRedisValueStillExists() {
        SessionGuard guard = guard(1);
        guard.revoke(Instant.now());
        when(guards.findById(guard.id())).thenReturn(Optional.of(guard));
        byte[] token = new byte[32];
        Arrays.fill(token, (byte) 3);
        String cookie = Base64.getUrlEncoder().withoutPadding().encodeToString(token);
        when(values.get(key(SessionService.sha256(token))))
                .thenReturn(guard.id() + "|" + Instant.now().getEpochSecond());

        BusinessError failure = catchThrowableOfType(BusinessError.class, () -> service.authenticate(cookie));

        assertThat(failure).isNotNull();
        assertThat(failure.code()).isEqualTo("AUTHENTICATION_REQUIRED");
        assertThat(failure.status()).isEqualTo(401);
    }

    private static Account account(int credentialVersion) {
        Account account = new Account("user@example.com", "User", "hash", Instant.now());
        ReflectionTestUtils.setField(account, "id", ACCOUNT_ID);
        ReflectionTestUtils.setField(account, "credentialVersion", credentialVersion);
        return account;
    }

    private static SessionGuard guard(int credentialVersion) {
        Instant now = Instant.now();
        return new SessionGuard(UUID.randomUUID(), digest(1), ACCOUNT_ID, credentialVersion, now,
                now.plusSeconds(3_600), 1_800, 60, digest(2));
    }

    private static String key(byte[] tokenDigest) {
        return NAMESPACE + ":session:" + HexFormat.of().formatHex(tokenDigest);
    }

    private static byte[] digest(int value) {
        byte[] bytes = new byte[32];
        Arrays.fill(bytes, (byte) value);
        return bytes;
    }
}
