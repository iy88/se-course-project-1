package io.github.iy88.project1.api.product;

import io.github.iy88.project1.casemanagement.persistence.CaseLifecycleStore;
import io.github.iy88.project1.product.application.CaseCommentAccess;
import io.github.iy88.project1.product.application.ProductInteractionStore;
import java.util.OptionalLong;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Component;

/**
 * Resolves the claimed manager's necessary scope for a product by reading the case row. The case
 * module owns claims and targets; the product module only asks whether the product is covered.
 */
@Component
@Profile("infrastructure")
class ProductCommentCaseAccess implements CaseCommentAccess {
    private static final String TARGET_PRODUCT = "product";
    private static final String TARGET_COMMENT = "comment";

    private final CaseLifecycleStore cases;
    private final ProductInteractionStore store;

    ProductCommentCaseAccess(CaseLifecycleStore cases, ProductInteractionStore store) {
        this.cases = cases;
        this.store = store;
    }

    @Override
    public boolean claimedForProduct(long managerId, long caseId, long productId) {
        return cases.find(caseId)
                .filter(facts -> facts.claimedBy(managerId) && !facts.archived() && facts.targetId() != null)
                .map(facts -> coversProduct(facts.targetType(), facts.targetId(), productId))
                .orElse(false);
    }

    private boolean coversProduct(String targetType, long targetId, long productId) {
        if (TARGET_PRODUCT.equals(targetType)) {
            return targetId == productId;
        }
        if (TARGET_COMMENT.equals(targetType)) {
            OptionalLong commentProduct = store.productIdOfComment(targetId);
            return commentProduct.isPresent() && commentProduct.getAsLong() == productId;
        }
        return false;
    }
}
