package io.github.iy88.project1.product.application;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.WriteTransaction;
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
import java.util.OptionalLong;
import java.util.Set;
import java.util.stream.Collectors;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;
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
    private final ProductDisplayRestrictions displayRestrictions;
    private final ApplicationEventPublisher events;
    private final Clock clock;
    private final TransactionTemplate transaction;

    @Autowired
    public ProductInteractions(ProductRepository products, ProductService productDetails,
                               ProductInteractionStore store, CaseCommentAccess cases,
                               CommentAccountAccess accounts, ProductSettings settings,
                               ProductDisplayRestrictions displayRestrictions,
                               ApplicationEventPublisher events, PlatformTransactionManager transactionManager,
                               ObjectProvider<Clock> clocks) {
        this(products, productDetails, store, cases, accounts, settings, displayRestrictions, events,
                transactionManager, clocks.getIfAvailable(Clock::systemUTC));
    }

    ProductInteractions(ProductRepository products, ProductService productDetails,
                        ProductInteractionStore store, CaseCommentAccess cases, CommentAccountAccess accounts,
                        ProductSettings settings, ProductDisplayRestrictions displayRestrictions,
                        ApplicationEventPublisher events, PlatformTransactionManager transactionManager, Clock clock) {
        this.products = products;
        this.productDetails = productDetails;
        this.store = store;
        this.cases = cases;
        this.accounts = accounts;
        this.settings = settings;
        this.displayRestrictions = displayRestrictions;
        this.events = events;
        this.clock = clock;
        this.transaction = new TransactionTemplate(transactionManager);
    }

    // ------------------------------------------------------------------ comments

    public CommentPage listComments(long viewerId, long productId, Integer page, Integer pageSize, Long caseId) {
        return listComments(viewerId, productId, page, pageSize, caseId, null);
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public CommentPage listComments(long viewerId, long productId, Integer page, Integer pageSize, Long caseId,
                                    Long anchorId) {
        Product product = requireProduct(productId);
        int[] paging = paging(page, pageSize);
        ProductInteractionStore.Scope scope = readScope(product, viewerId, caseId);
        if (anchorId != null) {
            var anchor = store.comment(anchorId).filter(comment -> comment.productId() == productId);
            if (scope != ProductInteractionStore.Scope.CASE) {
                anchor = anchor.filter(item -> item.published());
            }
            var thread = anchor.flatMap(comment -> comment.topLevel() ? Optional.of(comment)
                    : store.comment(comment.parentCommentId()));
            paging[0] = thread.filter(root -> root.productId() == productId && root.topLevel())
                    .filter(root -> switch (scope) {
                        case PUBLIC -> root.published();
                        case AUTHOR -> root.authorAccountId() == viewerId;
                        case CASE -> true;
                    })
                    .map(root -> Math.toIntExact(store.countNewerTopLevelComments(root, scope, viewerId)
                            / paging[1] + 1)).orElse(paging[0]);
        }
        long offset = (long) (paging[0] - 1) * paging[1];
        List<ProductComment> topLevel = store.topLevelComments(productId, scope, viewerId, paging[1], offset);
        long total = store.countTopLevelComments(productId, scope, viewerId);
        List<Long> parentIds = topLevel.stream().map(source -> source.commentId()).toList();
        Map<Long, List<ProductComment>> replies = store.replies(productId, parentIds, scope, viewerId).stream()
                .collect(Collectors.groupingBy(component -> component.parentCommentId(), LinkedHashMap::new,
                        Collectors.toList()));
        Set<Long> authorIds = new java.util.LinkedHashSet<>();
        topLevel.forEach(comment -> authorIds.add(comment.authorAccountId()));
        replies.values().forEach(list -> list.forEach(reply -> authorIds.add(reply.authorAccountId())));
        Map<Long, CommentAccountAccess.Profile> profiles = accounts.profiles(authorIds);
        List<CommentView> items = new ArrayList<>();
        for (ProductComment comment : topLevel) {
            List<CommentView> thread = replies.getOrDefault(comment.commentId(), List.of()).stream()
                    .map(reply -> view(reply, profiles, List.of()))
                    .toList();
            items.add(view(comment, profiles, thread));
        }
        return new CommentPage(items, paging[0], paging[1], total);
    }

    /** Returns the author if the published comment is in the viewer's ordinary comment scope. */
    public Optional<Long> reportableCommentAuthor(long viewerId, long commentId) {
        return store.comment(commentId).filter(item -> item.published())
                .filter(comment -> comment.authorAccountId() != viewerId)
                .filter(comment -> products.findById(comment.productId())
                        .filter(product -> !product.deleted())
                        .filter(product -> reportableCommentThread(product, comment, viewerId)).isPresent())
                .map(subject -> subject.authorAccountId());
    }

    /** Resolves the author of a previously accepted report, even after the comment is removed. */
    public Optional<Long> commentAuthor(long commentId) {
        return store.comment(commentId).map(subject -> subject.authorAccountId());
    }

    /** Product carrying a reported comment, including a removed comment's retained history. */
    public OptionalLong commentProductId(long commentId) {
        return store.comment(commentId)
                .map(comment -> OptionalLong.of(comment.productId()))
                .orElseGet(OptionalLong::empty);
    }

    private boolean reportableCommentThread(Product product, ProductComment comment, long viewerId) {
        var root = comment.topLevel() ? Optional.of(comment) : store.comment(comment.parentCommentId());
        return root.filter(parent -> parent.productId() == product.id() && parent.topLevel() && parent.published())
                .filter(parent -> baseVisible(product) || parent.authorAccountId() == viewerId).isPresent();
    }

    public CommentView createComment(long viewerId, long productId, String body) {
        return transaction.execute(status -> {
            requireAccountWritable(viewerId);
            Product product = lockProduct(productId);
            boolean seller = product.sellerAccountId() == viewerId;
            boolean visible = publiclyVisible(product);
            if (!seller && !visible) {
                throw notVisible();
            }
            if (!visible) {
                throw new BusinessError("COMMENT_NOT_ALLOWED", 409, "当前商品不能发表评论");
            }
            String text = validatedBody(body);
            requireCommentRate(viewerId);
            Instant now = clock.instant();
            long commentId = store.insertComment(productId, viewerId, null, text, now);
            ProductComment comment = store.comment(commentId)
                    .orElseThrow(() -> new BusinessError("DEPENDENCY_UNAVAILABLE", 503, "评论写入失败"));
            if (!seller) {
                events.publishEvent(new ProductCommentNotice(product.sellerAccountId(), productId, commentId,
                        false, now));
            }
            return view(comment, accounts.profiles(Set.of(viewerId)), List.of());
        });
    }

    public CommentView replyToComment(long viewerId, long productId, long commentId, String body) {
        return transaction.execute(status -> {
            requireAccountWritable(viewerId);
            Product product = lockProduct(productId);
            if (product.sellerAccountId() != viewerId) {
                throw new BusinessError("COMMENT_REPLY_NOT_ALLOWED", 403, "只能由商品卖方回复评论");
            }
            if (!publiclyVisible(product)) {
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
            if (parent.authorAccountId() != viewerId) {
                events.publishEvent(new ProductCommentNotice(parent.authorAccountId(), productId, replyId,
                        true, now));
            }
            return view(reply, accounts.profiles(Set.of(viewerId)), List.of());
        });
    }

    /** Returns the content of a published comment or of a published reply to the recipient. */
    public Optional<String> notificationCommentBody(long viewerId, long productId, long commentId, boolean reply) {
        return store.comment(commentId)
                .filter(comment -> comment.productId() == productId && comment.published())
                .filter(comment -> reply
                        ? !comment.topLevel() && store.comment(comment.parentCommentId())
                                .filter(parent -> parent.productId() == productId && parent.topLevel()
                                        && parent.published() && parent.authorAccountId() == viewerId).isPresent()
                        : comment.topLevel())
                .map(entry -> entry.body());
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
     * Product lookup for the enforcement prepare phase. It reads without a row lock; the caller
     * plans the product and comment keys and revalidates them under the write transaction.
     */
    public OptionalLong productForComment(long commentId) {
        return store.productIdOfComment(commentId);
    }

    /** Product and author of a comment, used when the caller needs both before locking. */
    public Optional<CommentTarget> commentTarget(long commentId) {
        return store.comment(commentId)
                .map(comment -> new CommentTarget(comment.commentId(), comment.productId(),
                        comment.authorAccountId()));
    }

    /**
     * Read-only snapshot of one comment for a caller that has already authorized the exact case
     * target. The body is retained after moderation so the claimed manager can review it; this
     * method does not widen the public or author comment scope.
     */
    public Optional<CommentSnapshot> commentSnapshot(long commentId) {
        return store.comment(commentId)
                .map(comment -> new CommentSnapshot(comment.commentId(), comment.productId(),
                        comment.authorAccountId(), comment.parentCommentId(), comment.body(), comment.state(),
                        comment.createdAt(), comment.removedAt()));
    }

    /**
     * Locks one comment row for a caller that already planned the PRODUCT_DETAIL comment key. The
     * caller must hold the product row first, matching the product -> comment order used by all
     * comment mutations.
     */
    public ProductComment lockCommentRow(long commentId) {
        return store.lockComment(commentId).orElseThrow(ProductInteractions::contentNotFound);
    }

    /**
     * Acquires the planned PRODUCT_DETAIL comment key and locks its row. For callers outside a
     * {@code SubjectPlan} callback; the key must already be part of the write lock plan.
     */
    public ProductComment lockCommentRow(WriteTransaction transaction, long commentId) {
        ProductComment[] locked = new ProductComment[1];
        transaction.lock(commentLockKey(commentId), () -> locked[0] = lockCommentRow(commentId));
        return locked[0];
    }

    /**
     * Enforcement entry used by the handling work package (R2b): a claimed manager removes one
     * comment and the removal keeps the body, author and time for review history. The caller owns
     * the surrounding transaction; this call joins it. Case-target authorization stays with the
     * caller.
     */
    public RemovedComment removeComment(long managerId, long caseId, long commentId, String enforcementId,
                                        String reason) {
        String text = requiredReason(reason);
        return transaction.execute(status -> {
            // Resolve the product without a lock so the row lock order stays product -> comment.
            long productId = store.comment(commentId).map(mapped -> mapped.productId())
                    .orElseThrow(ProductInteractions::contentNotFound);
            products.lockById(productId)
                    .filter(product -> !product.deleted())
                    .orElseThrow(ProductInteractions::contentNotFound);
            ProductComment comment = store.lockComment(commentId)
                    .filter(found -> found.productId() == productId)
                    .orElseThrow(ProductInteractions::contentNotFound);
            if (!cases.claimedForProduct(managerId, caseId, comment.productId())) {
                throw new BusinessError("ACTION_NOT_ALLOWED", 403, "只能移除本人认领事项范围内的评论");
            }
            comment.requireRemovable();
            return removeCommentFacts(comment, managerId, caseId, enforcementId, text, clock.instant(),
                    "STATE_CONFLICT");
        });
    }

    /**
     * Locked enforcement variant. The case coordinator has already authorized the case target and
     * acquired the PRODUCT and PRODUCT_DETAIL comment keys through the shared lock plan; this
     * method re-reads under those locks and writes only the removal facts.
     */
    public RemovedComment removeCommentLocked(WriteTransaction transaction, long caseId, long commentId,
                                              long expectedProductId, String enforcementId, String reason,
                                              Instant at) {
        transaction.requireLocked(productLockKey(expectedProductId));
        transaction.requireLocked(commentLockKey(commentId));
        if (at == null) {
            throw new BusinessError(INVALID_INPUT, 422, "移除时间无效");
        }
        String text = requiredReason(reason);
        ProductComment comment = store.comment(commentId).orElseThrow(ProductInteractions::contentNotFound);
        if (comment.productId() != expectedProductId) {
            throw targetConflict("评论所属商品已变化");
        }
        if (comment.removedAt() != null) {
            throw targetConflict("评论已被移除");
        }
        products.findById(expectedProductId).filter(product -> !product.deleted())
                .orElseThrow(ProductInteractions::contentNotFound);
        long managerId = Long.parseLong(transaction.context().actorId());
        return removeCommentFacts(comment, managerId, caseId, enforcementId, text, at, "TARGET_STATE_CONFLICT");
    }

    private RemovedComment removeCommentFacts(ProductComment comment, long managerId, long caseId,
                                              String enforcementId, String reason, Instant at,
                                              String conflictCode) {
        String basisRef = enforcementId == null || enforcementId.isBlank()
                ? "case:" + caseId : "case:" + caseId + ":enforcement:" + enforcementId;
        if (!store.markRemovedByAdmin(comment.commentId(), managerId, reason, basisRef, at)) {
            throw new BusinessError(conflictCode, 409, "评论已被移除");
        }
        return new RemovedComment(Long.toString(comment.commentId()), comment.authorAccountId(),
                comment.state(), ProductComment.REMOVED_BY_ADMIN);
    }

    /** Shared key for the comment row in the existing PRODUCT_DETAIL lock domain. */
    public static LockPlan.Key commentLockKey(long commentId) {
        return new LockPlan.Key(LockPlan.Domain.PRODUCT_DETAIL, List.of(commentId));
    }

    /** Shared key for the product root; comment writes always take it before the comment row. */
    public static LockPlan.Key productLockKey(long productId) {
        return new LockPlan.Key(LockPlan.Domain.PRODUCT, List.of(productId));
    }

    private static BusinessError contentNotFound() {
        return new BusinessError("CONTENT_NOT_FOUND", 404, "评论不存在");
    }

    private static BusinessError targetConflict(String message) {
        return new BusinessError("TARGET_STATE_CONFLICT", 409, message);
    }

    // ------------------------------------------------------------------ favourites

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public FavoritePage listFavorites(long accountId, Integer page, Integer pageSize) {
        var result = readFavorites(accountId, null, page, pageSize);
        var items = result.items().stream().map(candidate -> candidate.item()).toList();
        return new FavoritePage(items, result.page(), result.pageSize(), result.total());
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public FavoriteResources listFavoriteResources(long accountId, String state, Integer page, Integer pageSize) {
        if (state != null && !Set.of("valid", "invalid").contains(state)) {
            throw new BusinessError(INVALID_INPUT, 422, "收藏状态无效");
        }
        var result = readFavorites(accountId, state, page, pageSize);
        var items = result.items().stream().map(row -> new FavoriteResourceItem(Long.toString(row.favoriteId()),
                row.item().favoritedAt(), row.item().status(), row.item().product())).toList();
        return new FavoriteResources("favorite", items, result.page(), result.pageSize(), result.total(),
                clock.instant());
    }

    /** Overview counts use the same validity predicate as the favourite list. */
    public FavoriteCounts favoriteCounts(long accountId) {
        long total = store.countFavorites(accountId, null);
        long valid = store.countFavorites(accountId, "valid");
        return new FavoriteCounts(total, valid, total - valid);
    }

    private FavoriteSelection readFavorites(long accountId, String state, Integer page, Integer pageSize) {
        int[] paging = paging(page, pageSize);
        long offset = (long) (paging[0] - 1) * paging[1];
        List<ProductInteractionStore.FavoriteRow> rows = store.favorites(accountId, state, paging[1], offset);
        long total = store.countFavorites(accountId, state);
        List<Long> productIds = rows.stream().map(member -> member.productId()).toList();
        if (productIds.isEmpty()) {
            return new FavoriteSelection(List.of(), paging[0], paging[1], total);
        }
        Map<Long, Product> productsById = products.findByIdIn(productIds).stream()
                .collect(Collectors.toMap(value -> value.id(), product -> product));
        Set<Long> restricted = displayRestrictions.activeProductIds(productsById.keySet());
        List<Product> validProducts = rows.stream()
                .map(row -> productsById.get(row.productId()))
                .filter(product -> product != null && baseVisible(product) && !restricted.contains(product.id()))
                .toList();
        Map<Long, ProductService.ProductSummary> summaries = productDetails.summaries(validProducts).stream()
                .collect(Collectors.toMap(summary -> Long.parseLong(summary.id()), summary -> summary));
        List<OwnedFavorite> items = new ArrayList<>();
        for (ProductInteractionStore.FavoriteRow row : rows) {
            ProductService.ProductSummary summary = summaries.get(row.productId());
            var item = summary == null
                    ? new FavoriteItem(Long.toString(row.productId()), "invalid", row.favoritedAt(), null, "该商品已失效")
                    : new FavoriteItem(Long.toString(row.productId()), "valid", row.favoritedAt(), summary, null);
            items.add(new OwnedFavorite(row.favoriteId(), item));
        }
        return new FavoriteSelection(items, paging[0], paging[1], total);
    }

    public FavoriteStatus favoriteStatus(long accountId, long productId) {
        // A favourite keeps its own fact when the product becomes invisible or is deleted, so the
        // state is resolved before the product row decides whether the caller may learn about it.
        Optional<ProductInteractionStore.FavoriteRow> favorite = store.favorite(accountId, productId);
        Product product = products.findById(productId).orElse(null);
        boolean valid = product != null && publiclyVisible(product);
        if (favorite.isEmpty() && !valid) {
            throw notVisible();
        }
        return new FavoriteStatus(favorite.isPresent(), valid,
                favorite.map(element -> element.favoritedAt()).orElse(null));
    }

    public FavoriteStatus addFavorite(long accountId, long productId) {
        return transaction.execute(status -> {
            requireAccountWritable(accountId);
            Product product = requireProduct(productId);
            if (!publiclyVisible(product)) {
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
        if (publiclyVisible(product)) {
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
    private boolean publiclyVisible(Product product) {
        return baseVisible(product) && !displayRestrictions.hasActive(product.id());
    }

    private static boolean baseVisible(Product product) {
        return !product.deleted()
                && (Product.PUBLIC.equals(product.lifecycleState())
                || Product.IN_TRADE.equals(product.lifecycleState()));
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

    private static CommentView view(ProductComment comment,
                                    Map<Long, CommentAccountAccess.Profile> profiles,
                                    List<CommentView> replies) {
        CommentAccountAccess.Profile profile = profiles.get(comment.authorAccountId());
        String authorName = profile == null ? "" : profile.displayName();
        return new CommentView(Long.toString(comment.commentId()), Long.toString(comment.productId()),
                new AuthorRef(Long.toString(comment.authorAccountId()), authorName,
                        profile == null ? null : profile.avatarUrl()),
                comment.body(), comment.state(),
                comment.parentCommentId() == null ? null : Long.toString(comment.parentCommentId()),
                comment.createdAt(), replies);
    }

    private static BusinessError notVisible() {
        return new BusinessError(NOT_VISIBLE, 404, "商品不存在");
    }

    public record AuthorRef(String id, String displayName, String avatarUrl) {
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

    public record FavoriteResourceItem(String favoriteId, Instant updatedAt, String state,
                                       ProductService.ProductSummary productSummary) {
    }

    public record FavoriteResources(String kind, List<FavoriteResourceItem> items, int page, int pageSize,
                                    long total, Instant asOf) {
    }

    public record FavoriteCounts(long total, long valid, long invalid) {
    }

    private record OwnedFavorite(long favoriteId, FavoriteItem item) {
    }

    private record FavoriteSelection(List<OwnedFavorite> items, int page, int pageSize, long total) {
    }

    public record FavoriteStatus(boolean favorited, boolean valid, Instant favoritedAt) {
    }

    /** Product and author of a comment, resolved before the caller plans its locks. */
    public record CommentTarget(long commentId, long productId, long authorAccountId) {
    }

    /** Exact comment content for the claimed manager's case target. */
    public record CommentSnapshot(long commentId, long productId, long authorAccountId, Long parentCommentId,
                                  String body, String state, Instant createdAt, Instant removedAt) {
    }

    /**
     * A removed comment with the retained author and named before/after states. The three-argument
     * constructor keeps the previous direct-entry result shape.
     */
    public record RemovedComment(String commentId, long authorAccountId, String previousState,
                                 String currentState) {
        public RemovedComment(String commentId, long authorAccountId, String status) {
            this(commentId, authorAccountId, null, status);
        }

        public String resultId() {
            return commentId;
        }

        public String status() {
            return currentState;
        }
    }
}
