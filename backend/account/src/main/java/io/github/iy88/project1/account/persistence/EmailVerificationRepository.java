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

    @Modifying
    @Query("""
            update EmailVerification v set v.invalidatedAt = :now, v.code = null
            where v.accountId = :accountId
              and v.purpose in ('email_change_old', 'email_change_new')
              and v.consumedAt is null and v.invalidatedAt is null
            """)
    int invalidateEmailChange(@Param("accountId") long accountId, @Param("now") Instant now);
}
