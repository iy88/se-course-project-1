package io.github.iy88.project1.product.application;

import java.time.Instant;

/** A comment or reply addressed to an account other than its author. */
public record ProductCommentNotice(long recipientId, long productId, long commentId, boolean reply,
                                   Instant occurredAt) {
}
