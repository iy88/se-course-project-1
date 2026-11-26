package io.github.iy88.project1.account.persistence;

import jakarta.persistence.LockModeType;
import java.time.Instant;
import java.util.Optional;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.Repository;
import org.springframework.data.repository.query.Param;

public interface EmailVerificationRepository extends Repository<EmailVerification, Long> {
    EmailVerification save(EmailVerification verification);

    Optional<EmailVerification> findById(long id);

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select v from EmailVerification v where v.id = :id")
    Optional<EmailVerification> lockById(@Param("id") long id);

    /**
     * Account lookup used to take the account lock before the verification row lock. Returning the
     * scalar avoids loading a stale entity into the persistence context before the locking read.
     */
    @Query("select v.accountId from EmailVerification v where v.id = :id and v.accountId is not null")
    Optional<Long> findAccountIdById(@Param("id") long id);

    /**
     * Latest round for one purpose and normalized address, regardless of the entry that requested
     * it. The caller uses its presence to decide whether old rows need the named invalidation below.
     */
    @Query(value = """
            SELECT * FROM email_verification
            WHERE purpose = :purpose
              AND normalize_email(email) = normalize_email(:email)
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """, nativeQuery = true)
    Optional<EmailVerification> findLatestByPurposeAndEmail(@Param("purpose") String purpose,
                                                            @Param("email") String email);

    /**
     * Invalidates every open round in the same purpose and address scope and clears the original
     * code. Lease fields are released so a delivery worker cannot keep an invalidated row claimed.
     */
    @Modifying(flushAutomatically = true)
    @Query(value = """
            UPDATE email_verification
            SET invalidated_at = :now, code = NULL, lease_token = NULL, lease_until = NULL
            WHERE purpose = :purpose
              AND normalize_email(email) = normalize_email(:email)
              AND consumed_at IS NULL
              AND invalidated_at IS NULL
            """, nativeQuery = true)
    int invalidateActiveByPurposeAndEmail(@Param("purpose") String purpose, @Param("email") String email,
                                          @Param("now") Instant now);

    /**
     * Draws an id from the same identity sequence as email_verification rows without inserting a
     * row. Used only for an unknown password-reset request so both branches return one item.
     */
    @Query(value = "SELECT nextval(pg_get_serial_sequence('email_verification', 'id'))", nativeQuery = true)
    long nextVerificationId();

    @Modifying(flushAutomatically = true)
    @Query("""
            update EmailVerification v
            set v.invalidatedAt = :now, v.code = null, v.leaseToken = null, v.leaseUntil = null
            where v.accountId = :accountId
              and v.purpose in ('email_change_old', 'email_change_new')
              and v.consumedAt is null and v.invalidatedAt is null
            """)
    int invalidateEmailChange(@Param("accountId") long accountId, @Param("now") Instant now);
}
