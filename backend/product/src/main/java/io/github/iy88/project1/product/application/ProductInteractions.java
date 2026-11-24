package io.github.iy88.project1.product.application;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.product.ProductSettings;
import io.github.iy88.project1.product.domain.ProductComment;
import io.github.iy88.project1.product.persistence.Product;
import io.github.iy88.project1.product.persistence.ProductRepository;
import java.time.Clock;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.stream.Collectors;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * Product comments, seller replies and account favourites.
 *
 * <p>Visibility is decided from the current product state: a public or in-trade product exposes the
 * published list; a hidden product exposes the reader's own comments, a seller their own thread, and
 * a claimed manager the case's necessary scope. Display restrictions are applied by the enforcement
 * work package through the product state this class reads, so the rule stays in one place.
 */
@Service
@Profile("infrastructure")
public class ProductInteractions {
    private static final String NOT_VISIBLE = "RESOURCE_NOT_VISIBLE";
    private static final String INVALID_INPUT = "INPUT_INVALID";

    private final ProductRepository products;
    private final ProductService productDetails;
    private final ProductInteractionStore store;
    private final CaseCommentAccess cases;
    private final CommentAccountAccess accounts;
    private final ProductSettings settings;
    private final Clock clock;
    private final TransactionTemplate transaction;

    @Autowired
    public ProductInteractions(ProductRepository products, ProductService productDetails,
                               ProductInteractionStore store, CaseCommentAccess cases,
                               CommentAccountAccess accounts, ProductSettings settings,
                               PlatformTransactionManager transactionManager, ObjectProvider<Clock> clocks) {
        this(products, productDetails, store, cases, accounts, settings, transactionManager,
                clocks.getIfAvailable(Clock::systemUTC));
    }

    ProductInteractions(ProductRepository products, ProductService productDetails,
                        ProductInteractionStore store, CaseCommentAccess cases, CommentAccountAccess accounts,
                        ProductSettings settings, PlatformTransactionManager transactionManager, Clock clock) {
        this.products = products;
        this.productDetails = productDetails;
        this.store = store;
        this.cases = cases;
        this.accounts = accounts;
        this.settings = settings;
        this.clock = clock;
        this.transaction = new TransactionTemplate(transactionManager);
    }

    // ------------------------------------------------------------------ comments

    public CommentPage listComments(long viewerId, long productId, Integer page, Integer pageSize, Long caseId) {
        Product product = requireProduct(productId);
        int[] paging = paging(page, pageSize);
        ProductInteractionStore.Scope scope = readScope(product, viewerId, caseId);
        long offset = (long) (paging[0] - 1) * paging[1];
        List<ProductComment> topLevel = store.topLevelComments(productId, scope, viewerId, paging[1], offset);
        long total = store.countTopLevelComments(productId, scope, viewerId);
        List<Long> parentIds = topLevel.stream().map(ProductComment::commentId).toList();
        Map<Long, List<ProductComment>> replies = store.replies(productId, parentIds, scope, viewerId).stream()
                .collect(Collectors.groupingBy(ProductComment::parentCommentId, LinkedHashMap::new,
                        Collectors.toList()));
        Set<Long> authorIds = new java.util.LinkedHashSet<>();
        topLevel.forEach(comment -> authorIds.add(comment.authorAccountId()));
        replies.values().forEach(list -> list.forEach(reply -> authorIds.add(reply.authorAccountId())));
        Map<Long, String> profiles = accounts.displayNames(authorIds);
        List<CommentView> items = new ArrayList<>();
        for (ProductComment comment : topLevel) {
            List<CommentView> thread = replies.getOrDefault(comment.commentId(), List.of()).stream()
                    .map(reply -> view(reply, profiles, List.of()))
                    .toList();
            items.add(view(comment, profiles, thread));
        }
        return new CommentPage(items, paging[0], paging[1], total);
    }

    public CommentView createComment(long viewerId, long productId, String body) {
        return transaction.execute(status -> {
            requireAccountWritable(viewerId);
            Product product = lockProduct(productId);
            boolean seller = product.sellerAccountId() == viewerId;
            if (!seller && !visible(product)) {
                throw notVisible();
            }
            if (!commentable(product)) {
                throw new BusinessError("COMMENT_NOT_ALLOWED", 409, "当前商品不能发表评论");
            }
            String text = validatedBody(body);
            requireCommentRate(viewerId);
            Instant now = clock.instant();
            long commentId = store.insertComment(productId, viewerId, null, text, now);
            ProductComment comment = store.comment(commentId)
                    .orElseThrow(() -> new BusinessError("DEPENDENCY_UNAVAILABLE", 503, "评论写入失败"));
            return view(comment, accounts.displayNames(Set.of(viewerId)), List.of());
        });
    }

    public CommentView replyToComment(long viewerId, long productId, long commentId, String body) {
        return transaction.execute(status -> {
            requireAccountWritable(viewerId);
            Product product = lockProduct(productId);
            if (product.sellerAccountId() != viewerId) {
                throw new BusinessError("COMMENT_REPLY_NOT_ALLOWED", 403, "只能由商品卖方回复评论");
            }
            if (!commentable(product)) {
                throw new BusinessError("COMMENT_NOT_ALLOWED", 409, "当前商品不能回复评论");
            }
            ProductComment parent = store.lockComment(commentId)
                    .filter(comment -> comment.productId() == productId)
                    .orElseThrow(ProductInteractions::notVisible);
            parent.requireReplyTarget();
            String text = validatedBody(body);
            requireCommentRate(viewerId);
            Instant now = clock.instant();
            long replyId = store.insertComment(productId, viewerId, parent.commentId(), text, now);
            ProductComment reply = store.comment(replyId)
                    .orElseThrow(() -> new BusinessError("DEPENDENCY_UNAVAILABLE", 503, "回复写入失败"));
            return view(reply, accounts.displayNames(Set.of(viewerId)), List.of());
        });
    }

    public void deleteComment(long viewerId, long productId, long commentId) {
        transaction.executeWithoutResult(status -> {
            requireAccountWritable(viewerId);
            // Documented lock order: product row first, then the comment row.
            lockProduct(productId);
            ProductComment comment = store.lockComment(commentId)
                    .filter(found -> found.productId() == productId)
                    .orElseThrow(ProductInteractions::notVisible);
            comment.requireDeleteBy(viewerId);
            if (comment.deletedAt() != null) {
                return;
            }
            if (!store.markDeletedByAuthor(commentId, clock.instant())) {
                ProductComment current = store.comment(commentId).orElseThrow(ProductInteractions::notVisible);
                current.requireDeleteBy(viewerId);
                if (current.removedAt() != null) {
                    throw new BusinessError("COMMENT_ALREADY_REMOVED", 409, "评论已被管理员移除");
                }
            }
        });
    }

    /**
     * Enforcement entry used by the handling work package (R2b): a claimed manager removes one
     * comment and the removal keeps the body, author and time for review history. The caller owns
     * the surrounding transaction; this call joins it.
     */
    public RemovedComment removeComment(long managerId, long caseId, long commentId, String enforcementId,
                                        String reason) {
        String text = requiredReason(reason);
        return transaction.execute(status -> {
            // Resolve the product without a lock so the row lock order stays product -> comment.
            long productId = store.comment(commentId).map(ProductComment::productId)
                    .orElseThrow(() -> new BusinessError("CONTENT_NOT_FOUND", 404, "评论不存在"));
            products.lockById(productId)
                    .filter(product -> !product.deleted())
                    .orElseThrow(() -> new BusinessError("CONTENT_NOT_FOUND", 404, "评论不存在"));
            ProductComment comment = store.lockComment(commentId)
                    .filter(found -> found.productId() == productId)
                    .orElseThrow(() -> new BusinessError("CONTENT_NOT_FOUND", 404, "评论不存在"));
            if (!cases.claimedForProduct(managerId, caseId, comment.productId())) {
                throw new BusinessError("ACTION_NOT_ALLOWED", 403, "只能移除本人认领事项范围内的评论");
            }
            comment.requireRemovable();
            String basisRef = enforcementId == null || enforcementId.isBlank()
                    ? "case:" + caseId : "case:" + caseId + ":enforcement:" + enforcementId;
            if (!store.markRemovedByAdmin(commentId, managerId, text, basisRef, clock.instant())) {
                throw new BusinessError("STATE_CONFLICT", 409, "评论已被移除");
            }
            return new RemovedComment(Long.toString(commentId), comment.authorAccountId(),
                    ProductComment.REMOVED_BY_ADMIN);
        });
    }

    // ------------------------------------------------------------------ favourites

    public FavoritePage listFavorites(long accountId, Integer page, Integer pageSize) {
        int[] paging = paging(page, pageSize);
        long offset = (long) (paging[0] - 1) * paging[1];
        List<ProductInteractionStore.FavoriteRow> rows = store.favorites(accountId, paging[1], offset);
        long total = store.countFavorites(accountId);
        List<Long> productIds = rows.stream().map(ProductInteractionStore.FavoriteRow::productId).toList();
        if (productIds.isEmpty()) {
            return new FavoritePage(List.of(), paging[0], paging[1], total);
        }
        Map<Long, Product> productsById = products.findByIdIn(productIds).stream()
                .collect(Collectors.toMap(Product::id, product -> product));
        List<Product> validProducts = rows.stream()
                .map(row -> productsById.get(row.productId()))
                .filter(product -> product != null && visible(product))
                .toList();
        Map<Long, ProductService.ProductSummary> summaries = productDetails.summaries(validProducts).stream()
                .collect(Collectors.toMap(summary -> Long.parseLong(summary.id()), summary -> summary));
        List<FavoriteItem> items = new ArrayList<>();
        for (ProductInteractionStore.FavoriteRow row : rows) {
            ProductService.ProductSummary summary = summaries.get(row.productId());
            items.add(summary == null
                    ? new FavoriteItem(Long.toString(row.productId()), "invalid", row.favoritedAt(), null,
                    "该商品已失效")
                    : new FavoriteItem(Long.toString(row.productId()), "valid", row.favoritedAt(), summary, null));
        }
        return new FavoritePage(items, paging[0], paging[1], total);
    }

    public FavoriteStatus favoriteStatus(long accountId, long productId) {
        // A favourite keeps its own fact when the product becomes invisible or is deleted, so the
        // state is resolved before the product row decides whether the caller may learn about it.
        Optional<ProductInteractionStore.FavoriteRow> favorite = store.favorite(accountId, productId);
        Product product = products.findById(productId).orElse(null);
        boolean valid = product != null && visible(product);
        if (favorite.isEmpty() && !valid) {
            throw notVisible();
        }
        return new FavoriteStatus(favorite.isPresent(), valid,
                favorite.map(ProductInteractionStore.FavoriteRow::favoritedAt).orElse(null));
    }

    public FavoriteStatus addFavorite(long accountId, long productId) {
        return transaction.execute(status -> {
            requireAccountWritable(accountId);
            Product product = requireProduct(productId);
            if (!visible(product)) {
                throw notVisible();
            }
            ProductInteractionStore.FavoriteRow favorite = store.favorite(accountId, productId).orElse(null);
            if (favorite == null) {
                store.insertFavorite(accountId, productId, clock.instant());
                favorite = store.favorite(accountId, productId).orElse(null);
            }
            if (favorite == null) {
                throw new BusinessError("DEPENDENCY_UNAVAILABLE", 503, "收藏写入失败");
            }
            return new FavoriteStatus(true, true, favorite.favoritedAt());
        });
    }

    public void removeFavorite(long accountId, long productId) {
        transaction.executeWithoutResult(status -> {
            requireAccountWritable(accountId);
            store.deleteFavorite(accountId, productId);
        });
    }

    // ------------------------------------------------------------------ helpers

    private ProductInteractionStore.Scope readScope(Product product, long viewerId, Long caseId) {
        // A claimed manager reads the case's necessary scope, including removal facts, even while
        // the product is still publicly listed.
        if (caseId != null && cases.claimedForProduct(viewerId, caseId, product.id())) {
            return ProductInteractionStore.Scope.CASE;
        }
        if (visible(product)) {
            return ProductInteractionStore.Scope.PUBLIC;
        }
        if (product.sellerAccountId() == viewerId) {
            return ProductInteractionStore.Scope.AUTHOR;
        }
        if (store.hasCommentBy(product.id(), viewerId)) {
            return ProductInteractionStore.Scope.AUTHOR;
        }
        throw notVisible();
    }

    private Product requireProduct(long productId) {
        return products.findById(productId)
                .filter(product -> !product.deleted())
                .orElseThrow(ProductInteractions::notVisible);
    }

    private Product lockProduct(long productId) {
        return products.lockById(productId)
                .filter(product -> !product.deleted())
                .orElseThrow(ProductInteractions::notVisible);
    }

    /** A comment or favourite needs a product that is currently shown to the public. */
    private static boolean visible(Product product) {
        return !product.deleted()
                && (Product.PUBLIC.equals(product.lifecycleState())
                || Product.IN_TRADE.equals(product.lifecycleState()));
    }

    private static boolean commentable(Product product) {
        return visible(product);
    }

    private void requireAccountWritable(long accountId) {
        if (accounts.writeRestricted(accountId)) {
            throw new BusinessError("ACCOUNT_WRITE_RESTRICTED", 403, "账户当前受限");
        }
    }

    private void requireCommentRate(long accountId) {
        Instant since = clock.instant().minusSeconds(settings.commentRateLimitWindowSeconds());
        if (store.countCommentsSince(accountId, since) >= settings.commentRateLimitCount()) {
            throw new BusinessError("RATE_LIMITED", 429, "评论过于频繁，请稍后再试");
        }
    }

    private String validatedBody(String value) {
        String body = value == null ? "" : value.trim();
        if (body.isEmpty() || body.codePointCount(0, body.length()) > settings.commentMaxLength()) {
            throw new BusinessError(INVALID_INPUT, 422, "评论内容无效");
        }
        return body;
    }

    private static String requiredReason(String value) {
        String reason = value == null ? "" : value.trim();
        if (reason.isEmpty() || reason.codePointCount(0, reason.length()) > 1000) {
            throw new BusinessError(INVALID_INPUT, 422, "移除原因无效");
        }
        return reason;
    }

    private int[] paging(Integer page, Integer pageSize) {
        int current = page == null ? 1 : page;
        int size = pageSize == null ? settings.pageSize() : pageSize;
        if (current < 1 || size < 1 || size > settings.pageSizeMax()) {
            throw new BusinessError(INVALID_INPUT, 422, "分页参数无效");
        }
        return new int[]{current, size};
    }

    private static CommentView view(ProductComment comment, Map<Long, String> profiles,
                                    List<CommentView> replies) {
        String authorName = profiles.getOrDefault(comment.authorAccountId(), "");
        return new CommentView(Long.toString(comment.commentId()), Long.toString(comment.productId()),
                new AuthorRef(Long.toString(comment.authorAccountId()), authorName),
                comment.body(), comment.state(),
                comment.parentCommentId() == null ? null : Long.toString(comment.parentCommentId()),
                comment.createdAt(), replies);
    }

    private static BusinessError notVisible() {
        return new BusinessError(NOT_VISIBLE, 404, "商品不存在");
    }

    public record AuthorRef(String id, String displayName) {
    }

    public record CommentView(String id, String productId, AuthorRef author, String body, String status,
                              String replyToCommentId, Instant createdAt, List<CommentView> replies) {
    }

    public record CommentPage(List<CommentView> items, int page, int pageSize, long total) {
    }

    public record FavoriteItem(String productId, String status, Instant favoritedAt,
                               ProductService.ProductSummary product, String message) {
    }

    public record FavoritePage(List<FavoriteItem> items, int page, int pageSize, long total) {
    }

    public record FavoriteStatus(boolean favorited, boolean valid, Instant favoritedAt) {
    }

    public record RemovedComment(String commentId, long authorAccountId, String status) {
    }
}
