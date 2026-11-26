package io.github.iy88.project1.api.product;

import io.github.iy88.project1.product.application.ProductTradeHistory;
import io.github.iy88.project1.trade.application.TradeOwnedReadModel;
import java.util.Optional;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Component;

/** Binds the product-side buyer history port to the trade-owned read model. */
@Component
@Profile("infrastructure")
class TradeProductHistoryAdapter implements ProductTradeHistory {
    private final TradeOwnedReadModel trades;

    TradeProductHistoryAdapter(TradeOwnedReadModel trades) {
        this.trades = trades;
    }

    @Override
    public Optional<PurchaseSnapshot> purchaseSnapshot(long productId, long buyerId, long tradeId) {
        return trades.buyerPurchaseProduct(productId, buyerId, tradeId)
                .map(snapshot -> new PurchaseSnapshot(snapshot.contentVersion(), snapshot.title(),
                        snapshot.description(), snapshot.priceCents(), snapshot.capturedAt()));
    }

    @Override
    public Optional<BuyerScope> buyerScope(long productId, long buyerId, Long tradeId) {
        return trades.buyerHistoryStart(productId, buyerId, tradeId).map(BuyerScope::new);
    }
}
