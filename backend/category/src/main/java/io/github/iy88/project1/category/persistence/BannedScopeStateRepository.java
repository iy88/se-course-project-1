package io.github.iy88.project1.category.persistence;

import jakarta.persistence.LockModeType;
import java.util.Optional;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.Repository;

public interface BannedScopeStateRepository extends Repository<BannedScopeState, Boolean> {
    BannedScopeState save(BannedScopeState state);

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select s from BannedScopeState s where s.singleton = true")
    Optional<BannedScopeState> lock();
}
