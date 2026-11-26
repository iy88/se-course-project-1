package io.github.iy88.project1.product.application;

/**
 * Product-side read port for the trade-owned party freeze qualification.
 *
 * <p>The trade module owns freeze rows. Keeping the port here avoids a product-to-trade module
 * dependency; the application assembly binds it to {@code TradePorts.Closure}. Callers must read
 * it in the same write transaction and after the existing account qualification lock, so a
 * concurrent freeze either commits before the read or waits for the product write to finish.</p>
 */
public interface ProductTradeFreeze {
    /**
     * Whether an unended freeze still covers the account as a trade party. This includes every
     * freeze source (timeout, admin case and account ban) because each source freezes both parties
     * of the affected trade.
     */
    boolean isPartyFrozen(long accountId);
}
