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

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select p from Product p where p.id = :id")
    Optional<Product> lockById(@Param("id") long id);

    @Query(value = """
            select p from Product p
            where p.deletedAt is null and p.lifecycleState = 'public'
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
}
