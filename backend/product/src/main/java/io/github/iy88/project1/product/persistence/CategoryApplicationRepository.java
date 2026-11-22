package io.github.iy88.project1.product.persistence;

import jakarta.persistence.LockModeType;
import java.util.Optional;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.Repository;
import org.springframework.data.repository.query.Param;

public interface CategoryApplicationRepository extends Repository<CategoryApplication, Long> {
    CategoryApplication save(CategoryApplication application);

    Optional<CategoryApplication> findFirstByProductIdAndStatusOrderByIdDesc(long productId, String status);

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select a from CategoryApplication a where a.productId = :productId and a.status = 'pending'")
    Optional<CategoryApplication> lockPending(@Param("productId") long productId);
}
