package io.github.iy88.project1.product.application;

import java.time.Instant;
import java.util.List;
import java.util.Optional;

/**
 * Product-owned facts and state changes used by the trade module.
 *
 * <p>Every state-changing call must run inside the caller's write transaction. Occupancy is
 * acquired and released with conditional updates so a concurrent trade cannot take or release the
 * same product twice; the unique occupancy column remains the final invariant.
 */
public interface ProductTradeStore {
    record TradeProduct(long productId, long sellerId, int contentVersion, String lifecycleState,
                        Long occupiedByTradeId, String title, String description, long priceCents,
                        List<String> categoryNames, List<Long> imageFileIds) {
        public TradeProduct {
            categoryNames = List.copyOf(categoryNames);
            imageFileIds = List.copyOf(imageFileIds);
        }
    }

    /** Returns the current row, or empty when it does not exist or was deleted. */
    Optional<TradeProduct> read(long productId);

    /** Locks the product row in the caller's transaction and returns its state. */
    Optional<TradeProduct> lock(long productId);

    /** Read-only display fact for the next trade adaptation; it does not affect occupancy. */
    boolean displayRestricted(long productId);

    /** Marks the product as occupied and in trade. Fails with {@code PRODUCT_NOT_AVAILABLE} on a race. */
    void acquire(long productId, long tradeId, Instant now);

    /** Clears the occupancy held by {@code tradeId} and puts the product off shelf. */
    void release(long productId, long tradeId, Instant now);

    /** Clears the occupancy held by {@code tradeId} and returns the product to {@code public}. */
    void releaseToPublic(long productId, long tradeId, Instant now);
}
