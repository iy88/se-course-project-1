package io.github.iy88.project1.category.application;

import io.github.iy88.project1.category.persistence.CategoryNameRepository;
import io.github.iy88.project1.category.persistence.CategoryRepository;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Service;

@Service
@Profile("infrastructure")
public class CategoryDirectory {
    private final CategoryRepository categories;
    private final CategoryNameRepository names;

    public CategoryDirectory(CategoryRepository categories, CategoryNameRepository names) {
        this.categories = categories;
        this.names = names;
    }

    public Optional<Info> find(long categoryId) {
        return categories.findById(categoryId)
                .filter(category -> !category.deleted())
                .flatMap(category -> mainName(category.id())
                        .map(name -> new Info(category.id(), name, !category.disabled())));
    }

    public Map<Long, String> mainNames(Collection<Long> categoryIds) {
        Map<Long, String> result = new LinkedHashMap<>();
        for (Long categoryId : categoryIds.stream().distinct().sorted().toList()) {
            find(categoryId).ifPresent(info -> result.put(info.id(), info.mainName()));
        }
        return result;
    }

    private Optional<String> mainName(long categoryId) {
        return names.findByCategoryIdAndNameKindAndDeactivatedAtIsNull(categoryId, "main")
                .map(entry -> entry.name());
    }

    public record Info(long id, String mainName, boolean selectable) {
    }
}
