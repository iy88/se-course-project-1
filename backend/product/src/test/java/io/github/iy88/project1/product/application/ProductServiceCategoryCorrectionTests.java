package io.github.iy88.project1.product.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import io.github.iy88.project1.account.application.AccountAvatarService;
import io.github.iy88.project1.account.persistence.AccountRepository;
import io.github.iy88.project1.category.CategorySettings;
import io.github.iy88.project1.category.application.CategoryDirectory;
import io.github.iy88.project1.core.AuditActions;
import io.github.iy88.project1.core.AuditContext;
import io.github.iy88.project1.core.AuditStore;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.product.ProductSettings;
import io.github.iy88.project1.product.persistence.CategoryApplicationRepository;
import io.github.iy88.project1.product.persistence.Product;
import io.github.iy88.project1.product.persistence.ProductAuditRepository;
import io.github.iy88.project1.product.persistence.ProductCategory;
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
import org.mockito.ArgumentCaptor;
import org.springframework.core.env.Environment;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.SimpleTransactionStatus;

class ProductServiceCategoryCorrectionTests {
    private static final long SELLER = 7L;
    private static final long MANAGER = 9L;
    private static final long PRODUCT = 10L;
    private static final long CASE = 44L;
    private static final long OLD_CATEGORY = 3L;
    private static final long NEW_CATEGORY = 5L;
    private static final Instant NOW = Instant.parse("2026-11-26T02:00:00Z");

    private final ProductRepository products = mock(ProductRepository.class);
    private final ProductCategoryRepository links = mock(ProductCategoryRepository.class);
    private final ProductEditHistoryRepository edits = mock(ProductEditHistoryRepository.class);
    private final CategoryDirectory directory = mock(CategoryDirectory.class);
    private final CaseCommentAccess cases = mock(CaseCommentAccess.class);
    private final ProductCorrectionNotices notices = mock(ProductCorrectionNotices.class);
    private final AuditStore auditRecords = mock(AuditStore.class);
    private final PlatformTransactionManager transactions = mock(PlatformTransactionManager.class);
    private ProductService service;
    private Product product;
    private final ExecutionContext context = new ExecutionContext(UUID.randomUUID(),
            ExecutionContext.ActorKind.ACCOUNT, Long.toString(MANAGER), UUID.randomUUID(), null, 1L, "cfg");

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
        when(product.createdAt()).thenReturn(NOW);
        when(product.updatedAt()).thenReturn(NOW);
        when(products.lockById(PRODUCT)).thenReturn(Optional.of(product));
        when(products.save(any())).thenAnswer(call -> call.getArgument(0));

        when(links.activeCategoryIds(PRODUCT)).thenReturn(List.of(OLD_CATEGORY), List.of(NEW_CATEGORY));
        when(links.findByProductIdAndRemovedAtIsNullOrderByCategoryIdAsc(PRODUCT))
                .thenReturn(List.of(new ProductCategory(PRODUCT, OLD_CATEGORY, SELLER, NOW)));
        when(links.save(any())).thenAnswer(call -> call.getArgument(0));

        when(directory.find(OLD_CATEGORY)).thenReturn(Optional.of(new CategoryDirectory.Info(OLD_CATEGORY, "旧分类", true)));
        when(directory.find(NEW_CATEGORY)).thenReturn(Optional.of(new CategoryDirectory.Info(NEW_CATEGORY, "新分类", true)));
        when(directory.mainNames(any())).thenReturn(Map.of(OLD_CATEGORY, "旧分类", NEW_CATEGORY, "新分类"));

        var history = mock(ProductEditHistory.class);
        when(history.id()).thenReturn(99L);
        when(edits.save(any())).thenReturn(history);

        when(transactions.getTransaction(any())).thenReturn(new SimpleTransactionStatus());
        var environment = mock(Environment.class);
        when(environment.getRequiredProperty("OSS_ENDPOINT")).thenReturn("https://oss.example");
        when(environment.getRequiredProperty("OSS_REGION")).thenReturn("region");
        when(environment.getRequiredProperty("OSS_BUCKET")).thenReturn("bucket");
        when(environment.getRequiredProperty("OSS_PREFIX")).thenReturn("prefix");
        when(environment.getRequiredProperty("OSS_ACCESS_KEY_ID")).thenReturn("id");
        when(environment.getRequiredProperty("OSS_ACCESS_KEY_SECRET")).thenReturn("secret");
        var accounts = mock(AccountRepository.class);
        when(accounts.findById(anyLong())).thenReturn(Optional.empty());
        service = new ProductService(products, links, edits, mock(ProductAuditRepository.class),
                mock(CategoryApplicationRepository.class), mock(org.springframework.beans.factory.ObjectProvider.class),
                accounts, mock(AccountAvatarService.class), mock(AccountWriteGuard.class), directory,
                new ProductSettings(100, 5_000, 100_000_000, 20, 100, 9, 500, 10, 60),
                new CategorySettings(50, 100), mock(FileReferences.class), mock(FileRead.class),
                mock(ProductTradeHistory.class), mock(ProductEditNotices.class), cases, notices,
                mock(ProductDisplayRestrictions.class), mock(org.springframework.beans.factory.ObjectProvider.class), environment,
                mock(JdbcClient.class), transactions, auditRecords);
    }

    @Test
    void aClaimedManagerReplacesCategoriesAndRecordsTheCorrection() {
        when(cases.claimedForProduct(MANAGER, CASE, PRODUCT)).thenReturn(true);

        var result = service.correctCategory(MANAGER, PRODUCT,
                new ProductService.CorrectionCommand(List.of(String.valueOf(NEW_CATEGORY)), "分类放错了", "case", CASE),
                context);

        assertThat(result.previousCategories()).extracting(ProductService.CategoryRef::id)
                .containsExactly(String.valueOf(OLD_CATEGORY));
        assertThat(result.currentCategories()).extracting(ProductService.CategoryRef::id)
                .containsExactly(String.valueOf(NEW_CATEGORY));
        verify(product).touchContentVersion(any());
        verify(products).save(product);

        var saved = ArgumentCaptor.forClass(ProductEditHistory.class);
        verify(edits).save(saved.capture());
        assertThat(saved.getValue().operatorKind()).isEqualTo("admin");
        assertThat(saved.getValue().editKind()).isEqualTo("category_correction");
        assertThat(saved.getValue().reason()).isEqualTo("分类放错了");

        var savedLinks = ArgumentCaptor.forClass(ProductCategory.class);
        verify(links, org.mockito.Mockito.times(2)).save(savedLinks.capture());
        assertThat(savedLinks.getAllValues()).extracting(ProductCategory::source)
                .contains("admin_correction");
        assertThat(savedLinks.getAllValues()).filteredOn(link -> link.categoryId() == OLD_CATEGORY)
                .allSatisfy(link -> assertThat(link.active()).isFalse());
        verify(notices).categoryCorrected(eq(context), eq(SELLER), eq(PRODUCT), eq(99L), eq(CASE), any(), any());

        var audit = ArgumentCaptor.forClass(AuditContext.class);
        var auditTarget = ArgumentCaptor.forClass(ResourceRef.class);
        var auditBasis = ArgumentCaptor.forClass(ResourceRef.class);
        @SuppressWarnings("unchecked")
        var auditFacts = ArgumentCaptor.forClass(Map.class);
        verify(auditRecords).record(audit.capture(), eq(AuditActions.PRODUCT_CATEGORY_CORRECTED),
                auditTarget.capture(), auditBasis.capture(), auditFacts.capture());
        assertThat(audit.getValue().execution()).isEqualTo(context);
        assertThat(auditTarget.getValue()).isEqualTo(new ResourceRef("product", PRODUCT));
        assertThat(auditBasis.getValue()).isEqualTo(new ResourceRef("case", CASE));
        assertThat(auditFacts.getValue())
                .containsEntry("edit_id", "99")
                .containsEntry("previous_category_ids", List.of(String.valueOf(OLD_CATEGORY)))
                .containsEntry("current_category_ids", List.of(String.valueOf(NEW_CATEGORY)));
    }

    @Test
    void anAuditFailurePropagatesAndRollsBackTheCorrectionTransaction() {
        when(cases.claimedForProduct(MANAGER, CASE, PRODUCT)).thenReturn(true);
        when(auditRecords.record(any(), any(), any(), any(), any()))
                .thenThrow(new IllegalStateException("audit unavailable"));

        assertThatThrownBy(() -> service.correctCategory(MANAGER, PRODUCT,
                new ProductService.CorrectionCommand(List.of(String.valueOf(NEW_CATEGORY)), "分类放错了", "case", CASE),
                context))
                .isInstanceOf(IllegalStateException.class)
                .hasMessage("audit unavailable");
        verify(edits).save(any());
        verify(transactions).rollback(any());
    }

    @Test
    void aManagerWithoutTheClaimedCaseIsRejected() {
        when(cases.claimedForProduct(MANAGER, CASE, PRODUCT)).thenReturn(false);

        assertThatThrownBy(() -> service.correctCategory(MANAGER, PRODUCT,
                new ProductService.CorrectionCommand(List.of(String.valueOf(NEW_CATEGORY)), "分类放错了", "case", CASE),
                context))
                .isInstanceOfSatisfying(BusinessError.class, error -> {
                    assertThat(error.code()).isEqualTo("ACTION_NOT_ALLOWED");
                    assertThat(error.status()).isEqualTo(403);
                });
        verify(edits, never()).save(any());
        verify(products, never()).save(any());
        verify(notices, never()).categoryCorrected(any(), anyLong(), anyLong(), anyLong(), anyLong(), any(), any());
    }

    @Test
    void anEmptyCategorySelectionIsRejectedBeforeWriting() {
        assertThatThrownBy(() -> service.correctCategory(MANAGER, PRODUCT,
                new ProductService.CorrectionCommand(List.of(), "分类放错了", "case", CASE), context))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("CATEGORY_REQUIRED"));
        verify(edits, never()).save(any());
    }

    @Test
    void anEmptyReasonIsRejected() {
        assertThatThrownBy(() -> service.correctCategory(MANAGER, PRODUCT,
                new ProductService.CorrectionCommand(List.of(String.valueOf(NEW_CATEGORY)), "  ", "case", CASE),
                context))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("INPUT_INVALID"));
        verify(edits, never()).save(any());
    }

    @Test
    void anUnchangedSelectionDoesNotWriteHistoryOrBumpTheVersion() {
        when(cases.claimedForProduct(MANAGER, CASE, PRODUCT)).thenReturn(true);
        when(links.activeCategoryIds(PRODUCT)).thenReturn(List.of(OLD_CATEGORY));

        service.correctCategory(MANAGER, PRODUCT,
                new ProductService.CorrectionCommand(List.of(String.valueOf(OLD_CATEGORY)), "复核分类", "case", CASE),
                context);

        verify(product, never()).touchContentVersion(any());
        verify(edits, never()).save(any());
        verify(notices, never()).categoryCorrected(any(), anyLong(), anyLong(), anyLong(), anyLong(), any(), any());
    }
}
