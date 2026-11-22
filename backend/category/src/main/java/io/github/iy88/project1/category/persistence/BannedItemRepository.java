package io.github.iy88.project1.category.persistence;

import java.util.List;
import java.util.Optional;
import org.springframework.data.repository.Repository;

public interface BannedItemRepository extends Repository<BannedItem, Long> {
    BannedItem save(BannedItem item);

    Optional<BannedItem> findById(long id);

    List<BannedItem> findByDeletedAtIsNullOrderByDisplayOrderAscIdAsc();
}
