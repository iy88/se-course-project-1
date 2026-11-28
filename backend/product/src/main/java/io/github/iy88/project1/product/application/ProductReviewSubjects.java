package io.github.iy88.project1.product.application;

import io.github.iy88.project1.category.application.BannedScopeService;
import io.github.iy88.project1.category.application.CategoryDirectory;
import io.github.iy88.project1.category.application.CategoryService;
import io.github.iy88.project1.category.persistence.CategoryRepository;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.product.persistence.CategoryApplication;
import io.github.iy88.project1.product.persistence.CategoryApplicationRepository;
import io.github.iy88.project1.product.persistence.Product;
import io.github.iy88.project1.product.persistence.ProductAudit;
import io.github.iy88.project1.product.persistence.ProductAuditRepository;
import io.github.iy88.project1.product.persistence.ProductCategory;
import io.github.iy88.project1.product.persistence.ProductCategoryRepository;
import io.github.iy88.project1.product.persistence.ProductRepository;
import io.github.iy88.project1.storage.persistence.FileReferences;
import io.github.iy88.project1.storage.persistence.UploadRegistration;
import jakarta.persistence.EntityManager;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.TreeSet;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionSynchronizationManager;

/**
 * Product-owned review operations used by the shared review orchestrator.
 *
 * <p>The orchestrator authorizes the manager, opens the use-case write transaction and acquires the
 * keys returned by {@link #lockKeys(ProductAudit)} in order. This service then re-reads and writes
 * only product-owned state; it never starts a transaction of its own.
 */
@Service
@Profile("infrastructure")
public class ProductReviewSubjects {
    private final ProductRepository products;
    private final ProductCategoryRepository links;
    private final ProductAuditRepository audits;
    private final CategoryApplicationRepository applications;
    private final CategoryRepository categories;
    private final CategoryDirectory directory;
    private final CategoryService categoryService;
    private final BannedScopeService bannedScope;
    private final FileReferences fileReferences;
    private final ProductService productService;
    private final EntityManager entityManager;

    public ProductReviewSubjects(ProductRepository products, ProductCategoryRepository links,
                                 ProductAuditRepository audits, CategoryApplicationRepository applications,
                                 CategoryRepository categories, CategoryDirectory directory,
                                 CategoryService categoryService, BannedScopeService bannedScope,
                                 FileReferences fileReferences, ProductService productService, EntityManager entityManager) {
        this.products = products;
        this.links = links;
        this.audits = audits;
        this.applications = applications;
        this.categories = categories;
        this.directory = directory;
        this.categoryService = categoryService;
        this.bannedScope = bannedScope;
        this.fileReferences = fileReferences;
        this.productService = productService;
        this.entityManager = entityManager;
    }

    public ProductAudit audit(long auditId) {
        return audits.findById(auditId).orElseThrow(ProductReviewSubjects::notVisible);
    }

    public ProductAudit auditByCase(long caseId) {
        return audits.findByCaseId(caseId).orElseThrow(ProductReviewSubjects::notVisible);
    }

    /**
     * Lock keys in the shared product-domain order. Product and audit rows are explicit. The
     * category application has no separate {@link LockPlan.Domain} in this stage, so the product row
     * serializes its writes. Current category links and an application name already matching an
     * existing category are included for category locking.
     */
    public List<LockPlan.Key> lockKeys(ProductAudit audit) {
        if (audit == null) {
            throw notVisible();
        }
        Product product = requireProduct(audit.productId());
        Set<Long> categoryIds = new TreeSet<>(links.activeCategoryIds(product.id()));
        applications.findFirstByProductIdAndStatusOrderByIdDesc(product.id(), "pending")
                .flatMap(application -> categoryService.findActiveCategoryIdByName(application.proposedName()))
                .ifPresent(categoryIds::add);

        List<LockPlan.Key> keys = new ArrayList<>();
        keys.add(new LockPlan.Key(LockPlan.Domain.PRODUCT, List.of(product.id())));
        keys.add(new LockPlan.Key(LockPlan.Domain.PRODUCT_DETAIL, List.of(audit.id())));
        categoryIds.forEach(id -> keys.add(new LockPlan.Key(LockPlan.Domain.CATEGORY, List.of(id))));
        return List.copyOf(keys);
    }

    /** Acquires one planned row lock; the caller's active transaction owns commit and rollback. */
    public void lock(LockPlan.Key key) {
        requireWriteTransaction();
        long id = singlePart(key);
        Object row = switch (key.domain()) {
            case PRODUCT -> products.lockById(id).orElseThrow(ProductReviewSubjects::notVisible);
            case PRODUCT_DETAIL -> audits.lockById(id).orElseThrow(ProductReviewSubjects::notVisible);
            case CATEGORY -> categories.lockById(id).orElseThrow(ProductReviewSubjects::notVisible);
            default -> throw new IllegalArgumentException("Unsupported product review lock domain: " + key.domain());
        };
        // Another transaction could have committed since the lock candidates were read.
        entityManager.refresh(row);
    }

    public void requirePending(ProductAudit audit) {
        if (audit == null || !"pending".equals(audit.status())) {
            throw new BusinessError("REVIEW_NOT_PENDING", 409, "审核已处理");
        }
    }

    public Detail detail(long auditId) {
        ProductAudit audit = audit(auditId);
        Product product = requireProduct(audit.productId());
        CategoryApplication application = applications.findFirstByProductIdOrderByIdDesc(product.id())
                .orElse(null);
        return new Detail(audit, productService.reviewProjection(product), application(application),
                bannedScope.view());
    }

    /**
     * Saves the decision and its effects in the caller's transaction. The latest product content is
     * read after product, audit, application and category rows are locked.
     */
    public Decision decide(long auditId, long managerId, boolean approve, String reason,
                           List<Long> bannedItemIds, Boolean approveCategory, String categoryReason,
                           Instant now) {
        requireWriteTransaction();
        if (now == null || managerId <= 0) {
            throw new BusinessError("INPUT_INVALID", 422, "审核输入无效");
        }
        ProductAudit loaded = audit(auditId);
        requirePending(loaded);
        Product product = products.lockById(loaded.productId())
                .filter(found -> !found.deleted())
                .orElseThrow(ProductReviewSubjects::notVisible);
        ProductAudit audit = audits.lockById(auditId).orElseThrow(ProductReviewSubjects::notVisible);
        requirePending(audit);
        if (!Product.PENDING_REVIEW.equals(product.lifecycleState())) {
            throw new BusinessError("REVIEW_NOT_PENDING", 409, "商品已结束审核");
        }
        Instant updatedAt = product.updatedAt().isAfter(now) ? product.updatedAt() : now;

        String decisionReason = decisionReason(reason, approve);
        List<Long> reviewedBannedItemIds = reviewedBannedItemIds(bannedItemIds);

        Set<Long> activeCategoryIds = new LinkedHashSet<>(links.activeCategoryIds(product.id()));
        Map<Long, String> categoryNames = new LinkedHashMap<>(directory.mainNames(activeCategoryIds));

        CategoryApplication pendingApplication = applications.lockPending(product.id()).orElse(null);
        CategoryApplication resolvedApplication = decideApplication(pendingApplication, approve,
                approveCategory, categoryReason, managerId, product, activeCategoryIds, categoryNames, updatedAt);

        boolean hasSelectableCategory = activeCategoryIds.stream()
                .anyMatch(id -> directory.find(id).map(entry -> entry.selectable()).orElse(false));
        if (approve && !hasSelectableCategory) {
            throw new BusinessError("REVIEW_CATEGORY_INSUFFICIENT", 409,
                    "退回补充：请更换或补充分类");
        }

        List<Long> imageFileIds = currentImageFileIds(product.id());
        Map<String, Object> reviewedContent = reviewedContent(product, activeCategoryIds, categoryNames,
                imageFileIds);
        Map<String, Object> reviewedApplication = applicationSnapshot(resolvedApplication);

        audit.decide(managerId, approve, decisionReason, reviewedContent, reviewedApplication,
                reviewedBannedItemIds, now);
        audits.save(audit);
        product.transition(approve ? Product.PUBLIC : Product.REVIEW_REJECTED, updatedAt);
        products.save(product);

        return new Decision(audit, product, product.contentVersion(), application(resolvedApplication));
    }

    private CategoryApplication decideApplication(CategoryApplication pending, boolean approve,
                                                   Boolean approveCategory, String categoryReason,
                                                   long managerId, Product product,
                                                   Set<Long> activeCategoryIds,
                                                   Map<Long, String> categoryNames, Instant now) {
        if (pending == null) {
            if (approveCategory != null) {
                throw new BusinessError("CATEGORY_APPLICATION_NOT_PENDING", 409, "没有待处理分类申请");
            }
            return null;
        }
        if (approveCategory == null) {
            throw new BusinessError("INPUT_INVALID", 422, "存在待处理分类申请时必须给出分类申请结论");
        }
        if (!approveCategory) {
            String rejection = categoryReason(categoryReason);
            pending.reject(managerId, rejection, now);
            applications.save(pending);
            return pending;
        }
        if (!approve) {
            throw new BusinessError("INPUT_INVALID", 422, "商品未通过审核时不能批准分类申请");
        }

        Optional<Long> existing = categoryService.findActiveCategoryIdByName(pending.proposedName());
        long categoryId;
        String categoryName;
        String resolution;
        if (existing.isPresent()) {
            CategoryDirectory.Info info = directory.find(existing.get())
                    .orElseThrow(() -> new BusinessError("CATEGORY_NOT_SELECTABLE", 409, "分类不可用"));
            if (!info.selectable()) {
                throw new BusinessError("CATEGORY_NOT_SELECTABLE", 409, "分类不可用");
            }
            categories.lockById(info.id())
                    .orElseThrow(() -> new BusinessError("CATEGORY_NOT_SELECTABLE", 409, "分类不可用"));
            categoryId = info.id();
            categoryName = info.mainName();
            resolution = "existing_category";
        } else {
            CategoryService.CategoryDetail created = categoryService.createWithinReview(managerId,
                    pending.proposedName());
            categoryId = parseCategoryId(created.id());
            categoryName = created.mainName();
            resolution = "new_category";
        }

        addCategoryLink(product, categoryId, managerId, now);
        activeCategoryIds.add(categoryId);
        categoryNames.put(categoryId, categoryName);
        pending.approve(managerId, categoryId, resolution, now);
        applications.save(pending);
        return pending;
    }

    private void addCategoryLink(Product product, long categoryId, long managerId, Instant now) {
        if (links.activeCategoryIds(product.id()).contains(categoryId)) {
            return;
        }
        links.save(new ProductCategory(product.id(), categoryId, "application", "admin", managerId, now));
        product.touchContentVersion(now);
    }

    private Map<String, Object> reviewedContent(Product product, Set<Long> categoryIds,
                                                Map<Long, String> categoryNames, List<Long> imageFileIds) {
        List<Map<String, Object>> reviewedCategories = categoryIds.stream()
                .filter(categoryNames::containsKey)
                .map(id -> {
                    Map<String, Object> category = new LinkedHashMap<>();
                    category.put("category_id", Long.toString(id));
                    category.put("name", categoryNames.get(id));
                    return category;
                })
                .toList();
        Map<String, Object> content = new LinkedHashMap<>();
        content.put("content_version", product.contentVersion());
        content.put("title", product.title());
        content.put("description", product.description());
        content.put("price_cents", product.priceCents());
        content.put("image_file_ids", imageFileIds);
        content.put("category_ids", categoryIds.stream().map(String::valueOf).toList());
        content.put("categories", reviewedCategories);
        return content;
    }

    private List<Long> currentImageFileIds(long productId) {
        UploadRegistration.Target target = new UploadRegistration.Target("product", productId);
        return fileReferences.current(target, "image").stream()
                .map(element -> element.fileId())
                .toList();
    }

    private static Map<String, Object> applicationSnapshot(CategoryApplication application) {
        if (application == null) {
            return null;
        }
        Map<String, Object> snapshot = new LinkedHashMap<>();
        snapshot.put("application_id", Long.toString(application.id()));
        snapshot.put("proposed_name", application.proposedName());
        snapshot.put("status", application.status());
        snapshot.put("resolution", application.resolution());
        snapshot.put("resolved_category_id", application.resolvedCategoryId() == null ? null
                : Long.toString(application.resolvedCategoryId()));
        snapshot.put("decision", "approved".equals(application.status()) ? "approved" : "rejected");
        snapshot.put("reason", application.rejectionReason());
        return snapshot;
    }

    private List<Long> reviewedBannedItemIds(List<Long> requested) {
        if (requested == null || requested.isEmpty()) {
            return List.of();
        }
        Set<Long> current = new LinkedHashSet<>();
        for (BannedScopeService.GroupView group : bannedScope.view().groups()) {
            for (BannedScopeService.ItemView item : group.items()) {
                current.add(parseBannedItemId(item.id()));
            }
        }
        Set<Long> reviewed = new LinkedHashSet<>();
        for (Long id : requested) {
            if (id == null || id <= 0 || !current.contains(id)) {
                throw new BusinessError("INPUT_INVALID", 422, "禁发条目标识无效");
            }
            reviewed.add(id);
        }
        return List.copyOf(reviewed);
    }

    private static String decisionReason(String reason, boolean approve) {
        String value = trimToNull(reason);
        if (!approve && value == null) {
            throw new BusinessError("INPUT_INVALID", 422, "不通过时必须填写理由");
        }
        return value;
    }

    private static String categoryReason(String reason) {
        String value = trimToNull(reason);
        if (value == null) {
            throw new BusinessError("INPUT_INVALID", 422, "不批准分类申请时必须填写理由");
        }
        return value;
    }

    private Product requireProduct(long productId) {
        return products.findById(productId)
                .filter(product -> !product.deleted())
                .orElseThrow(ProductReviewSubjects::notVisible);
    }

    private static long singlePart(LockPlan.Key key) {
        if (key == null || key.parts().size() != 1 || key.parts().getFirst() <= 0) {
            throw new IllegalArgumentException("Product review locks require one positive identifier");
        }
        return key.parts().getFirst();
    }

    private static long parseCategoryId(String value) {
        try {
            return Long.parseLong(value);
        } catch (NumberFormatException invalid) {
            throw new IllegalStateException("Created category returned an invalid identifier", invalid);
        }
    }

    private static long parseBannedItemId(String value) {
        try {
            return Long.parseLong(value);
        } catch (NumberFormatException invalid) {
            throw new IllegalStateException("Current banned scope returned an invalid identifier", invalid);
        }
    }

    private static String trimToNull(String value) {
        if (value == null) {
            return null;
        }
        String trimmed = value.trim();
        return trimmed.isEmpty() ? null : trimmed;
    }

    private static void requireWriteTransaction() {
        if (!TransactionSynchronizationManager.isActualTransactionActive()
                || TransactionSynchronizationManager.isCurrentTransactionReadOnly()) {
            throw new IllegalStateException("A shared write transaction is required");
        }
    }

    private static BusinessError notVisible() {
        return new BusinessError("RESOURCE_NOT_VISIBLE", 404, "审核不存在");
    }

    private static Application application(CategoryApplication application) {
        return application == null ? null
                : new Application(Long.toString(application.id()), application.proposedName(),
                application.status());
    }

    public record Detail(ProductAudit audit, ProductService.ProductDetail product, Application application,
                         BannedScopeService.BannedScopeView bannedScope) {
    }

    public record Decision(ProductAudit audit, Product product, int reviewedContentVersion,
                           Application application) {
    }

    public record Application(String id, String proposedName, String status) {
    }
}
