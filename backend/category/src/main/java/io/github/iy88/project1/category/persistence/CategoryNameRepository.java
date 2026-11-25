package io.github.iy88.project1.category.persistence;

import jakarta.persistence.LockModeType;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.Repository;
import org.springframework.data.repository.query.Param;

public interface CategoryNameRepository extends Repository<CategoryName, Long> {
    CategoryName save(CategoryName name);

    Optional<CategoryName> findById(long id);

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select n from CategoryName n where n.id = :id")
    Optional<CategoryName> lockById(@Param("id") long id);

    Optional<CategoryName> findByCategoryIdAndNameKindAndDeactivatedAtIsNull(long categoryId, String nameKind);

    @Query(value = """
            select * from category_name
            where deactivated_at is null
              and normalize_category_name(name) = normalize_category_name(:name)
            """, nativeQuery = true)
    Optional<CategoryName> findActiveByNormalizedName(@Param("name") String name);

    List<CategoryName> findByCategoryIdOrderByIdAsc(long categoryId);

    List<CategoryName> findByDeactivatedAtIsNullOrderByCategoryIdAscIdAsc();

    @Modifying
    @Query("update CategoryName n set n.deactivatedAt = :now where n.categoryId = :categoryId and n.deactivatedAt is null")
    int deactivateAll(@Param("categoryId") long categoryId, @Param("now") Instant now);

    @Modifying
    @Query("update CategoryName n set n.nameKind = 'alias' where n.id = :id and n.nameKind = 'main'")
    int demoteMain(@Param("id") long id);
}
