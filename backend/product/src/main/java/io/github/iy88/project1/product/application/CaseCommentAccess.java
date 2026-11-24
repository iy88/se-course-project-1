package io.github.iy88.project1.product.application;

/**
 * Resolves whether an account currently handles a case whose necessary scope covers a product.
 * The case module owns claims; the product module asks this port before returning comments or
 * bodies that are hidden from the public list.
 */
public interface CaseCommentAccess {
    boolean claimedForProduct(long managerId, long caseId, long productId);
}
