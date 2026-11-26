package io.github.iy88.project1.core;

import java.util.Set;

/** Named business audit actions owned by the product and category modules. */
public final class AuditActions {
    public static final String PRODUCT_SUBMITTED = "product.submitted";
    public static final String PRODUCT_EDITED = "product.edited";
    public static final String PRODUCT_REVIEW_RESUBMITTED = "product.review_resubmitted";
    public static final String PRODUCT_REVIEW_WITHDRAWN = "product.review_withdrawn";
    public static final String PRODUCT_ON_SHELF = "product.on_shelf";
    public static final String PRODUCT_OFF_SHELF = "product.off_shelf";
    public static final String PRODUCT_CATEGORY_CORRECTED = "product.category_corrected";

    public static final String CATEGORY_APPLICATION_CREATED = "category_application.created";
    public static final String CATEGORY_APPLICATION_WITHDRAWN = "category_application.withdrawn";

    public static final String CATEGORY_CREATED = "category.created";
    public static final String CATEGORY_RENAMED = "category.renamed";
    public static final String CATEGORY_ALIAS_ADDED = "category.alias_added";
    public static final String CATEGORY_ALIAS_REMOVED = "category.alias_removed";
    public static final String CATEGORY_DISABLED = "category.disabled";
    public static final String CATEGORY_DELETED = "category.deleted";

    /**
     * Actions written by a domain service inside the owning business transaction. The HTTP
     * idempotency filter keeps claim/replay semantics for these routes but must not append a second,
     * post-commit audit row. {@code product.off_shelf} is included because its product-owned
     * WriteExecutor audit is the single writer for that route.
     */
    public static final Set<String> TRANSACTIONAL_WRITES = Set.of(
            PRODUCT_SUBMITTED, PRODUCT_EDITED, PRODUCT_REVIEW_RESUBMITTED, PRODUCT_REVIEW_WITHDRAWN,
            PRODUCT_ON_SHELF, PRODUCT_OFF_SHELF, PRODUCT_CATEGORY_CORRECTED, CATEGORY_APPLICATION_CREATED,
            CATEGORY_APPLICATION_WITHDRAWN, CATEGORY_CREATED, CATEGORY_RENAMED, CATEGORY_ALIAS_ADDED,
            CATEGORY_ALIAS_REMOVED, CATEGORY_DISABLED, CATEGORY_DELETED);

    private AuditActions() {
    }
}
