package io.github.iy88.project1.product.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.mock;
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
import io.github.iy88.project1.product.persistence.CategoryApplicationRepository;
import io.github.iy88.project1.product.persistence.Product;
import io.github.iy88.project1.product.persistence.ProductAudit;
import io.github.iy88.project1.product.persistence.ProductAuditRepository;
import io.github.iy88.project1.product.persistence.ProductCategoryRepository;
import io.github.iy88.project1.product.persistence.ProductEditHistoryRepository;
import io.github.iy88.project1.product.persistence.ProductRepository;
import io.github.iy88.project1.storage.application.FileRead;
import io.github.iy88.project1.storage.persistence.FileReferences;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.core.env.Environment;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.SimpleTransactionStatus;

class ProductServiceDisplayRestrictionTests {
    private static final long SELLER = 7L;
    private static final long VIEWER = 8L;
    private static final long PRODUCT = 10L;
    private static final Instant NOW = Instant.parse("2026-11-26T03:00:00Z");

    private final ProductRepository products = mock(ProductRepository.class);
    private final ProductCategoryRepository links = mock(ProductCategoryRepository.class);
    private final ProductAuditRepository audits = mock(ProductAuditRepository.class);
    private final CategoryDirectory directory = mock(CategoryDirectory.class);
    private final AccountRepository accounts = mock(AccountRepository.class);
    private final FileReferences fileReferences = mock(FileReferences.class);
    private final ProductDisplayRestrictions displayRestrictions = mock(ProductDisplayRestrictions.class);
    private final AuditStore auditRecords = mock(AuditStore.class);
    private final AuditContext auditContext = new AuditContext(new ExecutionContext(UUID.randomUUID(),
            ExecutionContext.ActorKind.ACCOUNT, Long.toString(SELLER), UUID.randomUUID(), null, 1L, "cfg"),
            UUID.randomUUID());
    private ProductService service;

    @BeforeEach
    void setUp() {
        when(links.activeCategoryIds(anyLong())).thenReturn(List.of());
        when(directory.mainNames(any())).thenReturn(Map.of());
        when(accounts.findById(anyLong())).thenReturn(Optional.empty());
        when(fileReferences.current(any(), any())).thenReturn(List.of());
        var manager = mock(PlatformTransactionManager.class);
        when(manager.getTransaction(any())).thenReturn(new SimpleTransactionStatus());
        var environment = mock(Environment.class);
        when(environment.getRequiredProperty("OSS_ENDPOINT")).thenReturn("https://oss.example");
        when(environment.getRequiredProperty("OSS_REGION")).thenReturn("region");
        when(environment.getRequiredProperty("OSS_BUCKET")).thenReturn("bucket");
        when(environment.getRequiredProperty("OSS_PREFIX")).thenReturn("prefix");
        when(environment.getRequiredProperty("OSS_ACCESS_KEY_ID")).thenReturn("id");
        when(environment.getRequiredProperty("OSS_ACCESS_KEY_SECRET")).thenReturn("secret");
        @SuppressWarnings("unchecked")
        org.springframework.beans.factory.ObjectProvider<ProductTradeFreeze> freezeProvider =
                mock(org.springframework.beans.factory.ObjectProvider.class);
        when(freezeProvider.getIfAvailable()).thenReturn(mock(ProductTradeFreeze.class));
        service = new ProductService(products, links, mock(ProductEditHistoryRepository.class), audits,
                mock(CategoryApplicationRepository.class),
                mock(org.springframework.beans.factory.ObjectProvider.class), accounts,
                mock(AccountAvatarService.class), mock(AccountWriteGuard.class), directory,
                new ProductSettings(100, 5_000, 100_000_000, 20, 100, 9, 500, 10, 60),
                new CategorySettings(50, 100), fileReferences, mock(FileRead.class),
                mock(ProductTradeHistory.class), mock(ProductEditNotices.class),
                mock(CaseCommentAccess.class), mock(ProductCorrectionNotices.class), displayRestrictions,
                freezeProvider, environment, mock(JdbcClient.class), manager, auditRecords);
    }

    @Test
    void restrictedPublicProductIsHiddenFromAStranger() {
        Product product = product(Product.PUBLIC);
        when(products.findById(PRODUCT)).thenReturn(Optional.of(product));
        when(displayRestrictions.hasActive(PRODUCT)).thenReturn(true);

        assertThat(service.notificationTitle(VIEWER, PRODUCT)).isEmpty();
        assertFailure(() -> service.detail(VIEWER, PRODUCT), "RESOURCE_NOT_VISIBLE");
    }

    @Test
    void sellerKeepsTheTitleOfOwnRestrictedProduct() {
        Product product = product(Product.PUBLIC);
        when(products.findById(PRODUCT)).thenReturn(Optional.of(product));
        when(displayRestrictions.hasActive(PRODUCT)).thenReturn(true);

        assertThat(service.notificationTitle(SELLER, PRODUCT)).contains("Book");
    }

    @Test
    void relistFailsWhileAnyDisplayRestrictionIsActive() {
        Product product = product(Product.OFF_SHELF);
        ProductAudit audit = passedAudit();
        when(products.lockById(PRODUCT)).thenReturn(Optional.of(product));
        when(audits.findTopByProductIdOrderBySequenceNoDesc(PRODUCT)).thenReturn(Optional.of(audit));
        when(displayRestrictions.hasActive(PRODUCT)).thenReturn(true);

        assertFailure(() -> service.onShelf(SELLER, PRODUCT, 1, auditContext), "DISPLAY_RESTRICTED");
        assertThat(product.lifecycleState()).isEqualTo(Product.OFF_SHELF);
    }

    @Test
    void relistSucceedsOnlyAfterTheLastSourceIsReleased() {
        Product product = product(Product.OFF_SHELF);
        ProductAudit audit = passedAudit();
        when(products.lockById(PRODUCT)).thenReturn(Optional.of(product));
        when(audits.findTopByProductIdOrderBySequenceNoDesc(PRODUCT)).thenReturn(Optional.of(audit));
        when(displayRestrictions.hasActive(PRODUCT)).thenReturn(false);

        var detail = service.onShelf(SELLER, PRODUCT, 1, auditContext);

        assertThat(detail.lifecycleState()).isEqualTo(Product.PUBLIC);
        assertThat(product.lifecycleState()).isEqualTo(Product.PUBLIC);
    }

    private static ProductAudit passedAudit() {
        ProductAudit audit = mock(ProductAudit.class);
        when(audit.status()).thenReturn("passed");
        when(audit.id()).thenReturn(5L);
        when(audit.caseId()).thenReturn(6L);
        when(audit.submittedAt()).thenReturn(NOW);
        return audit;
    }

    private static Product product(String state) {
        Product product = new Product(SELLER, "Book", "Used book", 1_000, NOW);
        ReflectionTestUtils.setField(product, "id", PRODUCT);
        product.transition(state, NOW);
        return product;
    }

    private static void assertFailure(Runnable action, String code) {
        assertThatThrownBy(action::run)
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo(code));
    }
}
