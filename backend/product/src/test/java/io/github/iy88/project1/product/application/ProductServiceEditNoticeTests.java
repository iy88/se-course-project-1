package io.github.iy88.project1.product.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import io.github.iy88.project1.account.application.AccountAvatarService;
import io.github.iy88.project1.account.persistence.AccountRepository;
import io.github.iy88.project1.category.CategorySettings;
import io.github.iy88.project1.category.application.CategoryDirectory;
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
import org.springframework.core.env.Environment;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.SimpleTransactionStatus;

class ProductServiceEditNoticeTests {
    private static final long SELLER = 7L;
    private static final long PRODUCT = 10L;
    private static final long CATEGORY = 3L;
    private static final Instant NOW = Instant.parse("2026-11-23T05:00:00Z");

    private final ProductRepository products = mock(ProductRepository.class);
    private final ProductCategoryRepository links = mock(ProductCategoryRepository.class);
    private final ProductEditHistoryRepository edits = mock(ProductEditHistoryRepository.class);
    private final ProductEditNotices notices = mock(ProductEditNotices.class);
    private ProductService service;
    private Product product;

    @BeforeEach
    void setUp() {
        product = mock(Product.class);
        when(product.id()).thenReturn(PRODUCT);
        when(product.sellerAccountId()).thenReturn(SELLER);
        when(product.lifecycleState()).thenReturn(Product.PUBLIC);
        when(product.contentVersion()).thenReturn(1);
        when(product.title()).thenReturn("旧书");
        when(product.description()).thenReturn("描述");
        when(product.priceCents()).thenReturn(1200L);
        when(products.lockById(PRODUCT)).thenReturn(Optional.of(product));
        when(links.activeCategoryIds(PRODUCT)).thenReturn(List.of(CATEGORY));
        when(products.save(any())).thenAnswer(call -> call.getArgument(0));
        var history = mock(ProductEditHistory.class);
        when(history.id()).thenReturn(99L);
        when(edits.save(any())).thenReturn(history);

        var manager = mock(PlatformTransactionManager.class);
        when(manager.getTransaction(any())).thenReturn(new SimpleTransactionStatus());
        var environment = mock(Environment.class);
        when(environment.getRequiredProperty("OSS_ENDPOINT")).thenReturn("https://oss.example");
        when(environment.getRequiredProperty("OSS_REGION")).thenReturn("region");
        when(environment.getRequiredProperty("OSS_BUCKET")).thenReturn("bucket");
        when(environment.getRequiredProperty("OSS_PREFIX")).thenReturn("prefix");
        when(environment.getRequiredProperty("OSS_ACCESS_KEY_ID")).thenReturn("id");
        when(environment.getRequiredProperty("OSS_ACCESS_KEY_SECRET")).thenReturn("secret");
        service = new ProductService(products, links, edits, mock(ProductAuditRepository.class),
                mock(CategoryApplicationRepository.class), mock(org.springframework.beans.factory.ObjectProvider.class),
                mock(AccountRepository.class), mock(AccountAvatarService.class), mock(CategoryDirectory.class),
                new ProductSettings(100, 5_000, 100_000_000, 20, 100, 9, 500, 10, 60),
                new CategorySettings(50, 100), mock(FileReferences.class), mock(FileRead.class),
                mock(ProductTradeHistory.class), notices, mock(CaseCommentAccess.class),
                mock(ProductCorrectionNotices.class), environment, mock(JdbcClient.class), manager);
    }

    @Test
    void aSuccessfulEditInvokesTheNoticeHookWithTheSavedEditIdInTheSameCall() {
        var context = new ExecutionContext(UUID.randomUUID(), ExecutionContext.ActorKind.ACCOUNT,
                Long.toString(SELLER), UUID.randomUUID(), null, 1L, "cfg");

        service.edit(SELLER, PRODUCT, new ProductService.EditCommand("新标题", null, null, null, null, null, 1),
                context);

        verify(products).save(product);
        verify(notices).productEdited(eq(context), eq(SELLER), eq(PRODUCT), eq(99L), any(), eq(true), any());
        assertThat(product.lifecycleState()).isEqualTo(Product.PUBLIC);
    }
}
