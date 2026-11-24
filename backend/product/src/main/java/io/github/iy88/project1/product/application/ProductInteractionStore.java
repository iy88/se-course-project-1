package io.github.iy88.project1.product.application;

import io.github.iy88.project1.product.domain.ProductComment;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.OptionalLong;

/** Persistence seam for product comments, seller replies and favourites. */
public interface ProductInteractionStore {
    /** Which comments a reader may page over. */
    enum Scope {
        /** Public list: published comments only. */
        PUBLIC,
        /** Hidden product: only the reader's own comments, replies to them included when published. */
        AUTHOR,
        /** Claimed manager: every comment in the case's necessary scope, including removal facts. */
        CASE
    }

    record FavoriteRow(long productId, Instant favoritedAt) {
    }

    long insertComment(long productId, long authorAccountId, Long parentCommentId, String body, Instant now);

    Optional<ProductComment> comment(long commentId);

    Optional<ProductComment> lockComment(long commentId);

    List<ProductComment> topLevelComments(long productId, Scope scope, long viewerId, int limit, long offset);

    long countTopLevelComments(long productId, Scope scope, long viewerId);

    boolean hasCommentBy(long productId, long authorId);

    List<ProductComment> replies(long productId, List<Long> parentIds, Scope scope, long viewerId);

    boolean markDeletedByAuthor(long commentId, Instant now);

    boolean markRemovedByAdmin(long commentId, long adminId, String reason, String basisRef, Instant now);

    long countCommentsSince(long authorId, Instant since);

    OptionalLong productIdOfComment(long commentId);

    Optional<FavoriteRow> favorite(long accountId, long productId);

    List<FavoriteRow> favorites(long accountId, int limit, long offset);

    long countFavorites(long accountId);

    /** Returns false when the account already favourites the product. */
    boolean insertFavorite(long accountId, long productId, Instant now);

    boolean deleteFavorite(long accountId, long productId);
}
