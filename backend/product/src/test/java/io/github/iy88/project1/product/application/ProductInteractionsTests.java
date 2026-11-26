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

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.WriteTransaction;
import io.github.iy88.project1.product.ProductSettings;
import io.github.iy88.project1.product.domain.ProductComment;
import io.github.iy88.project1.product.persistence.Product;
import io.github.iy88.project1.product.persistence.ProductRepository;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.OptionalLong;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.SimpleTransactionStatus;

class ProductInteractionsTests {
    private static final long PRODUCT = 10L;
    private static final long OTHER_PRODUCT = 11L;
    private static final long SELLER = 7L;
    private static final long VIEWER = 8L;
    private static final long MANAGER = 9L;
    private static final long CASE = 100L;
    private static final Instant NOW = Instant.parse("2026-11-23T00:00:00Z");

    private final ProductRepository products = mock(ProductRepository.class);
    private final ProductService details = mock(ProductService.class);
    private final ProductInteractionStore store = mock(ProductInteractionStore.class);
    private final CaseCommentAccess cases = mock(CaseCommentAccess.class);
    private final CommentAccountAccess accounts = mock(CommentAccountAccess.class);
    private final ProductDisplayRestrictions displayRestrictions = mock(ProductDisplayRestrictions.class);
    private final ProductSettings settings = new ProductSettings(100, 5_000, 100_000_000, 20, 100, 9, 500, 2, 60);
    private ProductInteractions interactions;

    @BeforeEach
    void setUp() {
        PlatformTransactionManager manager = mock(PlatformTransactionManager.class);
        when(manager.getTransaction(any())).thenReturn(new SimpleTransactionStatus());
        interactions = new ProductInteractions(products, details, store, cases, accounts, settings,
                displayRestrictions, mock(ApplicationEventPublisher.class), manager, Clock.fixed(NOW, ZoneOffset.UTC));
        when(accounts.profiles(any())).thenReturn(Map.of(
                VIEWER, new CommentAccountAccess.Profile("Viewer", "https://img.example/viewer.png"),
                SELLER, new CommentAccountAccess.Profile("Seller", "https://img.example/seller.png")));
    }

    @Test
    void hiddenProductIsNotVisibleToStrangers() {
        when(products.findById(PRODUCT)).thenReturn(Optional.of(product(Product.OFF_SHELF)));
        when(store.hasCommentBy(PRODUCT, VIEWER)).thenReturn(false);

        assertFailure(() -> interactions.listComments(VIEWER, PRODUCT, 1, 20, null),
                "RESOURCE_NOT_VISIBLE");
    }

    @Test
    void hiddenProductExposesTheAuthorsOwnThread() {
        when(products.findById(PRODUCT)).thenReturn(Optional.of(product(Product.OFF_SHELF)));
        when(store.hasCommentBy(PRODUCT, VIEWER)).thenReturn(true);
        var comment = comment(500, VIEWER, null, NOW, null);
        when(store.topLevelComments(PRODUCT, ProductInteractionStore.Scope.AUTHOR, VIEWER, 20, 0L))
                .thenReturn(List.of(comment));
        when(store.countTopLevelComments(PRODUCT, ProductInteractionStore.Scope.AUTHOR, VIEWER)).thenReturn(1L);
        when(store.replies(eq(PRODUCT), eq(List.of(500L)), eq(ProductInteractionStore.Scope.AUTHOR), eq(VIEWER)))
                .thenReturn(List.of());

        var page = interactions.listComments(VIEWER, PRODUCT, 1, 20, null);

        assertThat(page.items()).singleElement().satisfies(item -> {
            assertThat(item.id()).isEqualTo("500");
            assertThat(item.status()).isEqualTo(ProductComment.PUBLISHED);
            assertThat(item.body()).isEqualTo("Hello");
        });
    }

    @Test
    void claimedManagerReadsTheCaseScopeIncludingRemovalFacts() {
        when(products.findById(PRODUCT)).thenReturn(Optional.of(product(Product.OFF_SHELF)));
        when(cases.claimedForProduct(MANAGER, CASE, PRODUCT)).thenReturn(true);
        var removed = comment(600, VIEWER, null, NOW.minusSeconds(60), NOW);
        when(store.topLevelComments(PRODUCT, ProductInteractionStore.Scope.CASE, MANAGER, 20, 0L))
                .thenReturn(List.of(removed));
        when(store.countTopLevelComments(PRODUCT, ProductInteractionStore.Scope.CASE, MANAGER)).thenReturn(1L);
        when(store.replies(eq(PRODUCT), eq(List.of(600L)), eq(ProductInteractionStore.Scope.CASE), eq(MANAGER)))
                .thenReturn(List.of());

        var page = interactions.listComments(MANAGER, PRODUCT, 1, 20, CASE);

        assertThat(page.items()).singleElement().satisfies(item -> {
            assertThat(item.status()).isEqualTo(ProductComment.REMOVED_BY_ADMIN);
            assertThat(item.body()).isEqualTo("Hello");
        });
    }

    @Test
    void publishedProductExposesRepliesInThePublicScope() {
        when(products.findById(PRODUCT)).thenReturn(Optional.of(product(Product.PUBLIC)));
        var top = comment(500, VIEWER, null, NOW, null);
        var reply = comment(501, SELLER, 500L, NOW.plusSeconds(5), null);
        when(store.topLevelComments(PRODUCT, ProductInteractionStore.Scope.PUBLIC, VIEWER, 20, 0L))
                .thenReturn(List.of(top));
        when(store.countTopLevelComments(PRODUCT, ProductInteractionStore.Scope.PUBLIC, VIEWER)).thenReturn(1L);
        when(store.replies(eq(PRODUCT), eq(List.of(500L)), eq(ProductInteractionStore.Scope.PUBLIC), eq(VIEWER)))
                .thenReturn(List.of(reply));

        var page = interactions.listComments(VIEWER, PRODUCT, 1, 20, null);

        assertThat(page.items()).singleElement().satisfies(item -> {
            assertThat(item.replies()).singleElement().satisfies(sellerReply -> {
                assertThat(sellerReply.replyToCommentId()).isEqualTo("500");
                assertThat(sellerReply.author().displayName()).isEqualTo("Seller");
                assertThat(sellerReply.author().avatarUrl()).isEqualTo("https://img.example/seller.png");
            });
        });
    }

    @Test
    void restrictedAccountsCannotWrite() {
        when(accounts.writeRestricted(VIEWER)).thenReturn(true);

        assertFailure(() -> interactions.createComment(VIEWER, PRODUCT, "Hello"), "ACCOUNT_WRITE_RESTRICTED");
        verify(products, never()).lockById(anyLong());
    }

    @Test
    void hiddenProductCannotBeCommentedOnByOthers() {
        when(products.lockById(PRODUCT)).thenReturn(Optional.of(product(Product.OFF_SHELF)));

        assertFailure(() -> interactions.createComment(VIEWER, PRODUCT, "Hello"), "RESOURCE_NOT_VISIBLE");
    }

    @Test
    void sellerCannotCommentBeforeTheProductIsPublic() {
        when(products.lockById(PRODUCT)).thenReturn(Optional.of(product(Product.PENDING_REVIEW)));

        assertFailure(() -> interactions.createComment(SELLER, PRODUCT, "Hello"), "COMMENT_NOT_ALLOWED");
    }

    @Test
    void commentRateLimitAppliesPerAccount() {
        when(products.lockById(PRODUCT)).thenReturn(Optional.of(product(Product.PUBLIC)));
        when(store.countCommentsSince(eq(VIEWER), any())).thenReturn(2L);

        assertFailure(() -> interactions.createComment(VIEWER, PRODUCT, "Hello"), "RATE_LIMITED");
        verify(store, never()).insertComment(anyLong(), anyLong(), any(), any(), any());
    }

    @Test
    void blankCommentsAreRejected() {
        when(products.lockById(PRODUCT)).thenReturn(Optional.of(product(Product.PUBLIC)));
        when(store.countCommentsSince(eq(VIEWER), any())).thenReturn(0L);

        assertFailure(() -> interactions.createComment(VIEWER, PRODUCT, "   "), "INPUT_INVALID");
    }

    @Test
    void createdCommentIsPublishedWithTheAuthorProfile() {
        when(products.lockById(PRODUCT)).thenReturn(Optional.of(product(Product.PUBLIC)));
        when(store.countCommentsSince(eq(VIEWER), any())).thenReturn(0L);
        when(store.insertComment(eq(PRODUCT), eq(VIEWER), eq(null), eq("Hello"), any())).thenReturn(500L);
        when(store.comment(500L)).thenReturn(Optional.of(comment(500, VIEWER, null, NOW, null)));

        var view = interactions.createComment(VIEWER, PRODUCT, "  Hello  ");

        assertThat(view.status()).isEqualTo(ProductComment.PUBLISHED);
        assertThat(view.body()).isEqualTo("Hello");
        assertThat(view.author().displayName()).isEqualTo("Viewer");
        assertThat(view.author().avatarUrl()).isEqualTo("https://img.example/viewer.png");
    }

    @Test
    void onlyTheSellerRepliesAndOnlyToTopLevelComments() {
        when(products.lockById(PRODUCT)).thenReturn(Optional.of(product(Product.PUBLIC)));
        assertFailure(() -> interactions.replyToComment(VIEWER, PRODUCT, 500, "Thanks"),
                "COMMENT_REPLY_NOT_ALLOWED");

        when(store.lockComment(500L)).thenReturn(Optional.of(
                new ProductComment(500, PRODUCT, VIEWER, 900L, "Nested", NOW, null, null, null, null)));
        assertFailure(() -> interactions.replyToComment(SELLER, PRODUCT, 500, "Thanks"), "STATE_CONFLICT");
    }

    @Test
    void onlyTheAuthorDeletesAndRemovalWins() {
        when(products.lockById(PRODUCT)).thenReturn(Optional.of(product(Product.PUBLIC)));
        when(store.lockComment(500L)).thenReturn(Optional.of(comment(500, VIEWER, null, NOW, null)));
        assertFailure(() -> interactions.deleteComment(SELLER, PRODUCT, 500), "ACTION_NOT_ALLOWED");

        when(store.lockComment(501L)).thenReturn(Optional.of(comment(501, VIEWER, null, NOW, NOW)));
        assertFailure(() -> interactions.deleteComment(VIEWER, PRODUCT, 501), "COMMENT_ALREADY_REMOVED");
    }

    @Test
    void deletingAnAlreadyDeletedCommentIsIdempotent() {
        when(products.lockById(PRODUCT)).thenReturn(Optional.of(product(Product.PUBLIC)));
        when(store.lockComment(500L)).thenReturn(Optional.of(new ProductComment(500, PRODUCT, VIEWER, null,
                "Hello", NOW.minusSeconds(5), NOW.minusSeconds(1), null, null, null)));

        interactions.deleteComment(VIEWER, PRODUCT, 500);

        verify(store, never()).markDeletedByAuthor(anyLong(), any());
    }

    @Test
    void favoritesOfHiddenProductsAreNotCreatable() {
        when(products.findById(PRODUCT)).thenReturn(Optional.of(product(Product.OFF_SHELF)));

        assertFailure(() -> interactions.addFavorite(VIEWER, PRODUCT), "RESOURCE_NOT_VISIBLE");
        verify(store, never()).insertFavorite(anyLong(), anyLong(), any());
    }

    @Test
    void favoriteStatusKeepsInvalidFavouritesVisibleWithoutContent() {
        when(products.findById(PRODUCT)).thenReturn(Optional.of(product(Product.OFF_SHELF)));
        when(store.favorite(VIEWER, PRODUCT))
                .thenReturn(Optional.of(new ProductInteractionStore.FavoriteRow(100L, PRODUCT, NOW)));

        var status = interactions.favoriteStatus(VIEWER, PRODUCT);

        assertThat(status.favorited()).isTrue();
        assertThat(status.valid()).isFalse();
        assertThat(status.favoritedAt()).isEqualTo(NOW);
    }

    @Test
    void favoriteStatusOfAHiddenUnfavouritedProductIsNotFound() {
        when(products.findById(PRODUCT)).thenReturn(Optional.of(product(Product.OFF_SHELF)));
        when(store.favorite(VIEWER, PRODUCT)).thenReturn(Optional.empty());

        assertFailure(() -> interactions.favoriteStatus(VIEWER, PRODUCT), "RESOURCE_NOT_VISIBLE");
    }

    @Test
    void repeatedFavouriteKeepsTheFirstTime() {
        when(products.findById(PRODUCT)).thenReturn(Optional.of(product(Product.PUBLIC)));
        when(store.favorite(VIEWER, PRODUCT))
                .thenReturn(Optional.of(new ProductInteractionStore.FavoriteRow(100L, PRODUCT, NOW)));

        var status = interactions.addFavorite(VIEWER, PRODUCT);

        assertThat(status.favoritedAt()).isEqualTo(NOW);
        verify(store, never()).insertFavorite(anyLong(), anyLong(), any());
    }

    @Test
    void favouriteListHidesInvalidProductContent() {
        when(store.favorites(VIEWER, null, 20, 0L)).thenReturn(List.of(
                new ProductInteractionStore.FavoriteRow(100L, PRODUCT, NOW),
                new ProductInteractionStore.FavoriteRow(101L, OTHER_PRODUCT, NOW.minusSeconds(60))));
        when(store.countFavorites(VIEWER, null)).thenReturn(2L);
        Product valid = product(Product.PUBLIC);
        Product invalid = product(OTHER_PRODUCT, Product.OFF_SHELF);
        when(products.findByIdIn(List.of(PRODUCT, OTHER_PRODUCT))).thenReturn(List.of(valid, invalid));
        var summary = new ProductService.ProductSummary("10", "Book", 1_000, null, List.of(),
                new ProductService.SellerRef("7", "Seller"), NOW);
        when(details.summaries(List.of(valid))).thenReturn(List.of(summary));

        var page = interactions.listFavorites(VIEWER, 1, 20);

        assertThat(page.items()).hasSize(2);
        assertThat(page.items().get(0).status()).isEqualTo("valid");
        assertThat(page.items().get(0).product()).isNotNull();
        assertThat(page.items().get(1).status()).isEqualTo("invalid");
        assertThat(page.items().get(1).product()).isNull();
        assertThat(page.items().get(1).message()).isEqualTo("该商品已失效");
    }

    @Test
    void removalRequiresAClaimOnTheCase() {
        var comment = comment(500, VIEWER, null, NOW, null);
        when(products.lockById(PRODUCT)).thenReturn(Optional.of(product(Product.PUBLIC)));
        when(store.comment(500L)).thenReturn(Optional.of(comment));
        when(store.lockComment(500L)).thenReturn(Optional.of(comment));
        when(cases.claimedForProduct(MANAGER, CASE, PRODUCT)).thenReturn(false);

        assertFailure(() -> interactions.removeComment(MANAGER, CASE, 500, "E-1", "spam"), "ACTION_NOT_ALLOWED");
        verify(store, never()).markRemovedByAdmin(anyLong(), anyLong(), any(), any(), any());
    }

    @Test
    void removalKeepsTheAuthorForTheResultNotification() {
        when(products.lockById(PRODUCT)).thenReturn(Optional.of(product(Product.PUBLIC)));
        when(store.comment(500L)).thenReturn(Optional.of(comment(500, VIEWER, null, NOW, null)));
        when(store.lockComment(500L)).thenReturn(Optional.of(comment(500, VIEWER, null, NOW, null)));
        when(cases.claimedForProduct(MANAGER, CASE, PRODUCT)).thenReturn(true);
        when(store.markRemovedByAdmin(eq(500L), eq(MANAGER), eq("spam"), eq("case:100:enforcement:E-1"), any()))
                .thenReturn(true);

        var removed = interactions.removeComment(MANAGER, CASE, 500, "E-1", "spam");

        assertThat(removed.authorAccountId()).isEqualTo(VIEWER);
        assertThat(removed.status()).isEqualTo(ProductComment.REMOVED_BY_ADMIN);
    }

    @Test
    void lockedRemovalTrustsThePreparedKeysAndKeepsTheAuthor() {
        var transaction = mock(WriteTransaction.class);
        when(transaction.context()).thenReturn(context(MANAGER));
        when(store.comment(500L)).thenReturn(Optional.of(comment(500, VIEWER, null, NOW, null)));
        when(products.findById(PRODUCT)).thenReturn(Optional.of(product(Product.PUBLIC)));
        when(store.markRemovedByAdmin(eq(500L), eq(MANAGER), eq("spam"), eq("case:100:enforcement:E-1"), eq(NOW)))
                .thenReturn(true);

        var removed = interactions.removeCommentLocked(transaction, CASE, 500, PRODUCT, "E-1", "spam", NOW);

        verify(transaction).requireLocked(ProductInteractions.productLockKey(PRODUCT));
        verify(transaction).requireLocked(ProductInteractions.commentLockKey(500));
        assertThat(removed.commentId()).isEqualTo("500");
        assertThat(removed.authorAccountId()).isEqualTo(VIEWER);
        assertThat(removed.previousState()).isEqualTo(ProductComment.PUBLISHED);
        assertThat(removed.currentState()).isEqualTo(ProductComment.REMOVED_BY_ADMIN);
        assertThat(removed.status()).isEqualTo(ProductComment.REMOVED_BY_ADMIN);
    }

    @Test
    void lockedRemovalRejectsAStaleProductTarget() {
        var transaction = mock(WriteTransaction.class);
        when(transaction.context()).thenReturn(context(MANAGER));
        when(store.comment(500L)).thenReturn(Optional.of(new ProductComment(500, OTHER_PRODUCT, VIEWER, null,
                "Hello", NOW, null, null, null, null)));

        assertFailure(() -> interactions.removeCommentLocked(transaction, CASE, 500, PRODUCT, "E-1", "spam", NOW),
                "TARGET_STATE_CONFLICT");
        verify(store, never()).markRemovedByAdmin(anyLong(), anyLong(), any(), any(), any());
    }

    @Test
    void lockedRemovalDistinguishesMissingAndAlreadyRemovedComments() {
        var transaction = mock(WriteTransaction.class);
        when(transaction.context()).thenReturn(context(MANAGER));
        when(store.comment(500L)).thenReturn(Optional.empty());
        when(store.comment(501L)).thenReturn(Optional.of(comment(501, VIEWER, null, NOW, NOW)));

        assertFailure(() -> interactions.removeCommentLocked(transaction, CASE, 500, PRODUCT, "E-1", "spam", NOW),
                "CONTENT_NOT_FOUND");
        assertFailure(() -> interactions.removeCommentLocked(transaction, CASE, 501, PRODUCT, "E-1", "spam", NOW),
                "TARGET_STATE_CONFLICT");
    }

    @Test
    void productAndCommentLookupsAreAvailableBeforeLocking() {
        when(store.productIdOfComment(500L)).thenReturn(OptionalLong.of(PRODUCT));
        when(store.comment(500L)).thenReturn(Optional.of(comment(500, VIEWER, null, NOW, null)));

        assertThat(interactions.productForComment(500L)).hasValue(PRODUCT);
        assertThat(interactions.commentTarget(500L)).get()
                .satisfies(target -> {
                    assertThat(target.commentId()).isEqualTo(500);
                    assertThat(target.productId()).isEqualTo(PRODUCT);
                    assertThat(target.authorAccountId()).isEqualTo(VIEWER);
                });
    }

    @Test
    void claimedManagerReadsTheCaseScopeOnAPublicProduct() {
        when(products.findById(PRODUCT)).thenReturn(Optional.of(product(Product.PUBLIC)));
        when(cases.claimedForProduct(MANAGER, CASE, PRODUCT)).thenReturn(true);
        var removed = comment(600, VIEWER, null, NOW.minusSeconds(60), NOW);
        when(store.topLevelComments(PRODUCT, ProductInteractionStore.Scope.CASE, MANAGER, 20, 0L))
                .thenReturn(List.of(removed));
        when(store.countTopLevelComments(PRODUCT, ProductInteractionStore.Scope.CASE, MANAGER)).thenReturn(1L);
        when(store.replies(eq(PRODUCT), eq(List.of(600L)), eq(ProductInteractionStore.Scope.CASE), eq(MANAGER)))
                .thenReturn(List.of());

        var page = interactions.listComments(MANAGER, PRODUCT, 1, 20, CASE);

        assertThat(page.items()).singleElement()
                .satisfies(item -> assertThat(item.status()).isEqualTo(ProductComment.REMOVED_BY_ADMIN));
    }

    @Test
    void favouriteStatusOfADeletedProductStaysInvalidInsteadOfMissing() {
        when(products.findById(PRODUCT)).thenReturn(Optional.of(deletedProduct()));
        when(store.favorite(VIEWER, PRODUCT))
                .thenReturn(Optional.of(new ProductInteractionStore.FavoriteRow(100L, PRODUCT, NOW)));

        var status = interactions.favoriteStatus(VIEWER, PRODUCT);

        assertThat(status.favorited()).isTrue();
        assertThat(status.valid()).isFalse();
    }

    @Test
    void pagingBoundsAreRejectedBeforeReading() {
        assertFailure(() -> interactions.listFavorites(VIEWER, 0, 20), "INPUT_INVALID");
        assertFailure(() -> interactions.listFavorites(VIEWER, 1, 101), "INPUT_INVALID");
        verify(store, never()).favorites(anyLong(), any(), any(Integer.class).intValue(), anyLong());
    }

    @Test
    void activeDisplayRestrictionHidesPublicCommentsFromStrangers() {
        when(products.findById(PRODUCT)).thenReturn(Optional.of(product(Product.PUBLIC)));
        when(displayRestrictions.hasActive(PRODUCT)).thenReturn(true);
        when(store.hasCommentBy(PRODUCT, VIEWER)).thenReturn(false);

        assertFailure(() -> interactions.listComments(VIEWER, PRODUCT, 1, 20, null), "RESOURCE_NOT_VISIBLE");
    }

    @Test
    void restrictedProductCannotBeFavorited() {
        when(products.findById(PRODUCT)).thenReturn(Optional.of(product(Product.PUBLIC)));
        when(displayRestrictions.hasActive(PRODUCT)).thenReturn(true);

        assertFailure(() -> interactions.addFavorite(VIEWER, PRODUCT), "RESOURCE_NOT_VISIBLE");
        verify(store, never()).insertFavorite(anyLong(), anyLong(), any());
    }

    @Test
    void favouriteOfARestrictedProductIsInvalidWithoutContent() {
        when(products.findById(PRODUCT)).thenReturn(Optional.of(product(Product.PUBLIC)));
        when(displayRestrictions.hasActive(PRODUCT)).thenReturn(true);
        when(store.favorite(VIEWER, PRODUCT))
                .thenReturn(Optional.of(new ProductInteractionStore.FavoriteRow(100L, PRODUCT, NOW)));

        var status = interactions.favoriteStatus(VIEWER, PRODUCT);

        assertThat(status.favorited()).isTrue();
        assertThat(status.valid()).isFalse();
    }

    @Test
    void favouriteListMarksARestrictedProductInvalidInOneBatch() {
        when(store.favorites(VIEWER, null, 20, 0L)).thenReturn(List.of(
                new ProductInteractionStore.FavoriteRow(100L, PRODUCT, NOW)));
        when(store.countFavorites(VIEWER, null)).thenReturn(1L);
        Product publicProduct = product(Product.PUBLIC);
        when(products.findByIdIn(List.of(PRODUCT))).thenReturn(List.of(publicProduct));
        when(displayRestrictions.activeProductIds(Set.of(PRODUCT))).thenReturn(Set.of(PRODUCT));

        var page = interactions.listFavorites(VIEWER, 1, 20);

        assertThat(page.items()).singleElement().satisfies(item -> {
            assertThat(item.status()).isEqualTo("invalid");
            assertThat(item.product()).isNull();
        });
    }

    private static void assertFailure(Runnable action, String code) {
        assertThatThrownBy(action::run)
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo(code));
    }

    private static Product product(String state) {
        return product(PRODUCT, state);
    }

    private static Product product(long id, String state) {
        Product product = new Product(SELLER, "Book", "Used book", 1_000, NOW);
        ReflectionTestUtils.setField(product, "id", id);
        product.transition(state, NOW);
        return product;
    }

    private static Product deletedProduct() {
        Product product = product(PRODUCT, Product.PUBLIC);
        ReflectionTestUtils.setField(product, "deletedAt", NOW);
        return product;
    }

    private static ExecutionContext context(long accountId) {
        return new ExecutionContext(UUID.randomUUID(), ExecutionContext.ActorKind.ACCOUNT,
                Long.toString(accountId), UUID.randomUUID(), null, 1L, "product-interaction-test");
    }

    private static ProductComment comment(long id, long author, Long parent, Instant createdAt, Instant removedAt) {
        return new ProductComment(id, PRODUCT, author, parent, "Hello", createdAt, null, removedAt,
                removedAt == null ? null : "spam", removedAt == null ? null : "case:100");
    }
}
