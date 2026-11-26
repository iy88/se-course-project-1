package io.github.iy88.project1.product.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
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
import io.github.iy88.project1.product.persistence.CategoryApplicationRepository;
import io.github.iy88.project1.product.persistence.Product;
import io.github.iy88.project1.product.persistence.ProductAuditRepository;
import io.github.iy88.project1.product.persistence.ProductCategoryRepository;
import io.github.iy88.project1.product.persistence.ProductEditHistory;
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
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.core.env.Environment;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.SimpleTransactionStatus;

/** BR-33/D-50 product-side qualification: publish/list/delist are frozen, ordinary edit is not. */
class ProductServiceTradeFreezeTests {
    private static final long SELLER = 7L;
    private static final long PRODUCT = 10L;
    private static final long CATEGORY = 3L;
    private static final Instant NOW = Instant.parse("2026-11-26T03:00:00Z");

    private final ProductRepository products = mock(ProductRepository.class);
    private final ProductCategoryRepository links = mock(ProductCategoryRepository.class);
    private final ProductAuditRepository audits = mock(ProductAuditRepository.class);
    private final ProductEditHistoryRepository edits = mock(ProductEditHistoryRepository.class);
    private final CategoryDirectory directory = mock(CategoryDirectory.class);
    private final AccountRepository accounts = mock(AccountRepository.class);
    private final FileReferences fileReferences = mock(FileReferences.class);
    private final ProductDisplayRestrictions displayRestrictions = mock(ProductDisplayRestrictions.class);
    private final ProductTradeFreeze freeze = mock(ProductTradeFreeze.class);
    private ProductService service;

    @BeforeEach
    @SuppressWarnings("unchecked")
    void setUp() {
        when(links.activeCategoryIds(anyLong())).thenReturn(List.of(CATEGORY));
        when(links.findByProductIdAndRemovedAtIsNullOrderByCategoryIdAsc(anyLong())).thenReturn(List.of());
        when(directory.mainNames(any())).thenReturn(Map.of(CATEGORY, "Book"));
        when(directory.find(CATEGORY)).thenReturn(Optional.of(new CategoryDirectory.Info(CATEGORY, "Book", true)));
        when(accounts.findById(anyLong())).thenReturn(Optional.empty());
        when(fileReferences.current(any(), anyString())).thenReturn(List.of());
        var history = mock(ProductEditHistory.class);
        when(history.id()).thenReturn(99L);
        when(edits.save(any())).thenReturn(history);
        when(products.save(any())).thenAnswer(call -> call.getArgument(0));

        ObjectProvider<ProductTradeFreeze> provider = mock(ObjectProvider.class);
        when(provider.getIfAvailable()).thenReturn(freeze);

        var manager = mock(PlatformTransactionManager.class);
        when(manager.getTransaction(any())).thenReturn(new SimpleTransactionStatus());
        var environment = mock(Environment.class);
        when(environment.getRequiredProperty("OSS_ENDPOINT")).thenReturn("https://oss.example");
        when(environment.getRequiredProperty("OSS_REGION")).thenReturn("region");
        when(environment.getRequiredProperty("OSS_BUCKET")).thenReturn("bucket");
        when(environment.getRequiredProperty("OSS_PREFIX")).thenReturn("prefix");
        when(environment.getRequiredProperty("OSS_ACCESS_KEY_ID")).thenReturn("id");
        when(environment.getRequiredProperty("OSS_ACCESS_KEY_SECRET")).thenReturn("secret");
        service = new ProductService(products, links, edits, audits,
                mock(CategoryApplicationRepository.class), mock(ObjectProvider.class), accounts,
                mock(AccountAvatarService.class), mock(AccountWriteGuard.class), directory,
                new ProductSettings(100, 5_000, 100_000_000, 20, 100, 9, 500, 10, 60),
                new CategorySettings(50, 100), fileReferences, mock(FileRead.class),
                mock(ProductTradeHistory.class), mock(ProductEditNotices.class),
                mock(CaseCommentAccess.class), mock(ProductCorrectionNotices.class), displayRestrictions,
                provider, environment, mock(JdbcClient.class), manager, mock(AuditStore.class));
    }

    @Test
    void createIsRejectedWhileTheSellerIsAFrozenParty() {
        when(freeze.isPartyFrozen(SELLER)).thenReturn(true);

        assertFailure(() -> service.create(SELLER, new ProductService.CreateCommand(
                "Book", "Used book", List.of(), 1_000L, List.of(String.valueOf(CATEGORY)), null),
                auditContext()));

        verify(products, never()).save(any());
    }

    @Test
    void resubmitIsRejectedWhileTheSellerIsAFrozenParty() {
        Product product = product(Product.REVIEW_REJECTED, 1);
        when(products.lockById(PRODUCT)).thenReturn(Optional.of(product));
        when(freeze.isPartyFrozen(SELLER)).thenReturn(true);

        assertFailure(() -> service.resubmit(SELLER, PRODUCT, 1, auditContext()));

        verify(products, never()).save(product);
    }

    @Test
    void relistIsRejectedWhileTheSellerIsAFrozenParty() {
        Product product = product(Product.OFF_SHELF, 1);
        when(products.lockById(PRODUCT)).thenReturn(Optional.of(product));
        when(freeze.isPartyFrozen(SELLER)).thenReturn(true);

        assertFailure(() -> service.onShelf(SELLER, PRODUCT, 1, auditContext()));

        verify(product, never()).transition(anyString(), any());
        verify(products, never()).save(product);
    }

    @Test
    void activeDelistIsRejectedWhileTheSellerIsAFrozenParty() {
        Product product = product(Product.PUBLIC, 1);
        when(products.lockById(PRODUCT)).thenReturn(Optional.of(product));
        when(freeze.isPartyFrozen(SELLER)).thenReturn(true);

        assertFailure(() -> service.lockForOffShelf(SELLER, PRODUCT, 1));

        verify(products, never()).save(product);
    }

    @Test
    void ordinaryEditStillWorksWithoutReadingThePartyFreeze() {
        Product product = product(Product.PUBLIC, 1);
        when(products.lockById(PRODUCT)).thenReturn(Optional.of(product));

        service.edit(SELLER, PRODUCT, new ProductService.EditCommand(
                "New title", null, null, null, null, null, 1), auditContext().execution());

        verify(products).save(product);
        verify(freeze, never()).isPartyFrozen(anyLong());
    }

    private static AuditContext auditContext() {
        var context = new ExecutionContext(UUID.randomUUID(), ExecutionContext.ActorKind.ACCOUNT,
                Long.toString(SELLER), UUID.randomUUID(), null, 1L, "freeze-test");
        return new AuditContext(context, UUID.randomUUID());
    }

    private static Product product(String lifecycle, int version) {
        Product product = mock(Product.class);
        when(product.id()).thenReturn(PRODUCT);
        when(product.sellerAccountId()).thenReturn(SELLER);
        when(product.lifecycleState()).thenReturn(lifecycle);
        when(product.contentVersion()).thenReturn(version);
        when(product.title()).thenReturn("Book");
        when(product.description()).thenReturn("Used book");
        when(product.priceCents()).thenReturn(1_000L);
        when(product.occupiedByTradeId()).thenReturn(null);
        return product;
    }

    private static void assertFailure(Runnable action) {
        assertThatThrownBy(action::run)
                .isInstanceOfSatisfying(BusinessError.class, error -> {
                    assertThat(error.code()).isEqualTo("TRADE_FROZEN");
                    assertThat(error.status()).isEqualTo(409);
                });
    }
}
