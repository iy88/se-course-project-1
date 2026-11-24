package io.github.iy88.project1.account.persistence;

import jakarta.persistence.LockModeType;
import java.util.Optional;
import java.util.UUID;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.Repository;
import org.springframework.data.repository.query.Param;

public interface SessionGuardRepository extends Repository<SessionGuard, UUID> {
    SessionGuard save(SessionGuard guard);

    Optional<SessionGuard> findById(UUID id);

    Optional<SessionGuard> findByTokenDigest(byte[] tokenDigest);

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select s from SessionGuard s where s.id = :id")
    Optional<SessionGuard> lockById(@Param("id") UUID id);
}
