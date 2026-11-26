package io.github.iy88.project1.account.application;

import io.github.iy88.project1.account.AccountSettings;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.sql.Timestamp;
import java.time.Duration;
import java.time.Instant;
import java.util.Locale;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import org.springframework.context.annotation.Profile;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

/**
 * Persistent send budget for email-verification requests.
 *
 * <p>The budget key is a keyed digest of the normalized address, never the address itself. The
 * primary-key row lock is the transaction-scoped serialization point for one purpose and address,
 * so known and unknown password-reset requests follow the same eligibility path.
 */
@Component
@Profile("infrastructure")
public class EmailRequestBudgetStore {
    private static final String DIGEST_LABEL = "email-request-budget:v1";
    private static final String HMAC = "HmacSHA256";

    private final JdbcClient jdbc;
    private final byte[] digestKey;

    public EmailRequestBudgetStore(JdbcClient jdbc, AccountSettings settings) {
        this.jdbc = jdbc;
        this.digestKey = derive(settings.entrySigningKey());
    }

    /**
     * Reserves one request slot inside the caller's transaction. The transaction is mandatory so
     * the row lock and the business write commit or roll back together.
     *
     * @return zero when the request may proceed, otherwise the positive Retry-After in seconds
     */
    @Transactional(propagation = Propagation.MANDATORY)
    public long reserve(String purpose, String normalizedEmail, Instant now, int intervalSeconds) {
        byte[] digest = digest(purpose, normalizedEmail);
        int inserted = jdbc.sql("""
                        INSERT INTO email_request_budget (purpose, email_digest, last_requested_at)
                        VALUES (:purpose, :digest, :now)
                        ON CONFLICT (purpose, email_digest) DO NOTHING
                        """)
                .param("purpose", purpose)
                .param("digest", digest)
                .param("now", Timestamp.from(now))
                .update();
        if (inserted == 1) {
            return 0L;
        }
        Instant previous = jdbc.sql("""
                        SELECT last_requested_at
                        FROM email_request_budget
                        WHERE purpose = :purpose AND email_digest = :digest
                        FOR UPDATE
                        """)
                .param("purpose", purpose)
                .param("digest", digest)
                .query((row, index) -> row.getTimestamp("last_requested_at").toInstant())
                .single();
        long retryAfter = retryAfter(previous, now, intervalSeconds);
        if (retryAfter > 0L) {
            return retryAfter;
        }
        jdbc.sql("""
                        UPDATE email_request_budget
                        SET last_requested_at = :now
                        WHERE purpose = :purpose AND email_digest = :digest
                        """)
                .param("now", Timestamp.from(now))
                .param("purpose", purpose)
                .param("digest", digest)
                .update();
        return 0L;
    }

    private byte[] digest(String purpose, String normalizedEmail) {
        try {
            Mac mac = Mac.getInstance(HMAC);
            mac.init(new SecretKeySpec(digestKey, HMAC));
            mac.update(purpose.getBytes(StandardCharsets.UTF_8));
            mac.update((byte) 0);
            return mac.doFinal(normalizedEmail.toLowerCase(Locale.ROOT).getBytes(StandardCharsets.UTF_8));
        } catch (GeneralSecurityException impossible) {
            throw new IllegalStateException("Could not key the email request budget", impossible);
        }
    }

    private static byte[] derive(String signingKey) {
        try {
            Mac mac = Mac.getInstance(HMAC);
            mac.init(new SecretKeySpec(signingKey.getBytes(StandardCharsets.UTF_8), HMAC));
            return mac.doFinal(DIGEST_LABEL.getBytes(StandardCharsets.UTF_8));
        } catch (GeneralSecurityException impossible) {
            throw new IllegalStateException("Could not derive the email request budget key", impossible);
        }
    }

    private static long retryAfter(Instant previous, Instant now, int intervalSeconds) {
        Instant eligibleAt = previous.plusSeconds(intervalSeconds);
        if (!now.isBefore(eligibleAt)) {
            return 0L;
        }
        long remainingMillis = Duration.between(now, eligibleAt).toMillis();
        return Math.max(1L, (remainingMillis + 999L) / 1000L);
    }
}
