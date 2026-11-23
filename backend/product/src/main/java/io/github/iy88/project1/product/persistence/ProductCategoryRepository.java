package io.github.iy88.project1.product.persistence;

import java.util.List;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.Repository;
import org.springframework.data.repository.query.Param;

public interface ProductCategoryRepository extends Repository<ProductCategory, Long> {
    ProductCategory save(ProductCategory link);

    List<ProductCategory> findByProductIdAndRemovedAtIsNullOrderByCategoryIdAsc(long productId);

    List<ProductCategory> findByProductIdInAndRemovedAtIsNullOrderByProductIdAscCategoryIdAsc(
            List<Long> productIds);

    boolean existsByCategoryIdAndRemovedAtIsNull(long categoryId);

    long countByCategoryIdAndRemovedAtIsNull(long categoryId);

    @Query("select distinct pc.categoryId from ProductCategory pc where pc.productId = :productId and pc.removedAt is null")
    List<Long> activeCategoryIds(long productId);

    @Query("""
            select count(distinct pc.productId) > 0
            from ProductCategory pc, Product p
            where pc.productId = p.id and pc.categoryId = :categoryId and pc.removedAt is null
              and p.lifecycleState = 'public' and p.deletedAt is null
            """)
    boolean existsPublicProductInCategory(@Param("categoryId") long categoryId);

    @Query("select count(distinct pc.productId) from ProductCategory pc where pc.categoryId = :categoryId")
    long countProductsInCategory(@Param("categoryId") long categoryId);
}
