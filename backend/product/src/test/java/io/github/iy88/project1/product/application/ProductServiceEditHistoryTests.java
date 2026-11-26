package io.github.iy88.project1.product.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import io.github.iy88.project1.account.application.AccountAvatarService;
import io.github.iy88.project1.account.persistence.AccountRepository;
import io.github.iy88.project1.category.CategorySettings;
import io.github.iy88.project1.category.application.CategoryDirectory;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.product.ProductSettings;
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
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.core.env.Environment;
import org.springframework.data.domain.PageImpl;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.SimpleTransactionStatus;

class ProductServiceEditHistoryTests {
    private static final long SELLER = 7L;
    private static final long BUYER = 8L;
    private static final long PRODUCT = 10L;
    private static final Instant REQUESTED = Instant.parse("2026-11-23T01:00:00Z");
    private static final Instant EDITED = Instant.parse("2026-11-23T02:00:00Z");

    private final ProductRepository products = mock(ProductRepository.class);
    private final ProductEditHistoryRepository edits = mock(ProductEditHistoryRepository.class);
    private final ProductTradeHistory tradeHistory = mock(ProductTradeHistory.class);
    private ProductService service;

    @BeforeEach
    void setUp() {
        var manager = mock(PlatformTransactionManager.class);
        when(manager.getTransaction(any())).thenReturn(new SimpleTransactionStatus());
        var environment = mock(Environment.class);
        when(environment.getRequiredProperty("OSS_ENDPOINT")).thenReturn("https://oss.example");
        when(environment.getRequiredProperty("OSS_REGION")).thenReturn("region");
        when(environment.getRequiredProperty("OSS_BUCKET")).thenReturn("bucket");
        when(environment.getRequiredProperty("OSS_PREFIX")).thenReturn("prefix");
        when(environment.getRequiredProperty("OSS_ACCESS_KEY_ID")).thenReturn("id");
        when(environment.getRequiredProperty("OSS_ACCESS_KEY_SECRET")).thenReturn("secret");
        service = new ProductService(products, mock(ProductCategoryRepository.class), edits,
                mock(ProductAuditRepository.class), mock(io.github.iy88.project1.product.persistence.CategoryApplicationRepository.class),
                mock(org.springframework.beans.factory.ObjectProvider.class), mock(AccountRepository.class),
                mock(AccountAvatarService.class), mock(AccountWriteGuard.class),
                mock(CategoryDirectory.class), new ProductSettings(100, 5_000, 100_000_000, 20, 100, 9, 500, 10, 60),
                new CategorySettings(50, 100), mock(FileReferences.class), mock(FileRead.class), tradeHistory,
                (context, sellerId, productId, editId, title, visible, occurredAt) -> { },
                mock(CaseCommentAccess.class), mock(ProductCorrectionNotices.class),
                mock(ProductDisplayRestrictions.class), environment, mock(JdbcClient.class), manager);
    }

    @Test
    void sellerKeepsTheFullHistoryAndReasons() {
        var product = product();
        when(products.findById(PRODUCT)).thenReturn(Optional.of(product));
        var edit = edit(Map.of("title", "old", "admin_note", "private"), "seller edit");
        when(edits.findByProductIdOrderByEditedAtDescIdDesc(eq(PRODUCT), any()))
                .thenReturn(new PageImpl<>(List.of(edit)));

        var page = service.editHistory(SELLER, PRODUCT, 1, 20);

        assertThat(page.items()).singleElement().satisfies(item -> {
            assertThat(item.reason()).isEqualTo("seller edit");
            assertThat(item.beforeContent()).containsKey("admin_note");
        });
    }

    @Test
    void buyerGetsOnlyTheRequestScopeAndPublicFieldsWithoutAdminNotes() {
        var product = product();
        when(products.findById(PRODUCT)).thenReturn(Optional.of(product));
        when(tradeHistory.buyerScope(PRODUCT, BUYER, 55L))
                .thenReturn(Optional.of(new ProductTradeHistory.BuyerScope(REQUESTED)));
        var edit = edit(Map.of("title", "old", "admin_note", "private"), "admin reason");
        when(edits.findBuyerHistory(PRODUCT, REQUESTED, org.springframework.data.domain.PageRequest.of(0, 20)))
                .thenReturn(new PageImpl<>(List.of(edit)));

        var page = service.editHistory(BUYER, PRODUCT, 55L, 1, 20);

        assertThat(page.items()).singleElement().satisfies(item -> {
            assertThat(item.reason()).isNull();
            assertThat(item.beforeContent()).containsOnlyKeys("title");
            assertThat(item.afterContent()).containsOnlyKeys("title");
        });
        verify(tradeHistory).buyerScope(PRODUCT, BUYER, 55L);
    }

    @Test
    void strangerCannotReadBuyerHistory() {
        var product = product();
        when(products.findById(PRODUCT)).thenReturn(Optional.of(product));
        when(tradeHistory.buyerScope(PRODUCT, BUYER, null)).thenReturn(Optional.empty());

        assertThatThrownBy(() -> service.editHistory(BUYER, PRODUCT, null, 1, 20))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("RESOURCE_NOT_VISIBLE"));
    }

    private static Product product() {
        Product product = mock(Product.class);
        when(product.id()).thenReturn(PRODUCT);
        when(product.sellerAccountId()).thenReturn(SELLER);
        when(product.deleted()).thenReturn(false);
        when(product.lifecycleState()).thenReturn(Product.PUBLIC);
        return product;
    }

    private static ProductEditHistory edit(Map<String, Object> before, String reason) {
        ProductEditHistory edit = mock(ProductEditHistory.class);
        when(edit.id()).thenReturn(99L);
        when(edit.editedAt()).thenReturn(EDITED);
        when(edit.operatorKind()).thenReturn("seller");
        when(edit.editKind()).thenReturn("content_edit");
        when(edit.beforeContent()).thenReturn(before);
        when(edit.afterContent()).thenReturn(Map.of("title", "new"));
        when(edit.reason()).thenReturn(reason);
        return edit;
    }
}
