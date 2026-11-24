package io.github.iy88.project1.product.application;

import io.github.iy88.project1.account.persistence.Account;
import io.github.iy88.project1.account.persistence.AccountRepository;
import io.github.iy88.project1.category.CategorySettings;
import io.github.iy88.project1.category.application.CategoryDirectory;
import io.github.iy88.project1.core.BusinessError;
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
import java.util.Set;
import org.springframework.context.annotation.Profile;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

@Service
@Profile("infrastructure")
public class ProductService {
    private final ProductRepository products;
    private final ProductCategoryRepository links;
    private final ProductEditHistoryRepository edits;
    private final ProductAuditRepository audits;
    private final CategoryApplicationRepository applications;
    private final AccountRepository accounts;
    private final CategoryDirectory directory;
    private final ProductSettings settings;
    private final CategorySettings categorySettings;
    private final FileReferences fileReferences;
    private final FileRead fileReads;
    private final OssSettings oss;
    private final JdbcClient jdbc;
    private final TransactionTemplate transaction;

    public ProductService(ProductRepository products, ProductCategoryRepository links,
                          ProductEditHistoryRepository edits, ProductAuditRepository audits,
                          CategoryApplicationRepository applications, AccountRepository accounts,
                          CategoryDirectory directory, ProductSettings settings, CategorySettings categorySettings,
                          FileReferences fileReferences, FileRead fileReads, org.springframework.core.env.Environment environment,
                          JdbcClient jdbc, PlatformTransactionManager manager) {
        this.products = products;
        this.links = links;
        this.edits = edits;
        this.audits = audits;
        this.applications = applications;
        this.accounts = accounts;
        this.directory = directory;
        this.settings = settings;
        this.categorySettings = categorySettings;
        this.fileReferences = fileReferences;
        this.fileReads = fileReads;
        this.oss = new OssSettings(environment.getRequiredProperty("OSS_ENDPOINT"),
                environment.getRequiredProperty("OSS_REGION"), environment.getRequiredProperty("OSS_BUCKET"),
                environment.getRequiredProperty("OSS_PREFIX"), environment.getRequiredProperty("OSS_ACCESS_KEY_ID"),
                environment.getRequiredProperty("OSS_ACCESS_KEY_SECRET"));
        this.jdbc = jdbc;
        this.transaction = new TransactionTemplate(manager);
    }

    public ProductDetail create(long sellerId, CreateCommand command) {
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
            Instant now = Instant.now();
            Product product = products.save(new Product(sellerId, title, description, price, now));
            saveLinks(product.id(), sellerId, categoryIds, now);
            long caseId = nextCaseId();
            ProductAudit audit = audits.save(new ProductAudit(product.id(), 1, caseId, now));
            if (proposed != null) {
                applications.save(new CategoryApplication(product.id(), sellerId, proposed, now));
            }
            attachImages(product.id(), sellerId, command.imageFileIds());
            return detail(product, sellerId, audit);
        });
    }

    public ProductDetail edit(long sellerId, long productId, EditCommand command) {
        return transaction.execute(status -> {
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
            Instant now = Instant.now();
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
            if (command.proposedCategoryName() != null) {
                if (!Product.PENDING_REVIEW.equals(product.lifecycleState())
                        && !Product.REVIEW_REJECTED.equals(product.lifecycleState())) {
                    throw new BusinessError("CATEGORY_APPLICATION_NOT_ALLOWED", 409, "当前状态不能提交分类申请");
                }
                if (applications.lockPending(productId).isEmpty()) {
                    applications.save(new CategoryApplication(productId, sellerId,
                            proposedName(command.proposedCategoryName()), now));
                }
            }
            if (command.imageFileIds() != null) {
                replaceImages(productId, sellerId, command.imageFileIds(), now);
            }
            product.editContent(title, description, price, now);
            products.save(product);
            Set<Long> afterCategories = new LinkedHashSet<>(links.activeCategoryIds(productId));
            edits.save(new ProductEditHistory(productId, sellerId, before, snapshot(product, afterCategories), now));
            return detail(product, sellerId, latestAudit(productId));
        });
    }

    public Resubmitted resubmit(long sellerId, long productId, Integer expectedVersion) {
        return transaction.execute(status -> {
            Product product = lockForSeller(sellerId, productId);
            requireVersion(product, expectedVersion);
            ProductAudit latest = latestAudit(productId);
            boolean rejected = Product.REVIEW_REJECTED.equals(product.lifecycleState())
                    || (Product.OFF_SHELF.equals(product.lifecycleState()) && latest != null
                        && "rejected".equals(latest.status()));
            if (!rejected) {
                throw new BusinessError("PRODUCT_NOT_RESUBMITTABLE", 409, "当前商品不能重新提交审核");
            }
            if (links.activeCategoryIds(productId).isEmpty()) {
                throw new BusinessError("CATEGORY_REQUIRED", 422, "商品至少需要一个分类");
            }
            Instant now = Instant.now();
            int sequence = audits.maxSequence(productId) + 1;
            ProductAudit audit = audits.save(new ProductAudit(productId, sequence, nextCaseId(), now));
            product.transition(Product.PENDING_REVIEW, now);
            products.save(product);
            return new Resubmitted(Long.toString(audit.id()), Long.toString(audit.caseId()),
                    product.lifecycleState(), product.contentVersion());
        });
    }

    public Withdrawn withdraw(long sellerId, long productId, Integer expectedVersion) {
        return transaction.execute(status -> {
            Product product = lockForSeller(sellerId, productId);
            requireVersion(product, expectedVersion);
            if (!Product.PENDING_REVIEW.equals(product.lifecycleState())) {
                throw new BusinessError("STATE_CONFLICT", 409, "商品不在待审核状态");
            }
            ProductAudit audit = audits.lockPending(productId)
                    .orElseThrow(() -> new BusinessError("REVIEW_NOT_PENDING", 409, "没有待处理审核"));
            Instant now = Instant.now();
            audit.withdraw(now);
            audits.save(audit);
            applications.lockPending(productId).ifPresent(application -> {
                application.withdraw(now);
                applications.save(application);
            });
            product.transition(Product.OFF_SHELF, now);
            products.save(product);
            return new Withdrawn(Product.OFF_SHELF, "withdrawn", "withdrawn", product.contentVersion());
        });
    }

    public OffShelf offShelf(long sellerId, long productId, Integer expectedVersion) {
        return transaction.execute(status -> {
            Product product = lockForSeller(sellerId, productId);
            requireVersion(product, expectedVersion);
            if (!Product.PUBLIC.equals(product.lifecycleState())) {
                throw new BusinessError("STATE_CONFLICT", 409, "商品不在公开状态");
            }
            if (product.occupiedByTradeId() != null) {
                throw new BusinessError("PRODUCT_LOCKED", 409, "商品存在未结束交易");
            }
            product.transition(Product.OFF_SHELF, Instant.now());
            products.save(product);
            return new OffShelf(detail(product, sellerId, latestAudit(productId)), 0);
        });
    }

    public ProductDetail onShelf(long sellerId, long productId, Integer expectedVersion) {
        return transaction.execute(status -> {
            Product product = lockForSeller(sellerId, productId);
            requireVersion(product, expectedVersion);
            if (!Product.OFF_SHELF.equals(product.lifecycleState())) {
                throw new BusinessError("STATE_CONFLICT", 409, "商品不在已下架状态");
            }
            ProductAudit latest = latestAudit(productId);
            if (latest == null || !"passed".equals(latest.status())) {
                throw new BusinessError("PRODUCT_NOT_RELISTABLE", 409, "最新审核未通过，不能重新上架");
            }
            product.transition(Product.PUBLIC, Instant.now());
            products.save(product);
            return detail(product, sellerId, latest);
        });
    }

    public ApplicationCreated createApplication(long sellerId, long productId, String proposedName) {
        String name = proposedName(proposedName);
        if (name == null) {
            throw new BusinessError("INPUT_INVALID", 422, "分类名称无效");
        }
        return transaction.execute(status -> {
            Product product = lockForSeller(sellerId, productId);
            if (!Product.PENDING_REVIEW.equals(product.lifecycleState())
                    && !Product.REVIEW_REJECTED.equals(product.lifecycleState())) {
                throw new BusinessError("CATEGORY_APPLICATION_NOT_ALLOWED", 409, "当前状态不能提交分类申请");
            }
            if (applications.lockPending(productId).isPresent()) {
                throw new BusinessError("CATEGORY_APPLICATION_CONFLICT", 409, "已有待处理分类申请");
            }
            CategoryApplication application = applications.save(new CategoryApplication(productId, sellerId, name,
                    Instant.now()));
            return new ApplicationCreated(Long.toString(application.id()), application.status());
        });
    }

    public void withdrawApplication(long sellerId, long productId) {
        transaction.executeWithoutResult(status -> {
            Product product = lockForSeller(sellerId, productId);
            if (!Product.PENDING_REVIEW.equals(product.lifecycleState())
                    && !Product.REVIEW_REJECTED.equals(product.lifecycleState())) {
                throw new BusinessError("CATEGORY_APPLICATION_NOT_PENDING", 409, "没有待处理分类申请");
            }
            CategoryApplication application = applications.lockPending(productId)
                    .orElseThrow(() -> new BusinessError("CATEGORY_APPLICATION_NOT_PENDING", 409, "没有待处理分类申请"));
            application.withdraw(Instant.now());
            applications.save(application);
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
                .filter(found -> !found.deleted())
                .orElseThrow(() -> new BusinessError("RESOURCE_NOT_VISIBLE", 404, "商品不存在"));
        boolean owner = product.sellerAccountId() == viewerId;
        if (!owner && !Product.PUBLIC.equals(product.lifecycleState())) {
            throw new BusinessError("RESOURCE_NOT_VISIBLE", 404, "商品不存在");
        }
        return detail(product, owner ? viewerId : 0, owner ? latestAudit(productId) : null);
    }

    public boolean ownsProduct(long accountId, long productId) {
        return products.findById(productId)
                .filter(product -> !product.deleted() && product.sellerAccountId() == accountId)
                .isPresent();
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

    public PageResult<EditView> editHistory(long viewerId, long productId, Integer page, Integer pageSize) {
        Product product = products.findById(productId).filter(found -> !found.deleted())
                .orElseThrow(() -> new BusinessError("RESOURCE_NOT_VISIBLE", 404, "商品不存在"));
        if (product.sellerAccountId() != viewerId) {
            throw new BusinessError("RESOURCE_NOT_VISIBLE", 404, "商品不存在");
        }
        int currentPage = page == null ? 1 : page;
        int size = pageSize == null ? settings.pageSize() : pageSize;
        if (currentPage < 1 || size < 1 || size > settings.pageSizeMax()) {
            throw new BusinessError("INPUT_INVALID", 422, "分页参数无效");
        }
        var pageResult = edits.findByProductIdOrderByEditedAtDescIdDesc(productId,
                PageRequest.of(currentPage - 1, size));
        List<EditView> items = pageResult.getContent().stream()
                .map(edit -> new EditView(Long.toString(edit.id()), edit.editedAt(), edit.operatorKind(),
                        edit.editKind(), edit.beforeContent(), edit.afterContent(), edit.reason()))
                .toList();
        return new PageResult<>(items, currentPage, size, pageResult.getTotalElements());
    }

    private ProductDetail detail(Product product, long ownerId, ProductAudit audit) {
        List<Long> categoryIds = links.activeCategoryIds(product.id());
        Map<Long, String> names = directory.mainNames(categoryIds);
        List<CategoryRef> categories = categoryIds.stream().filter(names::containsKey)
                .map(id -> new CategoryRef(Long.toString(id), names.get(id))).toList();
        Account seller = accounts.findById(product.sellerAccountId()).orElse(null);
        SellerRef sellerRef = new SellerRef(Long.toString(product.sellerAccountId()),
                seller == null ? "" : seller.displayName());
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
                    Product.OFF_SHELF.equals(product.lifecycleState()) && "passed".equals(audit.status()),
                    Product.PENDING_REVIEW.equals(product.lifecycleState()),
                    Product.REVIEW_REJECTED.equals(product.lifecycleState())
                            || Product.OFF_SHELF.equals(product.lifecycleState()) && "rejected".equals(audit.status()));
        }
        return new ProductDetail(Long.toString(product.id()), product.title(), product.description(),
                product.priceCents(), images(product.id()), categories, sellerRef, product.lifecycleState(),
                product.contentVersion(), product.createdAt(), product.updatedAt(), pending, latest, permissions);
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
        List<ProductSummary> items = new ArrayList<>();
        for (Product product : page) {
            List<CategoryRef> categories = categoriesByProduct.getOrDefault(product.id(), List.of()).stream()
                    .filter(names::containsKey)
                    .map(id -> new CategoryRef(Long.toString(id), names.get(id))).toList();
            items.add(new ProductSummary(Long.toString(product.id()), product.title(), product.priceCents(), null,
                    categories, new SellerRef(Long.toString(product.sellerAccountId()),
                    sellers.getOrDefault(product.sellerAccountId(), "")), product.createdAt()));
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
        if (org.springframework.transaction.support.TransactionSynchronizationManager.isActualTransactionActive()) {
            return List.of();
        }
        var target = new UploadRegistration.Target("product", productId);
        List<ImageRef> images = new ArrayList<>();
        for (FileReferences.Reference reference : fileReferences.current(target, "image")) {
            var read = OssClients.use(oss.endpoint(), oss.region(), oss.accessKeyId(), oss.accessKeySecret(),
                    client -> fileReads.prepare(target, reference.fileId(),
                            new OssFileObjects(client, oss.bucket(), oss.prefix()), () -> { }));
            images.add(new ImageRef(Long.toString(reference.fileId()), read.url().toString(), read.expiresAt()));
        }
        return images;
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

    private long nextCaseId() {
        return jdbc.sql("select nextval('product_review_case_seq')").query(Long.class).single();
    }

    private Map<String, Object> snapshot(Product product, Set<Long> categoryIds) {
        Map<String, Object> snapshot = new LinkedHashMap<>();
        snapshot.put("title", product.title());
        snapshot.put("description", product.description());
        snapshot.put("price_cents", product.priceCents());
        snapshot.put("image_file_ids", List.of());
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

    public record CategoryRef(String id, String name) {
    }

    public record SellerRef(String id, String displayName) {
    }

    public record ReviewRef(String auditId, String caseId, String status, Instant submittedAt, String reason,
                            Instant decidedAt) {
    }

    public record Permissions(boolean canEdit, boolean canOffShelf, boolean canRelist, boolean canWithdrawReview,
                              boolean canSubmitReview) {
    }

    public record ProductSummary(String id, String title, long priceCents, Object thumbnail,
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
                                ReviewRef pendingReview, ReviewRef latestReview, Permissions permissions) {
    }

    public record MyResourceItem(String productId, String title, String lifecycleState, Instant updatedAt) {
    }

    public record MyResources(String kind, List<MyResourceItem> items, int page, int pageSize, long total,
                              Instant asOf) {
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
