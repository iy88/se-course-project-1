package io.github.iy88.project1.category.persistence;

import jakarta.persistence.LockModeType;
import java.util.List;
import java.util.Optional;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.Repository;
import org.springframework.data.repository.query.Param;

public interface CategoryRepository extends Repository<Category, Long> {
    Category save(Category category);

    Optional<Category> findById(long id);

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select c from Category c where c.id = :id")
    Optional<Category> lockById(@Param("id") long id);

    @Query("select c from Category c where c.deletedAt is null order by c.id")
    List<Category> activeRecords();

    Page<Category> findByDeletedAtIsNullOrderByIdAsc(Pageable pageable);
}
