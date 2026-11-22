package io.github.iy88.project1.product.persistence;

import java.util.List;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.Repository;

public interface ProductCategoryRepository extends Repository<ProductCategory, Long> {
    ProductCategory save(ProductCategory link);

    List<ProductCategory> findByProductIdAndRemovedAtIsNullOrderByCategoryIdAsc(long productId);

    List<ProductCategory> findByProductIdInAndRemovedAtIsNullOrderByProductIdAscCategoryIdAsc(
            List<Long> productIds);

    boolean existsByCategoryIdAndRemovedAtIsNull(long categoryId);

    long countByCategoryIdAndRemovedAtIsNull(long categoryId);

    @Query("select distinct pc.categoryId from ProductCategory pc where pc.productId = :productId and pc.removedAt is null")
    List<Long> activeCategoryIds(long productId);
}
