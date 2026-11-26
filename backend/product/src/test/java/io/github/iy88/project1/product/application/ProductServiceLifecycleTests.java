package io.github.iy88.project1.product.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import io.github.iy88.project1.account.application.AccountAvatarService;
import io.github.iy88.project1.account.persistence.AccountRepository;
import io.github.iy88.project1.category.CategorySettings;
import io.github.iy88.project1.category.application.CategoryDirectory;
import io.github.iy88.project1.core.AuditContext;
import io.github.iy88.project1.core.AuditStore;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
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
import io.github.iy88.project1.storage.application.FileRead;
import io.github.iy88.project1.storage.persistence.FileReferences;
import io.github.iy88.project1.storage.persistence.UploadRegistration;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.core.env.Environment;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.SimpleTransactionStatus;

/**
 * Seller-side lifecycle rules for A07-A14 that are not already covered by the focused edit,
 * correction, freeze and display-restriction suites.
 */
@SuppressWarnings("unchecked")
class ProductServiceLifecycleTests {
    private static final long SELLER = 7L;
    private static final long STRANGER = 8L;
    private static final long PRODUCT = 10L;
    private static final long CATEGORY = 3L;
    private static final long CASE = 44L;
    private static final Instant NOW = Instant.parse("2026-11-26T03:00:00Z");

    private final ProductRepository products = mock(ProductRepository.class);
    private final ProductCategoryRepository links = mock(ProductCategoryRepository.class);
    private final ProductEditHistoryRepository edits = mock(ProductEditHistoryRepository.class);
    private final ProductAuditRepository audits = mock(ProductAuditRepository.class);
    private final CategoryApplicationRepository applications = mock(CategoryApplicationRepository.class);
    private final AccountRepository accounts = mock(AccountRepository.class);
    private final AccountAvatarService avatars = mock(AccountAvatarService.class);
    private final AccountWriteGuard writeGuard = mock(AccountWriteGuard.class);
    private final CategoryDirectory directory = mock(CategoryDirectory.class);
    private final FileReferences fileReferences = mock(FileReferences.class);
    private final ProductEditNotices editNotices = mock(ProductEditNotices.class);
    private final ProductDisplayRestrictions displayRestrictions = mock(ProductDisplayRestrictions.class);
    private final ProductTradeFreeze freeze = mock(ProductTradeFreeze.class);
    private final ProductReviewCaseLifecycle reviewCases = mock(ProductReviewCaseLifecycle.class);
    private final AuditStore auditRecords = mock(AuditStore.class);
    private final AtomicReference<CategoryApplication> savedApplication = new AtomicReference<>();
    private ProductService service;

    @BeforeEach
    void setUp() {
        when(links.activeCategoryIds(anyLong())).thenReturn(List.of(CATEGORY));
        when(links.findByProductIdAndRemovedAtIsNullOrderByCategoryIdAsc(anyLong())).thenReturn(List.of());
        when(links.save(any())).thenAnswer(call -> call.getArgument(0));
        when(directory.find(CATEGORY))
                .thenReturn(Optional.of(new CategoryDirectory.Info(CATEGORY, "Books", true)));
        when(directory.mainNames(any())).thenReturn(Map.of(CATEGORY, "Books"));
        when(accounts.findById(anyLong())).thenReturn(Optional.empty());
        when(fileReferences.current(any(), anyString())).thenReturn(List.of());
        when(products.save(any())).thenAnswer(call -> {
            Product product = call.getArgument(0);
            if (ReflectionTestUtils.getField(product, "id") == null) {
                ReflectionTestUtils.setField(product, "id", PRODUCT);
            }
            return product;
        });
        when(audits.save(any())).thenAnswer(call -> {
            ProductAudit audit = call.getArgument(0);
            if (ReflectionTestUtils.getField(audit, "id") == null) {
                ReflectionTestUtils.setField(audit, "id", 88L);
            }
            return audit;
        });
        when(applications.save(any())).thenAnswer(call -> {
            CategoryApplication application = call.getArgument(0);
            if (ReflectionTestUtils.getField(application, "id") == null) {
                ReflectionTestUtils.setField(application, "id", 77L);
            }
            savedApplication.set(application);
            return application;
        });
        when(applications.findFirstByProductIdAndStatusOrderByIdDesc(anyLong(), eq("pending")))
                .thenAnswer(call -> Optional.ofNullable(savedApplication.get()));
        when(applications.lockPending(anyLong())).thenReturn(Optional.empty());
        when(edits.save(any())).thenAnswer(call -> {
            ProductEditHistory history = call.getArgument(0);
            if (ReflectionTestUtils.getField(history, "id") == null) {
                ReflectionTestUtils.setField(history, "id", 99L);
            }
            return history;
        });
        when(reviewCases.open(any())).thenReturn(CASE);
        ObjectProvider<ProductReviewCaseLifecycle> reviewProvider = mock(ObjectProvider.class);
        when(reviewProvider.getIfAvailable()).thenReturn(reviewCases);
        ObjectProvider<ProductTradeFreeze> freezeProvider = mock(ObjectProvider.class);
        when(freezeProvider.getIfAvailable()).thenReturn(freeze);

        PlatformTransactionManager manager = mock(PlatformTransactionManager.class);
        when(manager.getTransaction(any())).thenReturn(new SimpleTransactionStatus());
        Environment environment = mock(Environment.class);
        when(environment.getRequiredProperty("OSS_ENDPOINT")).thenReturn("https://oss.example");
        when(environment.getRequiredProperty("OSS_REGION")).thenReturn("region");
        when(environment.getRequiredProperty("OSS_BUCKET")).thenReturn("bucket");
        when(environment.getRequiredProperty("OSS_PREFIX")).thenReturn("prefix");
        when(environment.getRequiredProperty("OSS_ACCESS_KEY_ID")).thenReturn("id");
        when(environment.getRequiredProperty("OSS_ACCESS_KEY_SECRET")).thenReturn("secret");
        service = new ProductService(products, links, edits, audits, applications, reviewProvider, accounts,
                avatars, writeGuard, directory,
                new ProductSettings(100, 5_000, 100_000_000, 20, 100, 9, 500, 10, 60),
                new CategorySettings(50, 100), fileReferences, mock(FileRead.class),
                mock(ProductTradeHistory.class), editNotices, mock(CaseCommentAccess.class),
                mock(ProductCorrectionNotices.class), displayRestrictions, freezeProvider, environment,
                mock(JdbcClient.class), manager, auditRecords);
    }

    @Test
    void createWithoutACategoryOrApplicationIsRejectedBeforeWriting() {
        assertFailure(() -> service.create(SELLER, new ProductService.CreateCommand(
                "Book", "Used book", List.of(), 1_000L, List.of(), null), auditContext()), "CATEGORY_REQUIRED");

        verify(products, never()).save(any());
        verify(audits, never()).save(any());
        verify(auditRecords, never()).record(any(), any(), any(), any(), any());
    }

    @Test
    void createOpensPendingReviewAndRegistersCategoryApplicationAndImageReference() {
        when(links.activeCategoryIds(anyLong())).thenReturn(List.of());
        ProductService.ProductDetail created = service.create(SELLER, new ProductService.CreateCommand(
                "Book", "Used book", List.of("501"), 1_000L, List.of(String.valueOf(CATEGORY)),
                "New category"), auditContext());

        assertThat(created.lifecycleState()).isEqualTo(Product.PENDING_REVIEW);
        assertThat(created.contentVersion()).isEqualTo(1);
        assertThat(created.pendingReview()).isNotNull();
        assertThat(created.pendingReview().caseId()).isEqualTo(Long.toString(CASE));
        assertThat(created.categoryApplication()).isNotNull();
        assertThat(created.categoryApplication().status()).isEqualTo("pending");
        verify(links).save(any(ProductCategory.class));
        verify(audits).save(any(ProductAudit.class));
        verify(applications).save(any(CategoryApplication.class));
        verify(fileReferences).attach(eq(SELLER),
                eq(new UploadRegistration.Target("product", PRODUCT)), eq(FilePurpose.PRODUCT_IMAGE),
                eq(List.of(501L)), eq("image"));
    }

    @Test
    void pendingAndRejectedProductsAreHiddenFromStrangersWhilePublicProductsAreReadable() {
        Product pending = product(Product.PENDING_REVIEW, 1);
        when(products.findById(PRODUCT)).thenReturn(Optional.of(pending));
        assertFailure(() -> service.detail(STRANGER, PRODUCT), "RESOURCE_NOT_VISIBLE");

        Product rejected = product(Product.REVIEW_REJECTED, 1);
        when(products.findById(PRODUCT)).thenReturn(Optional.of(rejected));
        assertFailure(() -> service.detail(STRANGER, PRODUCT), "RESOURCE_NOT_VISIBLE");

        Product published = product(Product.PUBLIC, 3);
        when(products.findById(PRODUCT)).thenReturn(Optional.of(published));
        ProductService.ProductDetail detail = service.detail(STRANGER, PRODUCT);
        assertThat(detail.lifecycleState()).isEqualTo(Product.PUBLIC);
        assertThat(detail.permissions()).isNull();
    }

    @Test
    void sellerKeepsTheDetailOfAnOffShelfProductWhileAStrangerGetsNotFound() {
        Product offShelf = product(Product.OFF_SHELF, 2);
        when(products.findById(PRODUCT)).thenReturn(Optional.of(offShelf));

        assertThat(service.detail(SELLER, PRODUCT).lifecycleState()).isEqualTo(Product.OFF_SHELF);
        assertFailure(() -> service.detail(STRANGER, PRODUCT), "RESOURCE_NOT_VISIBLE");
    }

    @Test
    void editingAProductInTradeIsRejectedWithoutHistoryOrNotice() {
        Product inTrade = product(Product.IN_TRADE, 4);
        when(products.lockById(PRODUCT)).thenReturn(Optional.of(inTrade));

        assertFailure(() -> service.edit(SELLER, PRODUCT, new ProductService.EditCommand(
                "New title", null, null, null, null, null, 4), auditContext().execution()),
                "EDIT_NOT_ALLOWED_IN_TRADE");

        verify(products, never()).save(any());
        verify(edits, never()).save(any());
        verify(editNotices, never()).productEdited(any(), anyLong(), anyLong(), anyLong(), any(), any(Boolean.class),
                any());
    }

    @Test
    void editingAPublicProductAdvancesTheVersionAndKeepsBeforeAndAfterHistory() {
        Product published = product(Product.PUBLIC, 1);
        when(products.lockById(PRODUCT)).thenReturn(Optional.of(published));
        ProductService.EditCommand command = new ProductService.EditCommand("New title", null, null, null,
                null, null, 1);

        ProductService.ProductDetail updated = service.edit(SELLER, PRODUCT, command, auditContext().execution());

        assertThat(updated.contentVersion()).isEqualTo(2);
        assertThat(updated.title()).isEqualTo("New title");
        ArgumentCaptor<ProductEditHistory> history = ArgumentCaptor.forClass(ProductEditHistory.class);
        verify(edits).save(history.capture());
        assertThat(history.getValue().beforeContent()).containsEntry("title", "Book");
        assertThat(history.getValue().afterContent()).containsEntry("title", "New title");
        verify(editNotices).productEdited(any(), eq(SELLER), eq(PRODUCT), eq(99L), eq("New title"), eq(true), any());
    }

    @Test
    void offShelfLockRejectsAProductWithTradeOccupancy() {
        Product locked = product(Product.PUBLIC, 1);
        ReflectionTestUtils.setField(locked, "occupiedByTradeId", 33L);
        when(products.lockById(PRODUCT)).thenReturn(Optional.of(locked));

        assertFailure(() -> service.lockForOffShelf(SELLER, PRODUCT, 1), "PRODUCT_LOCKED");

        verify(products, never()).save(any());
        assertThat(locked.lifecycleState()).isEqualTo(Product.PUBLIC);
    }

    @Test
    void relistIsRejectedWhenTheLatestReviewDidNotPass() {
        Product offShelf = product(Product.OFF_SHELF, 1);
        ProductAudit rejected = mock(ProductAudit.class);
        when(rejected.status()).thenReturn("rejected");
        when(products.lockById(PRODUCT)).thenReturn(Optional.of(offShelf));
        when(audits.findTopByProductIdOrderBySequenceNoDesc(PRODUCT)).thenReturn(Optional.of(rejected));

        assertFailure(() -> service.onShelf(SELLER, PRODUCT, 1, auditContext()), "PRODUCT_NOT_RELISTABLE");

        assertThat(offShelf.lifecycleState()).isEqualTo(Product.OFF_SHELF);
        verify(products, never()).save(any());
    }

    private static Product product(String lifecycle, int version) {
        Product product = new Product(SELLER, "Book", "Used book", 1_000L, NOW);
        ReflectionTestUtils.setField(product, "id", PRODUCT);
        product.transition(lifecycle, NOW);
        ReflectionTestUtils.setField(product, "contentVersion", version);
        return product;
    }

    private static AuditContext auditContext() {
        ExecutionContext context = new ExecutionContext(UUID.randomUUID(), ExecutionContext.ActorKind.ACCOUNT,
                Long.toString(SELLER), UUID.randomUUID(), null, 1L, "lifecycle-test");
        return new AuditContext(context, UUID.randomUUID());
    }

    private static void assertFailure(Runnable action, String code) {
        assertThatThrownBy(action::run)
                .isInstanceOfSatisfying(BusinessError.class, error -> {
                    assertThat(error.code()).isEqualTo(code);
                    assertThat(error.status()).isEqualTo(switch (code) {
                        case "CATEGORY_REQUIRED" -> 422;
                        case "RESOURCE_NOT_VISIBLE" -> 404;
                        default -> 409;
                    });
                });
    }
}
