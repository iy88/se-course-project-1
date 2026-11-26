package io.github.iy88.project1.category.application;

import io.github.iy88.project1.category.CategorySettings;
import io.github.iy88.project1.category.persistence.Category;
import io.github.iy88.project1.category.persistence.CategoryName;
import io.github.iy88.project1.category.persistence.CategoryNameRepository;
import io.github.iy88.project1.category.persistence.CategoryRepository;
import io.github.iy88.project1.core.AuditActions;
import io.github.iy88.project1.core.AuditContext;
import io.github.iy88.project1.core.AuditStore;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ResourceRef;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.context.annotation.Profile;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.data.domain.PageRequest;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

@Service
@Profile("infrastructure")
public class CategoryService {
    private final CategoryRepository categories;
    private final CategoryNameRepository names;
    private final CategorySettings settings;
    private final ObjectProvider<CategoryProductVisibility> productVisibility;
    private final TransactionTemplate transaction;
    private final AuditStore auditRecords;

    public CategoryService(CategoryRepository categories, CategoryNameRepository names, CategorySettings settings,
                           ObjectProvider<CategoryProductVisibility> productVisibility,
                           PlatformTransactionManager manager, AuditStore auditRecords) {
        this.categories = categories;
        this.names = names;
        this.settings = settings;
        this.productVisibility = productVisibility;
        this.transaction = new TransactionTemplate(manager);
        this.auditRecords = auditRecords;
    }

    public List<CategoryView> listPublic() {
        List<CategoryView> views = new ArrayList<>();
        Map<Long, List<CategoryName>> activeNames = activeNamesByCategory();
        for (Category category : categories.activeRecords()) {
            List<CategoryName> current = activeNames.getOrDefault(category.id(), List.of());
            String mainName = current.stream().filter(name -> "main".equals(name.nameKind())).findFirst()
                    .map(CategoryName::name).orElse(null);
            if (mainName == null) {
                continue;
            }
            boolean selectable = !category.disabled();
            boolean hasPublicProducts = hasPublicProducts(category.id());
            if (category.disabled() && !hasPublicProducts) {
                continue;
            }
            List<String> aliases = current.stream().filter(name -> "alias".equals(name.nameKind()))
                    .map(CategoryName::name).toList();
            views.add(new CategoryView(Long.toString(category.id()), mainName, aliases, selectable,
                    hasPublicProducts));
        }
        return views;
    }

    public CategoryPage listAdmin(int page, int pageSize) {
        var result = categories.findByDeletedAtIsNullOrderByIdAsc(PageRequest.of(page - 1, pageSize));
        return new CategoryPage(result.getContent().stream().map(this::detail).toList(),
                page, pageSize, result.getTotalElements());
    }

    /**
     * Resolves an active category by the same normalized name used by the unique index. The category
     * may be disabled; callers decide whether it is still selectable.
     */
    public Optional<Long> findActiveCategoryIdByName(String rawName) {
        String name = name(rawName);
        return names.findActiveByNormalizedName(name)
                .map(CategoryName::categoryId)
                .filter(categoryId -> categories.findById(categoryId)
                        .filter(category -> !category.deleted())
                        .isPresent());
    }

    public CategoryDetail create(long adminId, String rawName, AuditContext auditContext) {
        return create(adminId, rawName, auditContext, true);
    }

    /**
     * Category creation performed while approving a review decision. The enclosing review audit
     * already records the decision, the reviewed content and the application resolution in the same
     * shared transaction, so this path does not append a second business audit.
     */
    public CategoryDetail createWithinReview(long adminId, String rawName) {
        return create(adminId, rawName, null, false);
    }

    private CategoryDetail create(long adminId, String rawName, AuditContext auditContext, boolean recordAudit) {
        String name = name(rawName);
        try {
            return transaction.execute(status -> {
                Instant now = Instant.now();
                Category category = categories.save(new Category(adminId, now));
                CategoryName main = names.save(new CategoryName(category.id(), name, "main", now));
                if (recordAudit) {
                    Map<String, Object> facts = new LinkedHashMap<>();
                    facts.put("main_name", main.name());
                    facts.put("category_name_id", Long.toString(main.id()));
                    facts.put("state", category.state());
                    auditRecords.record(auditContext, AuditActions.CATEGORY_CREATED,
                            new ResourceRef("category", category.id()), null, facts);
                }
                return detail(category);
            });
        } catch (DataIntegrityViolationException conflict) {
            throw nameConflict();
        }
    }

    public CategoryDetail rename(long categoryId, String rawName, AuditContext auditContext) {
        String name = name(rawName);
        try {
            return transaction.execute(status -> {
                Category category = lock(categoryId);
                Instant now = Instant.now();
                CategoryName main = names.findByCategoryIdAndNameKindAndDeactivatedAtIsNull(categoryId, "main")
                        .orElseThrow(() -> new BusinessError("STATE_CONFLICT", 409, "分类缺少有效主名"));
                if (main.name().equals(name)) {
                    return detail(category);
                }
                String previousName = main.name();
                names.demoteMain(main.id());
                CategoryName renamed = names.save(new CategoryName(categoryId, name, "main", now));
                Map<String, Object> facts = new LinkedHashMap<>();
                facts.put("previous_main_name", previousName);
                facts.put("main_name", renamed.name());
                facts.put("category_name_id", Long.toString(renamed.id()));
                facts.put("state", category.state());
                auditRecords.record(auditContext, AuditActions.CATEGORY_RENAMED,
                        new ResourceRef("category", categoryId), null, facts);
                return detail(category);
            });
        } catch (DataIntegrityViolationException conflict) {
            throw nameConflict();
        }
    }

    public AliasCreated addAlias(long categoryId, String rawName, AuditContext auditContext) {
        String name = name(rawName);
        try {
            return transaction.execute(status -> {
                Category category = lock(categoryId);
                CategoryName alias = names.save(new CategoryName(category.id(), name, "alias", Instant.now()));
                Map<String, Object> facts = new LinkedHashMap<>();
                facts.put("category_name_id", Long.toString(alias.id()));
                facts.put("name", alias.name());
                facts.put("kind", alias.nameKind());
                auditRecords.record(auditContext, AuditActions.CATEGORY_ALIAS_ADDED,
                        new ResourceRef("category", categoryId), null, facts);
                return new AliasCreated(Long.toString(alias.id()), alias.name());
            });
        } catch (DataIntegrityViolationException conflict) {
            throw nameConflict();
        }
    }

    public void removeAlias(long categoryId, long categoryNameId, AuditContext auditContext) {
        transaction.executeWithoutResult(status -> {
            lock(categoryId);
            CategoryName name = names.lockById(categoryNameId)
                    .orElseThrow(() -> new BusinessError("RESOURCE_NOT_VISIBLE", 404, "分类名称不存在"));
            if (name.categoryId() != categoryId) {
                throw new BusinessError("RESOURCE_NOT_VISIBLE", 404, "分类名称不存在");
            }
            if (!name.active()) {
                return;
            }
            if (!"alias".equals(name.nameKind())) {
                throw new BusinessError("CATEGORY_NAME_NOT_ALIAS", 409, "主名不能作为别名移除");
            }
            name.deactivate(Instant.now());
            names.save(name);
            Map<String, Object> facts = new LinkedHashMap<>();
            facts.put("category_name_id", Long.toString(name.id()));
            facts.put("name", name.name());
            facts.put("kind", name.nameKind());
            auditRecords.record(auditContext, AuditActions.CATEGORY_ALIAS_REMOVED,
                    new ResourceRef("category", categoryId), null, facts);
        });
    }

    public CategoryDetail disable(long categoryId, AuditContext auditContext) {
        return transaction.execute(status -> {
            Category category = lock(categoryId);
            String previousState = category.state();
            category.disable(Instant.now());
            categories.save(category);
            if (!previousState.equals(category.state())) {
                Map<String, Object> facts = new LinkedHashMap<>();
                facts.put("previous_state", previousState);
                facts.put("current_state", category.state());
                auditRecords.record(auditContext, AuditActions.CATEGORY_DISABLED,
                        new ResourceRef("category", categoryId), null, facts);
            }
            return detail(category);
        });
    }

    public void delete(long categoryId, AuditContext auditContext) {
        transaction.executeWithoutResult(status -> {
            Category category = lockExisting(categoryId);
            if (category.deleted()) {
                return;
            }
            if (associatedProductCount(categoryId) > 0) {
                throw new BusinessError("CATEGORY_NOT_DELETABLE", 409, "分类已关联商品，只能停用");
            }
            Instant now = Instant.now();
            String previousState = category.state();
            category.delete(now);
            categories.save(category);
            names.deactivateAll(categoryId, now);
            Map<String, Object> facts = new LinkedHashMap<>();
            facts.put("previous_state", previousState);
            facts.put("current_state", category.state());
            auditRecords.record(auditContext, AuditActions.CATEGORY_DELETED,
                    new ResourceRef("category", categoryId), null, facts);
        });
    }

    private Category lock(long categoryId) {
        Category category = lockExisting(categoryId);
        if (category.deleted()) {
            throw new BusinessError("RESOURCE_NOT_VISIBLE", 404, "分类不存在");
        }
        return category;
    }

    private Category lockExisting(long categoryId) {
        return categories.lockById(categoryId)
                .orElseThrow(() -> new BusinessError("RESOURCE_NOT_VISIBLE", 404, "分类不存在"));
    }

    private CategoryDetail detail(Category category) {
        List<CategoryName> all = names.findByCategoryIdOrderByIdAsc(category.id());
        String mainName = all.stream().filter(name -> name.active() && "main".equals(name.nameKind()))
                .findFirst().map(CategoryName::name).orElse("");
        List<NameView> views = all.stream()
                .map(name -> new NameView(Long.toString(name.id()), name.name(), name.nameKind(), name.active()))
                .toList();
        return new CategoryDetail(Long.toString(category.id()), category.state(), mainName, views,
                associatedProductCount(category.id()), category.createdAt(), category.disabledAt());
    }

    private Map<Long, List<CategoryName>> activeNamesByCategory() {
        Map<Long, List<CategoryName>> grouped = new LinkedHashMap<>();
        for (CategoryName name : names.findByDeactivatedAtIsNullOrderByCategoryIdAscIdAsc()) {
            grouped.computeIfAbsent(name.categoryId(), key -> new ArrayList<>()).add(name);
        }
        return grouped;
    }

    private boolean hasPublicProducts(long categoryId) {
        CategoryProductVisibility visibility = productVisibility.getIfAvailable();
        return visibility != null && visibility.hasPublicProducts(categoryId);
    }

    private long associatedProductCount(long categoryId) {
        CategoryProductVisibility visibility = productVisibility.getIfAvailable();
        return visibility == null ? 0 : visibility.associatedProductCount(categoryId);
    }

    private String name(String value) {
        String name = value == null ? "" : value.trim();
        if (name.isEmpty() || name.codePointCount(0, name.length()) > settings.nameMaxLength()) {
            throw new BusinessError("INPUT_INVALID", 422, "分类名称无效");
        }
        return name;
    }

    private static BusinessError nameConflict() {
        return new BusinessError("CATEGORY_NAME_CONFLICT", 409, "分类名称已被占用");
    }

    public record CategoryView(String id, String mainName, List<String> aliases, boolean selectable,
                               boolean hasPublicProducts) {
    }

    public record NameView(String categoryNameId, String name, String kind, boolean active) {
    }

    public record CategoryDetail(String id, String state, String mainName, List<NameView> names,
                                 long associatedProductCount, Instant createdAt, Instant disabledAt) {
    }

    public record CategoryPage(List<CategoryDetail> items, int page, int pageSize, long total) {
    }

    public record AliasCreated(String categoryNameId, String name) {
    }
}
