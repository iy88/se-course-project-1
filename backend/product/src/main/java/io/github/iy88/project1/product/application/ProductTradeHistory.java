package io.github.iy88.project1.product.application;

import java.time.Instant;
import java.util.Optional;

/**
 * Narrow product-side port for looking up a buyer's legitimate edit-history range.
 *
 * <p>The trade module owns the request facts. Keeping the port here avoids a product-to-trade
 * module dependency; the application assembly provides the trade read-model implementation.
 */
public interface ProductTradeHistory {
    record PurchaseSnapshot(int contentVersion, String title, String description, long priceCents, Instant capturedAt) {}

    default Optional<PurchaseSnapshot> purchaseSnapshot(long productId, long buyerId, long tradeId) {
        return Optional.empty();
    }

    record BuyerScope(Instant requestedAt) {
    }

    /**
     * @param tradeId optional exact trade; when absent the earliest request of this buyer for the
     *                product defines the range
     * @return empty when the account is not the buyer of a matching request
     */
    Optional<BuyerScope> buyerScope(long productId, long buyerId, Long tradeId);
}
