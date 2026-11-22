package io.github.iy88.project1.product.persistence;

import jakarta.persistence.LockModeType;
import java.util.Optional;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.Repository;
import org.springframework.data.repository.query.Param;

public interface ProductAuditRepository extends Repository<ProductAudit, Long> {
    ProductAudit save(ProductAudit audit);

    Optional<ProductAudit> findById(long id);

    Optional<ProductAudit> findTopByProductIdOrderBySequenceNoDesc(long productId);

    Optional<ProductAudit> findTopByProductIdAndStatusOrderBySequenceNoDesc(long productId, String status);

    @Query("select coalesce(max(a.sequenceNo), 0) from ProductAudit a where a.productId = :productId")
    int maxSequence(@Param("productId") long productId);

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select a from ProductAudit a where a.productId = :productId and a.status = 'pending'")
    Optional<ProductAudit> lockPending(@Param("productId") long productId);
}
