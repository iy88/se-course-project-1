package io.github.iy88.project1.product.application;

import io.github.iy88.project1.account.application.AccountAvatarService;
import io.github.iy88.project1.account.persistence.Account;
import io.github.iy88.project1.account.persistence.AccountRepository;
import io.github.iy88.project1.category.CategorySettings;
import io.github.iy88.project1.category.application.CategoryDirectory;
import io.github.iy88.project1.core.AuditActions;
import io.github.iy88.project1.core.AuditContext;
import io.github.iy88.project1.core.AuditStore;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteTransaction;
import io.github.iy88.project1.product.ProductSettings;
import io.github.iy88.project1.product.persistence.CategoryApplication;
import io.github.iy88.project1.product.persistence.CategoryApplicationRepository;
import io.github.iy88.project1.product.persistence.Product;
import io.github.iy88.project1.product.persistence.ProductAudit;
import io.github.iy88.project1.product.persistence.ProductAuditRepository;
import io.github.iy88.project1.product.persistence.ProductCategory;
import io.github.iy88.project1.product.persistence.ProductCategoryRepository;
import io.github.iy88.project1.product.persistence.ProductEditHistory;
import io.github.iy88.project1.product.persistence.ProductEditHistoryRepository;
import io.github.iy88.project1.product.persistence.ProductRepository;
import io.github.iy88.project1.storage.FilePurpose;
import io.github.iy88.project1.storage.OssClients;
import io.github.iy88.project1.storage.OssFileObjects;
import io.github.iy88.project1.storage.application.FileRead;
import io.github.iy88.project1.storage.persistence.FileReferences;
import io.github.iy88.project1.storage.persistence.FileRegistry;
import io.github.iy88.project1.storage.persistence.UploadRegistration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.context.annotation.Profile;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionTemplate;

@Service
@Profile("infrastructure")
public class ProductService {
    private final ProductRepository products;
    private final ProductCategoryRepository links;
    private final ProductEditHistoryRepository edits;
    private final ProductAuditRepository audits;
    private final CategoryApplicationRepository applications;
    private final ObjectProvider<ProductReviewCaseLifecycle> reviewCases;
    private final AccountRepository accounts;
    private final AccountWriteGuard writeGuard;
    private final AccountAvatarService avatars;
    private final CategoryDirectory directory;
    private final ProductSettings settings;
    private final CategorySettings categorySettings;
    private final FileReferences fileReferences;
    private final FileRead fileReads;
    private final ProductTradeHistory tradeHistory;
    private final ProductEditNotices editNotices;
    private final CaseCommentAccess cases;
    private final ProductCorrectionNotices correctionNotices;
    private final ProductDisplayRestrictions displayRestrictions;
    private final ObjectProvider<ProductTradeFreeze> tradeFreezes;
    private final OssSettings oss;
    private final JdbcClient jdbc;
    private final TransactionTemplate transaction;
    private final AuditStore auditRecords;

    public ProductService(ProductRepository products, ProductCategoryRepository links,
                          ProductEditHistoryRepository edits, ProductAuditRepository audits,
                          CategoryApplicationRepository applications,
                          ObjectProvider<ProductReviewCaseLifecycle> reviewCases, AccountRepository accounts,
                          AccountAvatarService avatars, AccountWriteGuard writeGuard,
                          CategoryDirectory directory, ProductSettings settings, CategorySettings categorySettings,
                          FileReferences fileReferences, FileRead fileReads, ProductTradeHistory tradeHistory,
                          ProductEditNotices editNotices, CaseCommentAccess cases,
                          ProductCorrectionNotices correctionNotices,
                          ProductDisplayRestrictions displayRestrictions,
                          ObjectProvider<ProductTradeFreeze> tradeFreezes,
                          org.springframework.core.env.Environment environment,
                          JdbcClient jdbc, PlatformTransactionManager manager, AuditStore auditRecords) {
        this.products = products;
        this.links = links;
        this.edits = edits;
        this.audits = audits;
        this.applications = applications;
        this.reviewCases = reviewCases;
        this.accounts = accounts;
        this.writeGuard = writeGuard;
        this.avatars = avatars;
        this.directory = directory;
        this.settings = settings;
        this.categorySettings = categorySettings;
        this.fileReferences = fileReferences;
        this.fileReads = fileReads;
        this.tradeHistory = tradeHistory;
        this.editNotices = editNotices;
        this.cases = cases;
        this.correctionNotices = correctionNotices;
        this.displayRestrictions = displayRestrictions;
        this.tradeFreezes = tradeFreezes;
        this.oss = new OssSettings(environment.getRequiredProperty("OSS_ENDPOINT"),
                environment.getRequiredProperty("OSS_REGION"), environment.getRequiredProperty("OSS_BUCKET"),
                environment.getRequiredProperty("OSS_PREFIX"), environment.getRequiredProperty("OSS_ACCESS_KEY_ID"),
                environment.getRequiredProperty("OSS_ACCESS_KEY_SECRET"));
        this.jdbc = jdbc;
        this.transaction = new TransactionTemplate(manager); // REQUIRED: joins a caller's write transaction.
        this.auditRecords = auditRecords;
    }

    public ProductDetail create(long sellerId, CreateCommand command, AuditContext auditContext) {
        String title = title(command.title());
        String description = description(command.description());
        long price = price(command.priceCents());
        Set<Long> categoryIds = parseIds(command.categoryIds());
        if (categoryIds.isEmpty() && isBlank(command.proposedCategoryName())) {
            throw new BusinessError("CATEGORY_REQUIRED", 422, "请至少选择一个分类或提交新分类申请");
        }
        String proposed = proposedName(command.proposedCategoryName());
        requireSelectable(categoryIds);
        return transaction.execute(status -> {
            writeGuard.requireWritable(sellerId);
            requirePublishOrDelistable(sellerId);
            Instant now = Instant.now();
            Product product = products.save(new Product(sellerId, title, description, price, now));
            saveLinks(product.id(), sellerId, categoryIds, now);
            long caseId = openCase(now);
            ProductAudit audit = audits.save(new ProductAudit(product.id(), 1, caseId, now));
            CategoryApplication application = null;
            if (proposed != null) {
                application = applications.save(new CategoryApplication(product.id(), sellerId, proposed, now));
            }
            attachImages(product.id(), sellerId, command.imageFileIds());
            ProductDetail detail = detail(product, sellerId, audit);
            Map<String, Object> facts = new LinkedHashMap<>();
            facts.put("lifecycle_state", product.lifecycleState());
            facts.put("content_version", product.contentVersion());
            if (application != null) {
                facts.put("category_application_id", Long.toString(application.id()));
            }
            auditRecords.record(auditContext, AuditActions.PRODUCT_SUBMITTED,
                    new ResourceRef("product", product.id()), null, facts);
            return detail;
        });
    }

    /**
     * Seller edit entry. Buyer notices and the business audit are written in this same transaction,
     * so a notification, delivery-intent or audit failure rolls the edit back.
     */
    public ProductDetail edit(long sellerId, long productId, EditCommand command, ExecutionContext context) {
        return edit(sellerId, productId, command,
                new AuditContext(context == null ? internalContext() : context, UUID.randomUUID()));
    }

    public ProductDetail edit(long sellerId, long productId, EditCommand command, AuditContext auditContext) {
        ExecutionContext caller = auditContext.execution();
        return transaction.execute(status -> {
            writeGuard.requireWritable(sellerId);
            Product product = lockForSeller(sellerId, productId);
            if (Product.IN_TRADE.equals(product.lifecycleState())) {
                throw new BusinessError("EDIT_NOT_ALLOWED_IN_TRADE", 409, "交易中不能修改商品");
            }
            requireVersion(product, command.expectedVersion());
            if (command.title() == null && command.description() == null && command.priceCents() == null
                    && command.categoryIds() == null && command.proposedCategoryName() == null
                    && command.imageFileIds() == null) {
                throw new BusinessError("INPUT_INVALID", 422, "没有可更新的内容");
            }
            ProductAudit latest = latestAudit(productId);
            Instant now = Instant.now();
            int versionBefore = product.contentVersion();
            Set<Long> currentCategories = new LinkedHashSet<>(links.activeCategoryIds(productId));
            Map<String, Object> before = snapshot(product, currentCategories);
            String title = command.title() == null ? product.title() : title(command.title());
            String description = command.description() == null ? product.description()
                    : description(command.description());
            long price = command.priceCents() == null ? product.priceCents() : price(command.priceCents());
            if (command.categoryIds() != null) {
                Set<Long> replacement = parseIds(command.categoryIds());
                if (replacement.isEmpty()) {
                    throw new BusinessError("CATEGORY_REQUIRED", 422, "商品至少需要一个分类");
                }
                requireSelectable(replacement);
                for (ProductCategory link : links.findByProductIdAndRemovedAtIsNullOrderByCategoryIdAsc(productId)) {
                    if (!replacement.contains(link.categoryId())) {
                        link.remove(now, "seller", sellerId);
                        links.save(link);
                    }
                }
                saveLinks(productId, sellerId, replacement, now);
            }
            CategoryApplication createdApplication = null;
            if (command.proposedCategoryName() != null) {
                if (!categoryApplicationAllowed(product, latest)) {
                    throw new BusinessError("CATEGORY_APPLICATION_NOT_ALLOWED", 409, "当前状态不能提交分类申请");
                }
                if (applications.lockPending(productId).isEmpty()) {
                    createdApplication = applications.save(new CategoryApplication(productId, sellerId,
                            proposedName(command.proposedCategoryName()), now));
                }
            }
            if (command.imageFileIds() != null) {
                replaceImages(productId, sellerId, command.imageFileIds(), now);
            }
            product.editContent(title, description, price, now);
            products.save(product);
            Set<Long> afterCategories = new LinkedHashSet<>(links.activeCategoryIds(productId));
            Map<String, Object> after = snapshot(product, afterCategories);
            ProductEditHistory edit = edits.save(new ProductEditHistory(productId, sellerId, before, after, now));
            editNotices.productEdited(caller, sellerId, productId, edit.id(), product.title(),
                    Product.PUBLIC.equals(product.lifecycleState()), now);
            ProductDetail detail = detail(product, sellerId, latest);
            Map<String, Object> facts = new LinkedHashMap<>();
            facts.put("edit_id", Long.toString(edit.id()));
            facts.put("content_version_before", versionBefore);
            facts.put("content_version_after", product.contentVersion());
            facts.put("lifecycle_state", product.lifecycleState());
            facts.put("changed_fields", changedFields(before, after));
            if (createdApplication != null) {
                facts.put("category_application_id", Long.toString(createdApplication.id()));
            }
            auditRecords.record(auditContext, AuditActions.PRODUCT_EDITED,
                    new ResourceRef("product", productId), null, facts);
            return detail;
        });
    }

    /**
     * Administrator category correction (API-PRD-032). The acting manager must currently claim the
     * case named by the basis, and that case must cover this product; the same case is stored with
     * the correction history and the seller notice. Lifecycle, trade state, agreement and historical
     * trade snapshots are left untouched.
     */
    public CorrectionResult correctCategory(long managerId, long productId, CorrectionCommand command,
                                            ExecutionContext context) {
        return correctCategory(managerId, productId, command,
                new AuditContext(context == null ? internalContext() : context, UUID.randomUUID()));
    }

    public CorrectionResult correctCategory(long managerId, long productId, CorrectionCommand command,
                                            AuditContext auditContext) {
        String reason = correctionReason(command.reason());
        String basisType = command.basisType() == null ? "" : command.basisType().trim();
        // TC-PRD-035 treats a missing basis as an authority failure, not a malformed request.
        if (basisType.isEmpty() && command.basisId() <= 0) {
            throw new BusinessError("ACTION_NOT_ALLOWED", 403, "需要认领事项作为纠正依据");
        }
        if (!"case".equals(basisType) || command.basisId() <= 0) {
            throw new BusinessError("INPUT_INVALID", 422, "纠正依据无效");
        }
        long caseId = command.basisId();
        Set<Long> replacement = parseIds(command.categoryIds());
        if (replacement.isEmpty()) {
            throw new BusinessError("CATEGORY_REQUIRED", 422, "商品至少需要一个分类");
        }
        ExecutionContext caller = auditContext.execution();
        return transaction.execute(status -> {
            Product product = products.lockById(productId)
                    .filter(found -> !found.deleted())
                    .orElseThrow(() -> new BusinessError("RESOURCE_NOT_VISIBLE", 404, "商品不存在"));
            if (!cases.claimedForProduct(managerId, caseId, productId)) {
                throw new BusinessError("ACTION_NOT_ALLOWED", 403, "只能纠正本人认领事项范围内的商品");
            }
            requireSelectable(replacement);
            Instant now = Instant.now();
            Set<Long> current = new LinkedHashSet<>(links.activeCategoryIds(productId));
            if (current.equals(replacement)) {
                return new CorrectionResult(detail(product, 0, null), categoryRefs(current), categoryRefs(current));
            }
            Map<String, Object> before = snapshot(product, current);
            int versionBefore = product.contentVersion();
            for (ProductCategory link : links.findByProductIdAndRemovedAtIsNullOrderByCategoryIdAsc(productId)) {
                if (!replacement.contains(link.categoryId())) {
                    link.remove(now, "admin", managerId);
                    links.save(link);
                }
            }
            for (Long categoryId : replacement) {
                if (!current.contains(categoryId)) {
                    links.save(ProductCategory.adminCorrection(productId, categoryId, managerId, basisType, caseId,
                            now));
                }
            }
            product.touchContentVersion(now);
            products.save(product);
            Set<Long> after = new LinkedHashSet<>(links.activeCategoryIds(productId));
            ProductEditHistory edit = edits.save(ProductEditHistory.adminCorrection(productId, managerId, before,
                    snapshot(product, after), reason, basisType, caseId, now));
            correctionNotices.categoryCorrected(caller, product.sellerAccountId(), productId, edit.id(), caseId,
                    product.title(), now);
            Map<String, Object> facts = new LinkedHashMap<>();
            facts.put("edit_id", Long.toString(edit.id()));
            facts.put("content_version_before", versionBefore);
            facts.put("content_version_after", product.contentVersion());
            facts.put("previous_category_ids", current.stream().map(String::valueOf).toList());
            facts.put("current_category_ids", after.stream().map(String::valueOf).toList());
            auditRecords.record(auditContext, AuditActions.PRODUCT_CATEGORY_CORRECTED,
                    new ResourceRef("product", productId), new ResourceRef("case", caseId), facts);
            return new CorrectionResult(detail(product, 0, null), categoryRefs(current), categoryRefs(after));
        });
    }

    public Resubmitted resubmit(long sellerId, long productId, Integer expectedVersion, AuditContext auditContext) {
        return transaction.execute(status -> {
            writeGuard.requireWritable(sellerId);
            Product product = lockForSeller(sellerId, productId);
            requireVersion(product, expectedVersion);
            requirePublishOrDelistable(sellerId);
            ProductAudit latest = latestAudit(productId);
            if (!resubmittable(product, latest)) {
                throw new BusinessError("PRODUCT_NOT_RESUBMITTABLE", 409, "当前商品不能重新提交审核");
            }
            boolean hasSelectableCategory = links.activeCategoryIds(productId).stream()
                    .anyMatch(id -> directory.find(id).map(CategoryDirectory.Info::selectable).orElse(false));
            if (!hasSelectableCategory && applications.lockPending(productId).isEmpty()) {
                throw new BusinessError("CATEGORY_REQUIRED", 422, "请至少选择一个分类或提交新分类申请");
            }
            Instant now = Instant.now();
            int sequence = audits.maxSequence(productId) + 1;
            ProductAudit audit = audits.save(new ProductAudit(productId, sequence, openCase(now), now));
            product.transition(Product.PENDING_REVIEW, now);
            products.save(product);
            Map<String, Object> facts = new LinkedHashMap<>();
            facts.put("audit_id", Long.toString(audit.id()));
            facts.put("case_id", Long.toString(audit.caseId()));
            facts.put("lifecycle_state", product.lifecycleState());
            facts.put("content_version", product.contentVersion());
            auditRecords.record(auditContext, AuditActions.PRODUCT_REVIEW_RESUBMITTED,
                    new ResourceRef("product", productId), null, facts);
            return new Resubmitted(Long.toString(audit.id()), Long.toString(audit.caseId()),
                    product.lifecycleState(), product.contentVersion());
        });
    }

    public Withdrawn withdraw(long sellerId, long productId, Integer expectedVersion, AuditContext auditContext) {
        return transaction.execute(status -> {
            writeGuard.requireWritable(sellerId);
            Product product = lockForSeller(sellerId, productId);
            requireVersion(product, expectedVersion);
            if (!Product.PENDING_REVIEW.equals(product.lifecycleState())) {
                throw new BusinessError("STATE_CONFLICT", 409, "商品不在待审核状态");
            }
            ProductAudit audit = audits.lockPending(productId)
                    .orElseThrow(() -> new BusinessError("REVIEW_NOT_PENDING", 409, "没有待处理审核"));
            ProductReviewCaseLifecycle lifecycle = reviewCases.getIfAvailable();
            if (lifecycle != null) {
                lifecycle.requireUnclaimed(audit.caseId());
            }
            Instant now = Instant.now();
            audit.withdraw(now);
            audits.save(audit);
            CategoryApplication pending = applications.lockPending(productId).orElse(null);
            Long applicationId = null;
            if (pending != null) {
                pending.withdraw(now);
                applications.save(pending);
                applicationId = pending.id();
            }
            product.transition(Product.OFF_SHELF, now);
            products.save(product);
            Map<String, Object> facts = new LinkedHashMap<>();
            facts.put("audit_id", Long.toString(audit.id()));
            facts.put("lifecycle_state", product.lifecycleState());
            facts.put("content_version", product.contentVersion());
            if (applicationId != null) {
                facts.put("category_application_id", Long.toString(applicationId));
            }
            auditRecords.record(auditContext, AuditActions.PRODUCT_REVIEW_WITHDRAWN,
                    new ResourceRef("product", productId), null, facts);
            return new Withdrawn(Product.OFF_SHELF, "withdrawn", "withdrawn", product.contentVersion());
        });
    }

    /**
     * Locks the product row and checks the seller may take it off shelf. Callers use this inside a
     * shared {@link WriteTransaction} so the {@code PRODUCT} lock is recorded before trade locks,
     * then close pending requests and call {@link #completeOffShelf} with the real count.
     */
    public void lockForOffShelf(long sellerId, long productId, Integer expectedVersion) {
        writeGuard.requireWritable(sellerId);
        Product product = lockForSeller(sellerId, productId);
        requireOffShelfable(product, expectedVersion);
        requirePublishOrDelistable(sellerId);
    }

    /**
     * Applies the off-shelf transition after pending requests were closed in the same transaction.
     * The product row is locked again, which is a no-op when the caller already holds that row.
     */
    public OffShelf completeOffShelf(long sellerId, long productId, Integer expectedVersion,
                                     int closedPendingRequestCount) {
        if (closedPendingRequestCount < 0) {
            throw new IllegalArgumentException("Closed request count cannot be negative");
        }
        Product product = lockForSeller(sellerId, productId);
        requireOffShelfable(product, expectedVersion);
        requirePublishOrDelistable(sellerId);
        product.transition(Product.OFF_SHELF, Instant.now());
        products.save(product);
        return new OffShelf(detail(product, sellerId, latestAudit(productId)), closedPendingRequestCount);
    }

    /**
     * BR-33/D-50: an active party freeze pauses publication, listing, relisting and active
     * delisting even for unrelated products. It deliberately does not guard ordinary edits,
     * category applications, reviews, favorites or reports; account-ban checks stay in
     * {@link AccountWriteGuard#requireWritable(long)}.
     */
    private void requirePublishOrDelistable(long sellerId) {
        ProductTradeFreeze freezes = tradeFreezes.getIfAvailable();
        if (freezes == null) {
            throw new BusinessError("DEPENDENCY_UNAVAILABLE", 503, "交易资格暂不可用");
        }
        if (freezes.isPartyFrozen(sellerId)) {
            throw new BusinessError("TRADE_FROZEN", 409, "交易冻结期间不能发布、上架或下架商品");
        }
    }

    private static void requireOffShelfable(Product product, Integer expectedVersion) {
        requireVersion(product, expectedVersion);
        if (!Product.PUBLIC.equals(product.lifecycleState())) {
            throw new BusinessError("STATE_CONFLICT", 409, "商品不在公开状态");
        }
        if (product.occupiedByTradeId() != null) {
            throw new BusinessError("PRODUCT_LOCKED", 409, "商品存在未结束交易");
        }
    }

    public static LockPlan.Key offShelfLockKey(long productId) {
        return new LockPlan.Key(LockPlan.Domain.PRODUCT, List.of(productId));
    }

    public ProductDetail onShelf(long sellerId, long productId, Integer expectedVersion, AuditContext auditContext) {
        return transaction.execute(status -> {
            writeGuard.requireWritable(sellerId);
            Product product = lockForSeller(sellerId, productId);
            requireVersion(product, expectedVersion);
            requirePublishOrDelistable(sellerId);
            if (!Product.OFF_SHELF.equals(product.lifecycleState())) {
                throw new BusinessError("STATE_CONFLICT", 409, "商品不在已下架状态");
            }
            ProductAudit latest = latestAudit(productId);
            if (latest == null || !"passed".equals(latest.status())) {
                throw new BusinessError("PRODUCT_NOT_RELISTABLE", 409, "最新审核未通过，不能重新上架");
            }
            if (displayRestrictions.hasActive(productId)) {
                throw new BusinessError("DISPLAY_RESTRICTED", 409, "商品存在展示限制，不能上架");
            }
            product.transition(Product.PUBLIC, Instant.now());
            products.save(product);
            ProductDetail detail = detail(product, sellerId, latest);
            Map<String, Object> facts = new LinkedHashMap<>();
            facts.put("lifecycle_state", product.lifecycleState());
            facts.put("content_version", product.contentVersion());
            auditRecords.record(auditContext, AuditActions.PRODUCT_ON_SHELF,
                    new ResourceRef("product", productId), null, facts);
            return detail;
        });
    }

    public ApplicationCreated createApplication(long sellerId, long productId, String proposedName,
                                                AuditContext auditContext) {
        String name = proposedName(proposedName);
        if (name == null) {
            throw new BusinessError("INPUT_INVALID", 422, "分类名称无效");
        }
        return transaction.execute(status -> {
            writeGuard.requireWritable(sellerId);
            Product product = lockForSeller(sellerId, productId);
            if (!categoryApplicationAllowed(product, latestAudit(productId))) {
                throw new BusinessError("CATEGORY_APPLICATION_NOT_ALLOWED", 409, "当前状态不能提交分类申请");
            }
            if (applications.lockPending(productId).isPresent()) {
                throw new BusinessError("CATEGORY_APPLICATION_CONFLICT", 409, "已有待处理分类申请");
            }
            CategoryApplication application = applications.save(new CategoryApplication(productId, sellerId, name,
                    Instant.now()));
            Map<String, Object> facts = new LinkedHashMap<>();
            facts.put("product_id", Long.toString(productId));
            facts.put("status", application.status());
            auditRecords.record(auditContext, AuditActions.CATEGORY_APPLICATION_CREATED,
                    new ResourceRef("category_application", application.id()), null, facts);
            return new ApplicationCreated(Long.toString(application.id()), application.status());
        });
    }

    public void withdrawApplication(long sellerId, long productId, AuditContext auditContext) {
        transaction.executeWithoutResult(status -> {
            writeGuard.requireWritable(sellerId);
            Product product = lockForSeller(sellerId, productId);
            if (!categoryApplicationAllowed(product, latestAudit(productId))) {
                throw new BusinessError("CATEGORY_APPLICATION_NOT_PENDING", 409, "没有待处理分类申请");
            }
            CategoryApplication application = applications.lockPending(productId)
                    .orElseThrow(() -> new BusinessError("CATEGORY_APPLICATION_NOT_PENDING", 409, "没有待处理分类申请"));
            application.withdraw(Instant.now());
            applications.save(application);
            Map<String, Object> facts = new LinkedHashMap<>();
            facts.put("product_id", Long.toString(productId));
            facts.put("status", application.status());
            auditRecords.record(auditContext, AuditActions.CATEGORY_APPLICATION_WITHDRAWN,
                    new ResourceRef("category_application", application.id()), null, facts);
        });
    }

    public PageResult<ProductSummary> search(long viewerId, String keyword, List<String> categoryIds,
                                             Long minPrice, Long maxPrice, Integer page, Integer pageSize) {
        int currentPage = page == null ? 1 : page;
        int size = pageSize == null ? settings.pageSize() : pageSize;
        if (currentPage < 1 || size < 1 || size > settings.pageSizeMax()) {
            throw new BusinessError("INPUT_INVALID", 422, "分页参数无效");
        }
        if (minPrice != null && minPrice < 0 || maxPrice != null && maxPrice < 0
                || minPrice != null && maxPrice != null && minPrice > maxPrice) {
            throw new BusinessError("INPUT_INVALID", 422, "价格区间无效");
        }
        List<Long> categoryFilter = categoryIds == null || categoryIds.isEmpty()
                ? List.of(0L) : new ArrayList<>(parseIds(categoryIds));
        String term = keyword == null ? "" : keyword.trim();
        Pageable pageable = PageRequest.of(currentPage - 1, size);
        var result = products.search(term, categoryFilter, (long) (categoryIds == null ? 0 : parseIds(categoryIds).size()),
                minPrice, maxPrice, pageable);
        List<ProductSummary> items = summaries(result.getContent());
        return new PageResult<>(items, currentPage, size, result.getTotalElements());
    }

    public ProductDetail detail(long viewerId, long productId) {
        Product product = products.findById(productId)
                .filter(found -> detailVisibleTo(found, viewerId))
                .orElseThrow(() -> new BusinessError("RESOURCE_NOT_VISIBLE", 404, "商品不存在"));
        boolean owner = product.sellerAccountId() == viewerId;
        return detail(product, owner ? viewerId : 0, owner ? latestAudit(productId) : null);
    }

    public Optional<String> notificationTitle(long viewerId, long productId) {
        return products.findById(productId).filter(product -> detailVisibleTo(product, viewerId))
                .map(Product::title);
    }

    private boolean detailVisibleTo(Product product, long viewerId) {
        return !product.deleted()
                && (product.sellerAccountId() == viewerId
                || (Product.PUBLIC.equals(product.lifecycleState()) || Product.IN_TRADE.equals(product.lifecycleState()))
                && !displayRestrictions.hasActive(product.id()));
    }

    public boolean ownsProduct(long accountId, long productId) {
        return products.findById(productId)
                .filter(product -> !product.deleted() && product.sellerAccountId() == accountId)
                .isPresent();
    }

    /**
     * Content projection for a review reader whose manager authorization was already checked by the
     * integration layer. It intentionally carries neither seller permissions nor review state.
     */
    public ProductDetail reviewProjection(Product product) {
        return detail(product, 0, null);
    }

    public MyResources myResources(long accountId, String state, Integer page, Integer pageSize) {
        int currentPage = page == null ? 1 : page;
        int size = pageSize == null ? settings.pageSize() : pageSize;
        if (currentPage < 1 || size < 1 || size > settings.pageSizeMax()) {
            throw new BusinessError("INPUT_INVALID", 422, "分页参数无效");
        }
        String normalized = state == null ? null : state.trim();
        if (normalized != null && !normalized.isEmpty()
                && !Set.of(Product.PENDING_REVIEW, Product.REVIEW_REJECTED, Product.PUBLIC, Product.IN_TRADE,
                Product.OFF_SHELF).contains(normalized)) {
            throw new BusinessError("INPUT_INVALID", 422, "商品状态无效");
        }
        if (normalized != null && normalized.isEmpty()) {
            normalized = null;
        }
        var result = products.findForSeller(accountId, normalized, PageRequest.of(currentPage - 1, size));
        List<MyResourceItem> items = result.getContent().stream()
                .map(product -> new MyResourceItem(Long.toString(product.id()), product.title(),
                        product.lifecycleState(), product.updatedAt()))
                .toList();
        return new MyResources("product", items, currentPage, size, result.getTotalElements(), Instant.now());
    }

    /** Lifecycle counts for the account overview; one row per product, hidden products excluded. */
    public ProductCounts myCounts(long accountId) {
        var rows = jdbc.sql("""
                        select lifecycle_state, count(*) as total
                          from product
                         where seller_account_id = :account and deleted_at is null
                         group by lifecycle_state
                         order by lifecycle_state
                        """)
                .param("account", accountId)
                .query((row, index) -> new StateCount(row.getString("lifecycle_state"), row.getLong("total")))
                .list();
        long total = 0;
        Map<String, Long> byState = new LinkedHashMap<>();
        for (StateCount row : rows) {
            total += row.total();
            byState.put(row.state(), row.total());
        }
        return new ProductCounts(total, byState);
    }

    public PageResult<EditView> editHistory(long viewerId, long productId, Integer page, Integer pageSize) {
        return editHistory(viewerId, productId, null, page, pageSize);
    }

    /**
     * Seller reads the full history. A buyer reads only the changes from their own request time
     * onward, optionally narrowed to one exact trade, with administrator reasons removed.
     */
    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public PageResult<EditView> editHistory(long viewerId, long productId, Long tradeId, Integer page,
                                            Integer pageSize) {
        Product product = products.findById(productId).filter(found -> !found.deleted())
                .orElseThrow(() -> new BusinessError("RESOURCE_NOT_VISIBLE", 404, "商品不存在"));
        boolean seller = product.sellerAccountId() == viewerId;
        ProductTradeHistory.BuyerScope buyerScope = seller ? null
                : tradeHistory.buyerScope(productId, viewerId, tradeId)
                        .orElseThrow(() -> new BusinessError("RESOURCE_NOT_VISIBLE", 404, "商品不存在"));
        int currentPage = page == null ? 1 : page;
        int size = pageSize == null ? settings.pageSize() : pageSize;
        if (currentPage < 1 || size < 1 || size > settings.pageSizeMax()) {
            throw new BusinessError("INPUT_INVALID", 422, "分页参数无效");
        }
        Pageable pageable = PageRequest.of(currentPage - 1, size);
        var pageResult = seller
                ? edits.findByProductIdOrderByEditedAtDescIdDesc(productId, pageable)
                : edits.findBuyerHistory(productId, buyerScope.requestedAt(), pageable);
        List<EditView> items = pageResult.getContent().stream()
                .map(edit -> seller
                        ? new EditView(Long.toString(edit.id()), edit.editedAt(), edit.operatorKind(),
                                edit.editKind(), edit.beforeContent(), edit.afterContent(), edit.reason())
                        : new EditView(Long.toString(edit.id()), edit.editedAt(), edit.operatorKind(),
                                edit.editKind(), buyerContent(edit.beforeContent()),
                                buyerContent(edit.afterContent()), null))
                .toList();
        return new PageResult<>(items, currentPage, size, pageResult.getTotalElements());
    }

    private static ExecutionContext internalContext() {
        return new ExecutionContext(java.util.UUID.randomUUID(), ExecutionContext.ActorKind.SYSTEM,
                "product-edit", null, null, null, "internal");
    }

    private static Map<String, Object> buyerContent(Map<String, Object> content) {
        Map<String, Object> allowed = new LinkedHashMap<>();
        for (String key : List.of("title", "description", "price_cents", "image_file_ids", "category_ids")) {
            if (content != null && content.containsKey(key)) {
                allowed.put(key, content.get(key));
            }
        }
        return allowed;
    }

    private static List<String> changedFields(Map<String, Object> before, Map<String, Object> after) {
        List<String> changed = new ArrayList<>();
        for (String key : List.of("title", "description", "price_cents", "image_file_ids", "category_ids")) {
            if (!Objects.equals(before.get(key), after.get(key))) {
                changed.add(key);
            }
        }
        return changed;
    }

    private ProductDetail detail(Product product, long ownerId, ProductAudit audit) {
        List<Long> categoryIds = links.activeCategoryIds(product.id());
        Map<Long, String> names = directory.mainNames(categoryIds);
        List<CategoryRef> categories = categoryIds.stream().filter(names::containsKey)
                .map(id -> new CategoryRef(Long.toString(id), names.get(id))).toList();
        Account seller = accounts.findById(product.sellerAccountId()).orElse(null);
        SellerRef sellerRef = new SellerRef(Long.toString(product.sellerAccountId()),
                seller == null ? "" : seller.displayName(),
                seller == null ? null : avatars.currentUrl(seller.id()));
        boolean owner = ownerId == product.sellerAccountId();
        ReviewRef pending = null;
        ReviewRef latest = null;
        Permissions permissions = null;
        if (owner && audit != null) {
            if ("pending".equals(audit.status())) {
                pending = review(audit);
            } else {
                latest = review(audit);
            }
            permissions = new Permissions(
                    !Product.IN_TRADE.equals(product.lifecycleState()),
                    Product.PUBLIC.equals(product.lifecycleState()) && product.occupiedByTradeId() == null,
                    Product.OFF_SHELF.equals(product.lifecycleState()) && "passed".equals(audit.status())
                            && !displayRestrictions.hasActive(product.id()),
                    Product.PENDING_REVIEW.equals(product.lifecycleState()),
                    resubmittable(product, audit));
        }
        CategoryApplicationRef categoryApplication = owner
                ? applications.findFirstByProductIdAndStatusOrderByIdDesc(product.id(), "pending")
                .map(found -> new CategoryApplicationRef(Long.toString(found.id()), found.proposedName(),
                        found.status()))
                .orElse(null)
                : null;
        return new ProductDetail(Long.toString(product.id()), product.title(), product.description(),
                product.priceCents(), images(product.id()), categories, sellerRef, product.lifecycleState(),
                product.contentVersion(), product.createdAt(), product.updatedAt(), pending, latest, permissions,
                categoryApplication);
    }

    private List<CategoryRef> categoryRefs(Collection<Long> categoryIds) {
        Map<Long, String> names = directory.mainNames(categoryIds);
        return categoryIds.stream().filter(names::containsKey)
                .map(id -> new CategoryRef(Long.toString(id), names.get(id))).toList();
    }

    /** Shared list projection for callers that already loaded product rows. */
    public List<ProductSummary> summaries(List<Product> page) {
        if (page.isEmpty()) {
            return List.of();
        }
        List<Long> productIds = page.stream().map(Product::id).toList();
        Map<Long, List<Long>> categoriesByProduct = new LinkedHashMap<>();
        for (ProductCategory link : links.findByProductIdInAndRemovedAtIsNullOrderByProductIdAscCategoryIdAsc(
                productIds)) {
            categoriesByProduct.computeIfAbsent(link.productId(), key -> new ArrayList<>()).add(link.categoryId());
        }
        Set<Long> allCategories = new LinkedHashSet<>();
        categoriesByProduct.values().forEach(allCategories::addAll);
        Map<Long, String> names = directory.mainNames(allCategories);
        Set<Long> sellerIds = page.stream().map(Product::sellerAccountId).collect(java.util.stream.Collectors.toSet());
        Map<Long, String> sellers = new LinkedHashMap<>();
        for (Account account : accounts.findByIdIn(sellerIds)) {
            sellers.put(account.id(), account.displayName());
        }
        Map<Long, String> avatarsByAccount = avatars.currentUrls(sellerIds);
        Map<Long, ImageRef> thumbnails = thumbnailImages(fileReferences.firstCurrent(
                "product", productIds, "image"));
        List<ProductSummary> items = new ArrayList<>();
        for (Product product : page) {
            List<CategoryRef> categories = categoriesByProduct.getOrDefault(product.id(), List.of()).stream()
                    .filter(names::containsKey)
                    .map(id -> new CategoryRef(Long.toString(id), names.get(id))).toList();
            items.add(new ProductSummary(Long.toString(product.id()), product.title(), product.priceCents(),
                    thumbnails.get(product.id()),
                    categories, new SellerRef(Long.toString(product.sellerAccountId()),
                    sellers.getOrDefault(product.sellerAccountId(), ""),
                    avatarsByAccount.get(product.sellerAccountId())), product.createdAt()));
        }
        return items;
    }

    private void attachImages(long productId, long sellerId, List<String> values) {
        List<Long> ids = parseFileIds(values);
        if (ids.isEmpty()) {
            return;
        }
        if (ids.size() > settings.imageMaxCount()) {
            throw new BusinessError("INPUT_INVALID", 422, "图片数量超出限制");
        }
        try {
            fileReferences.attach(sellerId, new UploadRegistration.Target("product", productId),
                    FilePurpose.PRODUCT_IMAGE, ids, "image");
        } catch (FileRegistry.Rejected rejected) {
            throw fileError(rejected.getMessage());
        }
    }

    private void replaceImages(long productId, long sellerId, List<String> values, Instant now) {
        List<Long> ids = parseFileIds(values);
        if (ids.size() > settings.imageMaxCount()) {
            throw new BusinessError("INPUT_INVALID", 422, "图片数量超出限制");
        }
        var target = new UploadRegistration.Target("product", productId);
        var current = fileReferences.current(target, "image");
        if (!current.isEmpty()) {
            fileReferences.release(target,
                    current.stream().map(FileReferences.Reference::referenceId).toList(),
                    new FileReferences.RetentionBasis("product_image_replaced", Set.of("s2-v1"), null, Set.of()));
        }
        if (!ids.isEmpty()) {
            try {
                fileReferences.attach(sellerId, target, FilePurpose.PRODUCT_IMAGE, ids, "image");
            } catch (FileRegistry.Rejected rejected) {
                throw fileError(rejected.getMessage());
            }
        }
    }

    private List<ImageRef> images(long productId) {
        boolean transactional = org.springframework.transaction.support.TransactionSynchronizationManager
                .isActualTransactionActive();
        if (transactional && !org.springframework.transaction.support.TransactionSynchronizationManager
                .isCurrentTransactionReadOnly()) {
            return List.of();
        }
        var target = new UploadRegistration.Target("product", productId);
        List<ImageRef> images = new ArrayList<>();
        for (FileReferences.Reference reference : fileReferences.current(target, "image")) {
            var read = OssClients.use(oss.endpoint(), oss.region(), oss.accessKeyId(), oss.accessKeySecret(),
                    client -> {
                        var objects = new OssFileObjects(client, oss.bucket(), oss.prefix());
                        return transactional ? fileReads.signInReadSnapshot(target, reference.fileId(), objects)
                                : fileReads.prepare(target, reference.fileId(), objects, () -> { });
                    });
            images.add(new ImageRef(Long.toString(reference.fileId()), read.url().toString(), read.expiresAt()));
        }
        return images;
    }

    private Map<Long, ImageRef> thumbnailImages(Map<Long, FileReferences.Reference> references) {
        if (references.isEmpty()) {
            return Map.of();
        }
        try {
            return OssClients.use(oss.endpoint(), oss.region(), oss.accessKeyId(), oss.accessKeySecret(),
                    client -> {
                        var objects = new OssFileObjects(client, oss.bucket(), oss.prefix());
                        Map<Long, ImageRef> thumbnails = new LinkedHashMap<>();
                        for (var entry : references.entrySet()) {
                            var reference = entry.getValue();
                            try {
                                var read = fileReads.prepare(reference.target(), reference.fileId(), objects,
                                        () -> { });
                                thumbnails.put(entry.getKey(), new ImageRef(Long.toString(reference.fileId()),
                                        read.url().toString(), read.expiresAt()));
                            } catch (RuntimeException unavailable) {
                                // One unavailable thumbnail must not hide its product from the list.
                            }
                        }
                        return thumbnails;
                    });
        } catch (RuntimeException unavailable) {
            return Map.of();
        }
    }

    private static BusinessError fileError(String code) {
        return switch (code) {
            case "RESOURCE_NOT_VISIBLE" -> new BusinessError("RESOURCE_NOT_VISIBLE", 404, "文件不存在");
            case "FILE_PURPOSE_MISMATCH" -> new BusinessError("FILE_PURPOSE_MISMATCH", 422, "文件用途不符");
            case "FILE_NOT_REFERENCEABLE" -> new BusinessError("FILE_NOT_REFERENCEABLE", 409, "文件尚未核验");
            default -> new BusinessError("INPUT_INVALID", 422, "文件不可用");
        };
    }

    private static List<Long> parseFileIds(List<String> values) {
        if (values == null) {
            return List.of();
        }
        List<Long> ids = new ArrayList<>();
        for (String value : values) {
            try {
                long id = Long.parseLong(value);
                if (id <= 0) {
                    throw new NumberFormatException();
                }
                ids.add(id);
            } catch (NumberFormatException invalid) {
                throw new BusinessError("INPUT_INVALID", 422, "文件标识无效");
            }
        }
        return ids;
    }

    private void saveLinks(long productId, long sellerId, Collection<Long> categoryIds, Instant now) {
        Set<Long> existing = new LinkedHashSet<>(links.activeCategoryIds(productId));
        for (Long categoryId : categoryIds) {
            if (!existing.contains(categoryId)) {
                links.save(new ProductCategory(productId, categoryId, sellerId, now));
            }
        }
    }

    private void requireSelectable(Collection<Long> categoryIds) {
        for (Long categoryId : categoryIds) {
            var info = directory.find(categoryId)
                    .orElseThrow(() -> new BusinessError("CATEGORY_NOT_SELECTABLE", 422, "分类不可用"));
            if (!info.selectable()) {
                throw new BusinessError("CATEGORY_NOT_SELECTABLE", 422, "分类不可用");
            }
        }
    }

    private Product lockForSeller(long sellerId, long productId) {
        Product product = products.lockById(productId)
                .filter(found -> !found.deleted())
                .orElseThrow(() -> new BusinessError("RESOURCE_NOT_VISIBLE", 404, "商品不存在"));
        if (product.sellerAccountId() != sellerId) {
            throw new BusinessError("RESOURCE_NOT_VISIBLE", 404, "商品不存在");
        }
        return product;
    }

    private static void requireVersion(Product product, Integer expectedVersion) {
        if (expectedVersion == null || expectedVersion != product.contentVersion()) {
            throw new BusinessError("VERSION_CONFLICT", 409, "商品内容已被更新");
        }
    }

    private ProductAudit latestAudit(long productId) {
        return audits.findTopByProductIdOrderBySequenceNoDesc(productId).orElse(null);
    }

    /**
     * Shared eligibility for resubmission and the owner-facing permission. A review rejection keeps
     * its own lifecycle; a withdrawal or rejection after a submission lands on off_shelf with the
     * withdrawn or rejected latest audit. Pending and approved off-shelf relisting are excluded.
     */
    private static boolean resubmittable(Product product, ProductAudit latest) {
        if (Product.REVIEW_REJECTED.equals(product.lifecycleState())) {
            return true;
        }
        return Product.OFF_SHELF.equals(product.lifecycleState())
                && latest != null
                && ("rejected".equals(latest.status()) || "withdrawn".equals(latest.status()));
    }

    /**
     * Category applications prepare a replacement category while a review is active or while the
     * product can be resubmitted. Existing pending applications still block a second application;
     * old withdrawn or rejected applications are never reopened.
     */
    private static boolean categoryApplicationAllowed(Product product, ProductAudit latest) {
        return Product.PENDING_REVIEW.equals(product.lifecycleState()) || resubmittable(product, latest);
    }

    private long openCase(Instant submittedAt) {
        ProductReviewCaseLifecycle lifecycle = reviewCases.getIfAvailable();
        return lifecycle == null ? nextCaseId() : lifecycle.open(submittedAt);
    }

    private long nextCaseId() {
        return jdbc.sql("select nextval('product_review_case_seq')").query(Long.class).single();
    }

    private Map<String, Object> snapshot(Product product, Set<Long> categoryIds) {
        Map<String, Object> snapshot = new LinkedHashMap<>();
        snapshot.put("title", product.title());
        snapshot.put("description", product.description());
        snapshot.put("price_cents", product.priceCents());
        snapshot.put("image_file_ids", fileReferences.current(
                        new UploadRegistration.Target("product", product.id()), "image").stream()
                .map(reference -> Long.toString(reference.fileId()))
                .toList());
        snapshot.put("category_ids", categoryIds.stream().map(String::valueOf).toList());
        return snapshot;
    }

    private String title(String value) {
        String title = value == null ? "" : value.trim();
        if (title.isEmpty() || title.codePointCount(0, title.length()) > settings.titleMaxLength()) {
            throw new BusinessError("INPUT_INVALID", 422, "商品标题无效");
        }
        return title;
    }

    private String description(String value) {
        String description = value == null ? "" : value.trim();
        if (description.isEmpty()
                || description.codePointCount(0, description.length()) > settings.descriptionMaxLength()) {
            throw new BusinessError("INPUT_INVALID", 422, "商品描述无效");
        }
        return description;
    }

    private long price(Long value) {
        if (value == null || value < 0 || value > settings.priceMaxCents()) {
            throw new BusinessError("INPUT_INVALID", 422, "价格无效");
        }
        return value;
    }

    private static String correctionReason(String value) {
        String reason = value == null ? "" : value.trim();
        if (reason.isEmpty() || reason.codePointCount(0, reason.length()) > 1000) {
            throw new BusinessError("INPUT_INVALID", 422, "纠正理由无效");
        }
        return reason;
    }

    private String proposedName(String value) {
        if (value == null) {
            return null;
        }
        String name = value.trim();
        if (name.isEmpty() || name.codePointCount(0, name.length()) > categorySettings.nameMaxLength()) {
            throw new BusinessError("INPUT_INVALID", 422, "分类名称无效");
        }
        return name;
    }

    private static boolean isBlank(String value) {
        return value == null || value.isBlank();
    }

    private static Set<Long> parseIds(List<String> values) {
        Set<Long> ids = new LinkedHashSet<>();
        if (values == null) {
            return ids;
        }
        for (String value : values) {
            try {
                long id = Long.parseLong(value);
                if (id <= 0) {
                    throw new NumberFormatException();
                }
                ids.add(id);
            } catch (NumberFormatException invalid) {
                throw new BusinessError("INPUT_INVALID", 422, "标识无效");
            }
        }
        return ids;
    }

    private static ReviewRef review(ProductAudit audit) {
        return new ReviewRef(Long.toString(audit.id()), Long.toString(audit.caseId()), audit.status(),
                audit.submittedAt(), audit.decisionReason(), audit.decidedAt());
    }

    public record CreateCommand(String title, String description, List<String> imageFileIds, Long priceCents,
                                List<String> categoryIds, String proposedCategoryName) {
    }

    public record EditCommand(String title, String description, List<String> imageFileIds, Long priceCents,
                              List<String> categoryIds, String proposedCategoryName, Integer expectedVersion) {
    }

    public record CorrectionCommand(List<String> categoryIds, String reason, String basisType, long basisId) {
    }

    public record CorrectionResult(ProductDetail product, List<CategoryRef> previousCategories,
                                   List<CategoryRef> currentCategories) {
    }

    public record CategoryRef(String id, String name) {
    }

    public record SellerRef(String id, String displayName, String avatarUrl) {
        public SellerRef(String id, String displayName) {
            this(id, displayName, null);
        }
    }

    public record ReviewRef(String auditId, String caseId, String status, Instant submittedAt, String reason,
                            Instant decidedAt) {
    }

    public record Permissions(boolean canEdit, boolean canOffShelf, boolean canRelist, boolean canWithdrawReview,
                              boolean canSubmitReview) {
    }

    public record ProductSummary(String id, String title, long priceCents, ImageRef thumbnail,
                                 List<CategoryRef> categories, SellerRef seller, Instant createdAt) {
    }

    private record OssSettings(String endpoint, String region, String bucket, String prefix, String accessKeyId,
                               String accessKeySecret) {
    }

    public record ImageRef(String fileId, String url, Instant expiresAt) {
    }

    public record ProductDetail(String id, String title, String description, long priceCents,
                                List<ImageRef> images, List<CategoryRef> categories, SellerRef seller,
                                String lifecycleState, int contentVersion, Instant createdAt, Instant updatedAt,
                                ReviewRef pendingReview, ReviewRef latestReview, Permissions permissions,
                                CategoryApplicationRef categoryApplication) {
    }

    public record CategoryApplicationRef(String id, String proposedName, String status) {
    }

    public record MyResourceItem(String productId, String title, String lifecycleState, Instant updatedAt) {
    }

    public record MyResources(String kind, List<MyResourceItem> items, int page, int pageSize, long total,
                              Instant asOf) {
    }

    public record ProductCounts(long total, Map<String, Long> byState) {
        public ProductCounts {
            byState = Map.copyOf(byState);
        }
    }

    private record StateCount(String state, long total) {
    }

    public record EditView(String editId, Instant editedAt, String operatorKind, String editKind,
                           Map<String, Object> beforeContent, Map<String, Object> afterContent, String reason) {
    }

    public record ApplicationCreated(String applicationId, String status) {
    }

    public record Resubmitted(String auditId, String caseId, String lifecycleState, int contentVersion) {
    }

    public record Withdrawn(String lifecycleState, String auditStatus, String categoryApplicationStatus,
                            int contentVersion) {
    }

    public record OffShelf(ProductDetail product, int closedPendingRequestCount) {
    }

    public record PageResult<T>(List<T> items, int page, int pageSize, long total) {
    }
}
