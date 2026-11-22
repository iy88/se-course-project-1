package io.github.iy88.project1.account.persistence;

import jakarta.persistence.LockModeType;
import java.util.Optional;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.Repository;
import org.springframework.data.repository.query.Param;

public interface EmailVerificationRepository extends Repository<EmailVerification, Long> {
    EmailVerification save(EmailVerification verification);

    Optional<EmailVerification> findById(long id);

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select v from EmailVerification v where v.id = :id")
    Optional<EmailVerification> lockById(@Param("id") long id);
}
