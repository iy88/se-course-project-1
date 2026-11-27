package io.github.iy88.project1.product.persistence;

import java.time.Instant;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.Repository;
import org.springframework.data.repository.query.Param;

public interface ProductEditHistoryRepository extends Repository<ProductEditHistory, Long> {
    ProductEditHistory save(ProductEditHistory history);

    Page<ProductEditHistory> findByProductIdOrderByEditedAtDescIdDesc(long productId, Pageable pageable);

    /**
     * Buyer scope: changes at or after the request instant, newest first. The page count uses the
     * same predicate, so {@code total} matches the filtered items.
     */
    @Query("""
            select e from ProductEditHistory e
             where e.productId = :productId and e.editedAt >= :editedAt
             order by e.editedAt desc, e.id desc
            """)
    Page<ProductEditHistory> findBuyerHistory(@Param("productId") long productId,
                                              @Param("editedAt") Instant editedAt, Pageable pageable);

    Page<ProductEditHistory> findByProductIdAndBasisTypeAndBasisIdOrderByEditedAtDescIdDesc(
            long productId, String basisType, long basisId, Pageable pageable);

    long countByProductId(long productId);
}
