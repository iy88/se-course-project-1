package io.github.iy88.project1.product.application;

import io.github.iy88.project1.product.persistence.ProductRepository;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Read side of the account-owned product lifecycle counts. One grouped repository query excludes
 * hidden products and preserves the original state ordering.
 *
 * <p>The public entry point stays on {@link ProductService}; this query owns no transaction
 * annotations so callers keep their existing transaction boundary.
 */
final class ProductCountQueries {
    private final ProductRepository products;

    ProductCountQueries(ProductRepository products) {
        this.products = products;
    }

    /** Lifecycle counts for the account overview; one grouped row per state, hidden products excluded. */
    ProductService.ProductCounts counts(long accountId) {
        var rows = products.findLifecycleStateCountsForSeller(accountId);
        long total = 0;
        Map<String, Long> byState = new LinkedHashMap<>();
        for (ProductRepository.LifecycleStateCount row : rows) {
            total += row.getTotal();
            byState.put(row.getState(), row.getTotal());
        }
        return new ProductService.ProductCounts(total, byState);
    }
}
