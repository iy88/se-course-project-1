package io.github.iy88.project1.product.persistence;

import jakarta.persistence.LockModeType;
import java.util.List;
import java.util.Optional;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.Repository;
import org.springframework.data.repository.query.Param;

public interface ProductRepository extends Repository<Product, Long> {
    Product save(Product product);

    Optional<Product> findById(long id);

    List<Product> findByIdIn(List<Long> ids);

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select p from Product p where p.id = :id")
    Optional<Product> lockById(@Param("id") long id);

    @Query("""
            select p from Product p
            where p.sellerAccountId = :sellerId and p.deletedAt is null
              and (:state is null or p.lifecycleState = :state)
            order by p.updatedAt desc, p.id desc
            """)
    Page<Product> findForSeller(@Param("sellerId") long sellerId, @Param("state") String state, Pageable pageable);

    @Query(value = """
            select p from Product p
            where p.deletedAt is null and p.lifecycleState = 'public'
              and not exists (select r.id from ProductDisplayRestriction r
                               where r.productId = p.id and r.releasedAt is null)
              and (:keyword = '' or lower(p.title) like lower(concat('%', :keyword, '%'))
                   or lower(p.description) like lower(concat('%', :keyword, '%')))
              and (:minPrice is null or p.priceCents >= :minPrice)
              and (:maxPrice is null or p.priceCents <= :maxPrice)
              and (:categoryCount = 0 or
                   (select count(distinct pc.categoryId) from ProductCategory pc
                    where pc.productId = p.id and pc.removedAt is null and pc.categoryId in :categoryIds)
                   = :categoryCount)
            order by p.createdAt desc, p.id desc
            """,
            countQuery = """
            select count(p) from Product p
            where p.deletedAt is null and p.lifecycleState = 'public'
              and not exists (select r.id from ProductDisplayRestriction r
                               where r.productId = p.id and r.releasedAt is null)
              and (:keyword = '' or lower(p.title) like lower(concat('%', :keyword, '%'))
                   or lower(p.description) like lower(concat('%', :keyword, '%')))
              and (:minPrice is null or p.priceCents >= :minPrice)
              and (:maxPrice is null or p.priceCents <= :maxPrice)
              and (:categoryCount = 0 or
                   (select count(distinct pc.categoryId) from ProductCategory pc
                    where pc.productId = p.id and pc.removedAt is null and pc.categoryId in :categoryIds)
                   = :categoryCount)
            """)
    Page<Product> search(@Param("keyword") String keyword, @Param("categoryIds") List<Long> categoryIds,
                         @Param("categoryCount") long categoryCount, @Param("minPrice") Long minPrice,
                         @Param("maxPrice") Long maxPrice, Pageable pageable);

    @Query("""
            select p.lifecycleState as state, count(p) as total
            from Product p
            where p.sellerAccountId = :sellerId and p.deletedAt is null
            group by p.lifecycleState
            order by p.lifecycleState
            """)
    List<LifecycleStateCount> findLifecycleStateCountsForSeller(@Param("sellerId") long sellerId);

    /** Closed projection for the grouped lifecycle counts. */
    interface LifecycleStateCount {
        String getState();

        long getTotal();
    }
}
