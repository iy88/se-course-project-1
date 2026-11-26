package io.github.iy88.project1.account.application;

import io.github.iy88.project1.core.BusinessError;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.springframework.context.annotation.Profile;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;

@Service
@Profile("infrastructure")
public class EmailDeliveryService {
    private final JdbcClient jdbc;

    public EmailDeliveryService(JdbcClient jdbc) {
        this.jdbc = jdbc;
    }

    public List<Pending> claim(int limit, int maxAttempts, int leaseSeconds) {
        UUID lease = UUID.randomUUID();
        Instant now = Instant.now();
        Instant leaseUntil = now.plusSeconds(leaseSeconds);
        try {
            return jdbc.sql("""
                            WITH candidate AS (
                                SELECT v.id FROM email_verification v
                                WHERE v.code IS NOT NULL AND v.consumed_at IS NULL AND v.invalidated_at IS NULL
                                  AND v.expires_at > :now
                                  AND v.sent_at IS NULL AND v.next_attempt_at <= :now
                                  AND (v.lease_until IS NULL OR v.lease_until < :now)
                                  AND v.send_attempts < :maxAttempts
                                  AND (v.account_id IS NULL OR EXISTS (
                                      SELECT 1 FROM account a
                                      WHERE a.account_id = v.account_id
                                        AND a.credential_version = v.credential_version
                                  ))
                                ORDER BY v.next_attempt_at, v.id
                                LIMIT :limit
                                FOR UPDATE SKIP LOCKED
                            )
                            UPDATE email_verification v
                            SET lease_token = :lease, lease_until = :leaseUntil,
                                send_attempts = send_attempts + 1
                            FROM candidate
                            WHERE v.id = candidate.id
                            RETURNING v.id, v.email, v.purpose, v.code, v.expires_at, v.lease_token
                            """)
                    .param("now", Timestamp.from(now))
                    .param("maxAttempts", maxAttempts)
                    .param("limit", limit)
                    .param("lease", lease)
                    .param("leaseUntil", Timestamp.from(leaseUntil))
                    .query((row, index) -> new Pending(row.getLong("id"), row.getString("email"),
                            row.getString("purpose"), row.getString("code"), row.getTimestamp("expires_at").toInstant(),
                            row.getObject("lease_token", UUID.class)))
                    .list();
        } catch (DataAccessException unavailable) {
            throw new BusinessError("DEPENDENCY_UNAVAILABLE", 503, "邮件投递暂不可用");
        }
    }

    public void markSent(long id, UUID leaseToken, Instant now) {
        jdbc.sql("""
                        UPDATE email_verification
                        SET sent_at = :now, lease_token = NULL, lease_until = NULL, last_delivery_error = NULL
                        WHERE id = :id AND lease_token = :lease AND sent_at IS NULL
                        """)
                .param("now", Timestamp.from(now))
                .param("id", id)
                .param("lease", leaseToken)
                .update();
    }

    public void markFailed(long id, UUID leaseToken, Instant nextAttemptAt, String errorCategory) {
        jdbc.sql("""
                        UPDATE email_verification
                        SET next_attempt_at = :next, last_delivery_error = :error,
                            lease_token = NULL, lease_until = NULL
                        WHERE id = :id AND lease_token = :lease
                        """)
                .param("next", Timestamp.from(nextAttemptAt))
                .param("error", errorCategory)
                .param("id", id)
                .param("lease", leaseToken)
                .update();
    }

    public record Pending(long id, String email, String purpose, String code, Instant expiresAt, UUID leaseToken) {
    }
}
