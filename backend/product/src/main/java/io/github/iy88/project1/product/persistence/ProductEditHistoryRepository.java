package io.github.iy88.project1.product.persistence;

import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.repository.Repository;

public interface ProductEditHistoryRepository extends Repository<ProductEditHistory, Long> {
    ProductEditHistory save(ProductEditHistory history);

    Page<ProductEditHistory> findByProductIdOrderByEditedAtDescIdDesc(long productId, Pageable pageable);

    long countByProductId(long productId);
}
