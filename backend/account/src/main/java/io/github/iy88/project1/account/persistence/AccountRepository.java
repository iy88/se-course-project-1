package io.github.iy88.project1.account.persistence;

import jakarta.persistence.LockModeType;
import java.util.Optional;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.Repository;
import org.springframework.data.repository.query.Param;

public interface AccountRepository extends Repository<Account, Long> {
    Account save(Account account);

    Optional<Account> findById(long id);

    boolean existsByIdAndRole(long id, String role);

    long count();

    java.util.List<Account> findByIdIn(java.util.Collection<Long> ids);

    @Query(value = "select * from account where normalize_email(email) = normalize_email(:email)", nativeQuery = true)
    Optional<Account> findByEmail(@Param("email") String email);

    @Query(value = "select exists (select 1 from account where normalize_email(email) = normalize_email(:email))",
            nativeQuery = true)
    boolean existsByEmail(@Param("email") String email);

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select a from Account a where a.id = :id")
    Optional<Account> lockById(@Param("id") long id);
}
