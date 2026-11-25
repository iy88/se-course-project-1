package io.github.iy88.project1.product.domain;

import io.github.iy88.project1.core.BusinessError;
import java.time.Instant;

/**
 * One persisted product comment or seller reply. The state is derived from the facts so a removed
 * comment keeps its body, author and time for the author and the handling manager.
 */
public record ProductComment(long commentId, long productId, long authorAccountId, Long parentCommentId,
                             String body, Instant createdAt, Instant deletedAt, Instant removedAt,
                             String removedReason, String basisRef) {
    public static final String PUBLISHED = "published";
    public static final String DELETED_BY_AUTHOR = "deleted_by_author";
    public static final String REMOVED_BY_ADMIN = "removed_by_admin";

    public String state() {
        if (removedAt != null) {
            return REMOVED_BY_ADMIN;
        }
        if (deletedAt != null) {
            return DELETED_BY_AUTHOR;
        }
        return PUBLISHED;
    }

    public boolean published() {
        return PUBLISHED.equals(state());
    }

    public boolean topLevel() {
        return parentCommentId == null;
    }

    /** A reply target must be a published top-level comment; the first version has one level only. */
    public void requireReplyTarget() {
        if (!topLevel() || !published()) {
            throw new BusinessError("STATE_CONFLICT", 409, "只能回复已发表的顶级评论");
        }
    }

    public void requireDeleteBy(long accountId) {
        if (authorAccountId != accountId) {
            throw new BusinessError("ACTION_NOT_ALLOWED", 403, "只能删除本人评论");
        }
        if (removedAt != null) {
            throw new BusinessError("COMMENT_ALREADY_REMOVED", 409, "评论已被管理员移除");
        }
    }

    public void requireRemovable() {
        if (removedAt != null) {
            throw new BusinessError("STATE_CONFLICT", 409, "评论已被移除");
        }
    }

    public ProductComment deletedByAuthor(Instant at) {
        return new ProductComment(commentId, productId, authorAccountId, parentCommentId, body, createdAt, at,
                removedAt, removedReason, basisRef);
    }

    public ProductComment removedByAdmin(long adminId, String reason, String basis, Instant at) {
        return new ProductComment(commentId, productId, authorAccountId, parentCommentId, body, createdAt,
                deletedAt, at, reason, basis);
    }
}
